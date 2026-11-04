#!/usr/bin/env python3
"""dic-maker: 개념사전을 단계·분야별로 늘리는 도구. 표준 라이브러리만 쓴다.

모든 명령은 사전 저장소(catalog/tools/catalog.py가 있는 폴더)에서 실행한다. 다른 곳이면 --repo로 가리킨다.

python3 -I <스킬>/scripts/dic_maker.py gaps [--level N]            단계·분야별 격차, 사다리 빈칸, 후보함
python3 -I <스킬>/scripts/dic_maker.py start [--level N] [--count 30] [--box]   이번 실행 계획을 세우고 초안 파일 자리를 만든다
python3 -I <스킬>/scripts/dic_maker.py guide --domain <분야> [--level N]       조사 에이전트가 읽을 규칙·기준·기존 항목
python3 -I <스킬>/scripts/dic_maker.py check [--links]              초안 전체 검사(사전 규칙·겹침·별칭 오탐·근거·자료)
python3 -I <스킬>/scripts/dic_maker.py alias-audit [--all | --draft] 별칭이 실제 대화에서 얼마나 흔한지 잰다
python3 -I <스킬>/scripts/dic_maker.py review-sheet                 사람이 볼 검토 표(md)를 만든다
python3 -I <스킬>/scripts/dic_maker.py apply --note "변경 설명"     초안을 사전에 넣고 버전을 올린다
python3 -I <스킬>/scripts/dic_maker.py refresh [--days 90] [--links] 빨리 바뀌는 항목과 죽은 링크를 찾는다
python3 -I <스킬>/scripts/dic_maker.py mark-checked --ids <id>...   확인 날짜를 오늘로 바꾼다
python3 -I <스킬>/scripts/dic_maker.py status | cancel
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

WORK_DIR = ".dic-maker"
DRAFT_DIR = "draft"
RUN_FILE = "run.json"
LINKS_FILE = "links.json"
CORPUS_DIR = "corpus"
CORPUS_INDEX = "corpus_index.json"
REVIEW_FILE = "review.md"
HISTORY_DIR = "history"
DEFAULT_COUNT = 30
MAX_COUNT = 60
MAX_DOMAINS_PER_RUN = 5
AGENT_CONCURRENCY = 5
# 초안에만 있는 칸. 사전에 넣을 때 뺀다.
DRAFT_ONLY_FIELDS = ("basis",)
BASIS_MIN = 10
# 실제 대화 기록에서 절반 이상의 세션에 나오는 별칭은 너무 넓다고 본다. 4분의 1 이상이면 경고만 한다.
# 항목 자신의 이름(title·en)은 "API"처럼 흔해도 그 개념의 이름이므로 막지 않는다.
BROAD_SESSION_SHARE = 0.5
BROAD_WARN_SHARE = 0.25
BROAD_MIN_SESSIONS = 4
# 기존 항목과 낱말이 이만큼 겹치면 같은 내용을 다시 쓴 것으로 의심한다.
OVERLAP_JACCARD = 0.5
STALE_DAYS = 90
# 이 응답이면 링크가 죽은 것이다. 403·429 같은 봇 차단은 경고로만 남긴다.
DEAD_LINK_STATUSES = {"000", "404", "410"}
LINK_TIMEOUT = "25"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
PROJECTS_DIR = Path.home() / ".claude" / "projects"
STUDY_NOTES_ROOT = Path(os.environ.get("STUDY_NOTES_ROOT") or (Path.home() / "StudyNotes")).expanduser()
BOX_FILE = "concept_candidates.md"


# ---------- 저장소와 모듈 ----------

def find_repo(path: str | None) -> Path:
    repo = Path(path or os.getcwd()).expanduser().resolve()
    if not (repo / "catalog" / "tools" / "catalog.py").exists():
        raise SystemExit(f"사전 저장소가 아닙니다: {repo}. claude-study-notes를 받은 폴더에서 실행하거나 --repo로 가리키세요.")
    return repo


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Repo:
    """저장소의 사전 도구와 study-notes 스크립트를 함께 쓴다."""

    def __init__(self, root: Path):
        self.root = root
        self.catalog_root = root / "catalog"
        self.tool = load_module(root / "catalog" / "tools" / "catalog.py", "catalog_tool")
        scripts = root / "skills" / "study-notes" / "scripts"
        self.concepts = sys.modules.get("concepts") or load_module(scripts / "concepts.py", "concepts")
        self.study_notes = load_module(scripts / "study_notes.py", "study_notes_tool")
        self.work = root / WORK_DIR

    def catalog(self) -> dict:
        return self.tool.load_catalog(self.catalog_root)

    def read_json(self, name: str, default):
        path = self.work / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    def write_json(self, name: str, data) -> Path:
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path

    def draft_files(self) -> list[Path]:
        folder = self.work / DRAFT_DIR
        return sorted(folder.glob("*.json")) if folder.exists() else []

    def drafts(self) -> list[dict]:
        """초안 항목 전부. 파일 이름은 자유이고 분야는 id 접두사로 정한다."""
        items = []
        for path in self.draft_files():
            try:
                group = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise SystemExit(f"{path.name}: JSON이 아닙니다 ({error})")
            if not isinstance(group, list):
                raise SystemExit(f"{path.name}: 항목 목록(배열)이어야 합니다")
            for order, item in enumerate(group):
                if not isinstance(item, dict):
                    raise SystemExit(f"{path.name}: {order + 1}번째가 객체가 아닙니다")
                items.append({**item, "_file": path.name, "_order": order})
        return items


def today() -> str:
    return dt.date.today().isoformat()


def domain_of(item: dict) -> str:
    return str(item.get("id", "")).split(".")[0]


# ---------- 격차 ----------

def level_rows(catalog: dict) -> list[dict]:
    rows = []
    for level in catalog["levels"]:
        group = [i for i in catalog["items"] if i["level"] == level["level"]]
        count = Counter(i["kind"] for i in group)
        targets = level["targets"]
        total_target = targets["topic"] + targets["term"]
        rows.append({
            "level": level["level"], "name": level["name"],
            "topic": count["topic"], "topic_target": targets["topic"],
            "term": count["term"], "term_target": targets["term"],
            "filled": round((count["topic"] + count["term"]) / total_target, 3) if total_target else 1.0,
        })
    return rows


def domain_counts(catalog: dict, level: int) -> dict[str, Counter]:
    counts: dict[str, Counter] = {d["prefix"]: Counter() for d in catalog["domains"]}
    for item in catalog["items"]:
        if item["level"] == level:
            counts[item["_domain"]][item["kind"]] += 1
    return counts


def ladder_gaps(catalog: dict) -> list[dict]:
    """같은 묶음(group)에 4~5단계 항목만 있고 그 아래 입문 항목이 없는 곳. 심화만 있으면 올라갈 길이 없다."""
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in catalog["items"]:
        if item["kind"] == "topic":
            by_group[(item["_domain"], item["group"])].append(item)
    gaps = []
    for (domain, group), topics in sorted(by_group.items()):
        lowest = min(t["level"] for t in topics)
        if lowest >= 4:
            gaps.append({"domain": domain, "group": group, "lowest_level": lowest,
                         "topics": [t["id"] for t in topics]})
    return gaps


def read_box(path: Path | None = None) -> list[dict]:
    """study-notes 후보함. 날짜 | 개념 | 프로젝트 표를 읽는다."""
    path = path or STUDY_NOTES_ROOT / BOX_FILE
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}$", cells[0]):
            rows.append({"date": cells[0], "name": cells[1], "project": cells[2] if len(cells) > 2 else ""})
    return rows


def box_covered(catalog: dict, rows: list[dict]) -> list[dict]:
    """후보함의 이름이 사전 항목의 제목과 같거나 긴 별칭을 품으면 이미 들어간 것으로 짐작한다. 짐작이라 에이전트가 다시 본다."""
    names = {}
    for item in catalog["items"]:
        for name in (item["title"], item["en"], *item.get("aliases", [])):
            if len(name) >= 4:
                names[name.lower()] = item["id"]
    covered = []
    for row in rows:
        wanted = row["name"].lower()
        hit = names.get(wanted)
        for name, item_id in names.items():
            if hit:
                break
            # 영어 이름은 낱말 경계로("post"가 "postgresql"에 걸리지 않게), 한글은 후보 이름의 3분의 1 이상을 차지할 때만 본다.
            if name.isascii():
                if re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", wanted) and len(name) * 3 >= len(wanted):
                    hit = item_id
            elif (name in wanted and len(name) * 3 >= len(wanted)) or wanted in name:
                hit = item_id
        covered.append({**row, "covered_by": hit})
    return covered


def cmd_gaps(repo: Repo, args) -> int:
    catalog = repo.catalog()
    rows = level_rows(catalog)
    per_domain = {}
    for level in catalog["levels"]:
        if args.level and level["level"] != args.level:
            continue
        per_domain[str(level["level"])] = {d: dict(c) for d, c in domain_counts(catalog, level["level"]).items()}
    box = box_covered(catalog, read_box())
    print(json.dumps({
        "version": catalog["version"],
        "levels": rows,
        "emptiest_level": min(rows, key=lambda r: r["filled"])["level"],
        "domains_by_level": per_domain,
        "ladder_gaps": ladder_gaps(catalog),
        "box": box,
        "box_open": [b["name"] for b in box if not b["covered_by"]],
    }, ensure_ascii=False, indent=2))
    return 0


# ---------- 실행 계획 ----------

def split_count(level: dict, count: int) -> tuple[int, int]:
    """단계 목표치의 주제:용어 비율로 나눈다. 둘 다 1개 이상이다."""
    targets = level["targets"]
    ratio = targets["term"] / max(targets["topic"], 1)
    topics = max(1, round(count / (1 + ratio)))
    return topics, max(1, count - topics)


def plan_domains(catalog: dict, level: int, topics: int, terms: int) -> dict[str, dict]:
    """그 단계에서 가장 비어 있는 분야부터 몫을 나눈다."""
    counts = domain_counts(catalog, level)
    order = sorted(counts, key=lambda d: (sum(counts[d].values()), d))[:MAX_DOMAINS_PER_RUN]
    quotas = {d: {"topic": 0, "term": 0} for d in order}
    for kind, total in (("topic", topics), ("term", terms)):
        for index in range(total):
            quotas[order[index % len(order)]][kind] += 1
    return quotas


def sources_for(repo: Repo, catalog: dict, domain: str) -> str:
    """sources.md의 분야별 표에서 그 분야 행을 찾는다."""
    path = repo.catalog_root / "sources.md"
    if not path.exists():
        return ""
    name = next((d["name"] for d in catalog["domains"] if d["prefix"] == domain), "")
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 2 and cells[0] == name:
            return cells[1]
    return ""


def existing_brief(catalog: dict, domain: str, level: int | None) -> list[dict]:
    return [
        {"id": i["id"], "kind": i["kind"], "level": i["level"], "title": i["title"], "group": i["group"]}
        for i in catalog["items"] if i["_domain"] == domain and (level is None or abs(i["level"] - level) <= 1)
    ]


def cmd_start(repo: Repo, args) -> int:
    run = repo.read_json(RUN_FILE, None)
    if run and not args.force:
        raise SystemExit(f"진행 중인 실행이 있습니다({run['started']}, {run['mode']}). 이어 하려면 status·check를, 버리려면 cancel을 쓰세요.")
    catalog = repo.catalog()
    count = min(args.count or DEFAULT_COUNT, MAX_COUNT)
    box = [b for b in box_covered(catalog, read_box()) if not b["covered_by"]]
    if args.box:
        if not box:
            raise SystemExit("후보함에 사전에 없는 개념이 없습니다.")
        run = {"started": today(), "mode": "box", "level": None, "count": len(box), "quotas": {},
               "box": [b["name"] for b in box], "status": "drafting"}
        drafts = {"box": str(repo.work / DRAFT_DIR / "box.json")}
    else:
        rows = level_rows(catalog)
        level_no = args.level or min(rows, key=lambda r: r["filled"])["level"]
        level = next(l for l in catalog["levels"] if l["level"] == level_no)
        topics, terms = split_count(level, count)
        quotas = plan_domains(catalog, level_no, topics, terms)
        run = {"started": today(), "mode": "level", "level": level_no, "count": count, "topics": topics, "terms": terms,
               "quotas": quotas, "box": [b["name"] for b in box], "status": "drafting"}
        drafts = {d: str(repo.work / DRAFT_DIR / f"{d}.json") for d in quotas}
    (repo.work / DRAFT_DIR).mkdir(parents=True, exist_ok=True)
    for path in repo.draft_files():
        path.unlink()
    repo.write_json(RUN_FILE, run)
    print(json.dumps({
        **run, "draft_files": drafts, "agent_concurrency": AGENT_CONCURRENCY,
        "level_info": next((l for l in catalog["levels"] if l["level"] == run["level"]), None),
        "ladder_gaps": [g for g in ladder_gaps(catalog) if g["domain"] in drafts],
        "domains": {d: {"name": next(x["name"] for x in catalog["domains"] if x["prefix"] == d),
                        "sources": sources_for(repo, catalog, d)} for d in drafts if d != "box"},
    }, ensure_ascii=False, indent=2))
    return 0


RULES = """## 항목 작성 규칙 (dic-maker)

- 자료가 먼저다. 공식 문서·표준·공신력 있는 기관의 페이지에서 그 단계에 맞는 주제를 고르고, 그 페이지를 refs에 넣는다. 블로그·강의·roadmap.sh는 쓰지 않는다. 자료의 문장은 옮기지 않고 요약·목표·별칭·링크만 쓴다.
- basis 칸(초안에만 있음)에 근거를 한 줄로 적는다: 어느 자료의 어느 절에서 왔는지, 왜 이 단계인지(levels의 includes·excludes 기준), 왜 이 중요도인지.
- 단계는 자료의 종류가 아니라 **독자가 배우고 나서 할 수 있게 되는 일**(can_do)로 정한다. 표준 문서에서 왔다고 5단계가 아니고, 사용법 문서에서 왔다고 2단계가 아니다. 쓰는 법을 익히는 항목은 2~3단계, 설계를 고르고 오류 원인을 찾는 항목은 4단계, 내부 동작과 손익을 분석하는 항목만 5단계다.
- 같은 자료의 같은 절로 분야가 다른 항목을 여럿 만들지 않는다. 다른 분야 에이전트가 같은 자료를 쓸 것 같으면 자기 분야에 더 가까운 쪽만 쓴다.
- id는 <분야>.<묶음>.<이름>이고 기존 id와 겹치지 않는다. 묶음은 같은 분야의 기존 group과 맞춘다.
- title은 40자 이내의 이름이고 문장이 아니다. en은 영어 이름. summary는 15~120자 한 문장이고 마침표로 끝난다.
- topic의 objectives는 2~4개, 모두 '~할 수 있다'로 끝난다. 그 단계의 can_do에 맞춘다. term에는 objectives를 쓰지 않는다.
- term은 가르치는 주제가 있으면 parent에 그 주제 id(기존 또는 이번 초안)를 쓴다. 딸린 주제가 없는 독립 용어는 parent 없이 refs를 넣는다.
- aliases는 대화에서 그 개념을 가리킬 때 실제로 쓰는 말 2~6개. 2자 이상, 한글과 영어를 함께. "세션", "토큰", "추론", "fetch", "state"처럼 다른 뜻으로도 흔히 쓰는 말은 넣지 않고 "세션 쿠키", "모델 추론"처럼 좁힌다. title과 en은 자동으로 대조하므로 다시 넣지 않아도 된다.
- prerequisites는 같거나 낮은 단계의 기존 주제 id만. ★★★ 항목의 선수는 ★★★이어야 한다. 4~5단계 주제는 그 아래 입문 주제가 사전에 있는지 보고, 없으면 그 입문 주제도 함께 제안한다.
- 빨리 바뀌는 내용(모델 이름, 가격, 규격 개정)은 volatile: true와 checked_at(오늘 날짜)을 넣는다.
- 기존 항목과 겹치지 않는다. 같은 내용을 더 넓게 또는 좁게 다시 쓰지 않는다. 겹치면 기존 항목을 고치자고 basis에 적고 새 항목은 만들지 않는다.
- 프로젝트·대화에 묶인 표현("이 프로젝트", "우리 앱")과 비밀값을 쓰지 않는다.
"""


def item_format(repo: Repo) -> str:
    readme = repo.catalog_root / "README.md"
    if not readme.exists():
        return ""
    text = readme.read_text(encoding="utf-8")
    match = re.search(r"\n## 항목 형식\n.*?(?=\n## )", text, re.S)
    return match.group(0).strip() if match else ""


def cmd_guide(repo: Repo, args) -> int:
    catalog = repo.catalog()
    parts = [RULES]
    level = next((l for l in catalog["levels"] if l["level"] == args.level), None) if args.level else None
    if level:
        parts.append("## 이 단계의 기준\n" + json.dumps(level, ensure_ascii=False, indent=1))
    else:
        parts.append("## 단계 기준 (전체)\n" + json.dumps(catalog["levels"], ensure_ascii=False, indent=1))
    parts.append(item_format(repo))
    if args.domain:
        domain = next((d for d in catalog["domains"] if d["prefix"] == args.domain), None)
        if domain is None:
            raise SystemExit(f"없는 분야입니다: {args.domain}. 분야: {[d['prefix'] for d in catalog['domains']]}")
        parts.append(f"## 분야 {domain['prefix']} ({domain['name']})\n범위: {domain['covers']}\n기준 자료: {sources_for(repo, catalog, args.domain)}")
        existing = existing_brief(catalog, args.domain, args.level)
        parts.append("## 이 분야의 기존 항목 (근처 단계) — 겹치지 않게 보고, 묶음(group) 이름을 맞춘다\n" +
                     "\n".join(f"- {i['id']} [{i['kind']} L{i['level']} {i['group']}] {i['title']}" for i in existing))
    parts.append("## 넓은 말 (별칭으로 쓰지 않는다)\n" + ", ".join(catalog.get("broad_names", [])))
    print("\n\n".join(p for p in parts if p))
    return 0


# ---------- 검사 ----------

def strip_draft_fields(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in DRAFT_ONLY_FIELDS and not k.startswith("_")}


def merged_catalog(catalog: dict, drafts: list[dict]) -> dict:
    """기존 항목 뒤에 초안을 붙이고 파일 안 순서 규칙대로 늘어놓은 사전."""
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for item in catalog["items"]:
        by_domain[item["_domain"]].append(item)
    for item in drafts:
        clean = strip_draft_fields(item)
        by_domain[domain_of(item)].append({**clean, "_domain": domain_of(item), "_order": 0, "_draft": True})
    items = []
    for domain in catalog["domains"]:
        group = by_domain.get(domain["prefix"], [])
        try:
            group.sort(key=lambda i: (i["level"], ("topic", "term").index(i["kind"]), i["importance"]))
        except (KeyError, ValueError, TypeError):
            pass  # 필드가 깨진 항목은 check_item이 알려 준다
        for order, item in enumerate(group):
            item["_order"] = order
        items.extend(group)
    return {**catalog, "items": items}


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[가-힣a-z0-9]+", text.lower()) if len(w) >= 2}


def overlap_check(catalog: dict, drafts: list[dict]) -> tuple[list[str], list[str]]:
    """새 항목이 기존 항목과 이름·별칭·내용이 겹치는지 본다."""
    errors, warnings = [], []
    names: dict[str, str] = {}
    for item in catalog["items"]:
        names[item["title"].lower()] = item["id"]
        names[item["en"].lower()] = item["id"]
    aliases: dict[tuple[int, str], list[str]] = defaultdict(list)
    for item in catalog["items"]:
        for alias in item["aliases"]:
            aliases[(item["level"], alias.lower())].append(item["id"])
    bags = {i["id"]: tokens(" ".join([i["summary"], *i.get("objectives", [])])) for i in catalog["items"] if i["kind"] == "topic"}
    seen_titles: dict[str, str] = {}
    for item in drafts:
        label = item.get("id", f"{item.get('_file')}#{item.get('_order', 0) + 1}")
        for name in (str(item.get("title", "")), str(item.get("en", ""))):
            key = name.lower()
            if key and key in names:
                errors.append(f"{label}: 이름 '{name}'이 기존 항목 {names[key]}과 같다")
            if key and seen_titles.get(key) not in (None, label):
                errors.append(f"{label}: 이름 '{name}'이 초안 {seen_titles[key]}과 같다")
            seen_titles[key] = label
        for alias in item.get("aliases", []) or []:
            key = str(alias).lower()
            if key in names and names[key] != item.get("parent"):
                errors.append(f"{label}: 별칭 '{alias}'가 기존 항목 {names[key]}의 이름이다")
            owners = aliases.get((item.get("level"), key), [])
            if owners and item.get("parent") not in owners:
                warnings.append(f"{label}: 별칭 '{alias}'를 같은 단계의 {owners}도 쓴다")
        if item.get("kind") == "topic":
            bag = tokens(" ".join([str(item.get("summary", "")), *(item.get("objectives") or [])]))
            for other_id, other in bags.items():
                if bag and other and len(bag & other) / len(bag | other) >= OVERLAP_JACCARD:
                    warnings.append(f"{label}: {other_id}과 내용이 많이 겹친다(낱말 {len(bag & other)}개 공통). 다른 항목인지 확인")
    return errors, warnings


def basis_check(drafts: list[dict]) -> list[str]:
    errors = []
    for item in drafts:
        label = item.get("id", f"{item.get('_file')}#{item.get('_order', 0) + 1}")
        if len(str(item.get("basis", "")).strip()) < BASIS_MIN:
            errors.append(f"{label}: 근거(basis)를 한 줄 이상 적는다(자료·단계·중요도 이유)")
    return errors


def quota_check(run: dict | None, drafts: list[dict]) -> dict:
    counts: dict[str, Counter] = defaultdict(Counter)
    for item in drafts:
        counts[domain_of(item)][item.get("kind", "?")] += 1
    report = {"drafted": {d: dict(c) for d, c in counts.items()}, "short": [], "over": []}
    if run and run.get("quotas"):
        for domain, quota in run["quotas"].items():
            for kind in ("topic", "term"):
                have = counts[domain][kind]
                if have < quota[kind]:
                    report["short"].append(f"{domain} {kind} {have}/{quota[kind]}")
                elif have > quota[kind]:
                    report["over"].append(f"{domain} {kind} {have}/{quota[kind]}")
        if run.get("level"):
            report["wrong_level"] = [i.get("id") for i in drafts if i.get("level") != run["level"] and i.get("kind") == "topic"]
    return report


# ---------- 별칭 오탐 측정 ----------

def corpus_sessions(repo: Repo, limit_mb: int = 300) -> list[tuple[str, str]]:
    """이 컴퓨터의 Claude Code 대화 기록을 (이름, 사람·AI가 나눈 말)로 모은다. 결과는 저장소의 작업 폴더에만 저장한다."""
    index = repo.read_json(CORPUS_INDEX, {})
    folder = repo.work / CORPUS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    sessions = []
    if not PROJECTS_DIR.exists():
        return sessions
    for jsonl in sorted(PROJECTS_DIR.glob("*/*.jsonl")):
        if jsonl.stat().st_size > limit_mb * 1024 * 1024:
            continue
        key = hashlib.sha1(str(jsonl).encode()).hexdigest()[:16]
        stamp = f"{jsonl.stat().st_mtime_ns}:{jsonl.stat().st_size}"
        cache = folder / f"{key}.txt"
        if index.get(key) != stamp or not cache.exists():
            try:
                recs = repo.study_notes.load_conversation(jsonl, "claude")
                text = repo.concepts._normalize(repo.study_notes.spoken_text(recs))
            except Exception:  # 깨진 기록 하나 때문에 멈추지 않는다
                text = ""
            cache.write_text(text, encoding="utf-8")
            index[key] = stamp
        text = cache.read_text(encoding="utf-8")
        if len(text) >= 200:
            sessions.append((jsonl.stem[:8], text))
    repo.write_json(CORPUS_INDEX, index)
    return sessions


def audit_names(repo: Repo, names: list[str], sessions: list[tuple[str, str]]) -> dict[str, dict]:
    result = {}
    total = len(sessions)
    for name in names:
        norm = repo.concepts._normalize(name).strip()
        if len(norm) < 2:
            continue
        pattern = repo.concepts._name_pattern(norm)
        in_sessions = sum(1 for _, text in sessions if norm in text and pattern.search(text))
        share = round(in_sessions / total, 3) if total else 0.0
        result[name] = {"sessions": in_sessions, "share": share,
                        "too_broad": total >= BROAD_MIN_SESSIONS and share >= BROAD_SESSION_SHARE,
                        "common": total >= BROAD_MIN_SESSIONS and share >= BROAD_WARN_SHARE}
    return result


def alias_audit(repo: Repo, catalog: dict, drafts: list[dict]) -> tuple[list[str], list[str], dict]:
    sessions = corpus_sessions(repo)
    broad = {n.lower() for n in catalog.get("broad_names", [])}
    errors, warnings = [], []
    names = []
    for item in drafts:
        for alias in item.get("aliases", []) or []:
            if str(alias).lower() in broad:
                errors.append(f"{item.get('id')}: 별칭 '{alias}'는 넓은 말 목록에 있다")
            names.append(str(alias))
    if not sessions:
        return errors, warnings, {"sessions": 0, "note": "대화 기록이 없어 오탐률을 재지 못했다", "aliases": {}}
    audited = audit_names(repo, sorted(set(names)), sessions)
    for item in drafts:
        own = {str(item.get("title", "")).lower(), str(item.get("en", "")).lower()}
        for alias in item.get("aliases", []) or []:
            info = audited.get(str(alias))
            if not info or str(alias).lower() in own:
                continue
            where = f"대화 {info['sessions']}/{len(sessions)}개 세션에 나온다"
            if info["too_broad"]:
                errors.append(f"{item.get('id')}: 별칭 '{alias}'가 {where}. 너무 넓다. 좁은 말로 바꾼다")
            elif info["common"]:
                warnings.append(f"{item.get('id')}: 별칭 '{alias}'가 {where}. 다른 뜻으로도 쓰이는지 확인")
    return errors, warnings, {"sessions": len(sessions), "aliases": audited}


def cmd_alias_audit(repo: Repo, args) -> int:
    catalog = repo.catalog()
    sessions = corpus_sessions(repo)
    if args.all:
        names = sorted({a for i in catalog["items"] for a in i["aliases"]})
    elif args.names:
        names = args.names
    else:
        names = sorted({str(a) for i in repo.drafts() for a in (i.get("aliases") or [])})
    audited = audit_names(repo, names, sessions)
    ranked = sorted(audited.items(), key=lambda kv: -kv[1]["share"])
    print(json.dumps({"sessions": len(sessions), "too_broad": [n for n, v in ranked if v["too_broad"]],
                      "top": [{"alias": n, **v} for n, v in ranked[:40]]}, ensure_ascii=False, indent=1))
    return 0


# ---------- 링크 ----------

def fetch_link(url: str) -> dict:
    result = subprocess.run(
        ["curl", "-sL", "-m", LINK_TIMEOUT, "-A", UA, "-w", "\n%{http_code}", url],
        capture_output=True, text=True, errors="replace",
    )
    body, _, status = result.stdout.rpartition("\n")
    match = re.search(r"<title[^>]*>\s*(.*?)\s*</title>", body, re.I | re.S)
    title = re.sub(r"\s+", " ", match.group(1))[:120] if match else ""
    return {"status": status.strip() or "000", "title": title, "checked": today()}


def check_links(repo: Repo, urls: list[str], refresh: bool = False) -> dict[str, dict]:
    cache = repo.read_json(LINKS_FILE, {})
    for url in urls:
        if refresh or url not in cache or cache[url].get("status") != "200":
            cache[url] = fetch_link(url)
    repo.write_json(LINKS_FILE, cache)
    return {u: cache[u] for u in urls}


def links_of(items: list[dict]) -> list[str]:
    return sorted({ref for i in items for ref in (i.get("refs") or [])})


def run_checks(repo: Repo, with_links: bool) -> dict:
    catalog = repo.catalog()
    drafts = repo.drafts()
    run = repo.read_json(RUN_FILE, None)
    merged = merged_catalog(catalog, drafts)
    errors, warnings = repo.tool.check_catalog(merged)
    draft_ids = {i.get("id") for i in drafts}
    # 기존 사전의 경고는 이번 초안 탓이 아니다. 초안 id가 들어간 줄만 남긴다.
    errors = [e for e in errors if any(str(i) in e for i in draft_ids) or "순환" in e]
    warnings = [w for w in warnings if any(str(i) in w for i in draft_ids)]
    overlap_errors, overlap_warnings = overlap_check(catalog, drafts)
    alias_errors, alias_warnings, audit = alias_audit(repo, catalog, drafts)
    errors += basis_check(drafts) + overlap_errors + alias_errors
    warnings += overlap_warnings + alias_warnings
    links = {}
    if with_links:
        links = check_links(repo, links_of(drafts))
        for url, info in links.items():
            if info["status"] in DEAD_LINK_STATUSES:
                errors.append(f"링크 {url}: 응답 {info['status']}")
            elif info["status"] != "200":
                # 403·429는 대개 봇 차단이다. 에이전트가 WebFetch로 읽었으면 통과시키되 사람이 보게 경고로 남긴다.
                warnings.append(f"링크 {url}: 응답 {info['status']}({info['title'] or '제목 없음'}). 봇 차단이면 브라우저로 열어 확인")
    shared = defaultdict(list)
    for item in drafts:
        if item.get("kind") == "topic":
            for ref in item.get("refs") or []:
                shared[ref].append(item.get("id"))
    warnings += [f"같은 자료 {u}로 주제 {ids}를 만들었다. 분야가 달라도 한 항목으로 합칠 수 있는지 확인" for u, ids in shared.items() if len(ids) > 1]
    return {"items": len(drafts), "errors": errors, "warnings": warnings, "quota": quota_check(run, drafts),
            "alias_sessions": audit.get("sessions", 0), "links": links}


def cmd_check(repo: Repo, args) -> int:
    report = run_checks(repo, args.links)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if report["errors"] else 0


# ---------- 검토 표 ----------

def cmd_review_sheet(repo: Repo, args) -> int:
    catalog = repo.catalog()
    drafts = repo.drafts()
    run = repo.read_json(RUN_FILE, {})
    report = run_checks(repo, False)
    links = repo.read_json(LINKS_FILE, {})
    names = {d["prefix"]: d["name"] for d in catalog["domains"]}
    stars = repo.tool.STARS
    lines = [f"# 사전 추가 검토표 ({today()})", "",
             f"실행: {run.get('mode', '?')} · 단계 {run.get('level', '-')} · 항목 {len(drafts)}개 · 검사 오류 {len(report['errors'])}개 · 경고 {len(report['warnings'])}개", "",
             "승인하면 `/dic-maker apply`로 사전에 넣습니다. 빼고 싶은 항목은 초안 파일에서 지우거나 여기 적어 주세요.", ""]
    if report["errors"]:
        lines += ["## 검사 오류 (적용 전에 고쳐야 함)", *[f"- {e}" for e in report["errors"]], ""]
    if report["warnings"]:
        lines += ["## 경고 (판단 필요)", *[f"- {w}" for w in report["warnings"]], ""]
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for item in drafts:
        by_domain[domain_of(item)].append(item)
    for domain, group in sorted(by_domain.items()):
        lines += [f"## {names.get(domain, domain)} ({len(group)}개)", "",
                  "| id | 종류 | 단계 | 중요도 | 제목 | 요약 | 학습 목표 | 별칭 | 자료 | 근거 |", "|---|---|---|---|---|---|---|---|---|---|"]
        for item in group:
            refs = "<br>".join(f"[{(links.get(r) or {}).get('title') or r[:60]}]({r})" for r in (item.get("refs") or []))
            cell = lambda v: str(v).replace("|", "\\|").replace("\n", " ")
            lines.append("| " + " | ".join(cell(v) for v in (
                item.get("id"), item.get("kind"), item.get("level"), stars.get(item.get("importance"), "?"),
                f"{item.get('title')} ({item.get('en')})", item.get("summary"),
                " / ".join(item.get("objectives") or []) or (f"부모: {item.get('parent')}" if item.get("parent") else "독립 용어"),
                ", ".join(item.get("aliases") or []), refs or "-", item.get("basis", ""),
            )) + " |")
        lines.append("")
    path = repo.work / REVIEW_FILE
    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"review": str(path), "items": len(drafts), "errors": len(report["errors"]), "warnings": len(report["warnings"])},
                     ensure_ascii=False))
    return 0


# ---------- 적용 ----------

def bump_version(version: str) -> str:
    major, minor, _ = version.strip().split(".")
    return f"{major}.{int(minor) + 1}.0"


def cmd_apply(repo: Repo, args) -> int:
    drafts = repo.drafts()
    if not drafts:
        raise SystemExit("초안이 없습니다.")
    report = run_checks(repo, with_links=True)
    if report["errors"]:
        print(json.dumps(report, ensure_ascii=False, indent=1))
        raise SystemExit("검사 오류가 있어 적용하지 않습니다.")
    catalog = repo.catalog()
    items_dir = repo.catalog_root / "items"
    added: dict[str, list[str]] = defaultdict(list)
    for domain in catalog["domains"]:
        new = [strip_draft_fields(i) for i in drafts if domain_of(i) == domain["prefix"]]
        if not new:
            continue
        path = items_dir / f"{domain['prefix']}.json"
        existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        merged = existing + [repo.tool.clean_item(i) for i in new]
        merged.sort(key=repo.tool.sort_key)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        added[domain["prefix"]] = [i["id"] for i in new]
    fresh = repo.catalog()
    errors, _ = repo.tool.check_catalog(fresh)
    if errors:
        raise SystemExit("적용 뒤 검사에 실패했습니다. 항목 파일을 되돌리세요(git checkout catalog/items):\n" + "\n".join(errors))
    old_version = fresh["version"]
    new_version = bump_version(old_version)
    (repo.catalog_root / "VERSION").write_text(new_version + "\n", encoding="utf-8")
    changelog = repo.catalog_root / "CHANGELOG.md"
    topics = sum(1 for i in drafts if i.get("kind") == "topic")
    terms = len(drafts) - topics
    note = args.note or f"dic-maker로 주제 {topics}개, 용어 {terms}개를 더했다."
    head, sep, rest = changelog.read_text(encoding="utf-8").partition("\n## ")
    changelog.write_text(f"{head}\n## {new_version}\n\n- {note}\n- 분야별: " +
                         ", ".join(f"{d} {len(ids)}개" for d, ids in added.items()) + f"\n{sep}{rest}", encoding="utf-8")
    repo.tool.format_items(repo.catalog_root, repo.catalog())
    build_log = io.StringIO()
    with contextlib.redirect_stdout(build_log):   # build의 안내문이 이 명령의 JSON 출력과 섞이지 않게 한다
        built = repo.tool.cmd_build(repo.catalog_root, False)
    if built != 0:
        raise SystemExit("build에 실패했습니다.\n" + build_log.getvalue())
    run = repo.read_json(RUN_FILE, {}) or {}
    history = repo.work / HISTORY_DIR
    history.mkdir(parents=True, exist_ok=True)
    (history / f"{today()}_{new_version}.json").write_text(
        json.dumps({"run": run, "added": added, "items": [strip_draft_fields(i) for i in drafts]}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    for path in repo.draft_files():
        path.unlink()
    (repo.work / RUN_FILE).unlink(missing_ok=True)
    covered = [b for b in box_covered(fresh, read_box()) if b["covered_by"] and b["covered_by"] in {i for ids in added.values() for i in ids}]
    print(json.dumps({"version": new_version, "previous": old_version, "added": added, "topics": topics, "terms": terms,
                      "box_covered": [b["name"] for b in covered],
                      "next": "python3 -I -m unittest discover -s tests 로 테스트한 뒤 커밋한다. 푸시는 사용자에게 묻는다."},
                     ensure_ascii=False, indent=1))
    return 0


# ---------- 갱신 ----------

def cmd_refresh(repo: Repo, args) -> int:
    catalog = repo.catalog()
    cutoff = dt.date.today() - dt.timedelta(days=args.days)
    stale = []
    for item in catalog["items"]:
        if item.get("volatile"):
            checked = item.get("checked_at", "")
            try:
                old = dt.date.fromisoformat(checked) < cutoff
            except ValueError:
                old = True
            if old:
                stale.append({"id": item["id"], "title": item["title"], "checked_at": checked, "refs": item.get("refs", [])})
    broken = []
    if args.links:
        links = check_links(repo, links_of(catalog["items"]), refresh=True)
        owners: dict[str, list[str]] = defaultdict(list)
        for item in catalog["items"]:
            for ref in item.get("refs", []):
                owners[ref].append(item["id"])
        broken = [{"url": u, "status": v["status"], "items": owners[u]} for u, v in links.items() if v["status"] != "200"]
    print(json.dumps({"stale_volatile": stale, "days": args.days, "broken_links": broken,
                      "next": "항목을 자료와 대조해 고친 뒤 mark-checked --ids 로 날짜를 바꾼다"}, ensure_ascii=False, indent=1))
    return 0


def cmd_mark_checked(repo: Repo, args) -> int:
    catalog = repo.catalog()
    wanted = set(args.ids)
    found = set()
    for domain in catalog["domains"]:
        path = repo.catalog_root / "items" / f"{domain['prefix']}.json"
        if not path.exists():
            continue
        group = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for item in group:
            if item["id"] in wanted:
                item["volatile"] = True
                item["checked_at"] = today()
                found.add(item["id"])
                changed = True
        if changed:
            path.write_text(json.dumps([repo.tool.clean_item(i) for i in group], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    missing = sorted(wanted - found)
    if missing:
        raise SystemExit(f"사전에 없는 id: {missing}")
    print(json.dumps({"checked": sorted(found), "date": today()}, ensure_ascii=False))
    return 0


# ---------- 상태 ----------

def cmd_status(repo: Repo, args) -> int:
    run = repo.read_json(RUN_FILE, None)
    drafts = repo.drafts() if run else []
    catalog = repo.catalog()
    print(json.dumps({
        "version": catalog["version"], "items": len(catalog["items"]),
        "run": run, "drafted": quota_check(run, drafts)["drafted"] if run else {},
        "draft_files": [p.name for p in repo.draft_files()],
        "review": str(repo.work / REVIEW_FILE) if (repo.work / REVIEW_FILE).exists() else None,
        "levels": level_rows(catalog),
    }, ensure_ascii=False, indent=1))
    return 0


def cmd_cancel(repo: Repo, args) -> int:
    run = repo.read_json(RUN_FILE, None)
    removed = [p.name for p in repo.draft_files()]
    for path in repo.draft_files():
        path.unlink()
    (repo.work / RUN_FILE).unlink(missing_ok=True)
    (repo.work / REVIEW_FILE).unlink(missing_ok=True)
    print(json.dumps({"cancelled": bool(run), "removed_drafts": removed,
                      "message": "실행을 취소했습니다. 사전 파일은 건드리지 않았습니다." if run else "진행 중인 실행이 없습니다."},
                     ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="개념사전 늘리기 도구")
    parser.add_argument("--repo", help="사전 저장소 폴더(기본: 현재 폴더)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("gaps", help="격차 보기")
    p.add_argument("--level", type=int)
    p.set_defaults(fn=cmd_gaps)
    p = sub.add_parser("start", help="실행 계획 세우기")
    p.add_argument("--level", type=int)
    p.add_argument("--count", type=int, default=DEFAULT_COUNT, help=f"기본 {DEFAULT_COUNT}, 최대 {MAX_COUNT}")
    p.add_argument("--box", action="store_true", help="후보함의 개념만")
    p.add_argument("--force", action="store_true", help="진행 중인 실행을 버리고 새로 시작")
    p.set_defaults(fn=cmd_start)
    p = sub.add_parser("guide", help="조사 에이전트가 읽을 규칙")
    p.add_argument("--domain")
    p.add_argument("--level", type=int)
    p.set_defaults(fn=cmd_guide)
    p = sub.add_parser("check", help="초안 검사")
    p.add_argument("--links", action="store_true", help="자료 링크도 연다(네트워크)")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("alias-audit", help="별칭 오탐률 재기")
    p.add_argument("--all", action="store_true", help="사전 전체 별칭")
    p.add_argument("--names", nargs="*", help="특정 이름만")
    p.set_defaults(fn=cmd_alias_audit)
    p = sub.add_parser("review-sheet", help="검토표 만들기")
    p.set_defaults(fn=cmd_review_sheet)
    p = sub.add_parser("apply", help="초안을 사전에 넣기")
    p.add_argument("--note", help="CHANGELOG 한 줄")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("refresh", help="오래된 volatile 항목과 죽은 링크")
    p.add_argument("--days", type=int, default=STALE_DAYS)
    p.add_argument("--links", action="store_true")
    p.set_defaults(fn=cmd_refresh)
    p = sub.add_parser("mark-checked", help="확인 날짜 갱신")
    p.add_argument("--ids", nargs="+", required=True)
    p.set_defaults(fn=cmd_mark_checked)
    sub.add_parser("status", help="상태").set_defaults(fn=cmd_status)
    sub.add_parser("cancel", help="실행 취소").set_defaults(fn=cmd_cancel)
    args = parser.parse_args(argv)
    repo = Repo(find_repo(args.repo))
    return args.fn(repo, args)


if __name__ == "__main__":
    sys.exit(main())
