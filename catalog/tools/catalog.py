#!/usr/bin/env python3
"""AX 풀스택 개념사전 도구. 표준 라이브러리만 쓴다.

python3 -I catalog/tools/catalog.py check    항목 규칙을 검사한다
python3 -I catalog/tools/catalog.py format   항목 파일을 정해진 모양으로 다시 쓴다
python3 -I catalog/tools/catalog.py build    단계별 사전(md)과 catalog.json을 만든다 (--check면 최신인지만 본다)
python3 -I catalog/tools/catalog.py stats    단계·분야별 항목 수와 목표 대비 현황을 보여 준다
python3 -I catalog/tools/catalog.py links    refs 주소가 살아 있는지 확인한다(네트워크 사용)
python3 -I catalog/tools/catalog.py lint-note <노트.md>   교과서식 개념노트의 규칙을 검사한다
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

CATALOG_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = CATALOG_ROOT.parent / "skills" / "study-notes"
# 노트 검사는 스킬과 같은 코드를 쓴다. 스킬은 폴더만 복사해도 돌아야 해서 그쪽에 둔다.
sys.path.insert(0, str(SKILL_DIR / "scripts"))
from concepts import lint_note, split_note_topics  # noqa: E402

FIELD_ORDER = (
    "id", "title", "en", "kind", "level", "importance", "group", "summary", "objectives",
    "prerequisites", "parent", "related", "aliases", "refs", "volatile", "checked_at", "replaced_by",
)
REQUIRED = ("id", "title", "en", "kind", "level", "importance", "group", "summary", "aliases")
KINDS = ("topic", "term")
STARS = {1: "★★★", 2: "★★", 3: "★"}
ID_RE = re.compile(r"^[a-z]+(\.[a-z0-9-]+){2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 노트와 사전이 특정 프로젝트나 대화에 묶이지 않게 막는 표현이다.
BANNED_EXPRESSIONS = ("이번 대화", "이 프로젝트", "우리 프로젝트", "우리 앱", "우리 서비스")
# 제목이 문장으로 끝나는지 보는 어미. "람다"처럼 '다'로 끝나는 이름은 막지 않는다.
SENTENCE_ENDINGS = (
    ".", "?", "한다", "있다", "이다", "된다", "않다", "했다", "준다", "는다", "인다", "난다", "낸다", "든다", "른다",
    "는가", "한가", "을까", "를까", "할까", "않나", "만드나",
)
TITLE_MAX = 40
SUMMARY_MIN, SUMMARY_MAX = 15, 120
OBJECTIVES_MIN, OBJECTIVES_MAX = 2, 4
SHARED_ALIAS_LIMIT = 3
UNDERRATED_DEPENDENTS = 3
# refs로 쓰지 않는 곳: 블로그·개인 글, 상업·개인 강의, 위키, 요약 강좌 사이트. 하위 도메인도 막는다(ko.wikipedia.org, xxx.tistory.com).
# 대학이 자기 도메인에 공개한 강의 자료·교재(ocw.mit.edu 등)는 공식 문서가 없는 CS 개념에 예외로 쓴다(sources.md).
BANNED_REF_HOSTS = (
    "roadmap.sh", "medium.com", "velog.io", "tistory.com", "brunch.co.kr", "dev.to", "substack.com", "hashnode.dev",
    "youtube.com", "youtu.be", "inflearn.com", "udemy.com", "coursera.org", "edx.org", "fastcampus.co.kr", "codecademy.com",
    "wikipedia.org", "namu.wiki", "geeksforgeeks.org", "w3schools.com", "tutorialspoint.com", "javatpoint.com", "programiz.com",
)




def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(root: Path = CATALOG_ROOT) -> dict:
    """사전 전체를 읽는다. 항목에는 분야 접두사(_domain)와 파일 안 순서(_order)를 붙인다."""
    domains = read_json(root / "domains.json")
    levels = read_json(root / "levels.json")
    items: list[dict] = []
    for domain in domains:
        path = root / "items" / f"{domain['prefix']}.json"
        if not path.exists():
            continue
        for order, item in enumerate(read_json(path)):
            items.append({**item, "_domain": domain["prefix"], "_order": order})
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    catalog = {"version": version, "domains": domains, "levels": levels, "items": items}
    catalog["broad_names"] = load_broad_names(root)
    return catalog


def load_broad_names(root: Path) -> list[str]:
    """뜻이 넓어 후보 찾기에서 세지 않는 이름. 파일이 없으면 빈 목록이다."""
    path = root / "broad_names.json"
    return read_json(path)["names"] if path.exists() else []


def check_broad_names(catalog: dict) -> list[str]:
    """넓은 이름에 항목의 제목이 섞이면 그 항목을 찾을 수 없게 된다. 오타로 안 쓰이는 이름도 잡는다."""
    errors = []
    names: set[str] = set()
    for item in catalog["items"]:
        titles = {item["title"].lower(), item["en"].lower()}
        names |= titles | {alias.lower() for alias in item["aliases"]}
        if item["kind"] == "topic":
            errors += [f"{item['id']}: 제목이 넓은 이름 목록에 있다: {t}" for t in titles & set(catalog.get("broad_names", []))]
    errors += [f"넓은 이름 목록의 {name}은 어느 항목에도 없다" for name in catalog.get("broad_names", []) if name not in names]
    return errors


def banned_host(url: str) -> str | None:
    """refs로 쓰지 않는 사이트면 그 이름을 돌려준다."""
    host = (urlparse(url).hostname or "").lower()
    return next((name for name in BANNED_REF_HOSTS if host == name or host.endswith("." + name)), None)


def clean_item(item: dict) -> dict:
    """정해진 필드 순서로 저장할 모양을 만든다. 비어 있는 선택 필드는 뺀다."""
    return {key: item[key] for key in FIELD_ORDER if key in item and item[key] not in ([], None, "", False)}


def check_item(item: dict, known_levels: set[int]) -> list[str]:
    """항목 하나만 보고 알 수 있는 규칙을 검사한다."""
    label = item.get("id", "(id 없음)")
    errors = [f"{label}: 알 수 없는 필드 {key}" for key in item if not key.startswith("_") and key not in FIELD_ORDER]
    missing = [key for key in REQUIRED if item.get(key) in (None, "", [])]
    if missing:
        return errors + [f"{label}: 필수 필드 없음 {missing}"]
    if not ID_RE.match(item["id"]):
        errors.append(f"{label}: id 형식은 <분야>.<묶음>.<이름>이다")
    elif item["id"].split(".")[0] != item["_domain"]:
        errors.append(f"{label}: id 접두사가 파일 분야({item['_domain']})와 다르다")
    if item["kind"] not in KINDS:
        errors.append(f"{label}: kind는 topic 또는 term이다")
    if item["level"] not in known_levels:
        errors.append(f"{label}: level은 1~5다")
    if item["importance"] not in STARS:
        errors.append(f"{label}: importance는 1(필수)·2(중요)·3(선택)이다")
    title, summary = item["title"], item["summary"]
    if len(title) > TITLE_MAX or title.endswith(SENTENCE_ENDINGS):
        errors.append(f"{label}: 제목은 {TITLE_MAX}자 이내의 이름으로 쓴다(문장 금지): {title}")
    if not SUMMARY_MIN <= len(summary) <= SUMMARY_MAX or not summary.endswith("."):
        errors.append(f"{label}: 요약은 {SUMMARY_MIN}~{SUMMARY_MAX}자의 한 문장이고 마침표로 끝난다")
    objectives = item.get("objectives", [])
    if item["kind"] == "topic":
        if not OBJECTIVES_MIN <= len(objectives) <= OBJECTIVES_MAX:
            errors.append(f"{label}: 주제의 학습 목표는 {OBJECTIVES_MIN}~{OBJECTIVES_MAX}개다")
        if not item.get("refs"):
            errors.append(f"{label}: 주제는 공식 자료 링크(refs)가 필요하다")
    elif objectives:
        errors.append(f"{label}: 용어에는 학습 목표를 쓰지 않는다")
    elif not item.get("parent") and not item.get("refs"):
        errors.append(f"{label}: 부모 주제가 없는 용어는 공식 자료 링크(refs)가 필요하다")
    for objective in objectives:
        if not objective.endswith("수 있다"):
            errors.append(f"{label}: 학습 목표는 '~할 수 있다'로 끝난다: {objective}")
    for text in [title, summary, *objectives]:
        for banned in BANNED_EXPRESSIONS:
            if banned in text:
                errors.append(f"{label}: 프로젝트·대화에 묶인 표현 금지({banned.strip()}): {text}")
    aliases = item["aliases"]
    if len(set(aliases)) != len(aliases) or any(len(alias.strip()) < 2 for alias in aliases):
        errors.append(f"{label}: 별칭은 겹치지 않는 2자 이상이다")
    for ref in item.get("refs", []):
        if not ref.startswith("https://"):
            errors.append(f"{label}: 링크는 https로 시작한다: {ref}")
        banned = banned_host(ref)
        if banned:
            errors.append(f"{label}: 블로그·상업 강의·위키는 자료로 쓰지 않는다({banned}). 공식 문서나 대학 공개 강의를 쓴다: {ref}")
    if item.get("volatile") and not DATE_RE.match(str(item.get("checked_at", ""))):
        errors.append(f"{label}: 빠르게 바뀌는 항목은 확인 날짜(checked_at, YYYY-MM-DD)가 필요하다")
    return errors


def find_cycle(items: list[dict]) -> list[str] | None:
    """선수 개념의 순환을 찾는다. 없으면 None이다."""
    edges = {item["id"]: item.get("prerequisites", []) for item in items if "id" in item}
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for parent in edges.get(node, []):
            if state.get(parent) == 1:
                return [*stack[stack.index(parent):], parent]
            if parent not in state:
                found = visit(parent)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return None

    for node in edges:
        if node not in state:
            found = visit(node)
            if found:
                return found
    return None


def sort_key(item: dict) -> tuple[int, int, int]:
    """파일 안에서 지킬 순서: 단계, 주제 먼저, 중요도 순."""
    return item["level"], KINDS.index(item["kind"]), item["importance"]


def check_catalog(catalog: dict) -> tuple[list[str], list[str]]:
    """사전 전체를 검사해 (오류, 경고)를 돌려준다."""
    items = catalog["items"]
    known_levels = {level["level"] for level in catalog["levels"]}
    errors: list[str] = []
    warnings: list[str] = []
    for item in items:
        errors.extend(check_item(item, known_levels))
    ids = Counter(item.get("id") for item in items)
    errors.extend(f"{key}: id가 겹친다" for key, count in ids.items() if count > 1)
    if errors:
        return errors, warnings

    by_id = {item["id"]: item for item in items}
    for item in items:
        label = item["id"]
        for field in ("prerequisites", "related"):
            for other in item.get(field, []):
                if other == label or other not in by_id:
                    errors.append(f"{label}: {field}에 없는 항목 {other}")
        for other in item.get("prerequisites", []):
            if other in by_id and by_id[other]["level"] > item["level"]:
                errors.append(f"{label}: 선수 개념 {other}의 단계가 더 높다")
        parent = item.get("parent")
        if parent:
            target = by_id.get(parent)
            if item["kind"] != "term":
                errors.append(f"{label}: parent는 용어에만 쓴다")
            elif target is None or target["kind"] != "topic":
                errors.append(f"{label}: parent는 있는 주제여야 한다: {parent}")
            elif target["level"] > item["level"]:
                errors.append(f"{label}: parent {parent}의 단계가 더 높다")
    cycle = find_cycle(items)
    if cycle:
        errors.append("선수 개념 순환: " + " → ".join(cycle))

    previous: dict[str, tuple[int, int, int]] = {}
    for item in items:
        key = sort_key(item)
        if key < previous.get(item["_domain"], (0, 0, 0)):
            errors.append(f"{item['id']}: 파일 안 순서는 단계, 주제 먼저, 중요도 순이어야 한다")
        previous[item["_domain"]] = key

    shared = Counter()
    for item in items:
        for alias in item["aliases"]:
            shared[(item["level"], alias.lower())] += 1
    for (level, alias), count in shared.items():
        if count > SHARED_ALIAS_LIMIT:
            warnings.append(f"{level}단계에서 별칭 '{alias}'를 {count}개 항목이 함께 쓴다(너무 넓을 수 있다)")
    for item in items:
        if item["importance"] == 1:
            for parent in item.get("prerequisites", []):
                if parent in by_id and by_id[parent]["importance"] > 1:
                    warnings.append(f"{item['id']}: 필수(★★★)인데 선수 개념 {parent}의 중요도가 더 낮다")
    dependents = dependent_counts(items)
    for item in items:
        if item["importance"] == 3 and dependents[item["id"]] >= UNDERRATED_DEPENDENTS:
            warnings.append(f"{item['id']}: 선택(★)인데 {dependents[item['id']]}개 항목의 선수 개념이다. 중요도를 다시 볼 것")
    errors += check_broad_names(catalog)
    return errors, warnings


def dependent_counts(items: list[dict]) -> Counter:
    """각 항목을 선수 개념으로 삼는 항목 수."""
    counts: Counter = Counter()
    for item in items:
        for parent in item.get("prerequisites", []):
            counts[parent] += 1
    return counts


def effective_importance(items: list[dict]) -> dict[str, int]:
    """중요한 항목의 선수 개념은 그만큼 중요하다. 목록 안에서 뒤따르는 항목의 중요도를 끌어온다."""
    effective = {item["id"]: item["importance"] for item in items}
    changed = True
    while changed:
        changed = False
        for item in items:
            for parent in item.get("prerequisites", []):
                if parent in effective and effective[item["id"]] < effective[parent]:
                    effective[parent] = effective[item["id"]]
                    changed = True
    return effective


def study_order(items: list[dict], domain_order: dict[str, int]) -> list[dict]:
    """주제를 공부 순서로 늘어놓는다. 선수 개념을 먼저 두고, 그 안에서는 중요도가 높은 것을 앞에 둔다."""
    remaining = {item["id"]: item for item in items}
    effective = effective_importance(items)
    ordered: list[dict] = []
    while remaining:
        ready = [
            item for item in remaining.values()
            if not any(parent in remaining for parent in item.get("prerequisites", []))
        ]
        if not ready:  # 순환은 check가 막는다. 혹시 남으면 원래 순서로 잇는다.
            ready = list(remaining.values())
        chosen = min(ready, key=lambda it: (effective[it["id"]], domain_order[it["_domain"]], it["_order"]))
        ordered.append(chosen)
        del remaining[chosen["id"]]
    return ordered


def render_level(catalog: dict, level: dict) -> str:
    """단계 하나의 사전을 마크다운으로 만든다."""
    domain_order = {domain["prefix"]: index for index, domain in enumerate(catalog["domains"])}
    names = {domain["prefix"]: domain["name"] for domain in catalog["domains"]}
    items = [item for item in catalog["items"] if item["level"] == level["level"]]
    topics = [item for item in items if item["kind"] == "topic"]
    terms = [item for item in items if item["kind"] == "term"]
    lines = [
        f"# AX 풀스택 개념사전 · {level['level']}단계 {level['name']}",
        "",
        f"> 대상: {level['audience']}. 배우고 나면 {level['can_do']}.",
        f"> 사전 버전 {catalog['version']} · 주제 {len(topics)}개 · 용어 {len(terms)}개",
        "",
        "★★★ 필수 · ★★ 중요 · ★ 선택",
        "",
        "## 공부 순서",
        "",
        "중요한 주제를 앞에 두고, 먼저 알아야 할 주제가 그 앞에 오도록 늘어놓았다.",
        "",
    ]
    ordered = study_order(topics, domain_order)
    lines += [f"{index}. {STARS[item['importance']]} {item['title']} ({names[item['_domain']]})" for index, item in enumerate(ordered, 1)]
    if not ordered:
        lines.append("(아직 없음)")
    lines += ["", "## 1부. 주제", ""]
    for domain in catalog["domains"]:
        group = [item for item in topics if item["_domain"] == domain["prefix"]]
        if not group:
            continue
        lines += [f"### {domain['name']}", ""]
        for item in group:
            lines.append(f"- {STARS[item['importance']]} **{item['title']} ({item['en']})** `{item['id']}`: {item['summary']}")
            lines.extend(f"  - 목표: {objective}" for objective in item["objectives"])
        lines.append("")
    lines += ["## 2부. 용어", ""]
    for domain in catalog["domains"]:
        group = [item for item in terms if item["_domain"] == domain["prefix"]]
        if not group:
            continue
        lines += [f"### {domain['name']}", ""]
        lines.extend(f"- {STARS[item['importance']]} **{item['title']} ({item['en']})**: {item['summary']}" for item in group)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_index(catalog: dict) -> str:
    """단계·분야별 항목 수를 담은 첫 화면을 만든다."""
    items = catalog["items"]
    lines = [
        "# AX 풀스택 개념사전",
        "",
        f"사전 버전 {catalog['version']}. 이 폴더의 파일은 `catalog/tools/catalog.py build`가 만든다. 직접 고치지 말고 `catalog/items/`를 고친다.",
        "",
        "| 단계 | 대상 | 배우고 나면 | 주제 | 용어 |",
        "|---|---|---|---|---|",
    ]
    for level in catalog["levels"]:
        count = Counter(item["kind"] for item in items if item["level"] == level["level"])
        name = f"{level['level']}단계_{level['name']}"
        lines.append(f"| [{level['level']}단계 {level['name']}]({name}.md) | {level['audience']} | {level['can_do']} | {count['topic']} | {count['term']} |")
    return "\n".join(lines) + "\n"


def compact_catalog(text: str) -> str:
    """스킬에 넣는 사전. 사람이 읽을 일이 없으니 공백을 뺀다."""
    return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":")) + "\n"


def build_outputs(catalog: dict) -> dict[str, str]:
    """파일 이름별 생성 결과."""
    outputs = {"README.md": render_index(catalog)}
    for level in catalog["levels"]:
        outputs[f"{level['level']}단계_{level['name']}.md"] = render_level(catalog, level)
    payload = {
        "version": catalog["version"],
        "domains": catalog["domains"],
        "levels": catalog["levels"],
        "broad_names": catalog.get("broad_names", []),
        "items": [{**clean_item(item), "domain": item["_domain"]} for item in catalog["items"]],
    }
    outputs["catalog.json"] = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    return outputs


def format_items(root: Path, catalog: dict) -> int:
    """항목 파일을 정해진 모양으로 다시 쓴다. 바뀐 파일 수를 돌려준다."""
    changed = 0
    for domain in catalog["domains"]:
        path = root / "items" / f"{domain['prefix']}.json"
        if not path.exists():
            continue
        group = [clean_item(item) for item in catalog["items"] if item["_domain"] == domain["prefix"]]
        text = json.dumps(group, ensure_ascii=False, indent=2) + "\n"
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def cmd_lint_note(root: Path, path: Path) -> int:
    errors = lint_note(path.read_text(encoding="utf-8"), load_catalog(root))
    for error in errors:
        print("오류:", error)
    print(f"주제 {len(split_note_topics(path.read_text(encoding='utf-8')))}개, 오류 {len(errors)}개")
    return 1 if errors else 0


def cmd_check(root: Path) -> int:
    catalog = load_catalog(root)
    errors, warnings = check_catalog(catalog)
    for warning in warnings:
        print("경고:", warning)
    for error in errors:
        print("오류:", error)
    print(f"항목 {len(catalog['items'])}개, 오류 {len(errors)}개, 경고 {len(warnings)}개")
    return 1 if errors else 0


def cmd_format(root: Path) -> int:
    print("다시 쓴 파일", format_items(root, load_catalog(root)), "개")
    return 0


def cmd_build(root: Path, check_only: bool) -> int:
    catalog = load_catalog(root)
    errors, _ = check_catalog(catalog)
    if errors:
        print("\n".join(errors))
        return 1
    dist = root / "dist"
    outputs = build_outputs(catalog)
    stale = [name for name, text in outputs.items() if not (dist / name).exists() or (dist / name).read_text(encoding="utf-8") != text]
    # 스킬은 폴더만 복사해 설치해도 돌아야 하므로 스킬 폴더에도 사전을 넣는다.
    bundle = SKILL_DIR / "catalog.json"
    bundled = compact_catalog(outputs["catalog.json"])
    bundle_stale = root == CATALOG_ROOT and (not bundle.exists() or bundle.read_text(encoding="utf-8") != bundled)
    if check_only:
        names = stale + ([str(bundle)] if bundle_stale else [])
        print("최신이 아닌 파일:" if names else "모두 최신이다", *names)
        return 1 if names else 0
    dist.mkdir(exist_ok=True)
    for name in stale:
        (dist / name).write_text(outputs[name], encoding="utf-8")
    if bundle_stale:
        bundle.write_text(bundled, encoding="utf-8")
    print("만든 파일", len(stale) + bool(bundle_stale), "개")
    return 0


def cmd_stats(root: Path) -> int:
    catalog = load_catalog(root)
    items = catalog["items"]
    print(f"사전 버전 {catalog['version']}, 항목 {len(items)}개")
    for level in catalog["levels"]:
        group = [item for item in items if item["level"] == level["level"]]
        count = Counter(item["kind"] for item in group)
        print(f"{level['level']}단계 {level['name']}: 주제 {count['topic']}/{level['targets']['topic']}, 용어 {count['term']}/{level['targets']['term']}")
    for domain in catalog["domains"]:
        group = [item for item in items if item["_domain"] == domain["prefix"]]
        stars = Counter(STARS[item["importance"]] for item in group)
        print(f"{domain['name']}: {len(group)}개 {dict(stars)}")
    return 0


def cmd_links(root: Path) -> int:
    catalog = load_catalog(root)
    urls = sorted({ref for item in catalog["items"] for ref in item.get("refs", [])})
    broken = 0
    for url in urls:
        # 파이썬 배포판에 따라 인증서 묶음이 없어 urllib이 실패하므로 curl을 쓴다.
        result = subprocess.run(
            ["curl", "-sL", "-o", os.devnull, "-m", "25", "-A", "Mozilla/5.0", "-w", "%{http_code}", url],
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        if status != "200":
            broken += 1
        print(status, url)
    print(f"링크 {len(urls)}개, 문제 {broken}개")
    return 1 if broken else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AX 풀스택 개념사전 도구")
    parser.add_argument("--root", type=Path, default=CATALOG_ROOT, help="사전 폴더(테스트용)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "format", "stats", "links"):
        sub.add_parser(name)
    sub.add_parser("build").add_argument("--check", action="store_true", help="파일을 쓰지 않고 최신인지만 본다")
    sub.add_parser("lint-note").add_argument("note", type=Path, help="검사할 개념노트 md")
    args = parser.parse_args(argv)
    if args.command == "build":
        return cmd_build(args.root, args.check)
    if args.command == "lint-note":
        return cmd_lint_note(args.root, args.note)
    return {"check": cmd_check, "format": cmd_format, "stats": cmd_stats, "links": cmd_links}[args.command](args.root)


if __name__ == "__main__":
    sys.exit(main())
