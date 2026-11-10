"""dic-maker 도구 단위 테스트. 표준 라이브러리 unittest만 쓴다.

실행: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "dic-maker" / "scripts" / "dic_maker.py"
SKILL_DIR = ROOT / "skills" / "dic-maker"

_spec = importlib.util.spec_from_file_location("dic_maker", SCRIPT)
dm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dm)


def make_repo(base: Path) -> Path:
    """실제 사전을 복사한 임시 저장소. 사전 도구와 study-notes 스크립트가 함께 있어야 한다."""
    repo = base / "repo"
    shutil.copytree(ROOT / "catalog", repo / "catalog", ignore=shutil.ignore_patterns("__pycache__", "dist"))
    shutil.copytree(ROOT / "skills" / "study-notes" / "scripts", repo / "skills" / "study-notes" / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__"))
    return repo


def draft_topic(item_id: str = "mlops.serve.test-fixture-serving", **extra) -> dict:
    return {
        "id": item_id, "title": "시험용 서빙 기본", "en": "Test Fixture Serving Basics", "kind": "topic", "level": 4, "importance": 2,
        "group": "모델 서빙", "summary": "학습한 모델을 API 뒤에 두고 요청마다 추론하는 구조와 배치·실시간의 차이를 정한다.",
        "objectives": ["실시간 추론과 배치 추론을 요구사항에 맞게 고를 수 있다", "모델 서버의 지연과 처리량을 재서 병목을 찾을 수 있다"],
        "aliases": ["시험용 서빙", "test fixture serving"], "refs": ["https://example.com/serving"],
        "basis": "예시 자료의 Serving 절. 여러 기술을 엮는 설계라 4단계. 서비스 제작 경로라 ★★.", **extra,
    }


def draft_term(item_id: str = "mlops.serve.test-fixture-batch-inference", **extra) -> dict:
    return {
        "id": item_id, "title": "시험용 배치 추론", "en": "Test Fixture Batch Inference", "kind": "term", "level": 4, "importance": 2,
        "group": "모델 서빙", "summary": "모아 둔 입력을 한꺼번에 추론해 결과를 저장해 두는 방식이다.",
        "parent": "mlops.serve.test-fixture-serving", "aliases": ["시험용 배치 추론", "test fixture batch inference"], "basis": "위 주제가 가르치는 용어.", **extra,
    }


class DicMakerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.repo = make_repo(base)
        self.projects = base / "projects"
        self.projects.mkdir()
        self.notes = base / "notes"
        self.notes.mkdir()
        self._saved = (dm.PROJECTS_DIR, dm.STUDY_NOTES_ROOT, dm.fetch_link)
        dm.PROJECTS_DIR = self.projects
        dm.STUDY_NOTES_ROOT = self.notes
        dm.fetch_link = lambda url: {"status": "200" if "example.com" in url else "404", "title": "예시 문서", "checked": dm.today()}

    def tearDown(self):
        dm.PROJECTS_DIR, dm.STUDY_NOTES_ROOT, dm.fetch_link = self._saved
        self._tmp.cleanup()

    def run_cmd(self, *argv: str, ok: bool = True) -> dict:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = dm.main(["--repo", str(self.repo), *argv])
        self.assertEqual(code == 0, ok, buf.getvalue()[-800:])
        return json.loads(buf.getvalue())

    def write_draft(self, name: str, items: list[dict]) -> None:
        folder = self.repo / dm.WORK_DIR / dm.DRAFT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{name}.json").write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    def box(self, *names: str) -> None:
        rows = "\n".join(f"| 2026-11-04 | {n} | demo |" for n in names)
        (self.notes / dm.BOX_FILE).write_text(f"# 후보함\n\n| 날짜 | 개념 | 프로젝트 |\n|---|---|---|\n{rows}\n", encoding="utf-8")

    def say(self, name: str, text: str) -> None:
        folder = self.projects / "p"
        folder.mkdir(exist_ok=True)
        with (folder / f"{name}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "uuid": name, "timestamp": "2026-11-04T00:00:01Z",
                                 "message": {"content": text * 20}}, ensure_ascii=False) + "\n")

    # ----- 격차와 계획 -----

    def test_gaps_reports_levels_ladder_and_box(self):
        self.box("원자적 파일 교체", "HTTP 메서드와 상태 코드")
        out = self.run_cmd("gaps")
        self.assertEqual([r["level"] for r in out["levels"]], [1, 2, 3, 4, 5])
        self.assertIn(out["emptiest_level"], range(1, 6))
        self.assertTrue(any(g["lowest_level"] >= 4 for g in out["ladder_gaps"]))
        self.assertEqual(out["box_open"], ["원자적 파일 교체"])   # HTTP 메서드는 이미 사전에 있다

    def test_start_splits_count_by_level_ratio_and_refuses_twice(self):
        out = self.run_cmd("start", "--level", "4", "--count", "30")
        self.assertEqual((out["level"], out["topics"] + out["terms"]), (4, 30))
        self.assertEqual(sum(q["topic"] for q in out["quotas"].values()), out["topics"])
        self.assertEqual(sum(q["term"] for q in out["quotas"].values()), out["terms"])
        self.assertLessEqual(len(out["quotas"]), dm.MAX_DOMAINS_PER_RUN)
        self.assertNotIn("be", out["quotas"])   # 가장 많은 분야는 빠진다
        self.assertEqual(out["agent_concurrency"], dm.AGENT_CONCURRENCY)
        with self.assertRaises(SystemExit):
            self.run_cmd("start", "--level", "4")
        self.assertEqual(self.run_cmd("start", "--level", "2", "--force")["level"], 2)

    def test_start_picks_emptiest_level_and_box_mode(self):
        out = self.run_cmd("start")
        self.assertEqual(out["level"], self.run_cmd("gaps")["emptiest_level"])
        self.box("존재하지 않는 가상 개념 이름")
        out = self.run_cmd("start", "--force", "--box")
        self.assertEqual((out["mode"], out["box"], list(out["draft_files"])), ("box", ["존재하지 않는 가상 개념 이름"], ["box"]))

    def test_guide_has_rules_level_criteria_and_existing_items(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(dm.main(["--repo", str(self.repo), "guide", "--domain", "mlops", "--level", "4"]), 0)
        text = buf.getvalue()
        for marker in ("자료가 먼저다", '"can_do"', "## 항목 형식", "mlops.", "## 넓은 말", "basis"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn("## 절차", text)

    def test_guide_for_new_cs_domain_shows_boundary_neighbors_and_lecture_exception(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(dm.main(["--repo", str(self.repo), "guide", "--domain", "cs", "--level", "3"]), 0)
        text = buf.getvalue()
        for marker in ("## 분야 cs (컴퓨터 사이언스 기초)", "경계: 언어·도구에 매이지 않는 원리", "ocw.mit.edu", "## cs의 기존 항목",
                       "## 다른 분야에 이미 있는 비슷한 항목", "be.async.concurrency-parallelism", "be.python.unicode",
                       "dev.dsa.collections-choice", "예외: 대학이 자기 도메인에 공개한", "큐 자료구조"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        neighbors = text.split("## 다른 분야에 이미 있는 비슷한 항목")[1].split("\n## ")[0]
        self.assertNotIn("be.http.", neighbors)   # 이웃이 아닌 묶음은 보이지 않는다
        self.assertNotIn("L5", neighbors)   # 근처 단계(3±1)만 보인다
        with contextlib.redirect_stdout(io.StringIO()):
            dm.main(["--repo", str(self.repo), "guide", "--domain", "mlops", "--level", "4"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dm.main(["--repo", str(self.repo), "guide", "--domain", "ops", "--level", "4"])
        self.assertIn("경계: 네트워크 계층·프로토콜", out.getvalue())
        self.assertNotIn("## 다른 분야에 이미 있는 비슷한 항목", out.getvalue())

    def test_start_gives_the_empty_cs_domain_a_share_and_check_rejects_wiki_refs(self):
        # 실제 사전의 cs 크기에 기대지 않도록 시험용 사본에서 cs를 비운다(빈 분야가 몫을 받는지 본다)
        (self.repo / "catalog" / "items" / "cs.json").write_text("[]\n", encoding="utf-8")
        out = self.run_cmd("start", "--level", "3", "--count", "30")
        self.assertIn("cs", out["quotas"])
        self.assertTrue(out["draft_files"]["cs"].endswith("cs.json"))
        self.assertEqual(out["domains"]["cs"]["name"], "컴퓨터 사이언스 기초")
        self.assertIn("pages.cs.wisc.edu", out["domains"]["cs"]["sources"])
        wiki = draft_topic("cs.dsa.test-fixture-queue", title="시험용 큐 자료구조", en="Test Fixture Queue", group="자료구조", level=3,
                           aliases=["시험용 큐 자료구조", "test fixture queue"], refs=["https://en.wikipedia.org/wiki/Queue_(abstract_data_type)"])
        ocw = draft_topic("cs.algo.test-fixture-big-o", title="시험용 빅오 표기법", en="Test Fixture Big-O", group="알고리즘", level=3,
                          summary="입력이 커질 때 실행 시간이 늘어나는 정도를 최고차항으로 나타내는 표기법이다.",
                          aliases=["시험용 빅오", "test fixture big-o"], refs=["https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/"])
        self.write_draft("cs", [wiki, ocw])
        report = self.run_cmd("check", ok=False)
        self.assertTrue(any("cs.dsa.test-fixture-queue" in e and "자료로 쓰지 않는다" in e for e in report["errors"]), report["errors"])
        self.assertFalse(any("cs.algo.test-fixture-big-o" in e for e in report["errors"]), report["errors"])

    # ----- 검사 -----

    def test_check_catches_rule_overlap_basis_and_broad_alias(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [
            draft_topic(aliases=["모델 서빙", "서버", "세션"]),           # 기존 항목 이름, 넓은 말
            draft_term(basis=""),                                       # 근거 없음
            draft_term("mlops.serve.throughput", title="처리량", en="Throughput", parent=None, aliases=["처리량"]),  # 독립 용어인데 자료 없음
            draft_topic("mlops.eval.llm-regression", title="다른 제목", en="Other"),                           # id 겹침
        ])
        out = self.run_cmd("check", ok=False)
        joined = "\n".join(out["errors"])
        for marker in ("별칭 '서버'가 기존 항목", "넓은 말 목록", "근거(basis)", "부모 주제가 없는 용어", "id가 겹친다"):
            with self.subTest(marker=marker):
                self.assertIn(marker, joined)
        self.assertEqual(out["quota"]["drafted"]["mlops"], {"topic": 2, "term": 2})

    def test_check_passes_clean_draft_and_links(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(), draft_term()])
        out = self.run_cmd("check", "--links")
        self.assertEqual(out["errors"], [])
        self.assertEqual(out["links"]["https://example.com/serving"]["status"], "200")
        self.assertTrue(out["quota"]["short"])   # 몫을 못 채운 것은 오류가 아니다

    def test_bot_blocked_link_is_a_warning_and_shared_source_is_flagged(self):
        dm.fetch_link = lambda url: {"status": "403" if "blocked" in url else "200", "title": "Just a moment...", "checked": dm.today()}
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(refs=["https://example.com/blocked"]),
                                   draft_topic("mlops.serve.second", title="두 번째 주제", en="Second", aliases=["두 번째"],
                                               refs=["https://example.com/blocked"])])
        out = self.run_cmd("check", "--links")
        self.assertEqual(out["errors"], [])
        self.assertTrue(any("응답 403" in w and "봇 차단" in w for w in out["warnings"]))
        self.assertTrue(any("같은 자료" in w for w in out["warnings"]))

    def test_check_flags_dead_link_and_own_name_is_not_broad(self):
        for n in range(6):
            self.say(f"s{n}", "가상 모델 서빙 얘기를 또 했어요. 가상 추론 서버요. ")
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(title="가상 모델 서빙", en="Virtual Model Serving", aliases=["가상 모델 서빙", "가상 추론 서버"],
                                               refs=["https://dead.invalid/x"])])
        out = self.run_cmd("check", "--links", ok=False)
        self.assertTrue(any("응답 404" in e for e in out["errors"]))
        self.assertTrue(any("'가상 추론 서버'" in e and "너무 넓다" in e for e in out["errors"]))
        self.assertFalse(any("'가상 모델 서빙'" in e for e in out["errors"]))   # 항목 자신의 이름은 막지 않는다
        self.assertEqual(out["alias_sessions"], 6)

    def test_alias_audit_all_ranks_existing_aliases(self):
        for n in range(5):
            self.say(f"s{n}", "JWT 토큰으로 로그인했어요. ")
        out = self.run_cmd("alias-audit", "--all")
        self.assertEqual(out["sessions"], 5)
        self.assertIn("JWT", out["too_broad"])

    # ----- 검토표와 적용 -----

    def test_review_sheet_lists_items_and_errors(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(), draft_term(basis="")])
        out = self.run_cmd("review-sheet")
        text = Path(out["review"]).read_text(encoding="utf-8")
        self.assertIn("| mlops.serve.test-fixture-serving | topic | 4 | ★★ |", text)
        self.assertIn("부모: mlops.serve.test-fixture-serving", text)
        self.assertIn("## 검사 오류", text)
        self.assertEqual((out["items"], out["errors"]), (2, 1))

    def test_apply_merges_bumps_version_builds_and_clears(self):
        self.box("시험용 서빙 기본")
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(), draft_term(),
                                   draft_term("mlops.serve.test-fixture-throughput", title="시험용 처리량", en="Test Fixture Throughput", parent=None,
                                              aliases=["시험용 처리량", "test fixture throughput"], refs=["https://example.com/tp"])])
        before = (self.repo / "catalog" / "VERSION").read_text().strip()
        out = self.run_cmd("apply", "--note", "서빙 항목 시험")
        self.assertEqual((out["topics"], out["terms"], out["previous"]), (1, 2, before))
        self.assertEqual(out["version"], dm.bump_version(before))
        self.assertEqual(out["box_covered"], ["시험용 서빙 기본"])
        items = json.loads((self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8"))
        wanted = {"mlops.serve.test-fixture-serving", "mlops.serve.test-fixture-batch-inference", "mlops.serve.test-fixture-throughput"}
        added = {i["id"]: i for i in items if i["id"] in wanted}
        self.assertEqual(set(added), wanted)
        self.assertNotIn("basis", added["mlops.serve.test-fixture-serving"])
        self.assertIn("- 서빙 항목 시험", (self.repo / "catalog" / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertTrue((self.repo / "catalog" / "dist" / "catalog.json").exists())
        bundle = json.loads((self.repo / "catalog" / "dist" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(bundle["version"], out["version"])
        self.assertEqual(self.run_cmd("status")["run"], None)
        self.assertTrue(list((self.repo / dm.WORK_DIR / dm.HISTORY_DIR).glob("*.json")))
        tool_out = io.StringIO()
        with contextlib.redirect_stdout(tool_out):
            self.assertEqual(sys_tool_check(self.repo), 0)

    def test_apply_refuses_when_checks_fail(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(basis="")])
        with self.assertRaises(SystemExit):
            self.run_cmd("apply", ok=False)
        self.assertNotIn("mlops.serve.test-fixture-serving", (self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8"))

    def test_cancel_removes_drafts_but_not_catalog(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic()])
        out = self.run_cmd("cancel")
        self.assertEqual((out["cancelled"], out["removed_drafts"]), (True, ["mlops.json"]))
        self.assertEqual(self.run_cmd("cancel")["cancelled"], False)
        self.assertEqual(self.run_cmd("status")["version"], (ROOT / "catalog" / "VERSION").read_text().strip())

    # ----- 캠페인 (auto) -----

    def verdicts(self, **by_id) -> None:
        """검토 에이전트의 판정 파일. keep·fix·drop 또는 (판정, verified) 튀플."""
        data = {}
        for key, value in by_id.items():
            item_id = key.replace("__", ".").replace("_", "-")   # 인자 이름에는 .과 -를 못 쓴다
            verdict, verified = value if isinstance(value, tuple) else (value, True)
            data[item_id] = {"verdict": verdict, "verified": verified, "note": "시험"}
        (self.repo / dm.WORK_DIR / dm.VERDICTS_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def fixture(kind: str, item_id: str, title: str, en: str, summary: str, **extra) -> dict:
        base = draft_topic(item_id) if kind == "topic" else draft_term(item_id)
        base.update({"title": title, "en": en, "summary": summary, "aliases": [title, en.lower()], **extra})
        if kind == "topic":
            base["objectives"] = [f"{title}의 쓰임을 설명할 수 있다", f"{title}을 예제에 적용할 수 있다"]
        return base

    def test_campaign_opens_rounds_and_auto_apply_records_them(self):
        out = self.run_cmd("campaign", "--level", "4", "--total", "5", "--round", "3")
        self.assertEqual((out["level"], out["count"], out["round"], out["auto"]), (4, 3, 1, True))
        self.assertEqual((out["campaign"]["remaining"], out["campaign"]["rounds_planned"]), (5, 2))
        with self.assertRaises(SystemExit):   # 회차가 열려 있으면 또 열지 않는다
            self.run_cmd("start")
        with self.assertRaises(SystemExit):
            self.run_cmd("campaign", "--level", "4", "--total", "5", ok=False)
        self.write_draft("mlops", [draft_topic(), draft_term(),
                                   draft_term("mlops.serve.test-fixture-throughput", title="시험용 처리량", en="Test Fixture Throughput", parent=None,
                                              aliases=["시험용 처리량", "test fixture throughput"], refs=["https://example.com/tp"])])
        self.verdicts(mlops__serve__test_fixture_serving="keep", mlops__serve__test_fixture_batch_inference="keep", mlops__serve__test_fixture_throughput="keep")
        self.run_cmd("review-sheet")
        (self.repo / dm.WORK_DIR / "review-findings.md").write_text("# 검토\n", encoding="utf-8")
        out = self.run_cmd("apply", "--auto", "--note", "1회차")
        self.assertEqual((out["topics"], out["terms"], out["dropped"]), (1, 2, []))
        self.assertEqual((out["campaign"]["done"], out["campaign"]["rounds_done"], out["campaign"]["next"]), (3, 1, "continue"))
        archived = sorted(p.name for p in (self.repo / dm.WORK_DIR / dm.CAMPAIGN_DIR).iterdir())
        self.assertEqual(archived, ["round_1_review-findings.md", "round_1_review-verdicts.json", "round_1_review.md"])
        self.assertIsNone(self.run_cmd("status")["run"])
        out = self.run_cmd("start")   # 다음 회차는 남은 수만큼
        self.assertEqual((out["round"], out["count"], out["campaign"]["remaining"]), (2, 2, 2))
        status = self.run_cmd("status")["campaign"]
        self.assertEqual((status["status"], len(status["rounds"]), status["rounds"][0]["applied"]), ("running", 1, 3))

    def test_auto_gate_keeps_only_verified_keep_and_cascades(self):
        self.run_cmd("start", "--level", "4")
        kept_topic = draft_topic()
        kept_term = draft_term()
        unverified = self.fixture("term", "mlops.serve.test-fixture-warmup", "시험용 예열", "Test Fixture Warmup",
                                  "첫 요청 전에 모델을 미리 불러 두어 첫 응답 지연을 줄이는 준비 단계다.", parent=None, refs=["https://example.com/warm"])
        fix_topic = self.fixture("topic", "mlops.serve.test-fixture-canary", "시험용 카나리 배포", "Test Fixture Canary",
                                 "새 모델을 일부 트래픽에만 먼저 내보내 문제를 확인한 뒤 전체로 넓히는 배포 방식이다.", refs=["https://example.com/canary"])
        child_of_fix = self.fixture("term", "mlops.serve.test-fixture-traffic-split", "시험용 트래픽 분할", "Test Fixture Traffic Split",
                                    "요청을 비율로 나눠 여러 모델 버전에 보내는 설정이다.", parent="mlops.serve.test-fixture-canary")
        no_verdict = self.fixture("topic", "mlops.serve.test-fixture-shadow", "시험용 섀도 배포", "Test Fixture Shadow",
                                  "새 모델에 실제 요청을 복사해 보내되 응답은 쓰지 않고 비교만 하는 방식이다.", refs=["https://example.com/shadow"])
        self.write_draft("mlops", [kept_topic, kept_term, unverified, fix_topic, child_of_fix, no_verdict])
        self.verdicts(mlops__serve__test_fixture_serving="keep", mlops__serve__test_fixture_batch_inference="keep",
                      mlops__serve__test_fixture_warmup=("keep", False), mlops__serve__test_fixture_canary="fix",
                      mlops__serve__test_fixture_traffic_split="keep")
        out = self.run_cmd("apply", "--auto")
        self.assertEqual(sorted(out["added"]["mlops"]), ["mlops.serve.test-fixture-batch-inference", "mlops.serve.test-fixture-serving"])
        reasons = {d["id"]: d["reason"] for d in out["dropped"]}
        self.assertEqual(set(reasons), {"mlops.serve.test-fixture-warmup", "mlops.serve.test-fixture-canary",
                                        "mlops.serve.test-fixture-traffic-split", "mlops.serve.test-fixture-shadow"})
        self.assertIn("확인하지 못했다", reasons["mlops.serve.test-fixture-warmup"])
        self.assertIn("수정 요청", reasons["mlops.serve.test-fixture-canary"])
        self.assertIn("test-fixture-canary", reasons["mlops.serve.test-fixture-traffic-split"])
        self.assertIn("판정이 없다", reasons["mlops.serve.test-fixture-shadow"])
        self.assertNotIn("campaign", out)   # 캠페인 없이도 auto는 된다
        log = json.loads((self.repo / dm.WORK_DIR / dm.DROPPED_FILE).read_text(encoding="utf-8"))
        self.assertEqual(len(log), 4)
        self.assertTrue(all(entry["basis"] for entry in log))
        items = (self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8")
        self.assertNotIn("test-fixture-canary", items)

    def test_auto_apply_drops_items_with_check_errors_instead_of_failing(self):
        self.run_cmd("start", "--level", "4")
        clean = draft_term("mlops.serve.test-fixture-throughput", title="시험용 처리량", en="Test Fixture Throughput", parent=None,
                           aliases=["시험용 처리량", "test fixture throughput"], refs=["https://example.com/tp"])
        self.write_draft("mlops", [draft_topic(basis=""), draft_term(), clean])
        self.verdicts(mlops__serve__test_fixture_serving="keep", mlops__serve__test_fixture_batch_inference="keep", mlops__serve__test_fixture_throughput="keep")
        out = self.run_cmd("apply", "--auto")
        self.assertEqual(out["added"]["mlops"], ["mlops.serve.test-fixture-throughput"])
        reasons = {d["id"]: d["reason"] for d in out["dropped"]}
        self.assertTrue(reasons["mlops.serve.test-fixture-serving"].startswith("검사 오류"))
        self.assertIn("test-fixture-serving", reasons["mlops.serve.test-fixture-batch-inference"])

    def test_auto_apply_needs_verdicts_and_zero_yield_keeps_version(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic()])
        with self.assertRaises(SystemExit):
            self.run_cmd("apply", "--auto", ok=False)
        self.assertIsNotNone(self.run_cmd("status")["run"])   # 판정 파일이 없으면 아무것도 바꾸지 않는다
        self.run_cmd("cancel")
        self.run_cmd("campaign", "--level", "4", "--total", "10", "--round", "2")
        before = (self.repo / "catalog" / "VERSION").read_text().strip()
        for round_no in (1, 2):
            self.write_draft("mlops", [draft_topic()])
            self.verdicts(mlops__serve__test_fixture_serving="drop")
            out = self.run_cmd("apply", "--auto")
            self.assertEqual((out["version"], out["topics"], len(out["dropped"])), (before, 0, 1))
            if round_no == 1:
                self.assertEqual(out["campaign"]["next"], "continue")
                self.assertEqual(self.run_cmd("start")["round"], 2)
        self.assertEqual(out["campaign"]["next"], "stop")
        self.assertIn("연속", out["campaign"]["stop_reason"])
        self.assertEqual(self.run_cmd("status")["campaign"]["status"], "finished")
        self.assertNotIn("round", self.run_cmd("start", "--level", "4"))   # 끝난 캠페인은 보통 실행을 막지 않는다

    def test_campaign_stop_reasons_and_guards(self):
        catalog = {"levels": [{"level": 4, "name": "실전", "targets": {"topic": 1, "term": 1}}],
                   "items": [{"level": 4, "kind": "topic"}, {"level": 4, "kind": "term"}]}
        base = {"level": 4, "total": 100, "done": 0, "rounds": [], "over_target": False}
        self.assertIn("목표치", dm.campaign_stop_reason(base, catalog))
        self.assertIsNone(dm.campaign_stop_reason({**base, "over_target": True}, catalog))
        self.assertIn("목표 100개", dm.campaign_stop_reason({**base, "done": 100, "over_target": True}, catalog))
        low = [{"planned": 60, "applied": 20}, {"planned": 60, "applied": 29}]
        self.assertIn("연속", dm.campaign_stop_reason({**base, "over_target": True, "rounds": low}, catalog))
        self.assertIsNone(dm.campaign_stop_reason({**base, "over_target": True, "rounds": low[:1]}, catalog))
        self.assertIsNone(dm.campaign_stop_reason({**base, "over_target": True, "rounds": [low[0], {"planned": 60, "applied": 30}]}, catalog))
        for argv in (("--level", "9", "--total", "10"), ("--level", "4", "--total", str(dm.MAX_TOTAL + 1)),
                     ("--level", "4", "--total", "10", "--round", str(dm.MAX_COUNT + 1))):
            with self.assertRaises(SystemExit):
                self.run_cmd("campaign", *argv, ok=False)
        self.run_cmd("start", "--level", "4")
        with self.assertRaises(SystemExit):   # 실행이 열려 있으면 캠페인을 열지 않는다
            self.run_cmd("campaign", "--level", "4", "--total", "10", ok=False)
        self.run_cmd("cancel")
        self.run_cmd("campaign", "--level", "4", "--total", "10")
        self.run_cmd("cancel")   # cancel은 회차와 캠페인을 함께 닫는다
        self.assertEqual(self.run_cmd("status")["campaign"]["status"], "cancelled")

    def test_cancel_closes_campaign_but_keeps_applied_rounds(self):
        self.run_cmd("campaign", "--level", "4", "--total", "10", "--round", "1")
        self.write_draft("mlops", [draft_topic()])
        self.verdicts(mlops__serve__test_fixture_serving="keep")
        version = self.run_cmd("apply", "--auto")["version"]
        self.run_cmd("start")
        with self.assertRaises(SystemExit):
            self.run_cmd("start", "--level", "2", "--force", ok=False)
        with self.assertRaises(SystemExit):
            self.run_cmd("start", "--all", "--force", ok=False)
        out = self.run_cmd("cancel")
        self.assertTrue(out["campaign_cancelled"])
        self.assertIn("1회차 1개", out["message"])
        self.assertEqual((self.repo / "catalog" / "VERSION").read_text().strip(), version)
        self.assertIn("mlops.serve.test-fixture-serving", (self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8"))
        self.assertEqual(self.run_cmd("campaign", "--level", "2", "--total", "3")["level"], 2)   # 닫힌 뒤에는 새로 열 수 있다

    # ----- 전체 단계 (all) -----

    def write_level_draft(self, level: int, name: str, items: list[dict]) -> None:
        self.write_draft(f"L{level}/{name}", items)

    def test_start_all_plans_every_level_and_prewarms_corpus(self):
        self.say("s0", "대화 기록이 하나 있어요. ")
        out = self.run_cmd("start", "--all", "--count", "30")
        self.assertEqual((out["mode"], out["level"], sorted(out["levels"])), ("all", None, ["1", "2", "3", "4", "5"]))
        for key, plan in out["levels"].items():
            with self.subTest(level=key):
                self.assertEqual(plan["topics"] + plan["terms"], 30)
                self.assertTrue(all(p.endswith(f"L{key}/{d}.json") for d, p in plan["draft_files"].items()))
                self.assertTrue((self.repo / dm.WORK_DIR / dm.DRAFT_DIR / f"L{key}").is_dir())
        self.assertEqual(out["topics"], sum(p["topics"] for p in out["levels"].values()))
        self.assertIn("level_info", out["plans"]["3"])
        self.assertEqual(out["alias_sessions"], 1)   # 에이전트를 띄우기 전에 대화 기록 색인을 만들어 둔다
        self.assertTrue((self.repo / dm.WORK_DIR / dm.CORPUS_INDEX).exists())
        for bad in (["--all", "--level", "2"], ["--all", "--box"]):
            with self.assertRaises(SystemExit):
                self.run_cmd("start", "--force", *bad)

    def test_check_level_sees_only_its_level_and_skips_file_being_written(self):
        self.run_cmd("start", "--all", "--count", "10")
        self.write_level_draft(4, "mlops", [draft_topic(), draft_term()])
        self.write_level_draft(2, "be", [draft_topic("be.x.y", title="다른 이름", en="Another", level=2, basis="")])
        folder = self.repo / dm.WORK_DIR / dm.DRAFT_DIR
        (folder / "L3" / "fe.json").write_text('[{"id": "fe.half', encoding="utf-8")   # 다른 에이전트가 쓰는 중
        out = self.run_cmd("check", "--level", "4")
        self.assertEqual(out["errors"], [])                                 # 2단계의 오류는 보이지 않는다
        self.assertEqual((out["level"], out["items"]), (4, 2))
        self.assertTrue(any("L3/fe.json" in w and "쓰는 중" in w for w in out["warnings"]))
        self.assertEqual(out["quota"]["drafted"]["mlops"], {"topic": 1, "term": 1})
        self.assertTrue(out["quota"]["short"])
        with self.assertRaises(SystemExit):                                  # 전체 검사는 깨진 파일을 봐준다
            self.run_cmd("check", ok=False)
        with self.assertRaises(SystemExit):                                  # 자기 단계의 깨진 파일도 오류다
            self.run_cmd("check", "--level", "3", ok=False)
        (folder / "L3" / "fe.json").unlink()
        out = self.run_cmd("check", ok=False)
        self.assertTrue(any("be.x.y" in e for e in out["errors"]))
        self.assertEqual(out["quota"]["by_level"]["4"]["drafted"]["mlops"], {"topic": 1, "term": 1})
        status = self.run_cmd("status")
        self.assertEqual(status["draft_files"], ["L2/be.json", "L4/mlops.json"])
        self.assertIn("mlops", status["missing_files"]["4"] + list(status["drafted"]["4"]))
        out = self.run_cmd("cancel")
        self.assertEqual(out["removed_drafts"], ["L2/be.json", "L4/mlops.json"])
        self.assertEqual([p.name for p in folder.iterdir()], [])

    def test_cross_level_duplicate_is_tagged_for_both_levels(self):
        self.run_cmd("start", "--all", "--count", "10")
        self.write_level_draft(4, "mlops", [draft_topic()])
        self.write_level_draft(3, "mlops", [draft_topic("mlops.serve.model-serving-intro", level=3)])
        for level in (3, 4):
            out = self.run_cmd("check", "--level", str(level), ok=False)
            with self.subTest(level=level):
                self.assertTrue(out["cross_level"])
                self.assertTrue(all(e.startswith(dm.CROSS_LEVEL_TAG) for e in out["cross_level"]))
                self.assertIn("(L", out["cross_level"][0])
        out = self.run_cmd("check", "--level", "4", ok=False)
        self.assertTrue(any("wrong_level" in k for k in out["quota"]))
        self.assertEqual(out["quota"]["wrong_level"], [])
        self.assertEqual(self.run_cmd("check", "--level", "3", ok=False)["quota"]["wrong_level"], [])
        sheet = self.run_cmd("review-sheet")
        self.assertIn("단계 사이 겹침", Path(sheet["review"]).read_text(encoding="utf-8"))

    def test_review_sheet_all_writes_per_level_and_apply_merges_all(self):
        self.run_cmd("start", "--all", "--count", "10")
        self.write_level_draft(4, "mlops", [draft_topic(), draft_term()])
        self.write_level_draft(2, "mlops", [draft_term("mlops.serve.test-fixture-throughput", title="시험용 처리량", en="Test Fixture Throughput", level=2,
                                                       parent=None, aliases=["시험용 처리량", "test fixture throughput"], refs=["https://example.com/tp"])])
        out = self.run_cmd("review-sheet")
        self.assertEqual(sorted(out["reviews"]), ["1", "2", "3", "4", "5"])
        self.assertIn("| mlops.serve.test-fixture-serving | topic | 4 |", Path(out["reviews"]["4"]).read_text(encoding="utf-8"))
        self.assertNotIn("mlops.serve.test-fixture-serving", Path(out["reviews"]["2"]).read_text(encoding="utf-8"))
        index = Path(out["review"]).read_text(encoding="utf-8")
        self.assertIn("[4단계](review_4.md): 주제 1개, 용어 1개", index)
        self.assertIn("다섯 단계를 한 번에", index)
        before = (self.repo / "catalog" / "VERSION").read_text().strip()
        out = self.run_cmd("apply")
        self.assertEqual((out["topics"], out["terms"], out["version"]), (1, 2, dm.bump_version(before)))
        changelog = (self.repo / "catalog" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("모든 단계에 주제 1개, 용어 2개", changelog)
        self.assertIn("4단계 2개", changelog)
        self.assertEqual([p.name for p in (self.repo / dm.WORK_DIR / dm.DRAFT_DIR).iterdir()], [])
        self.assertEqual(self.run_cmd("status")["run"], None)

    def test_shared_caches_survive_a_concurrent_writer(self):
        repo = dm.Repo(self.repo)

        def slow_fetch(url):   # 네트워크를 여는 사이 다른 프로세스가 캐시에 항목을 넣는다
            repo.write_json(dm.LINKS_FILE, {"https://example.com/other": {"status": "200", "title": "다른 에이전트", "checked": dm.today()}})
            return {"status": "200", "title": "예시", "checked": dm.today()}

        dm.fetch_link = slow_fetch
        dm.check_links(repo, ["https://example.com/mine"])
        cache = repo.read_json(dm.LINKS_FILE, {})
        self.assertEqual(sorted(cache), ["https://example.com/mine", "https://example.com/other"])
        self.assertEqual([p.name for p in (self.repo / dm.WORK_DIR).glob("*.tmp")], [])
        with repo.locked():
            self.assertTrue((self.repo / dm.WORK_DIR / dm.LOCK_FILE).exists())

    # ----- 갱신 -----

    def test_refresh_lists_stale_volatile_and_mark_checked_updates(self):
        path = self.repo / "catalog" / "items" / "rag.json"
        items = json.loads(path.read_text(encoding="utf-8"))
        target = next(i for i in items if i.get("volatile"))
        target["checked_at"] = "2020-01-01"
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        out = self.run_cmd("refresh")
        self.assertIn(target["id"], [s["id"] for s in out["stale_volatile"]])
        self.run_cmd("mark-checked", "--ids", target["id"])
        self.assertNotIn(target["id"], [s["id"] for s in self.run_cmd("refresh")["stale_volatile"]])
        with self.assertRaises(SystemExit):
            self.run_cmd("mark-checked", "--ids", "no.such.id", ok=False)

    def test_refuses_outside_repo(self):
        with self.assertRaises(SystemExit):
            dm.main(["--repo", self._tmp.name, "status"])


def sys_tool_check(repo: Path) -> int:
    spec = importlib.util.spec_from_file_location("catalog_tool_check", repo / "catalog" / "tools" / "catalog.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.cmd_check(repo / "catalog")


class SkillDocsTest(unittest.TestCase):
    def test_skill_describes_options_and_stops_before_apply(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("/dic-maker box", "/dic-maker c", "/dic-maker apply", "/dic-maker refresh", "/dic-maker a 30", "review-sheet",
                       "apply를 스스로 실행하지 않는다", "푸시는 사용자에게 묻는다", "적대적 검토자", "guide --domain", "mark-checked",
                       "start --all", "check --links --level", "review_1.md", "[단계 간]",
                       "/dic-maker 3 240 auto", "campaign --level", "apply --auto", "review-verdicts.json", "campaign-dropped.json"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_plugin_lists_skills_folder(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("./skills", plugin["skills"])
        self.assertTrue((SKILL_DIR / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
