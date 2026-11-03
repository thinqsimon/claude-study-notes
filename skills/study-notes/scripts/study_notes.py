#!/usr/bin/env python3
"""study-notes 스킬 보조 스크립트 (표준 라이브러리만 사용).

Claude Code 또는 OpenAI Codex의 세션 기록에서 지난 정리 이후의 대화만 잘라내고,
정리가 끝나면 체크포인트와 index.md를 갱신한다.

  - claude: ~/.claude/projects/<프로젝트 인코딩>/<세션id>.jsonl
  - codex : $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<시각>-<스레드id>.jsonl
            (스레드 목록은 $CODEX_HOME/state_*.sqlite 의 threads 테이블)

사용:
  study_notes.py extract --agent claude|codex --cwd PATH [--session ID] [--level N] [--notes-root DIR]
                         (대화를 잘라내고, 그 대화에 나온 개념 중 이 단계의 사전 항목을 후보로 알려 준다)
  study_notes.py concept ID [ID ...]   (노트를 쓸 항목의 학습 목표·선수 개념·공식 문서를 보여 준다)
  study_notes.py candidate --title 이름 [--title 이름 ...] [--cwd PATH] [--notes-root DIR]
                         (사전에 없는 개념을 후보함에 적는다)
  study_notes.py commit  --agent claude|codex --session ID --file NOTE_MD [--notes-root DIR]
                         (개념노트를 검사해 등록한다. 통과하지 못하면 오류를 보여 주고 등록하지 않는다)
  study_notes.py status  --agent claude|codex [--cwd PATH] [--session ID] [--notes-root DIR]
  study_notes.py level   [N|이름] [--notes-root DIR]
  study_notes.py cancel  --agent claude|codex [--cwd PATH] [--session ID] [--notes-root DIR]
                         (extract 후 commit 전인 정리를 취소: 미완성 노트·델타 삭제, 체크포인트는 유지)

설명 수준(level)은 1 왕초보 · 2 입문 · 3 기초 · 4 실전 · 5 심화. 고른 값은 <노트 폴더>/settings.json에 기억된다.
노트 폴더는 기본이 ~/StudyNotes이고, 환경 변수 STUDY_NOTES_ROOT나 --notes-root로 바꿀 수 있다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import ntpath
import os
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

# python -I로 실행하면 스크립트 폴더가 경로에 없어 직접 넣는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import concepts  # noqa: E402

IS_WINDOWS = os.name == "nt"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
CODEX_HOME = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
DEFAULT_NOTES_ROOT = Path(os.environ.get("STUDY_NOTES_ROOT") or (Path.home() / "StudyNotes")).expanduser()
# 개념노트는 특정 프로젝트에 묶이지 않으므로 한 폴더에 모은다. 경로를 다루기 쉽게 공백을 뺀다.
CONCEPT_FOLDER = "AX개념노트"
CANDIDATE_FILE = "concept_candidates.md"

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

def normalize_cwd(cwd: str, windows: bool = IS_WINDOWS) -> str:
    """작업 디렉터리를 도구가 기록하는 형태의 절대경로로 통일한다.

    - macOS는 경로의 한글을 자모 분리형(NFD)으로 돌려주므로 완성형(NFC)으로 정규화
    - Windows에서 Git Bash가 주는 `/c/Users/...` 는 `C:\\Users\\...` 로 바꾸고 드라이브 문자는 대문자로
    """
    cwd = unicodedata.normalize("NFC", cwd)
    if windows:
        m = re.match(r"^/([A-Za-z])(/.*)?$", cwd)
        if m:
            cwd = f"{m.group(1)}:" + (m.group(2) or "/")
        cwd = ntpath.normpath(cwd)
        if re.match(r"^[a-z]:", cwd):
            cwd = cwd[0].upper() + cwd[1:]
        return cwd
    return os.path.abspath(cwd)


def path_key(p: str, windows: bool = IS_WINDOWS) -> str:
    """경로 비교용 키: NFC + 구분자 통일 + (Windows) 대소문자 무시."""
    s = unicodedata.normalize("NFC", p).replace("\\", "/").rstrip("/")
    return s.lower() if windows else s


def encode_cwd(cwd: str) -> str:
    """Claude Code가 프로젝트 폴더명을 만드는 규칙: 영숫자 외 문자는 전부 '-'.

    예) /Users/me/proj → -Users-me-proj,  C:\\Users\\me\\proj → C--Users-me-proj
    """
    return re.sub(r"[^A-Za-z0-9]", "-", unicodedata.normalize("NFC", cwd))


def project_dir(cwd: str) -> Path:
    want = PROJECTS_DIR / encode_cwd(cwd)
    if want.exists() or not PROJECTS_DIR.exists():
        return want
    # Windows는 드라이브 문자·폴더명 대소문자가 섞일 수 있으니 대소문자 무시로 한 번 더 찾는다
    low = want.name.lower()
    for d in PROJECTS_DIR.iterdir():
        if d.is_dir() and d.name.lower() == low:
            return d
    return want


def project_name(cwd: str, windows: bool = IS_WINDOWS) -> str:
    cwd = cwd.rstrip("/\\")
    name = ntpath.basename(cwd) if (windows or "\\" in cwd) else os.path.basename(cwd)
    return name or "project"


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
    want = path_key(cwd)
    # 1순위: 스레드 목록 DB (사용자가 직접 연 스레드만, 최근 순)
    for db in sorted(CODEX_HOME.glob("state_*.sqlite"), reverse=True):
        try:
            # as_uri()는 Windows 경로(C:\...)와 한글 경로를 file:///C:/... 형태로 올바르게 인코딩한다
            con = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
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
            if path_key(tcwd or "") == want and Path(rollout).exists():
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
        if path_key(meta.get("cwd") or "") == want:
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


def spoken_text(recs: list[dict]) -> str:
    """사람과 AI가 나눈 말만 모은다. 도구 입출력의 코드 속 낱말은 그 개념을 다뤘다는 근거가 못 된다."""
    parts: list[str] = []
    for rec in recs:
        content = rec.get("message", {}).get("content")
        if isinstance(content, str):
            parts.append(clean_text(content))
        elif isinstance(content, list):
            parts.extend(clean_text(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
    return "\n".join(part for part in parts if part)


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


def safe_name(name: str) -> str:
    """파일명에 쓸 수 없는 문자만 '-'로 바꾼다. 한글·공백은 그대로 둔다."""
    return re.sub(r'[\\/:*?"<>|]', "-", name).strip() or "project"


def next_note_path(notes_root: Path, project: str) -> tuple[Path, int]:
    """<프로젝트>/<프로젝트>_YYYY-MM-DD_NN.md.

    프로젝트마다 같은 날짜의 노트가 생기므로 파일명에 프로젝트를 넣어 다른 폴더의 노트와 겹치지 않게 한다.
    NN은 같은 날의 옛 이름(YYYY-MM-DD_NN.md, v1.2 이전)과 새 이름을 모두 세어 이어 붙인다.
    """
    today = dt.date.today().strftime("%Y-%m-%d")
    folder = notes_root / project
    prefix = safe_name(project)
    existing = sorted(folder.glob(f"*{today}_*.md")) if folder.exists() else []
    pattern = re.compile(rf"^(?:{re.escape(prefix)}_)?{today}_(\d+)\.md$")
    nn = 1
    for f in existing:
        m = pattern.match(f.name)
        if m:
            nn = max(nn, int(m.group(1)) + 1)
    return folder / f"{prefix}_{today}_{nn:02d}.md", nn


# ---------- 설명 수준 (5단계) ----------
# 배움일기 코치 앱의 '답변 수준'과 같은 이름·대상·방식이다. 노트를 쓰는 AI가 이 값으로 어휘와 설명 깊이를 맞춘다.
LEVELS: dict[int, dict[str, str]] = {
    1: {"name": "왕초보", "audience": "컴퓨터·IT 용어가 낯선 분",
        "style": "중학생도 아는 쉬운 말, 일상 비유 먼저, 용어는 바로 풀이, 코드는 최소로"},
    2: {"name": "입문", "audience": "비전공으로 막 입과한 분",
        "style": "핵심 용어 소개와 한 줄 풀이, 비유 다음 짧은 코드와 주석, 흔한 실수"},
    3: {"name": "기초", "audience": "변수·함수·조건문을 익힌 분",
        "style": "아는 용어는 그대로, 새 개념만 풀이, 단계별 예제와 그렇게 되는 이유"},
    4: {"name": "실전", "audience": "웹 프로젝트를 만드는 분",
        "style": "동작 원리·설계 이유·장단점, 실무형 코드와 디버깅 방법"},
    5: {"name": "심화", "audience": "전공자·실무 경험자",
        "style": "기초 생략, 정확한 용어로 간결하게, 내부 동작·트레이드오프·공식 문서"},
}
# 고르기 전에는 2단계로 쓴다. v1.3까지의 노트(초보 개발자 대상)와 같은 수준이다.
DEFAULT_LEVEL = 2
SETTINGS_FILE = "settings.json"
LEVEL_PREFIX_RE = re.compile(r"^(?:level|lv|수준|단계)\s*[=:：]?\s*", re.I)
LEVEL_NUMBER_RE = re.compile(r"^([1-5])\s*(?:단계)?\s*(.*)$")


def level_label(level: int) -> str:
    return f"{level}단계 {LEVELS[level]['name']}"


def parse_level(text) -> int:
    """'3', '3단계', '기초', '3단계 기초', 'level=3'을 3으로 바꾼다. 알아볼 수 없으면 ValueError."""
    s = LEVEL_PREFIX_RE.sub("", unicodedata.normalize("NFC", str(text)).strip()).strip()
    m = LEVEL_NUMBER_RE.match(s)
    if m:
        level, rest = int(m.group(1)), m.group(2).strip()
        if rest and rest != LEVELS[level]["name"]:
            raise ValueError(f"단계 번호와 이름이 맞지 않습니다: {text!r}. {level}단계는 '{level_label(level)}'입니다")
        return level
    for level, info in LEVELS.items():
        if s == info["name"]:
            return level
    choices = ", ".join(level_label(n) for n in LEVELS)
    raise ValueError(f"알 수 없는 설명 수준입니다: {text!r}. 1~5 숫자나 이름으로 고르세요 ({choices})")


def level_info(level: int) -> dict:
    info = LEVELS[level]
    return {"level": level, "level_name": info["name"], "level_label": level_label(level),
            "level_audience": info["audience"], "level_style": info["style"]}


def level_table() -> list[dict]:
    """처음 실행 때 사용자에게 보여 줄 다섯 단계 표."""
    return [{"level": n, "label": level_label(n), "audience": i["audience"], "style": i["style"]}
            for n, i in LEVELS.items()]


def settings_path(notes_root: Path) -> Path:
    return notes_root / SETTINGS_FILE


def load_settings(notes_root: Path) -> dict:
    p = settings_path(notes_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}          # 손으로 고치다 깨진 파일은 고른 적 없는 것으로 본다
    return data if isinstance(data, dict) else {}


def remember_level(notes_root: Path, level: int) -> None:
    settings = load_settings(notes_root)
    settings["level"] = level
    p = settings_path(notes_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def current_level(notes_root: Path) -> tuple[int, str]:
    """기억된 수준과 출처. 고른 적이 없으면 (DEFAULT_LEVEL, "unset")."""
    value = load_settings(notes_root).get("level")
    if type(value) is int and value in LEVELS:
        return value, "saved"
    return DEFAULT_LEVEL, "unset"


def note_level(note: Path) -> int | None:
    """노트 frontmatter의 level(1~5). 없거나 알아볼 수 없으면 None."""
    try:
        lines = note.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not lines or lines[0].lstrip("﻿").strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key.strip() == "level":
            try:
                return parse_level(value.strip().strip("'\""))
            except ValueError:
                return None
    return None


# ---------- 서브커맨드 ----------

def cmd_extract(args) -> int:
    cwd = normalize_cwd(args.cwd)
    notes_root = Path(args.notes_root).expanduser().resolve()
    try:
        requested = parse_level(args.level) if args.level else None
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    level, level_source = (requested, "argument") if requested else current_level(notes_root)
    jsonl, session = resolve_session_file(args.agent, cwd, args.session)
    project = project_name(cwd)
    state = load_state(notes_root, session)
    state["agent"] = args.agent
    recs = collect_delta(jsonl, state, args.agent)
    dpath = delta_path(notes_root, session)
    n = write_delta_file(dpath, recs, project, session)
    suggested, _ = next_note_path(notes_root, CONCEPT_FOLDER)
    catalog = concepts.load_catalog()
    if n:
        found = concepts.find_candidates(spoken_text(recs), catalog, level, concepts.load_used(notes_root))
    else:
        found = {"candidates": [], "candidate_total": 0, "other_levels": {}}
    concept_dir = notes_root / CONCEPT_FOLDER
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
        "note_no": (len(list(concept_dir.glob("*.md"))) if concept_dir.exists() else 0) + 1,
        "catalog_version": catalog["version"],
        **found,
        **level_info(level),
        "level_source": level_source,
        "pending_last_uuid": recs[-1]["uuid"] if recs else None,
        "pending_last_timestamp": recs[-1].get("timestamp") if recs else None,
    }
    if level_source == "unset":
        # 처음 실행: SKILL.md 절차대로 이 표를 보여 주고 단계를 물은 뒤 쓴다.
        out["levels"] = level_table()
    # commit 때 쓰도록 임시 저장
    state["_pending"] = {"last_uuid": out["pending_last_uuid"], "last_timestamp": out["pending_last_timestamp"],
                         "level": level, "suggested_file": str(suggested),
                         "started_at": dt.datetime.now().isoformat(timespec="seconds")}
    save_state(notes_root, session, state)
    if requested is not None:
        remember_level(notes_root, requested)   # 앱에서 단계를 고르면 설정이 바뀌는 것과 같다
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


README_TEXT = """# StudyNotes — AI 대화 학습장

Claude Code(`/study-notes`)와 OpenAI Codex(`$study-notes`)의 study-notes 스킬이 개발 대화에 나온 개념을
개념사전에서 찾아 교과서처럼 설명해 저장하는 곳입니다. 한 번 쓴 개념은 다시 쓰지 않습니다.

## 폴더 구조
```
StudyNotes/
  README.md            이 파일
  index.md             모든 프로젝트의 주제 목록 (자동 갱신)
  settings.json        기억한 설명 수준 (예: {"level": 3})
  concepts_used.json   이미 쓴 개념 (항목을 지우면 그 개념을 다시 쓸 수 있음)
  concept_candidates.md  대화에 나왔지만 사전에 없는 개념
  .state/              증분 정리용 체크포인트 (지우면 처음부터 다시 정리됨)
  AX개념노트/          실행 1회마다 AX개념노트_YYYY-MM-DD_NN.md 한 파일
  <프로젝트명>/        v1 스킬이 만든 예전 노트 (그대로 둡니다)
```

## 노트 파일 구조
- 맨 위 frontmatter: title / project / level / level_name / catalog_version / created / topics
- 제목 끝과 제목 아래 인용문 첫 줄에 설명 수준 (예: `설명 수준: 3단계 기초`)
- `## N. 주제` 섹션이 학습 단위. 각 섹션은
  학습 목표 → 먼저 알아야 할 것 → 왜 필요한가 → 핵심 개념 → 예제 → 비슷한 개념과 차이 → 흔한 실수 → 직접 해 보기 → 확인 문제 → 정답 → 공식 문서
- 일반 Markdown만 사용하므로 VS Code, Obsidian, Typora 어디서나 열립니다.

## 사용법
1. 개발하다가 정리하고 싶을 때 Claude Code에서는 `/study-notes`, Codex에서는 `$study-notes` 입력
2. 다음에 또 입력하면 **지난번 이후 대화만** 살펴 새 파일로 정리합니다. 한 번에 주제 3~5개를 씁니다
3. 사전은 아직 백엔드·API 중심입니다. 대화에 나온 개념이 사전에 없으면 노트를 만들지 않고 후보함에 적습니다
4. 설명 수준(1 왕초보 · 2 입문 · 3 기초 · 4 실전 · 5 심화)은 처음 실행할 때 한 번 고르면 기억됩니다.
   바꾸려면 `/study-notes 4`, `/study-notes 실전`처럼 붙여 부릅니다 (Codex는 `$study-notes 4`)
5. 옵션: `/study-notes h` 사용법 · `/study-notes d` 현재 단계와 정리 상태 · `/study-notes s` 진행 중 정리 취소
   (정리 도중 ESC로 멈춘 뒤 `s`를 부르면 미완성 노트를 지우고, 다음 실행 때 같은 대화부터 다시 정리합니다)

## 상태 확인
```bash
# Claude Code
python3 -I ~/.claude/skills/study-notes/scripts/study_notes.py status --agent claude --cwd "$PWD"
# Codex
python3 -I ~/.codex/skills/study-notes/scripts/study_notes.py status --agent codex --cwd "$PWD"
```
"""

INDEX_COLUMNS = ("날짜", "프로젝트", "수준", "주제", "유형", "태그", "요약", "노트")
# 예전 버전이 만든 표의 열 구성. upgrade_index가 지금 열 구성으로 바꾼다.
LEGACY_INDEX_COLUMNS = (
    ("날짜", "프로젝트", "주제", "유형", "태그", "노트"),          # 요약 열 이전
    ("날짜", "프로젝트", "주제", "유형", "태그", "요약", "노트"),  # 수준 열 이전 (v1.4 전)
)
TABLE_DIVIDER_RE = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+$")


def table_header(columns) -> str:
    return "| " + " | ".join(columns) + " |"


def table_divider(count: int) -> str:
    return "|" + "---|" * count


def table_row(cells: dict) -> str:
    return "| " + " | ".join(cells.get(c, "") for c in INDEX_COLUMNS) + " |"


INDEX_HEADER = (
    "# 학습 주제 목록\n\n"
    "`/study-notes` 실행 때마다 자동으로 행이 추가됩니다. 주제명을 눌러 해당 노트로 이동하세요.\n\n"
    f"{table_header(INDEX_COLUMNS)}\n{table_divider(len(INDEX_COLUMNS))}\n"
)

TOPIC_RE = re.compile(r"^## (\d+)\. (.+?)\s*$")
META_RE = re.compile(r"`유형`\s*([^|]+?)\s*\|\s*`태그`\s*([^|]+?)\s*(?:\||$)")
# 템플릿의 "> 한 줄 요약: …" 줄. index.md에 실어 두면 본문을 열지 않고도 중복 여부를 판단할 수 있다.
SUMMARY_RE = re.compile(r"^>\s*한 줄 요약\s*[:：]\s*(.+?)\s*$")


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
                       "summary": "", "anchor": slugify_heading(f"{m.group(1)}. {m.group(2)}")}
            topics.append(current)
            continue
        if current and not current["summary"] and not current["type"]:
            ms = SUMMARY_RE.match(line)
            if ms:
                current["summary"] = ms.group(1).strip()
                continue
        if current and not current["type"]:
            mm = META_RE.search(line)
            if mm:
                current["type"] = mm.group(1).strip()
                current["tags"] = mm.group(2).strip()
    return topics


def table_cell(text: str) -> str:
    """표 칸 안의 | 와 줄바꿈이 GFM 표를 깨지 않게 한다."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def upgrade_index(index: Path, notes_root: Path) -> None:
    """예전 열 구성의 index.md를 지금 열 구성(INDEX_COLUMNS)으로 바꾼다. 이미 최신이면 그대로 둔다.

    - 요약 열이 없던 표: 같은 프로젝트 노트에서 제목으로 요약을 찾아 채운다.
    - 수준 열이 없던 표(v1.4 전): 링크된 노트의 frontmatter level로 채운다. 예전 노트는 level이 없어 빈 칸이다.
    """
    lines = index.read_text(encoding="utf-8").splitlines()
    legacy = next((cols for cols in LEGACY_INDEX_COLUMNS if table_header(cols) in lines), None)
    if legacy is None:
        return
    summaries: dict[tuple[str, str], str] = {}
    if "요약" not in legacy:
        for note in notes_root.glob("*/*.md"):
            for t in parse_topics(note):
                if t["summary"]:
                    summaries.setdefault((note.parent.name, t["title"]), t["summary"])
    levels: dict[str, str] = {}

    def level_of(link: str) -> str:
        m = re.search(r"\]\(([^)#]+)", link)
        if not m:
            return ""
        rel = m.group(1)
        if rel not in levels:
            note = notes_root / rel
            level = note_level(note) if note.is_file() else None
            levels[rel] = level_label(level) if level else ""
        return levels[rel]

    out = []
    in_table = False
    for line in lines:
        if line == table_header(legacy):
            in_table = True
            line = table_header(INDEX_COLUMNS)
        elif in_table and TABLE_DIVIDER_RE.match(line):
            line = table_divider(len(INDEX_COLUMNS))
        elif in_table and line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
            if len(cells) == len(legacy):
                row = dict(zip(legacy, cells))
                if "요약" not in row:
                    row["요약"] = table_cell(summaries.get((row["프로젝트"], row["주제"]), ""))
                row["수준"] = level_of(row["노트"])
                line = table_row(row)
        out.append(line)
    index.write_text("\n".join(out) + "\n", encoding="utf-8")


def cmd_commit(args) -> int:
    notes_root = Path(args.notes_root).expanduser().resolve()
    session = args.session
    note = Path(args.file).expanduser().resolve()
    if not note.exists():
        raise SystemExit(f"노트 파일이 없습니다: {note}")
    text = note.read_text(encoding="utf-8")
    concept_ids: list[str] = []
    # v1 형식 노트를 다시 등록하는 일이 있어, 개념노트일 때만 검사한다.
    if note.parent.name == CONCEPT_FOLDER or "catalog_version" in concepts.frontmatter(text):
        errors = concepts.lint_concept_note(text, concepts.load_catalog(), concepts.load_used(notes_root))
        if errors:
            raise SystemExit("노트 검사를 통과하지 못해 등록하지 않았습니다. 고친 뒤 다시 commit 하세요:\n- " + "\n- ".join(errors))
        concept_ids = concepts.note_concept_ids(text)
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
    else:
        upgrade_index(index, notes_root)

    project = note.parent.name
    date = dt.date.today().strftime("%Y-%m-%d")
    rel = note.relative_to(notes_root).as_posix()
    topics = parse_topics(note)
    # 노트에 적힌 수준이 우선이다. 없으면 extract 때의 수준을 쓴다.
    level = note_level(note) or pending.get("level")
    level_text = level_label(level) if level in LEVELS else ""
    rows = [
        table_row({
            "날짜": date, "프로젝트": project, "수준": level_text,
            "주제": table_cell(t["title"]), "유형": table_cell(t["type"]), "태그": table_cell(t["tags"]),
            "요약": table_cell(t["summary"]), "노트": f"[{note.stem}#{t['no']}]({rel}#{t['anchor']})",
        })
        for t in topics
    ]
    with index.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(rows) + ("\n" if rows else ""))
    if concept_ids:
        concepts.mark_used(notes_root, concept_ids, rel, date)

    dp = delta_path(notes_root, session)
    if dp.exists():
        dp.unlink()
    print(json.dumps({"committed": str(note), "topics": len(topics), "run_count": state["run_count"],
                      "level": level_text or None, "index": str(index), "concepts": concept_ids},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_status(args) -> int:
    cwd = normalize_cwd(args.cwd)
    notes_root = Path(args.notes_root).expanduser().resolve()
    jsonl, session = resolve_session_file(args.agent, cwd, args.session)
    state = load_state(notes_root, session)
    recs = collect_delta(jsonl, state, args.agent)
    pending_msgs = sum(1 for r in recs if render_blocks(r))
    level, level_source = current_level(notes_root)
    print(json.dumps({
        "agent": args.agent,
        "project": project_name(cwd),
        "transcript": str(jsonl),
        "session": session,
        "run_count": state.get("run_count", 0),
        "last_summarized_at": fmt_local(state.get("last_timestamp")),
        "unsummarized_messages": pending_msgs,
        "files": state.get("files", []),
        **level_info(level),
        "level_source": level_source,
        "in_progress": pending_info(state),
        "catalog_version": concepts.load_catalog()["version"],
        "concepts_used": len(concepts.load_used(notes_root)),
        "settings": str(settings_path(notes_root)),
    }, ensure_ascii=False, indent=2))
    return 0


def pending_info(state: dict) -> dict | None:
    """extract는 했지만 commit은 안 한 정리가 있으면 그 정보, 없으면 None."""
    pending = state.get("_pending")
    if not pending or not pending.get("last_uuid"):
        return None
    note = pending.get("suggested_file")
    return {
        "note": note,
        "note_exists": bool(note) and Path(note).exists(),
        "started_at": pending.get("started_at"),
        "level": level_label(pending["level"]) if pending.get("level") in LEVELS else None,
    }


def is_registered(notes_root: Path, note: Path) -> bool:
    """index.md에 오른 노트인가. 노트 폴더를 함께 쓰는 다른 세션이 같은 이름으로 등록했을 수 있다."""
    index = notes_root / "index.md"
    if not index.exists():
        return False
    return f"]({note.resolve().relative_to(notes_root).as_posix()}#" in index.read_text(encoding="utf-8")


def cmd_cancel(args) -> int:
    """진행 중(extract 후 commit 전)인 정리를 취소한다.

    미완성 노트 파일과 델타 파일을 지우고 pending을 비운다. 체크포인트(last_uuid)는 건드리지 않으므로
    다음 extract가 같은 대화부터 다시 잘라낸다. 이미 commit된 노트(state.files)는 절대 지우지 않는다.
    """
    notes_root = Path(args.notes_root).expanduser().resolve()
    if args.session:
        session = args.session
    else:
        _, session = resolve_session_file(args.agent, normalize_cwd(args.cwd), None)
    state = load_state(notes_root, session)
    pending = state.pop("_pending", None)
    removed_note = None
    if pending and pending.get("suggested_file"):
        note = Path(pending["suggested_file"])
        committed = {Path(f).resolve() for f in state.get("files", [])}
        inside = notes_root in note.resolve().parents
        if note.exists() and inside and note.resolve() not in committed and not is_registered(notes_root, note):
            note.unlink()
            removed_note = str(note)
    dp = delta_path(notes_root, session)
    removed_delta = dp.exists()
    if removed_delta:
        dp.unlink()
    if state_path(notes_root, session).exists() or pending:
        save_state(notes_root, session, state)
    print(json.dumps({
        "cancelled": bool(pending),
        "session": session,
        "removed_note": removed_note,
        "removed_delta": removed_delta,
        "checkpoint_kept_at": fmt_local(state.get("last_timestamp")),
        "message": ("정리를 취소했습니다. 체크포인트는 그대로라서 다음 실행 때 같은 대화부터 다시 정리합니다."
                    if pending else "진행 중인 정리가 없습니다."),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_concept(args) -> int:
    """노트를 쓸 항목의 내용을 사전에서 꺼내 보여 준다."""
    print(json.dumps({"concepts": concepts.concept_details(concepts.load_catalog(), args.ids)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_candidate(args) -> int:
    """사전에 없는 개념을 후보함에 적는다. 같은 이름은 다시 적지 않는다."""
    notes_root = Path(args.notes_root).expanduser().resolve()
    path = notes_root / CANDIDATE_FILE
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    else:
        existing = "# 사전 후보함\n\n대화에 나왔지만 개념사전에 없는 개념입니다. 사전을 늘릴 때 참고합니다.\n\n| 날짜 | 개념 | 프로젝트 |\n|---|---|---|\n"
    known = {c.strip().lower() for row in existing.splitlines() if row.startswith("|") for c in row.split("|")[2:3]}
    project = project_name(normalize_cwd(args.cwd))
    date = dt.date.today().strftime("%Y-%m-%d")
    added = []
    for title in args.title:
        name = table_cell(unicodedata.normalize("NFC", title))
        if name and name.lower() not in known:
            existing += f"| {date} | {name} | {table_cell(project)} |\n"
            known.add(name.lower())
            added.append(name)
    notes_root.mkdir(parents=True, exist_ok=True)
    path.write_text(existing, encoding="utf-8")
    print(json.dumps({"added": added, "file": str(path)}, ensure_ascii=False, indent=2))
    return 0


def cmd_level(args) -> int:
    """설명 수준 보기(값 없이)·바꾸기(값과 함께)."""
    notes_root = Path(args.notes_root).expanduser().resolve()
    if args.value:
        try:
            level = parse_level(" ".join(args.value))
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        remember_level(notes_root, level)
        out = {**level_info(level), "level_source": "saved", "settings": str(settings_path(notes_root))}
    else:
        level, source = current_level(notes_root)
        out = {**level_info(level), "level_source": source}
        if source == "unset":
            out["levels"] = level_table()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    # Windows 콘솔(cp949)에서 한글 JSON 출력이 깨지거나 예외가 나지 않도록
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
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
    p.add_argument("--level", default=None,
                   help="이번 노트의 설명 수준: 1~5 또는 왕초보·입문·기초·실전·심화 (다음 실행을 위해 기억된다)")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("commit", help="작성한 노트를 등록하고 체크포인트 갱신")
    common(p)
    p.add_argument("--file", required=True, help="작성한 노트 md 경로")
    p.set_defaults(fn=cmd_commit)

    p = sub.add_parser("concept", help="사전 항목의 학습 목표·선수 개념·공식 문서 보기")
    p.add_argument("ids", nargs="+", help="항목 id (extract 출력의 candidates에 있다)")
    p.set_defaults(fn=cmd_concept)

    p = sub.add_parser("candidate", help="사전에 없는 개념을 후보함에 적기")
    p.add_argument("--title", action="append", required=True, help="개념 이름. 여러 번 줄 수 있다")
    p.add_argument("--cwd", default=os.getcwd(), help="프로젝트 작업 디렉터리(기본: 현재)")
    p.add_argument("--notes-root", default=str(DEFAULT_NOTES_ROOT))
    p.set_defaults(fn=cmd_candidate)

    p = sub.add_parser("status", help="체크포인트와 미정리 메시지 수 확인")
    common(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("cancel", help="진행 중인 정리 취소 (미완성 노트·델타 삭제, 체크포인트 유지)")
    common(p)
    p.set_defaults(fn=cmd_cancel)

    p = sub.add_parser("level", help="설명 수준 보기·바꾸기 (1 왕초보 · 2 입문 · 3 기초 · 4 실전 · 5 심화)")
    p.add_argument("value", nargs="*", help="바꿀 단계. 비우면 지금 단계를 보여 준다")
    p.add_argument("--notes-root", default=str(DEFAULT_NOTES_ROOT))
    p.set_defaults(fn=cmd_level)

    args = ap.parse_args(argv)
    if args.cmd == "commit" and not args.session:
        ap.error("commit에는 --session 이 필요합니다")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
