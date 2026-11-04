"""개념사전 읽기, 대화에서 후보 찾기, 개념노트 검사. 표준 라이브러리만 쓴다.

스킬 폴더만 복사해 설치해도 돌아가도록 사전(catalog.json)과 함께 이 폴더 안에 둔다.
저장소의 catalog/tools/catalog.py도 노트 검사는 이 파일의 것을 쓴다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

CATALOG_FILE = Path(__file__).resolve().parents[1] / "catalog.json"
USED_FILE = "concepts_used.json"
MAX_TOPICS_PER_NOTE = 5
CANDIDATE_LIMIT = 20
STARS = {1: "★★★", 2: "★★", 3: "★"}
# 학습장 앱 앞단(Cloudflare)이 명령 주입으로 보고 업로드를 403으로 막는 모양. 2026-11-03에 운영에서 시험해 찾았다.
# 백틱·파이프·세미콜론 뒤, 또는 작은따옴표로 끝난 줄의 바로 다음 줄에 명령이 오면 걸린다.
# 앞단의 판단이 들쭉날쭉해 통과하는 표기(`curl x`)까지 조금 넓게 잡는다. 다른 규칙이 더 있을 수 있어 전부를 보장하지는 못한다.
UPLOAD_BLOCKED_RE = re.compile(r"(?:[`|;]\s*|'\n)(?:python\s+-[cm]\b|curl\s+\S|wget\s+\S|perl\s+-e\b)")

NOTE_SECTIONS = (
    "학습 목표", "먼저 알아야 할 것", "왜 필요한가", "핵심 개념", "예제로 이해하기", "비슷한 개념과 차이",
    "흔한 실수", "직접 해 보기", "확인 문제", "정답", "공식 문서",
)
NOTE_OPTIONAL_LAST = "만난 곳"
NOTE_MIN_CHARS = {1: 1500, 2: 2500, 3: 4000, 4: 4000, 5: 4000}
# 노트 본문이 특정 프로젝트나 그때의 대화를 전제하지 않게 막는다. 코드 블록 밖에서만 본다.
NOTE_BANNED_RE = re.compile(
    r"이번 대화|이번 작업|이번 실행|이 실행에서|이 대화|이 프로젝트|우리 프로젝트|우리 앱|우리 서비스|이 저장소|사용자가 (요청|말)|앞서 (말|만든)|"
    r"(backend|frontend|harness|scripts|docs|samples)/[\w./-]+"
)
NOTE_META_RE = re.compile(r"`개념`\s*([a-z0-9.-]+)")
NOTE_HEADING_RE = re.compile(r"^## (?:\d+\.\s*)?(.+?)\s*$")
NOTE_SUBHEADING_RE = re.compile(r"^### (.+?)\s*$")


def split_note_topics(text: str) -> list[tuple[str, list[str]]]:
    """코드 블록을 건너뛰며 노트를 주제별로 나눈다. 목차는 주제가 아니다."""
    topics: list[tuple[str, list[str]]] = []
    fence = None
    for line in text.split("\n"):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
        heading = NOTE_HEADING_RE.match(line) if fence is None else None
        if heading:
            if heading.group(1) != "목차":
                topics.append((heading.group(1), []))
            else:
                topics.append(("", []))
            continue
        if topics:
            topics[-1][1].append(line)
    return [(title, lines) for title, lines in topics if title]


def strip_fences(lines: list[str]) -> list[str]:
    """코드 블록을 뺀 줄만 남긴다."""
    kept, fence = [], None
    for line in lines:
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            mark = marker.group(1)
            if fence is None:
                fence = mark
                continue
            if mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
                continue
        if fence is None:
            kept.append(line)
    return kept


def lint_note(text: str, catalog: dict) -> list[str]:
    """개념노트가 사전과 맞고, 대화를 몰라도 읽히는 모양인지 검사한다."""
    by_id = {item["id"]: item for item in catalog["items"]}
    errors: list[str] = []
    topics = split_note_topics(text)
    if not topics:
        return ["주제(## 제목)가 없다"]
    for title, lines in topics:
        label = title[:30]
        meta = next((NOTE_META_RE.search(line) for line in lines if NOTE_META_RE.search(line)), None)
        if meta is None:
            errors.append(f"{label}: 메타 줄에 `개념` id가 없다")
            continue
        item = by_id.get(meta.group(1))
        if item is None:
            errors.append(f"{label}: 사전에 없는 id {meta.group(1)}")
            continue
        if not title.startswith(item["title"]):
            errors.append(f"{label}: 제목이 사전의 제목({item['title']})으로 시작하지 않는다")
        prose = strip_fences(lines)
        sections = [m.group(1) for m in map(NOTE_SUBHEADING_RE.match, prose) if m]
        expected = [name for name in sections if name != NOTE_OPTIONAL_LAST]
        if expected != list(NOTE_SECTIONS):
            errors.append(f"{label}: 소제목이 정해진 순서와 다르다: {expected}")
        joined = "\n".join(prose)
        for objective in item.get("objectives", []):
            if objective not in joined:
                errors.append(f"{label}: 학습 목표가 빠졌다: {objective}")
        for found in NOTE_BANNED_RE.finditer(re.sub(r"https?://\S+", "", joined)):
            errors.append(f"{label}: 프로젝트·대화에 묶인 표현: {found.group(0)}")
        if not re.search(r"\]\(https://", section_text(prose, "공식 문서")):
            errors.append(f"{label}: 공식 문서 링크가 없다")
        if not re.search(r"(?m)^\s*1\. ", section_text(prose, "정답")):
            errors.append(f"{label}: 정답이 없다")
        questions = len(re.findall(r"(?m)^\s*\d+\. ", section_text(prose, "확인 문제")))
        if questions < 2:
            errors.append(f"{label}: 확인 문제는 2개 이상이다")
        if questions != len(re.findall(r"(?m)^\s*\d+\. ", section_text(prose, "정답"))):
            errors.append(f"{label}: 확인 문제와 정답의 수가 다르다")
        if sum(len(line) for line in lines) < NOTE_MIN_CHARS[item["level"]]:
            errors.append(f"{label}: {item['level']}단계 노트로 너무 짧다({sum(len(line) for line in lines)}자)")
    return errors


def section_text(prose: list[str], name: str) -> str:
    """소제목 하나의 내용을 돌려준다."""
    collected, inside = [], False
    for line in prose:
        match = NOTE_SUBHEADING_RE.match(line)
        if match:
            inside = match.group(1) == name
            continue
        if inside:
            collected.append(line)
    return "\n".join(collected)


# ---------- 사전 읽기 ----------

def load_catalog(path: Path = CATALOG_FILE) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"개념사전을 읽을 수 없습니다: {path} ({exc}). 스킬을 다시 설치하세요") from None


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def _name_pattern(name: str) -> re.Pattern:
    """영문 이름은 낱말 경계를 본다('API'가 'rapid'에 걸리지 않게). 한글은 조사가 붙으므로 경계를 보지 않는다."""
    escaped = re.escape(name)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])" if name.isascii() else escaped)


def find_candidates(text: str, catalog: dict, level: int, used, limit: int = CANDIDATE_LIMIT) -> dict:
    """대화에 이름이 나온 주제를 찾는다. 용어가 나오면 그 용어를 가르치는 주제의 점수로 친다.

    "세션"이나 commit처럼 뜻이 넓은 이름(broad_names)은 세지 않는다. 그 개념을 다뤘다는 근거가 못 된다.
    """
    haystack = _normalize(text)
    broad = {_normalize(name) for name in catalog.get("broad_names", [])}
    by_id = {item["id"]: item for item in catalog["items"]}
    hits: Counter = Counter()
    matched: dict[str, set] = {}
    for item in catalog["items"]:
        topic = item if item["kind"] == "topic" else by_id.get(item.get("parent"))
        if topic is None or topic["id"] in used:
            continue
        names = {_normalize(n).strip() for n in (item["title"], item["en"], *item.get("aliases", []))}
        for name in names:
            if len(name) < 2 or name in broad or name not in haystack:
                continue
            count = len(_name_pattern(name).findall(haystack))
            if count:
                hits[topic["id"]] += count
                matched.setdefault(topic["id"], set()).add(name)
    at_level = [by_id[i] for i in hits if by_id[i]["level"] == level]
    at_level.sort(key=lambda item: (item["importance"], -hits[item["id"]], item["id"]))
    others = Counter(by_id[i]["level"] for i in hits if by_id[i]["level"] != level)
    return {
        "candidates": [
            {"id": item["id"], "title": item["title"], "en": item["en"], "importance": STARS[item["importance"]],
             "hits": hits[item["id"]], "matched": sorted(matched[item["id"]])[:4]}
            for item in at_level[:limit]
        ],
        "candidate_total": len(at_level),
        "other_levels": {str(k): others[k] for k in sorted(others)},
    }


def concept_details(catalog: dict, ids: list[str]) -> list[dict]:
    """노트를 쓰는 데 필요한 내용을 모은다: 항목 자체, 선수 개념, 헷갈리는 개념, 함께 풀어 줄 용어."""
    by_id = {item["id"]: item for item in catalog["items"]}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise SystemExit(f"사전에 없는 id입니다: {', '.join(missing)}")
    brief = lambda item: {"id": item["id"], "title": item["title"], "level": item["level"], "summary": item["summary"]}
    details = []
    for concept_id in ids:
        item = by_id[concept_id]
        details.append({
            **{k: item[k] for k in ("id", "title", "en", "kind", "level", "group", "summary") if k in item},
            "importance": STARS[item["importance"]],
            "objectives": item.get("objectives", []),
            "refs": item.get("refs", []),
            "prerequisites": [brief(by_id[p]) for p in item.get("prerequisites", []) if p in by_id],
            "related": [brief(by_id[r]) for r in item.get("related", []) if r in by_id],
            "terms": [brief(t) for t in catalog["items"] if t.get("parent") == concept_id],
        })
    return details


# ---------- 한 번 쓴 개념 ----------

def load_used(notes_root: Path) -> dict:
    path = notes_root / USED_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def mark_used(notes_root: Path, ids: list[str], note: str, date: str) -> None:
    used = load_used(notes_root)
    for concept_id in ids:
        used[concept_id] = {"note": note, "date": date}
    (notes_root / USED_FILE).write_text(json.dumps(used, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------- 등록 전 검사 ----------

def frontmatter(text: str) -> dict[str, str]:
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return values
        key, sep, value = line.partition(":")
        if sep:
            values[key.strip()] = value.strip().strip("'\"")
    return {}


def note_concept_ids(text: str) -> list[str]:
    return [found for _, lines in split_note_topics(text) for found in _meta_ids(lines)]


def _meta_ids(lines: list[str]) -> list[str]:
    for line in strip_fences(lines):
        match = NOTE_META_RE.search(line)
        if match:
            return [match.group(1)]
    return []


def lint_concept_note(text: str, catalog: dict, used, max_topics: int = MAX_TOPICS_PER_NOTE) -> list[str]:
    """lint_note에 더해, 앱과 index.md가 읽는 모양과 '한 번 쓴 개념은 다시 쓰지 않는다'를 확인한다."""
    errors = lint_note(text, catalog)
    front = frontmatter(text)
    for key in ("title", "project", "level", "catalog_version"):
        if not front.get(key):
            errors.append(f"frontmatter에 {key}가 없다")
    prose = strip_fences(text.splitlines())
    if len(prose) != len(text.splitlines()) and _fence_left_open(text):
        errors.append("닫히지 않은 코드 블록이 있다")
    for found in list(UPLOAD_BLOCKED_RE.finditer(text))[:3]:
        errors.append(f"학습장 앱 업로드가 막히는 표기다: {found.group(0)!r}. 명령은 언어를 지정한 코드 블록(```bash)으로 옮기고, 여러 줄이면 함수로 묶어 줄 앞에 명령이 바로 오지 않게 한다")
    if _toc_has_prose(prose):
        errors.append("목차 아래에는 표만 쓴다. 앱이 목차를 버리므로 다른 글은 사라진다. 환경 설명은 주제의 예제로 옮긴다")
    h1 = next((i for i, line in enumerate(prose) if re.match(r"^# ", line)), None)
    if h1 is None:
        errors.append("H1 제목(# )이 없다")
    elif not any(line.startswith("> 설명 수준:") for line in prose[h1 + 1 : h1 + 3]):
        errors.append("H1 바로 아래 인용문 첫 줄에 '> 설명 수준:'이 없다")
    for line in prose:
        if line.startswith("## ") and line.strip() != "## 목차" and not re.match(r"^## \d+\. ", line):
            errors.append(f"주제 제목은 '## N. 제목' 모양이어야 한다: {line[:40]}")
    topics = split_note_topics(text)
    if len(topics) > max_topics:
        errors.append(f"한 노트의 주제는 {max_topics}개까지다: {len(topics)}개")
    by_id = {item["id"]: item for item in catalog["items"]}
    seen: set[str] = set()
    for title, lines in topics:
        label = title[:30]
        body = strip_fences(lines)
        meta = next((line for line in body if NOTE_META_RE.search(line)), "")
        for field in ("`유형`", "`태그`", "`난이도`", "`단계`", "`중요도`"):
            if meta and field not in meta:
                errors.append(f"{label}: 메타 줄에 {field} 칸이 없다")
        if not any(line.startswith("> 한 줄 요약") for line in body):
            errors.append(f"{label}: '> 한 줄 요약:' 줄이 없다")
        for concept_id in _meta_ids(lines):
            item = by_id.get(concept_id)
            if concept_id in seen:
                errors.append(f"{label}: 같은 개념이 두 번 나온다: {concept_id}")
            seen.add(concept_id)
            if concept_id in used:
                errors.append(f"{label}: 이미 쓴 개념이다: {concept_id}")
            if item is None:
                continue
            if item["kind"] != "topic":
                errors.append(f"{label}: 용어는 주제가 될 수 없다. '{item.get('parent')}'로 쓴다")
            if str(item["level"]) != front.get("level"):
                errors.append(f"{label}: 이 개념은 {item['level']}단계인데 노트는 {front.get('level')}단계다")
    return errors


def _toc_has_prose(prose: list[str]) -> bool:
    in_toc = False
    for line in prose:
        if line.startswith("## "):
            in_toc = line.strip() == "## 목차"
        elif in_toc and line.strip() and not line.startswith("|") and line.strip() != "---":
            return True
    return False


def _fence_left_open(text: str) -> bool:
    fence = None
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})(.*)$", line)
        if not marker:
            continue
        mark, rest = marker.group(1), marker.group(2)
        if fence is None:
            fence = mark
        elif mark[0] == fence[0] and len(mark) >= len(fence) and not rest.strip():
            fence = None
    return fence is not None
