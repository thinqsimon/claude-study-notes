#!/usr/bin/env python3
"""study-notes 스킬 보조 스크립트 (표준 라이브러리만 사용).

Claude Code 또는 OpenAI Codex의 세션 기록에서 지난 정리 이후의 대화만 잘라내고,
정리가 끝나면 체크포인트와 index.md를 갱신한다.

  - claude: ~/.claude/projects/<프로젝트 인코딩>/<세션id>.jsonl
  - codex : $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<시각>-<스레드id>.jsonl
            (스레드 목록은 $CODEX_HOME/state_*.sqlite 의 threads 테이블)

사용:
  study_notes.py extract --agent claude|codex --cwd PATH [--session ID] [--notes-root DIR]
  study_notes.py commit  --agent claude|codex --session ID --file NOTE_MD [--notes-root DIR]
  study_notes.py status  --agent claude|codex [--cwd PATH] [--session ID] [--notes-root DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
DEFAULT_NOTES_ROOT = Path.home() / "StudyNotes"

TOOL_INPUT_MAX = 300
TOOL_RESULT_MAX = 500

STRIP_PATTERNS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.S),
    re.compile(r"<ide_opened_file>.*?</ide_opened_file>", re.S),
    re.compile(r"<ide_selection>.*?</ide_selection>", re.S),
    re.compile(r"<task-notification>.*?</task-notification>", re.S),
    re.compile(r"<command-message>.*?</command-message>", re.S),
    re.compile(r"<command-name>.*?</command-name>", re.S),
    # Codex가 사용자 메시지에 끼워 넣는 래퍼들
    re.compile(r"<environment_context>.*?</environment_context>", re.S),
    re.compile(r"<external_codex_apps_open_page>.*?</external_codex_apps_open_page>", re.S),
    re.compile(r"<user_instructions>.*?</user_instructions>", re.S),
    re.compile(r"<permissions instructions>.*?</permissions instructions>", re.S),
    re.compile(r"<turn_aborted>.*?</turn_aborted>", re.S),
    re.compile(r"<app_context>.*?</app_context>", re.S),
]
# 알려지지 않은 태그 하나로만 감싸인 메시지(도구가 넣은 메타)는 통째로 버린다
WRAPPED_ONLY_RE = re.compile(r"^\s*<([A-Za-z_][\w-]*)[^>]*>.*</\1>\s*$", re.S)

AGENTS = ("claude", "codex")


# ---------- 경로 계산 ----------

def encode_cwd(cwd: str) -> str:
    """Claude Code가 프로젝트 폴더명을 만드는 규칙: 영숫자 외 문자는 전부 '-'.

    macOS는 경로의 한글을 자모 분리형(NFD)으로 돌려주므로 완성형(NFC)으로 먼저 정규화한다.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", unicodedata.normalize("NFC", cwd))


def project_dir(cwd: str) -> Path:
    return PROJECTS_DIR / encode_cwd(cwd)


def project_name(cwd: str) -> str:
    return Path(cwd).name or "project"


def find_session_file(pdir: Path, session: str | None) -> Path:
    if session:
        f = pdir / f"{session}.jsonl"
        if not f.exists():
            raise SystemExit(f"세션 기록을 찾을 수 없습니다: {f}")
        return f
    files = sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise SystemExit(f"프로젝트 기록 폴더에 jsonl이 없습니다: {pdir}")
    return files[0]


# ---------- Codex 백엔드 ----------

def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def codex_thread_id(jsonl: Path) -> str:
    """rollout-2026-10-26T17-25-04-<uuid>.jsonl → <uuid>"""
    stem = jsonl.stem
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", stem)
    return m.group(1) if m else stem


def codex_find_session_file(cwd: str, session: str | None) -> Path:
    sessions_dir = CODEX_HOME / "sessions"
    if not sessions_dir.exists():
        raise SystemExit(f"Codex 세션 폴더가 없습니다: {sessions_dir}")
    if session:
        hits = sorted(sessions_dir.rglob(f"rollout-*{session}*.jsonl"))
        if not hits:
            raise SystemExit(f"세션 기록을 찾을 수 없습니다: {session}")
        return hits[-1]
    want = nfc(os.path.abspath(cwd))
    # 1순위: 스레드 목록 DB (사용자가 직접 연 스레드만, 최근 순)
    for db in sorted(CODEX_HOME.glob("state_*.sqlite"), reverse=True):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT rollout_path, cwd FROM threads "
                    "WHERE thread_source = 'user' AND archived = 0 ORDER BY updated_at DESC"
                ).fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        for rollout, tcwd in rows:
            if nfc(tcwd or "") == want and Path(rollout).exists():
                return Path(rollout)
    # 2순위: 파일을 직접 훑어 session_meta.cwd 비교 (서브에이전트 스레드는 제외)
    cands: list[Path] = []
    for f in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            with f.open(encoding="utf-8") as fh:
                first = json.loads(fh.readline() or "{}")
        except (OSError, json.JSONDecodeError):
            continue
        if first.get("type") != "session_meta":
            continue
        meta = first.get("payload") or {}
        if isinstance(meta.get("source"), dict):      # {"subagent": …}
            continue
        if nfc(meta.get("cwd") or "") == want:
            cands.append(f)
    if not cands:
        raise SystemExit(f"이 폴더에서 연 Codex 스레드 기록이 없습니다: {cwd}")
    return max(cands, key=lambda p: p.stat().st_mtime)


CMD_RE = re.compile(r'cmd:\s*"((?:[^"\\]|\\.)*)"')


def codex_tool_summary(name: str, raw) -> str:
    """도구 호출 입력을 한 줄 설명으로. exec(JS 래퍼)는 안의 셸 명령만 뽑는다."""
    if isinstance(raw, str):
        m = CMD_RE.search(raw)
        if m:
            try:
                return json.loads('"' + m.group(1) + '"')
            except json.JSONDecodeError:
                return m.group(1)
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    if isinstance(raw, dict):
        for k in ("cmd", "command", "prompt", "message", "task_name", "path"):
            if raw.get(k):
                return str(raw[k])
        return json.dumps(raw, ensure_ascii=False)
    return str(raw or "")


OUT_PREFIX_RE = re.compile(r"^Script completed\nWall time [^\n]*\nOutput:\n?", re.S)


def codex_tool_output(out) -> tuple[str, bool]:
    """도구 결과를 (본문, 오류 여부)로. exec 결과는 JSON 래퍼를 벗긴다."""
    if isinstance(out, list):
        out = "\n".join(x.get("text", "") for x in out if isinstance(x, dict))
    text = str(out or "")
    text = OUT_PREFIX_RE.sub("", text)
    is_error = False
    try:
        d = json.loads(text)
        if isinstance(d, dict) and "output" in d:
            is_error = d.get("exit_code") not in (0, None)
            text = str(d["output"])
    except (json.JSONDecodeError, TypeError):
        pass
    return text, is_error


def codex_records(jsonl: Path):
    """Codex rollout 레코드를 Claude 형식({type, uuid, timestamp, message.content})으로 바꿔 낸다."""
    for rec in iter_records(jsonl):
        if rec.get("type") != "response_item":
            continue
        p = rec.get("payload") or {}
        t = p.get("type")
        ts = rec.get("timestamp")
        rid = p.get("id") or f"ord-{rec.get('ordinal')}"
        if t == "message":
            role = p.get("role")
            if role not in ("user", "assistant"):
                continue                                   # developer 메시지(시스템) 제외
            blocks = [{"type": "text", "text": c.get("text", "")}
                      for c in (p.get("content") or [])
                      if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")]
            yield {"type": role, "uuid": rid, "timestamp": ts, "message": {"content": blocks}}
        elif t in ("custom_tool_call", "function_call"):
            raw = p.get("input") if t == "custom_tool_call" else p.get("arguments")
            summary = codex_tool_summary(p.get("name", "?"), raw)
            yield {"type": "assistant", "uuid": rid, "timestamp": ts,
                   "message": {"content": [{"type": "tool_use", "name": p.get("name", "?"),
                                            "input": {"command": summary}}]}}
        elif t in ("custom_tool_call_output", "function_call_output"):
            text, is_error = codex_tool_output(p.get("output"))
            yield {"type": "user", "uuid": rid, "timestamp": ts,
                   "message": {"content": [{"type": "tool_result", "content": text, "is_error": is_error}]}}


# ---------- 공통: 에이전트별 분기 ----------

def resolve_session_file(agent: str, cwd: str, session: str | None) -> tuple[Path, str]:
    """(기록 파일, 세션 id)"""
    if agent == "codex":
        f = codex_find_session_file(cwd, session)
        return f, codex_thread_id(f)
    f = find_session_file(project_dir(cwd), session)
    return f, f.stem


def load_conversation(jsonl: Path, agent: str) -> list[dict]:
    if agent == "codex":
        return list(codex_records(jsonl))
    return [r for r in iter_records(jsonl) if is_conversation(r)]


def state_path(notes_root: Path, session: str) -> Path:
    return notes_root / ".state" / f"{session}.json"


def delta_path(notes_root: Path, session: str) -> Path:
    return notes_root / ".state" / f"{session}.delta.md"


def load_state(notes_root: Path, session: str) -> dict:
    p = state_path(notes_root, session)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"session": session, "last_uuid": None, "last_timestamp": None, "run_count": 0, "files": []}


def save_state(notes_root: Path, session: str, state: dict) -> None:
    p = state_path(notes_root, session)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- 기록 파싱 ----------

def iter_records(jsonl: Path):
    with jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def is_conversation(rec: dict) -> bool:
    if rec.get("type") not in ("user", "assistant"):
        return False
    if rec.get("isMeta"):
        return False
    if rec.get("isSidechain"):
        return False
    return bool(rec.get("uuid"))


def clean_text(text: str) -> str:
    for pat in STRIP_PATTERNS:
        text = pat.sub("", text)
    text = text.strip()
    if WRAPPED_ONLY_RE.match(text):
        return ""
    return text


def shorten(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[:n].rstrip() + " …(생략)"


def render_blocks(rec: dict) -> str:
    """레코드 하나를 학습 정리용 텍스트로 바꾼다. 내용이 없으면 빈 문자열."""
    content = rec.get("message", {}).get("content")
    parts: list[str] = []
    if isinstance(content, str):
        t = clean_text(content)
        if t:
            parts.append(t)
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text":
                t = clean_text(b.get("text", ""))
                if t:
                    parts.append(t)
            elif kind == "tool_use":
                name = b.get("name", "?")
                inp = b.get("input", {}) or {}
                desc = inp.get("description") or inp.get("command") or inp.get("prompt") or inp.get("file_path") or ""
                if not desc:
                    desc = json.dumps(inp, ensure_ascii=False)
                parts.append(f"[도구: {name}] {shorten(str(desc), TOOL_INPUT_MAX)}")
            elif kind == "tool_result":
                rc = b.get("content")
                if isinstance(rc, list):
                    rc = "\n".join(x.get("text", "") for x in rc if isinstance(x, dict))
                rc = clean_text(str(rc or ""))
                if rc:
                    tag = "[결과(오류)]" if b.get("is_error") else "[결과]"
                    parts.append(f"{tag} {shorten(rc, TOOL_RESULT_MAX)}")
            # thinking 등은 제외
    return "\n".join(parts).strip()


def collect_delta(jsonl: Path, state: dict, agent: str = "claude") -> list[dict]:
    """체크포인트 이후의 대화 레코드만 모은다."""
    last_uuid = state.get("last_uuid")
    last_ts = state.get("last_timestamp")
    all_recs = load_conversation(jsonl, agent)
    if last_uuid and any(r["uuid"] == last_uuid for r in all_recs):
        idx = next(i for i, r in enumerate(all_recs) if r["uuid"] == last_uuid)
        return all_recs[idx + 1:]
    if last_ts:
        return [r for r in all_recs if (r.get("timestamp") or "") > last_ts]
    return all_recs


def fmt_local(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        d = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def write_delta_file(path: Path, recs: list[dict], project: str, session: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# 정리 대상 대화 (project={project}, session={session[:8]})", ""]
    count = 0
    for r in recs:
        body = render_blocks(r)
        if not body:
            continue
        role = "사용자" if r["type"] == "user" else "AI"
        lines.append(f"### {role} · {fmt_local(r.get('timestamp'))}")
        lines.append(body)
        lines.append("")
        count += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return count


def next_note_path(notes_root: Path, project: str) -> tuple[Path, int]:
    today = dt.date.today().strftime("%Y-%m-%d")
    folder = notes_root / project
    existing = sorted(folder.glob(f"{today}_*.md")) if folder.exists() else []
    nn = 1
    for f in existing:
        m = re.match(rf"{today}_(\d+)\.md$", f.name)
        if m:
            nn = max(nn, int(m.group(1)) + 1)
    return folder / f"{today}_{nn:02d}.md", nn


# ---------- 서브커맨드 ----------

def cmd_extract(args) -> int:
    cwd = os.path.abspath(args.cwd)
    notes_root = Path(args.notes_root).expanduser()
    jsonl, session = resolve_session_file(args.agent, cwd, args.session)
    project = project_name(cwd)
    state = load_state(notes_root, session)
    state["agent"] = args.agent
    recs = collect_delta(jsonl, state, args.agent)
    dpath = delta_path(notes_root, session)
    n = write_delta_file(dpath, recs, project, session)
    suggested, _ = next_note_path(notes_root, project)
    out = {
        "agent": args.agent,
        "project": project,
        "session": session,
        "transcript": str(jsonl),
        "new_messages": n,
        "from": fmt_local(recs[0].get("timestamp")) if recs else None,
        "to": fmt_local(recs[-1].get("timestamp")) if recs else None,
        "delta_path": str(dpath),
        "suggested_file": str(suggested),
        "index_path": str(notes_root / "index.md"),
        "run_no": state.get("run_count", 0) + 1,
        "pending_last_uuid": recs[-1]["uuid"] if recs else None,
        "pending_last_timestamp": recs[-1].get("timestamp") if recs else None,
    }
    # commit 때 쓰도록 임시 저장
    state["_pending"] = {"last_uuid": out["pending_last_uuid"], "last_timestamp": out["pending_last_timestamp"]}
    save_state(notes_root, session, state)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


README_TEXT = """# StudyNotes — AI 대화 학습장

Claude Code(`/study-notes`)와 OpenAI Codex(`$study-notes`)의 study-notes 스킬이 개발 대화에서
공부할 주제를 골라 교재처럼 다시 설명해 저장하는 곳입니다.

## 폴더 구조
```
StudyNotes/
  README.md            이 파일
  index.md             모든 프로젝트의 주제 목록 (자동 갱신)
  .state/              증분 정리용 체크포인트 (지우면 처음부터 다시 정리됨)
  <프로젝트명>/        실행 1회마다 YYYY-MM-DD_NN.md 한 파일
```

## 노트 파일 구조
- 맨 위 frontmatter: title / project / session / created / covers / topics
- `## N. 주제` 섹션이 학습 단위. 각 섹션은
  상황 → 왜 필요한가 → 핵심 개념 → 프로젝트 적용 → (문제해결) → 명령어/코드 → 흔한 실수 → 자가 점검 → 더 공부할 것
- 일반 Markdown만 사용하므로 VS Code, Obsidian, Typora 어디서나 열립니다.

## 사용법
1. 개발하다가 정리하고 싶을 때 Claude Code에서는 `/study-notes`, Codex에서는 `$study-notes` 입력
2. 다음에 또 입력하면 **지난번 이후 대화만** 새 파일로 정리됩니다
3. 다른 프로젝트에서도 같은 명령을 쓰면 `<프로젝트명>/` 폴더가 따로 생깁니다

## 상태 확인
```bash
# Claude Code
python3 -I ~/.claude/skills/study-notes/scripts/study_notes.py status --agent claude --cwd "$PWD"
# Codex
python3 -I ~/.codex/skills/study-notes/scripts/study_notes.py status --agent codex --cwd "$PWD"
```
"""

INDEX_HEADER = """# 학습 주제 목록

`/study-notes` 실행 때마다 자동으로 행이 추가됩니다. 주제명을 눌러 해당 노트로 이동하세요.

| 날짜 | 프로젝트 | 주제 | 유형 | 태그 | 노트 |
|---|---|---|---|---|---|
"""

TOPIC_RE = re.compile(r"^## (\d+)\. (.+?)\s*$")
META_RE = re.compile(r"`유형`\s*([^|]+?)\s*\|\s*`태그`\s*([^|]+?)\s*(?:\||$)")


def slugify_heading(text: str) -> str:
    """GitHub 방식 앵커: 소문자, 공백→-, 구두점 제거(한글 유지)."""
    s = text.strip().lower()
    s = re.sub(r"[^\w\s가-힣-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


def parse_topics(note: Path) -> list[dict]:
    topics: list[dict] = []
    current: dict | None = None
    in_fence = False
    for line in note.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence      # 코드 블록 안의 "## 제목" 예시는 주제가 아니다
            continue
        if in_fence:
            continue
        m = TOPIC_RE.match(line)
        if m:
            current = {"no": int(m.group(1)), "title": m.group(2).strip(), "type": "", "tags": "",
                       "anchor": slugify_heading(f"{m.group(1)}. {m.group(2)}")}
            topics.append(current)
            continue
        if current and not current["type"]:
            mm = META_RE.search(line)
            if mm:
                current["type"] = mm.group(1).strip()
                current["tags"] = mm.group(2).strip()
    return topics


def cmd_commit(args) -> int:
    notes_root = Path(args.notes_root).expanduser()
    session = args.session
    note = Path(args.file).expanduser().resolve()
    if not note.exists():
        raise SystemExit(f"노트 파일이 없습니다: {note}")
    state = load_state(notes_root, session)
    pending = state.pop("_pending", None)
    if not pending or not pending.get("last_uuid"):
        raise SystemExit("먼저 extract를 실행해야 합니다 (pending 체크포인트 없음)")
    state["last_uuid"] = pending["last_uuid"]
    state["last_timestamp"] = pending["last_timestamp"]
    state["run_count"] = state.get("run_count", 0) + 1
    state.setdefault("files", []).append(str(note))
    save_state(notes_root, session, state)

    readme = notes_root / "README.md"
    if not readme.exists():
        readme.write_text(README_TEXT, encoding="utf-8")
    index = notes_root / "index.md"
    if not index.exists():
        index.write_text(INDEX_HEADER, encoding="utf-8")

    project = note.parent.name
    date = dt.date.today().strftime("%Y-%m-%d")
    rel = note.relative_to(notes_root).as_posix()
    topics = parse_topics(note)
    rows = [
        f"| {date} | {project} | {t['title']} | {t['type']} | {t['tags']} | [{note.stem}#{t['no']}]({rel}#{t['anchor']}) |"
        for t in topics
    ]
    with index.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + ("\n" if rows else ""))

    dp = delta_path(notes_root, session)
    if dp.exists():
        dp.unlink()
    print(json.dumps({"committed": str(note), "topics": len(topics), "run_count": state["run_count"],
                      "index": str(index)}, ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    cwd = os.path.abspath(args.cwd)
    notes_root = Path(args.notes_root).expanduser()
    jsonl, session = resolve_session_file(args.agent, cwd, args.session)
    state = load_state(notes_root, session)
    recs = collect_delta(jsonl, state, args.agent)
    pending_msgs = sum(1 for r in recs if render_blocks(r))
    print(json.dumps({
        "agent": args.agent,
        "project": project_name(cwd),
        "transcript": str(jsonl),
        "session": session,
        "run_count": state.get("run_count", 0),
        "last_summarized_at": fmt_local(state.get("last_timestamp")),
        "unsummarized_messages": pending_msgs,
        "files": state.get("files", []),
    }, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--agent", choices=AGENTS, default="claude",
                       help="기록을 읽을 도구: claude(기본) 또는 codex")
        p.add_argument("--cwd", default=os.getcwd(), help="프로젝트 작업 디렉터리(기본: 현재)")
        p.add_argument("--session", default=None,
                       help="세션/스레드 id(기본: 이 폴더에서 가장 최근 기록)")
        p.add_argument("--notes-root", default=str(DEFAULT_NOTES_ROOT))

    p = sub.add_parser("extract", help="지난 정리 이후 대화를 델타 파일로 추출")
    common(p)
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("commit", help="작성한 노트를 등록하고 체크포인트 갱신")
    common(p)
    p.add_argument("--file", required=True, help="작성한 노트 md 경로")
    p.set_defaults(fn=cmd_commit)

    p = sub.add_parser("status", help="체크포인트와 미정리 메시지 수 확인")
    common(p)
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    if args.cmd == "commit" and not args.session:
        ap.error("commit에는 --session 이 필요합니다")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
