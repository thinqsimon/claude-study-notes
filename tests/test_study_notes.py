"""study_notes.py 단위 테스트. 표준 라이브러리 unittest만 쓴다.

실행: python3 -m unittest discover -s tests -v
실제 ~/StudyNotes와 ~/.claude 기록은 건드리지 않는다(임시 폴더만 쓴다).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "study-notes"

_spec = importlib.util.spec_from_file_location("study_notes", SKILL_DIR / "scripts" / "study_notes.py")
sn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sn)


def run(*argv: str) -> dict:
    """스크립트 main()을 실행하고 stdout JSON을 돌려준다."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = sn.main(list(argv))
    assert code == 0, code
    return json.loads(buf.getvalue())


def cells(row: str) -> list[str]:
    return [c.strip() for c in row.split("|")[1:-1]]


NOTE = """---
title: demo 배움노트 #01 · 3단계 기초
project: demo
level: 3
level_name: 기초
session: abcdef12
created: 2026-10-31 10:00
covers: 2026-10-31 09:00 ~ 2026-10-31 10:00
topics: 2
---
# demo 배움노트 #01 · 2026-10-31 · 3단계 기초

> 설명 수준: 3단계 기초. 변수·함수·조건문을 익힌 분에게 맞춰 썼어요.
>
> 체크포인트와 경로 정규화를 다뤘다.

## 목차
| # | 주제 | 유형 | 난이도 |
|---|---|---|---|
| 1 | 체크포인트 | 개념 | ★★☆ |
| 2 | 경로 정규화 | 문제해결 | ★★☆ |

---

## 1. 체크포인트
> 한 줄 요약: 어디까지 처리했는지 저장해 두면 다음엔 그 뒤만 처리한다.

`유형` 개념 | `태그` 설계, 상태관리 | `난이도` ★★☆

본문.

## 2. 경로 정규화
> 한 줄 요약: macOS 한글 경로는 NFD라서 NFC로 맞춰야 비교가 된다.

`유형` 문제해결 | `태그` unicode, macos | `난이도` ★★☆

본문.
"""
NOTE_WITHOUT_LEVEL = NOTE.replace("level: 3\nlevel_name: 기초\n", "")


class ParseLevelTest(unittest.TestCase):
    def test_numbers_names_and_prefixes(self):
        cases = {"3": 3, " 5 ": 5, "3단계": 3, "3 단계": 3, "기초": 3, "3단계 기초": 3, "심화": 5,
                 "level=4": 4, "Level 1": 1, "수준: 입문": 2, "lv2": 2, 4: 4}
        for text, level in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sn.parse_level(text), level)

    def test_rejects_unknown_or_mismatched(self):
        for text in ("", "0", "6", "30", "중급", "3단계 심화", "왕초보 입문"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    sn.parse_level(text)

    def test_names_match_the_app_and_default_is_two(self):
        self.assertEqual([sn.level_label(n) for n in sorted(sn.LEVELS)],
                         ["1단계 왕초보", "2단계 입문", "3단계 기초", "4단계 실전", "5단계 심화"])
        self.assertEqual(sn.DEFAULT_LEVEL, 2)


class LevelCommandTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_unset_shows_table_then_choice_is_remembered(self):
        out = run("level", "--notes-root", str(self.root))
        self.assertEqual((out["level"], out["level_source"]), (2, "unset"))
        self.assertEqual([row["label"] for row in out["levels"]][0], "1단계 왕초보")
        self.assertEqual(len(out["levels"]), 5)

        out = run("level", "4", "--notes-root", str(self.root))
        self.assertEqual((out["level"], out["level_label"], out["level_source"]), (4, "4단계 실전", "saved"))
        self.assertEqual(json.loads((self.root / "settings.json").read_text(encoding="utf-8")), {"level": 4})

        out = run("level", "--notes-root", str(self.root))
        self.assertEqual((out["level"], out["level_source"]), (4, "saved"))
        self.assertNotIn("levels", out)

    def test_two_word_value(self):
        self.assertEqual(run("level", "3단계", "기초", "--notes-root", str(self.root))["level"], 3)

    def test_invalid_value_exits_with_message_and_saves_nothing(self):
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sn.main(["level", "7", "--notes-root", str(self.root)])
        self.assertIn("알 수 없는 설명 수준", str(caught.exception.code))
        self.assertFalse((self.root / "settings.json").exists())

    def test_broken_settings_file_counts_as_unset(self):
        (self.root / "settings.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(run("level", "--notes-root", str(self.root))["level_source"], "unset")

    def test_other_settings_keys_survive(self):
        (self.root / "settings.json").write_text('{"memo": "keep"}', encoding="utf-8")
        run("level", "5", "--notes-root", str(self.root))
        self.assertEqual(json.loads((self.root / "settings.json").read_text(encoding="utf-8")),
                         {"memo": "keep", "level": 5})


class ExtractCommitTest(unittest.TestCase):
    """가짜 Claude Code 기록으로 extract → 노트 작성 → commit을 끝까지 돌린다."""

    session = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "notes"
        self.cwd = base / "demo"
        self.cwd.mkdir()
        projects = base / "projects"
        pdir = projects / sn.encode_cwd(sn.normalize_cwd(str(self.cwd)))
        pdir.mkdir(parents=True)
        records = [
            {"type": "user", "uuid": "u1", "timestamp": "2026-10-31T00:00:00Z",
             "message": {"content": "체크포인트가 뭐예요?"}},
            {"type": "assistant", "uuid": "a1", "timestamp": "2026-10-31T00:00:05Z",
             "message": {"content": [{"type": "text", "text": "어디까지 처리했는지 저장해 두는 것입니다."}]}},
        ]
        (pdir / f"{self.session}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
        self._projects = sn.PROJECTS_DIR
        sn.PROJECTS_DIR = projects

    def tearDown(self):
        sn.PROJECTS_DIR = self._projects
        self._tmp.cleanup()

    def extract(self, *extra: str) -> dict:
        return run("extract", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                   "--notes-root", str(self.root), *extra)

    def commit(self, note: Path) -> dict:
        return run("commit", "--agent", "claude", "--session", self.session, "--file", str(note),
                   "--notes-root", str(self.root))

    def write_note(self, out: dict, body: str) -> Path:
        note = Path(out["suggested_file"])
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(body, encoding="utf-8")
        return note

    def test_first_run_reports_unset_level_with_table(self):
        out = self.extract()
        self.assertEqual(out["new_messages"], 2)
        self.assertEqual((out["level"], out["level_label"], out["level_source"]), (2, "2단계 입문", "unset"))
        self.assertEqual(len(out["levels"]), 5)
        self.assertFalse((self.root / "settings.json").exists())

    def test_level_argument_is_used_and_remembered(self):
        out = self.extract("--level", "기초")
        self.assertEqual((out["level"], out["level_source"], out["level_audience"]),
                         (3, "argument", "변수·함수·조건문을 익힌 분"))
        self.assertNotIn("levels", out)
        self.assertEqual((self.extract()["level"], self.extract()["level_source"]), (3, "saved"))
        status = run("status", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                     "--notes-root", str(self.root))
        self.assertEqual((status["level_label"], status["level_source"]), ("3단계 기초", "saved"))

    def test_invalid_level_argument_stops_before_extracting(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            sn.main(["extract", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                     "--notes-root", str(self.root), "--level", "중급"])
        self.assertFalse((self.root / ".state").exists())

    def test_commit_writes_level_column(self):
        note = self.write_note(self.extract("--level", "3"), NOTE)
        result = self.commit(note)
        self.assertEqual((result["topics"], result["level"]), (2, "3단계 기초"))
        index = (self.root / "index.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("| 날짜 | 프로젝트 | 수준 | 주제 | 유형 | 태그 | 요약 | 노트 |", index)
        self.assertIn("|---|---|---|---|---|---|---|---|", index)
        row = cells(next(line for line in index if "| 체크포인트 |" in line))
        self.assertEqual(row[1:6], ["demo", "3단계 기초", "체크포인트", "개념", "설계, 상태관리"])
        self.assertTrue(row[6].startswith("어디까지 처리했는지"))
        self.assertIn("#1-체크포인트)", row[7])

    def test_note_level_wins_over_extract_level(self):
        note = self.write_note(self.extract("--level", "5"), NOTE)
        self.assertEqual(self.commit(note)["level"], "3단계 기초")

    def test_commit_falls_back_to_extract_level(self):
        note = self.write_note(self.extract("--level", "5"), NOTE_WITHOUT_LEVEL)
        self.assertEqual(self.commit(note)["level"], "5단계 심화")


class UpgradeIndexTest(unittest.TestCase):
    """예전 index.md(6열·7열)를 8열로 바꾼다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "demo").mkdir()
        (self.root / "demo" / "demo_2026-10-31_01.md").write_text(NOTE, encoding="utf-8")
        (self.root / "demo" / "2026-10-27_01.md").write_text(NOTE_WITHOUT_LEVEL, encoding="utf-8")
        self.index = self.root / "index.md"

    def tearDown(self):
        self._tmp.cleanup()

    def rows(self) -> list[list[str]]:
        return [cells(line) for line in self.index.read_text(encoding="utf-8").splitlines()
                if line.startswith("| 2026")]

    def test_seven_columns_gain_level_column(self):
        self.index.write_text(
            "# 학습 주제 목록\n\n안내문\n\n"
            "| 날짜 | 프로젝트 | 주제 | 유형 | 태그 | 요약 | 노트 |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 2026-10-31 | demo | 체크포인트 | 개념 | 설계 | 요약문 | [demo_2026-10-31_01#1](demo/demo_2026-10-31_01.md#1-체크포인트) |\n"
            "| 2026-10-27 | demo | 경로 정규화 | 문제해결 | unicode | 요약2 | [2026-10-27_01#2](demo/2026-10-27_01.md#2-경로-정규화) |\n",
            encoding="utf-8")
        sn.upgrade_index(self.index, self.root)
        lines = self.index.read_text(encoding="utf-8").splitlines()
        self.assertIn("| 날짜 | 프로젝트 | 수준 | 주제 | 유형 | 태그 | 요약 | 노트 |", lines)
        self.assertIn("|---|---|---|---|---|---|---|---|", lines)
        self.assertIn("안내문", lines)
        first, second = self.rows()
        self.assertEqual(first[:4], ["2026-10-31", "demo", "3단계 기초", "체크포인트"])
        self.assertEqual(first[6], "요약문")
        self.assertEqual(second[2], "")          # 예전 노트는 level이 없다
        before = self.index.read_text(encoding="utf-8")
        sn.upgrade_index(self.index, self.root)    # 두 번 돌려도 그대로
        self.assertEqual(self.index.read_text(encoding="utf-8"), before)

    def test_six_columns_gain_summary_and_level(self):
        self.index.write_text(
            "| 날짜 | 프로젝트 | 주제 | 유형 | 태그 | 노트 |\n"
            "|---|---|---|---|---|---|\n"
            "| 2026-10-31 | demo | 체크포인트 | 개념 | 설계 | [demo_2026-10-31_01#1](demo/demo_2026-10-31_01.md#1-체크포인트) |\n",
            encoding="utf-8")
        sn.upgrade_index(self.index, self.root)
        (row,) = self.rows()
        self.assertEqual(len(row), 8)
        self.assertEqual(row[2], "3단계 기초")
        self.assertTrue(row[6].startswith("어디까지 처리했는지"))


class DocsTest(unittest.TestCase):
    def test_skill_and_readme_list_every_level(self):
        for doc in (SKILL_DIR / "SKILL.md", ROOT / "README.md"):
            text = doc.read_text(encoding="utf-8")
            for n in sn.LEVELS:
                with self.subTest(doc=doc.name, level=n):
                    self.assertIn(sn.level_label(n), text)

    def test_template_shows_level(self):
        template = (SKILL_DIR / "templates" / "note.md").read_text(encoding="utf-8")
        for marker in ("level: ", "level_name: ", "· <level_label>", "> 설명 수준: <level_label>"):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)


if __name__ == "__main__":
    unittest.main()
