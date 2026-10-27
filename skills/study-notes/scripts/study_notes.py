#!/usr/bin/env python3
"""study-notes 스킬 보조 스크립트 (표준 라이브러리만 사용).

Claude Code 세션 기록(~/.claude/projects/<proj>/<session>.jsonl)에서
지난 정리 이후의 대화만 잘라내고, 정리가 끝나면 체크포인트와 index.md를 갱신한다.

사용:
  study_notes.py extract --cwd PATH [--session ID] [--notes-root DIR]
  study_notes.py commit  --session ID --file NOTE_MD [--cwd PATH] [--notes-root DIR]
  study_notes.py status  [--cwd PATH] [--session ID] [--notes-root DIR]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
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
]


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
    return text.strip()


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


def collect_delta(jsonl: Path, state: dict) -> list[dict]:
    """체크포인트 이후의 대화 레코드만 모은다."""
    last_uuid = state.get("last_uuid")
    last_ts = state.get("last_timestamp")
    all_recs = [r for r in iter_records(jsonl) if is_conversation(r)]
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
    pdir = project_dir(cwd)
    jsonl = find_session_file(pdir, args.session)
    session = jsonl.stem
    project = project_name(cwd)
    state = load_state(notes_root, session)
    recs = collect_delta(jsonl, state)
    dpath = delta_path(notes_root, session)
    n = write_delta_file(dpath, recs, project, session)
    suggested, _ = next_note_path(notes_root, project)
    out = {
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

Claude Code의 `/study-notes` 스킬이 개발 대화에서 공부할 주제를 골라 교재처럼 다시 설명해 저장하는 곳입니다.

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
1. Claude Code에서 개발하다가 정리하고 싶을 때 `/study-notes` 입력
2. 다음에 또 입력하면 **지난번 이후 대화만** 새 파일로 정리됩니다
3. 다른 프로젝트에서도 같은 명령을 쓰면 `<프로젝트명>/` 폴더가 따로 생깁니다

## 상태 확인
```bash
python3 -I ~/.claude/skills/study-notes/scripts/study_notes.py status --cwd "$PWD"
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
    pdir = project_dir(cwd)
    jsonl = find_session_file(pdir, args.session)
    session = jsonl.stem
    state = load_state(notes_root, session)
    recs = collect_delta(jsonl, state)
    pending_msgs = sum(1 for r in recs if render_blocks(r))
    print(json.dumps({
        "project": project_name(cwd),
        "project_dir": str(pdir),
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
        p.add_argument("--cwd", default=os.getcwd(), help="프로젝트 작업 디렉터리(기본: 현재)")
        p.add_argument("--session", default=None, help="세션 id(기본: 가장 최근 jsonl)")
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
