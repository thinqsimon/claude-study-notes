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


def draft_topic(item_id: str = "mlops.serve.model-serving", **extra) -> dict:
    return {
        "id": item_id, "title": "모델 서빙 기본", "en": "Model Serving Basics", "kind": "topic", "level": 4, "importance": 2,
        "group": "모델 서빙", "summary": "학습한 모델을 API 뒤에 두고 요청마다 추론하는 구조와 배치·실시간의 차이를 정한다.",
        "objectives": ["실시간 추론과 배치 추론을 요구사항에 맞게 고를 수 있다", "모델 서버의 지연과 처리량을 재서 병목을 찾을 수 있다"],
        "aliases": ["모델 서빙", "model serving"], "refs": ["https://example.com/serving"],
        "basis": "예시 자료의 Serving 절. 여러 기술을 엮는 설계라 4단계. 서비스 제작 경로라 ★★.", **extra,
    }


def draft_term(item_id: str = "mlops.serve.batch-inference", **extra) -> dict:
    return {
        "id": item_id, "title": "배치 추론", "en": "Batch Inference", "kind": "term", "level": 4, "importance": 2,
        "group": "모델 서빙", "summary": "모아 둔 입력을 한꺼번에 추론해 결과를 저장해 두는 방식이다.",
        "parent": "mlops.serve.model-serving", "aliases": ["배치 추론", "batch inference"], "basis": "위 주제가 가르치는 용어.", **extra,
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
        self.box("임시 파일과 원자적 교체")
        out = self.run_cmd("start", "--force", "--box")
        self.assertEqual((out["mode"], out["box"], list(out["draft_files"])), ("box", ["임시 파일과 원자적 교체"], ["box"]))

    def test_guide_has_rules_level_criteria_and_existing_items(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(dm.main(["--repo", str(self.repo), "guide", "--domain", "mlops", "--level", "4"]), 0)
        text = buf.getvalue()
        for marker in ("자료가 먼저다", '"can_do"', "## 항목 형식", "mlops.", "## 넓은 말", "basis"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn("## 절차", text)

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
            self.say(f"s{n}", "모델 서빙 얘기를 또 했어요. 추론 서버요. ")
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(title="모델 서빙", en="Model Serving", aliases=["모델 서빙", "추론 서버"],
                                               refs=["https://dead.invalid/x"])])
        out = self.run_cmd("check", "--links", ok=False)
        self.assertTrue(any("응답 404" in e for e in out["errors"]))
        self.assertTrue(any("'추론 서버'" in e and "너무 넓다" in e for e in out["errors"]))
        self.assertFalse(any("'모델 서빙'" in e for e in out["errors"]))   # 항목 자신의 이름은 막지 않는다
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
        self.assertIn("| mlops.serve.model-serving | topic | 4 | ★★ |", text)
        self.assertIn("부모: mlops.serve.model-serving", text)
        self.assertIn("## 검사 오류", text)
        self.assertEqual((out["items"], out["errors"]), (2, 1))

    def test_apply_merges_bumps_version_builds_and_clears(self):
        self.box("모델 서빙 기본")
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic(), draft_term(),
                                   draft_term("mlops.serve.throughput", title="처리량", en="Throughput", parent=None,
                                              aliases=["처리량", "throughput"], refs=["https://example.com/tp"])])
        before = (self.repo / "catalog" / "VERSION").read_text().strip()
        out = self.run_cmd("apply", "--note", "서빙 항목 시험")
        self.assertEqual((out["topics"], out["terms"], out["previous"]), (1, 2, before))
        self.assertEqual(out["version"], dm.bump_version(before))
        self.assertEqual(out["box_covered"], ["모델 서빙 기본"])
        items = json.loads((self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8"))
        wanted = {"mlops.serve.model-serving", "mlops.serve.batch-inference", "mlops.serve.throughput"}
        added = {i["id"]: i for i in items if i["id"] in wanted}
        self.assertEqual(set(added), wanted)
        self.assertNotIn("basis", added["mlops.serve.model-serving"])
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
        self.assertNotIn("mlops.serve.model-serving", (self.repo / "catalog" / "items" / "mlops.json").read_text(encoding="utf-8"))

    def test_cancel_removes_drafts_but_not_catalog(self):
        self.run_cmd("start", "--level", "4")
        self.write_draft("mlops", [draft_topic()])
        out = self.run_cmd("cancel")
        self.assertEqual((out["cancelled"], out["removed_drafts"]), (True, ["mlops.json"]))
        self.assertEqual(self.run_cmd("cancel")["cancelled"], False)
        self.assertEqual(self.run_cmd("status")["version"], (ROOT / "catalog" / "VERSION").read_text().strip())

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
        for marker in ("/dic-maker box", "/dic-maker c", "/dic-maker apply", "/dic-maker refresh", "review-sheet",
                       "apply를 스스로 실행하지 않는다", "푸시는 사용자에게 묻는다", "적대적 검토자", "guide --domain", "mark-checked"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_plugin_lists_skills_folder(self):
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertIn("./skills", plugin["skills"])
        self.assertTrue((SKILL_DIR / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
