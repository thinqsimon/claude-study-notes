"""study_notes.py 단위 테스트. 표준 라이브러리 unittest만 쓴다.

실행: python3 -m unittest discover -s tests -v
실제 ~/StudyNotes와 ~/.claude 기록은 건드리지 않는다(임시 폴더만 쓴다).
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "study-notes"

_spec = importlib.util.spec_from_file_location("study_notes", SKILL_DIR / "scripts" / "study_notes.py")
sn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sn)
concepts = sn.concepts


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

    def write_v1_note(self, body: str) -> Path:
        """v1 형식 노트. 개념노트 폴더 밖에 쓰면 검사하지 않고 등록한다."""
        note = self.root / "demo" / "demo_2026-10-31_01.md"
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
        self.extract("--level", "3")
        result = self.commit(self.write_v1_note(NOTE))
        self.assertEqual((result["topics"], result["level"]), (2, "3단계 기초"))
        index = (self.root / "index.md").read_text(encoding="utf-8").splitlines()
        self.assertIn("| 날짜 | 프로젝트 | 수준 | 주제 | 유형 | 태그 | 요약 | 노트 |", index)
        self.assertIn("|---|---|---|---|---|---|---|---|", index)
        row = cells(next(line for line in index if "| 체크포인트 |" in line))
        self.assertEqual(row[1:6], ["demo", "3단계 기초", "체크포인트", "개념", "설계, 상태관리"])
        self.assertTrue(row[6].startswith("어디까지 처리했는지"))
        self.assertIn("#1-체크포인트)", row[7])

    def test_note_level_wins_over_extract_level(self):
        self.extract("--level", "5")
        self.assertEqual(self.commit(self.write_v1_note(NOTE))["level"], "3단계 기초")

    def test_commit_falls_back_to_extract_level(self):
        self.extract("--level", "5")
        self.assertEqual(self.commit(self.write_v1_note(NOTE_WITHOUT_LEVEL))["level"], "5단계 심화")


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


class CancelTest(ExtractCommitTest):
    """extract 뒤 commit 전에 cancel하면 미완성 노트·델타만 지우고 체크포인트는 남긴다."""

    def cancel(self) -> dict:
        return run("cancel", "--agent", "claude", "--session", self.session, "--notes-root", str(self.root))

    def status(self) -> dict:
        return run("status", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                   "--notes-root", str(self.root))

    def test_cancel_removes_partial_note_and_delta_but_keeps_checkpoint(self):
        out = self.extract("--level", "3")
        note = self.write_note(out, "# 쓰다 만 노트\n")
        self.assertTrue(Path(out["delta_path"]).exists())
        progress = self.status()["in_progress"]
        self.assertEqual((progress["note"], progress["note_exists"], progress["level"]), (str(note), True, "3단계 기초"))

        result = self.cancel()
        self.assertEqual((result["cancelled"], result["removed_note"], result["removed_delta"]), (True, str(note), True))
        self.assertFalse(note.exists())
        self.assertFalse(Path(out["delta_path"]).exists())
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        self.assertNotIn("_pending", state)
        self.assertIsNone(state["last_uuid"])          # 체크포인트는 그대로
        self.assertIsNone(self.status()["in_progress"])
        self.assertEqual(self.extract()["new_messages"], 2)   # 다음 실행이 같은 대화를 다시 잘라낸다

    def test_cancel_without_pending_reports_nothing_to_cancel(self):
        result = self.cancel()
        self.assertEqual((result["cancelled"], result["removed_note"]), (False, None))

    def test_cancel_never_deletes_committed_note(self):
        self.extract("--level", "3")
        note = self.write_v1_note(NOTE)
        self.commit(note)
        # 다음 extract는 같은 경로가 아닌 _02를 제안하지만, pending이 커밋된 파일을 가리켜도 지우지 않는지 확인한다
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        state["_pending"] = {"last_uuid": "x", "last_timestamp": "x", "level": 3, "suggested_file": str(note)}
        sn.save_state(self.root, self.session, state)
        result = self.cancel()
        self.assertEqual((result["cancelled"], result["removed_note"]), (True, None))
        self.assertTrue(note.exists())


class DocsTest(unittest.TestCase):
    def test_skill_and_readme_describe_options(self):
        for doc in (SKILL_DIR / "SKILL.md", ROOT / "README.md"):
            text = doc.read_text(encoding="utf-8")
            for marker in ("/study-notes h", "/study-notes d", "/study-notes s", "cancel"):
                with self.subTest(doc=doc.name, marker=marker):
                    self.assertIn(marker, text)

    def test_skill_and_readme_list_every_level(self):
        for doc in (SKILL_DIR / "SKILL.md", ROOT / "README.md"):
            text = doc.read_text(encoding="utf-8")
            for n in sn.LEVELS:
                with self.subTest(doc=doc.name, level=n):
                    self.assertIn(sn.level_label(n), text)

    def test_template_shows_level(self):
        template = (SKILL_DIR / "templates" / "concept-note.md").read_text(encoding="utf-8")
        for marker in ("level: ", "level_name: ", "· <level_label>", "> 설명 수준: <level_label>"):
            with self.subTest(marker=marker):
                self.assertIn(marker, template)


def concept_note(items: list[dict], level: int, version: str = "0.2.0") -> str:
    """사전 항목으로 검사를 통과하는 개념노트를 만든다."""
    label = sn.level_label(level)
    head = (
        f"---\ntitle: AX 개념노트 #01 · {label}\nproject: AX 개념노트\nlevel: {level}\n"
        f"level_name: {sn.LEVELS[level]['name']}\ncatalog_version: {version}\ncreated: 2026-11-03 10:00\n"
        f"topics: {len(items)}\n---\n# AX 개념노트 #01 · {label}\n\n> 설명 수준: {label}. 맞춰 썼어요.\n\n"
    )
    body = []
    for number, item in enumerate(items, 1):
        goals = "\n".join(f"- {goal}" for goal in item.get("objectives", []))
        body.append(
            f"## {number}. {item['title']} ({item['en']})\n> 한 줄 요약: {item['summary']}\n\n"
            f"`유형` 개념 | `태그` 시험 | `난이도` {'★' * level} | `개념` {item['id']} | `단계` {label} | `중요도` ★★★\n\n"
            f"### 학습 목표\n{goals}\n\n### 먼저 알아야 할 것\n없음\n\n### 왜 필요한가\n{'본문 ' * 1300}\n\n"
            "### 핵심 개념\n설명\n\n### 예제로 이해하기\n```bash\n## 코드 안의 제목은 주제가 아니다\necho hi\n```\n\n"
            "### 비슷한 개념과 차이\n차이\n\n### 흔한 실수\n실수\n\n### 직접 해 보기\n과제\n\n"
            "### 확인 문제\n1. 질문?\n2. 질문?\n\n### 정답\n1. 답\n2. 답\n\n"
            "### 공식 문서\n- [문서](https://example.com/doc) — 설명\n\n---\n\n"
        )
    return head + "".join(body)


class ConceptFlowTest(unittest.TestCase):
    """대화에서 후보를 찾아 개념노트를 등록하기까지."""

    session = "aaaaaaaa-2222-3333-4444-555555555555"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "notes"
        self.cwd = base / "demo"
        self.cwd.mkdir()
        projects = base / "projects"
        self.pdir = projects / sn.encode_cwd(sn.normalize_cwd(str(self.cwd)))
        self.pdir.mkdir(parents=True)
        self.write_records("r1", "JWT로 로그인을 만들고 토큰을 검증하는 방법을 알려 주세요. CORS 오류도 났어요.")
        self._projects = sn.PROJECTS_DIR
        sn.PROJECTS_DIR = projects
        self.catalog = concepts.load_catalog()
        self.by_id = {item["id"]: item for item in self.catalog["items"]}

    def tearDown(self):
        sn.PROJECTS_DIR = self._projects
        self._tmp.cleanup()

    def write_records(self, uuid: str, text: str) -> None:
        with (self.pdir / f"{self.session}.jsonl").open("a", encoding="utf-8") as fh:
            for kind, key in (("user", "u"), ("assistant", "a")):
                content = text if kind == "user" else [{"type": "text", "text": text}]
                fh.write(json.dumps({"type": kind, "uuid": f"{uuid}{key}", "timestamp": f"2026-11-03T00:00:0{len(uuid)}Z",
                                     "message": {"content": content}}, ensure_ascii=False) + "\n")

    def extract(self, *extra: str) -> dict:
        return run("extract", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                   "--notes-root", str(self.root), *extra)

    def commit(self, note: Path) -> dict:
        return run("commit", "--agent", "claude", "--session", self.session, "--file", str(note),
                   "--notes-root", str(self.root))

    def commit_error(self, note: Path) -> str:
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sn.main(["commit", "--agent", "claude", "--session", self.session, "--file", str(note),
                     "--notes-root", str(self.root)])
        return str(caught.exception)

    def write_note(self, out: dict, text: str) -> Path:
        note = Path(out["suggested_file"])
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(text, encoding="utf-8")
        return note

    def test_extract_lists_candidates_for_the_level(self):
        out = self.extract("--level", "3")
        self.assertEqual(Path(out["suggested_file"]).parent.name, sn.CONCEPT_FOLDER)
        self.assertEqual((out["note_no"], out["catalog_version"]), (1, self.catalog["version"]))
        ids = [c["id"] for c in out["candidates"]]
        self.assertIn("be.auth.jwt-flow", ids)
        self.assertTrue(all(self.by_id[i]["level"] == 3 and self.by_id[i]["kind"] == "topic" for i in ids))
        self.assertIn("4", out["other_levels"])      # CORS는 4단계에 있다
        self.assertEqual(out["candidates"], sorted(out["candidates"], key=lambda c: (-len(c["importance"]), -c["hits"], c["id"])))

    def test_no_candidates_for_unrelated_talk(self):
        (self.pdir / f"{self.session}.jsonl").unlink()
        self.write_records("r2", "오늘 점심은 김치찌개를 먹었어요.")
        out = self.extract("--level", "3")
        self.assertEqual((out["candidates"], out["candidate_total"], out["other_levels"]), ([], 0, {}))

    def test_tool_output_is_not_counted_as_talk(self):
        (self.pdir / f"{self.session}.jsonl").unlink()
        record = {"type": "assistant", "uuid": "t1", "timestamp": "2026-11-03T00:00:01Z", "message": {"content": [
            {"type": "text", "text": "파일을 읽어 볼게요."},
            {"type": "tool_use", "name": "Read", "input": {"file_path": "src/jwt_session.py"}},
        ]}}
        result = {"type": "user", "uuid": "t2", "timestamp": "2026-11-03T00:00:02Z", "message": {"content": [
            {"type": "tool_result", "content": "def verify_jwt(token): session = cors()"},
        ]}}
        (self.pdir / f"{self.session}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in (record, result)) + "\n", encoding="utf-8")
        out = self.extract("--level", "3")
        self.assertEqual(out["new_messages"], 2)
        self.assertEqual(out["candidates"], [])

    def test_cancel_keeps_note_registered_by_another_session(self):
        # 이 세션이 추천받은 이름으로 다른 세션이 먼저 노트를 등록한 경우
        mine = self.extract("--level", "3")
        other = "bbbbbbbb-2222-3333-4444-555555555555"
        (self.pdir / f"{other}.jsonl").write_text(
            (self.pdir / f"{self.session}.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
        run("extract", "--agent", "claude", "--cwd", str(self.cwd), "--session", other, "--notes-root", str(self.root))
        note = self.write_note(mine, concept_note([self.by_id["be.auth.jwt-flow"]], 3))
        run("commit", "--agent", "claude", "--session", other, "--file", str(note), "--notes-root", str(self.root))
        result = run("cancel", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                     "--notes-root", str(self.root))
        self.assertEqual((result["cancelled"], result["removed_note"]), (True, None))
        self.assertTrue(note.exists())

    def test_cancel_still_removes_unfinished_note(self):
        out = self.extract("--level", "3")
        note = self.write_note(out, "쓰다 만 노트")
        result = run("cancel", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                     "--notes-root", str(self.root))
        self.assertEqual(result["removed_note"], str(note))
        self.assertFalse(note.exists())

    def test_commit_records_used_concept_and_hides_it_next_time(self):
        out = self.extract("--level", "3")
        result = self.commit(self.write_note(out, concept_note([self.by_id["be.auth.jwt-flow"]], 3)))
        self.assertEqual((result["topics"], result["concepts"]), (1, ["be.auth.jwt-flow"]))
        used = json.loads((self.root / "concepts_used.json").read_text(encoding="utf-8"))
        self.assertTrue(used["be.auth.jwt-flow"]["note"].startswith(f"{sn.CONCEPT_FOLDER}/"))
        self.assertIn("be.auth.jwt-flow", (self.root / "index.md").read_text(encoding="utf-8") + str(used))
        self.write_records("r3", "JWT 로그인을 다시 설명해 주세요.")
        again = self.extract()
        self.assertEqual(again["note_no"], 2)
        self.assertNotIn("be.auth.jwt-flow", [c["id"] for c in again["candidates"]])

    def test_commit_rejects_used_concept_and_keeps_pending(self):
        out = self.extract("--level", "3")
        self.commit(self.write_note(out, concept_note([self.by_id["be.auth.jwt-flow"]], 3)))
        self.write_records("r3", "JWT 다시 한 번")
        second = self.extract()
        message = self.commit_error(self.write_note(second, concept_note([self.by_id["be.auth.jwt-flow"]], 3)))
        self.assertIn("이미 쓴 개념", message)
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        self.assertIn("_pending", state)             # 고쳐서 다시 commit 할 수 있다
        self.assertEqual(state["run_count"], 1)

    def test_commit_rejects_note_that_breaks_rules(self):
        out = self.extract("--level", "3")
        good = concept_note([self.by_id["be.auth.jwt-flow"]], 3)
        cases = {
            "`개념` id가 없다": good.replace("`개념` be.auth.jwt-flow", "`개념 없음`"),
            "프로젝트·대화에 묶인": good.replace("### 핵심 개념\n설명", "### 핵심 개념\n이번 대화에서 만든 코드"),
            "catalog_version": good.replace("catalog_version: 0.2.0\n", ""),
            "닫히지 않은 코드 블록": good + "\n```bash\necho\n",
            "'## N. 제목'": good.replace("## 1. ", "## "),
            "한 줄 요약": good.replace("> 한 줄 요약:", "요약:"),
            "소제목": good.replace("### 흔한 실수\n실수\n\n", ""),
            "설명 수준": good.replace("> 설명 수준:", "> 수준:"),
            "업로드가 막히는 표기": good.replace("### 핵심 개념\n설명", "### 핵심 개념\n`curl -s https://example.com`으로 확인한다"),
            "목차 아래에는 표만": good.replace("# AX 개념노트 #01", "## 목차\n| # | 주제 |\n|---|---|\n\n예제 환경은 맥이다.\n\n# AX 개념노트 #01", 1),
            "이 실행에서": good.replace("### 핵심 개념\n설명", "### 핵심 개념\n이 실행에서는 짧은 키를 썼다"),
        }
        for expected, text in cases.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, self.commit_error(self.write_note(out, text)))
        self.assertFalse((self.root / "concepts_used.json").exists())

    def test_ordinary_sentence_about_running_is_not_rejected(self):
        out = self.extract("--level", "3")
        text = concept_note([self.by_id["be.auth.jwt-flow"]], 3).replace("### 핵심 개념\n설명", "### 핵심 개념\n명령이 실행됩니다.")
        self.assertEqual(self.commit(self.write_note(out, text))["concepts"], ["be.auth.jwt-flow"])

    def test_commit_rejects_wrong_level_term_and_too_many_topics(self):
        out = self.extract("--level", "3")
        topics = [i for i in self.catalog["items"] if i["kind"] == "topic" and i["level"] == 3]
        self.assertIn("4단계인데", self.commit_error(self.write_note(out, concept_note([self.by_id["be.http.cors"]], 3))))
        self.assertIn("5개까지", self.commit_error(self.write_note(out, concept_note(topics[:6], 3))))
        term = next(i for i in self.catalog["items"] if i["kind"] == "term" and i["level"] == 3)
        self.assertIn("용어는 주제가 될 수 없다", self.commit_error(self.write_note(out, concept_note([term], 3))))

    def test_concept_shows_what_is_needed_to_write(self):
        detail = run("concept", "be.auth.jwt-flow")["concepts"][0]
        self.assertEqual(detail["objectives"], self.by_id["be.auth.jwt-flow"]["objectives"])
        self.assertTrue(detail["refs"])
        self.assertIn("importance", detail)
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
            sn.main(["concept", "be.없는.항목"])

    def test_candidate_box_skips_duplicates(self):
        common = ("--cwd", str(self.cwd), "--notes-root", str(self.root))
        self.assertEqual(run("candidate", "--title", "React 훅", "--title", "Zustand", *common)["added"], ["React 훅", "Zustand"])
        self.assertEqual(run("candidate", "--title", "react 훅", "--title", "SSR", *common)["added"], ["SSR"])
        text = (self.root / sn.CANDIDATE_FILE).read_text(encoding="utf-8")
        self.assertEqual(text.count("| demo |"), 3)


class UploadBlockTest(unittest.TestCase):
    """운영 앞단에서 직접 시험한 결과를 고정한다."""

    def test_shapes_blocked_by_the_edge(self):
        for text in ("`python -c ", "`curl -s ", "`curl https://example.com`", "`perl -e ", "|python -c ", "; python -c ",
                     '```\npython -c "x"\n```', "`python -m pip`", "| python -m json.tool", "```\npython -m x", "`wget -q ",
                     "`curl -X POST`", "'\ncurl -s http://x", "'\ncurl http://x", "'\npython -c x", "'\npython -m x",
                     "'\nwget http://x", "'\nperl -e x",
                     "curl http://x -d '{\"a\": 1}'\ncurl http://y -d '{\"b\": 2}'"):
            with self.subTest(text=text):
                self.assertIsNotNone(concepts.UPLOAD_BLOCKED_RE.search(text))

    def test_shapes_that_pass_the_edge(self):
        for text in ("`curl`", "`python app.py`", "`python3 -c ", "`bash -c ", "`ls -la`", "`git status`",
                     '```bash\npython -c "x"\n```', 'python -c "import os"', "&& python -c ",
                     "| python3 -m json.tool", "`python3 -m json.tool`", "'\npython3 -c x", "'\nbash x.sh", "'\nls",
                     "\ncurl -s http://x", '"\ncurl -s http://x', "'\n\ncurl -s http://x", "x\ncurl -s http://x",
                     "curl -s http://x\ncurl -s http://y", "-d '{\"a\": 1}'\nreq -X POST http://y",
                     "'\n   curl -i -X DELETE http://x", '```bash\ncurl -s http://x\n```'):
            with self.subTest(text=text):
                self.assertIsNone(concepts.UPLOAD_BLOCKED_RE.search(text))


class MatchingTest(unittest.TestCase):
    catalog = {"items": [
        {"id": "x.a.api", "title": "API 만들기", "en": "Building API", "kind": "topic", "level": 3, "importance": 2,
         "summary": "s", "aliases": ["API"]},
        {"id": "x.a.cache", "title": "캐시", "en": "Cache", "kind": "topic", "level": 3, "importance": 1,
         "summary": "s", "aliases": ["캐시"]},
        {"id": "x.a.ttl", "title": "만료 시간", "en": "TTL", "kind": "term", "level": 3, "importance": 1,
         "summary": "s", "parent": "x.a.cache", "aliases": ["TTL"]},
        {"id": "x.a.deep", "title": "심화 캐시", "en": "Deep Cache", "kind": "topic", "level": 5, "importance": 1,
         "summary": "s", "aliases": ["심화 캐시"]},
    ]}

    def ids(self, text, used=()):
        return [c["id"] for c in concepts.find_candidates(text, self.catalog, 3, used)["candidates"]]

    def test_broad_names_are_not_counted(self):
        catalog = {**self.catalog, "broad_names": ["api", "캐시"]}
        ids = lambda text: [c["id"] for c in concepts.find_candidates(text, catalog, 3, {})["candidates"]]
        self.assertEqual(ids("api 캐시 얘기"), [])
        self.assertEqual(ids("API 만들기를 배운다"), ["x.a.api"])    # 제목이 나오면 찾는다
        self.assertEqual(ids("TTL을 짧게 했다"), ["x.a.cache"])

    def test_english_needs_word_boundary(self):
        self.assertEqual(self.ids("rapid capital"), [])
        self.assertEqual(self.ids("REST api를 만들었다"), ["x.a.api"])

    def test_korean_matches_with_particles(self):
        self.assertEqual(self.ids("캐시를 비웠다"), ["x.a.cache"])

    def test_term_counts_for_its_topic(self):
        self.assertEqual(self.ids("TTL을 짧게"), ["x.a.cache"])

    def test_importance_comes_before_hits(self):
        self.assertEqual(self.ids("api api api 캐시"), ["x.a.cache", "x.a.api"])

    def test_used_topics_and_their_terms_are_skipped(self):
        self.assertEqual(self.ids("TTL 캐시 api", used={"x.a.cache": {}}), ["x.a.api"])

    def test_other_levels_are_counted(self):
        out = concepts.find_candidates("심화 캐시", self.catalog, 3, {})
        self.assertEqual(out["other_levels"], {"5": 1})


class RealCatalogMatchingTest(unittest.TestCase):
    """실제 대화에서 나온 오탐을 고정한다."""

    def ids(self, text, level):
        catalog = concepts.load_catalog()
        return [c["id"] for c in concepts.find_candidates(text, catalog, level, {})["candidates"]]

    def test_homonyms_do_not_make_candidates(self):
        texts = {
            3: "이 세션을 다시 열었어요. session id는 없습니다. 스크립트를 실행하고 인코딩해서 보내요. 태그를 붙이고 v1.5를 썼어요.",
            4: "git commit 하고 origin/main에 올렸어요. 포크(fork)도 했고 rollback도 했어요.",
            2: "JWT 말고 토큰이라고만 말했어요. 테스트 하실 분이 있어요. 체크리스트와 리포트를 봤어요.",
        }
        unwanted = {
            3: {"be.auth.session-cookie", "be.python.cli-pathlib", "be.python.unicode", "be.rest.openapi-docs", "be.rest.versioning"},
            4: {"be.arch.transaction-boundary", "be.http.cors", "be.arch.reusable-starter"},
            2: {"llm.basics.token-context", "be.test.pytest-first"},
        }
        for level, text in texts.items():
            with self.subTest(level=level):
                self.assertFalse(unwanted[level] & set(self.ids(text, level)), self.ids(text, level))

    def test_real_discussions_are_still_found(self):
        cases = [
            ("세션 쿠키로 로그인을 만들었어요. 세션 방식과 JWT를 비교합니다.", 3, "be.auth.session-cookie"),
            ("JWT 로그인을 구현했어요.", 3, "be.auth.jwt-flow"),
            ("인증과 인가의 차이를 배웠어요.", 3, "be.auth.authn-authz"),
            ("입력 검증에서 422가 났어요.", 3, "be.fastapi.validation"),
            ("문자 인코딩 때문에 한글 깨짐이 생겼어요.", 3, "be.python.unicode"),
            ("입력 토큰과 컨텍스트 창을 봤어요.", 2, "llm.basics.token-context"),
            ("트랜잭션을 어디서 묶을까요?", 4, "be.arch.transaction-boundary"),
            ("CORS 오류가 났어요.", 4, "be.http.cors"),
            ("pytest로 테스트 코드를 썼어요.", 2, "be.test.pytest-first"),
        ]
        for text, level, wanted in cases:
            with self.subTest(wanted=wanted):
                self.assertIn(wanted, self.ids(text, level))


class PackagingTest(unittest.TestCase):
    """원격 설치는 스킬 폴더만 가져가는 경우가 있다."""

    def test_skill_folder_alone_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "study-notes"
            shutil.copytree(SKILL_DIR, copy, ignore=shutil.ignore_patterns("__pycache__"))
            notes = Path(tmp) / "notes"
            env = {**os.environ, "STUDY_NOTES_ROOT": str(notes)}
            script = str(copy / "scripts" / "study_notes.py")
            shown = subprocess.run([sys.executable, "-I", script, "concept", "be.auth.jwt-flow"],
                                   capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertEqual(json.loads(shown.stdout)["concepts"][0]["id"], "be.auth.jwt-flow")
            saved = subprocess.run([sys.executable, "-I", script, "level", "3"],
                                   capture_output=True, text=True, encoding="utf-8", env=env, cwd=tmp)
            self.assertEqual(saved.returncode, 0, saved.stderr)
            self.assertTrue((notes / "settings.json").exists())

    def test_bundled_catalog_matches_source(self):
        bundled = json.loads((SKILL_DIR / "catalog.json").read_text(encoding="utf-8"))
        source = json.loads((ROOT / "catalog" / "dist" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(bundled, source)

    def test_plugin_version_is_documented(self):
        version = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"**v{version}**", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_template_sections_match_the_check(self):
        text = (SKILL_DIR / "templates" / "concept-note.md").read_text(encoding="utf-8")
        found = [line[4:].strip() for line in text.splitlines() if line.startswith("### ")]
        self.assertEqual([name for name in found if name != concepts.NOTE_OPTIONAL_LAST], list(concepts.NOTE_SECTIONS))



class QueueTest(unittest.TestCase):
    """u 옵션: 목록 만들기 → 주제별 작성 → 묶어 등록. 토큰이 끊겨도 이어진다."""

    session = "cccccccc-2222-3333-4444-555555555555"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "notes"
        self.cwd = base / "demo"
        self.cwd.mkdir()
        projects = base / "projects"
        self.pdir = projects / sn.encode_cwd(sn.normalize_cwd(str(self.cwd)))
        self.pdir.mkdir(parents=True)
        self.say("u1", "JWT 로그인을 구현하고 세션 쿠키와 비교했어요. HTTP 헤더와 입력 검증도 다뤘어요.")
        self._projects = sn.PROJECTS_DIR
        sn.PROJECTS_DIR = projects
        self.catalog = concepts.load_catalog()
        self.by_id = {item["id"]: item for item in self.catalog["items"]}
        self.level3 = [i for i in self.catalog["items"] if i["kind"] == "topic" and i["level"] == 3]

    def tearDown(self):
        sn.PROJECTS_DIR = self._projects
        self._tmp.cleanup()

    def say(self, uuid: str, text: str) -> None:
        with (self.pdir / f"{self.session}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"type": "user", "uuid": uuid, "timestamp": f"2026-11-04T00:00:{len(uuid):02d}Z",
                                 "message": {"content": text}}, ensure_ascii=False) + "\n")

    def extract(self, *extra: str) -> dict:
        return run("extract", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                   "--notes-root", str(self.root), *extra)

    def add(self, *ids: str) -> dict:
        return run("queue-add", "--session", self.session, "--ids", *ids, "--notes-root", str(self.root))

    def next(self, *extra: str) -> dict:
        return run("queue-next", "--notes-root", str(self.root), *extra)

    def bundle(self) -> dict:
        return run("queue-bundle", "--notes-root", str(self.root))

    def write(self, topic: dict, level_item: dict | None = None) -> None:
        item = level_item or self.by_id[topic["id"]]
        note = concept_note([item], item["level"])
        Path(topic["draft_file"]).write_text(note[note.index("## 1. "):], encoding="utf-8")
        run("queue-done", "--id", item["id"], "--notes-root", str(self.root))

    def fill(self, count: int) -> list[str]:
        self.extract("--level", "3", "--all")
        ids = [i["id"] for i in self.level3[:count]]
        self.add(*ids)
        return ids

    def test_all_returns_every_candidate(self):
        text = " ".join(i["title"] for i in self.level3)
        self.say("u2", text)
        limited = self.extract("--level", "3")
        everything = self.extract("--all")
        self.assertEqual(len(limited["candidates"]), concepts.CANDIDATE_LIMIT)
        self.assertEqual(len(everything["candidates"]), everything["candidate_total"])
        self.assertGreater(everything["candidate_total"], concepts.CANDIDATE_LIMIT)

    def test_all_candidates_keep_only_fields_for_choosing(self):
        candidate = self.extract("--level", "3", "--all")["candidates"][0]
        self.assertEqual(set(candidate), {"id", "title", "importance", "hits", "matched"})

    def test_queue_next_lists_level_info_once(self):
        ids = self.fill(3)
        out = self.next()
        self.assertEqual([t["level"] for t in out["topics"]], [3, 3, 3])
        self.assertTrue(all("level_style" not in t for t in out["topics"]))
        self.assertEqual(list(out["levels"]), ["3"])
        self.assertEqual(out["levels"]["3"]["level_label"], "3단계 기초")
        self.assertEqual(sorted(t["id"] for t in out["topics"]), sorted(ids))

    def test_guide_prints_rules_and_template_without_procedure(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.assertEqual(sn.main(["guide"]), 0)
        text = buf.getvalue()
        for marker in ("대화의 정리가 아니라 교과서", "1단계 왕초보", "## 작성 규칙", "### 학습 목표", "### 공식 문서"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        for marker in ("queue-bundle", "## 절차", "title: AX"):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, text)

    def test_queue_add_skips_duplicates_and_used(self):
        self.extract("--level", "3", "--all")
        first = self.add("be.auth.jwt-flow", "be.fastapi.validation", "be.auth.jwt-flow")
        self.assertEqual(first["added"], ["be.auth.jwt-flow", "be.fastapi.validation"])
        concepts.mark_used(self.root, ["be.rest.status-choice"], "x.md", "2026-11-04")
        self.say("u2", "더 이야기했어요")
        self.extract("--all")
        second = self.add("be.auth.jwt-flow", "be.rest.status-choice", "be.auth.session-cookie")
        self.assertEqual(second["added"], ["be.auth.session-cookie"])
        self.assertEqual(second["skipped"], ["be.auth.jwt-flow", "be.rest.status-choice"])
        self.assertEqual(second["queue"]["total"], 3)

    def test_queue_add_rejects_what_is_not_a_topic_of_this_level(self):
        self.extract("--level", "3", "--all")
        term = next(i for i in self.catalog["items"] if i["kind"] == "term" and i["level"] == 3)
        for bad, message in (("be.없는.항목", "사전에 없는"), (term["id"], "용어는"), ("be.http.cors", "4단계")):
            with self.subTest(bad=bad), self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
                sn.main(["queue-add", "--session", self.session, "--ids", bad, "--notes-root", str(self.root)])
            self.assertIn(message, str(caught.exception))

    def test_queued_topics_are_not_candidates_again(self):
        self.extract("--level", "3", "--all")
        self.add("be.auth.jwt-flow")
        self.say("u2", "JWT 로그인을 또 이야기했어요")
        ids = [c["id"] for c in self.extract("--all")["candidates"]]
        self.assertNotIn("be.auth.jwt-flow", ids)

    def test_next_gives_at_most_thirty_in_importance_order(self):
        self.fill(45)
        out = self.next()
        self.assertEqual(len(out["topics"]), sn.MAX_RUN_TOPICS)
        self.assertEqual(out["queue"]["pending"], 45)
        stars = [len(t["importance"]) for t in out["topics"]]
        self.assertEqual(stars, sorted(stars, reverse=True))
        self.assertEqual(len(self.next("--limit", "99")["topics"]), sn.MAX_RUN_TOPICS)
        self.assertEqual(len(self.next("--limit", "2")["topics"]), 2)

    def test_done_rejects_bad_topic_and_keeps_it_pending(self):
        ids = self.fill(1)
        topic = self.next()["topics"][0]
        Path(topic["draft_file"]).write_text("## 1. 제목만 있는 조각\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sn.main(["queue-done", "--id", ids[0], "--notes-root", str(self.root)])
        self.assertIn("통과하지 못했습니다", str(caught.exception))
        self.assertEqual(self.next()["queue"]["pending"], 1)

    def test_done_rejects_wrong_concept_and_frontmatter(self):
        self.fill(2)
        first, second = self.next()["topics"]
        other = concept_note([self.by_id[second["id"]]], 3)
        Path(first["draft_file"]).write_text(other[other.index("## 1. "):], encoding="utf-8")
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sn.main(["queue-done", "--id", first["id"], "--notes-root", str(self.root)])
        self.assertIn(first["id"], str(caught.exception))
        Path(first["draft_file"]).write_text(concept_note([self.by_id[first["id"]]], 3), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(io.StringIO()):
            sn.main(["queue-done", "--id", first["id"], "--notes-root", str(self.root)])
        self.assertIn("frontmatter", str(caught.exception))

    def test_interrupted_run_loses_only_unfinished_topics(self):
        self.fill(5)
        topics = self.next()["topics"]
        for topic in topics[:2]:
            self.write(topic)
        Path(topics[2]["draft_file"]).write_text("쓰다 끊긴 글", encoding="utf-8")   # 토큰이 여기서 끊겼다
        after = self.next()
        self.assertEqual(after["queue"], {"total": 5, "done": 0, "written": 2, "pending": 3})
        self.assertEqual([t["id"] for t in after["topics"]], [t["id"] for t in topics[2:]])
        for topic in after["topics"]:
            self.write(topic)
        out = self.bundle()
        self.assertEqual(len(out["notes"][0]["topics"]), 5)
        self.assertEqual(out["queue"], {"total": 5, "done": 5, "written": 0, "pending": 0})

    def test_bundle_splits_every_twenty_and_is_registered(self):
        ids = self.fill(30)
        for topic in self.next()["topics"]:
            self.write(topic)
        out = self.bundle()
        self.assertEqual([len(n["topics"]) for n in out["notes"]], [20, 10])
        self.assertTrue(all(n["level"] == "3단계 기초" for n in out["notes"]))
        used = json.loads((self.root / "concepts_used.json").read_text(encoding="utf-8"))
        self.assertEqual(set(ids), set(used))
        index = (self.root / "index.md").read_text(encoding="utf-8")
        self.assertEqual(sum(1 for line in index.splitlines() if "| 3단계 기초 |" in line), 30)
        first = Path(out["notes"][0]["file"]).read_text(encoding="utf-8")
        self.assertEqual(concepts.frontmatter(first)["topics"], "20")
        self.assertIn("## 20. ", first)
        self.assertEqual(concepts.lint_concept_note(first, self.catalog, {}, sn.TOPICS_PER_FILE), [])
        self.assertEqual(list((self.root / sn.PARTS_DIR).glob("*.md")), [])
        self.assertNotEqual(out["notes"][0]["file"], out["notes"][1]["file"])

    def test_bundle_keeps_levels_in_separate_files(self):
        self.fill(1)
        self.say("u2", "1단계 이야기")
        self.extract("--level", "1", "--all")
        one = next(i for i in self.catalog["items"] if i["kind"] == "topic" and i["level"] == 1)
        self.add(one["id"])
        for topic in self.next()["topics"]:
            self.write(topic)
        self.assertEqual(sorted(n["level"] for n in self.bundle()["notes"]), ["1단계 왕초보", "3단계 기초"])

    def test_checkpoint_moves_only_when_a_note_is_made(self):
        self.fill(1)
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        self.assertIsNone(state.get("last_uuid"))     # 목록만 만들었다
        self.assertNotIn("_pending", state)
        topic = self.next()["topics"][0]
        self.write(topic)
        self.say("u2", "목록을 만든 뒤에 나눈 이야기")
        self.bundle()
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        self.assertEqual((state["last_uuid"], state["run_count"]), ("u1", 1))
        self.assertEqual(self.extract()["new_messages"], 1)   # 뒤의 이야기는 다음에 살핀다

    def test_bundle_with_nothing_ready_changes_nothing(self):
        self.fill(1)
        out = self.bundle()
        self.assertEqual(out["notes"], [])
        state = json.loads(sn.state_path(self.root, self.session).read_text(encoding="utf-8"))
        self.assertIsNone(state.get("last_uuid"))

    def test_next_works_without_session_after_tokens_run_out(self):
        self.fill(2)
        sn.PROJECTS_DIR = Path(self._tmp.name) / "없는 폴더"
        self.assertEqual(len(self.next()["topics"]), 2)

    def test_thirty_topics_fit_the_app_limit(self):
        """앱은 파일 하나에 50만 자까지 받는다. 실제 노트의 주제가 약 1만 자다."""
        self.assertLess(sn.TOPICS_PER_FILE * 11_000, 500_000)
        self.assertLessEqual(sn.TOPICS_PER_FILE, sn.MAX_RUN_TOPICS)

    def test_status_shows_queue(self):
        self.fill(3)
        status = run("status", "--agent", "claude", "--cwd", str(self.cwd), "--session", self.session,
                     "--notes-root", str(self.root))
        self.assertEqual(status["queue"], {"total": 3, "done": 0, "written": 0, "pending": 3})
        self.assertIsNone(status["in_progress"])

    def test_plain_run_still_excludes_queue_and_is_limited(self):
        self.fill(1)
        self.say("u2", "JWT 로그인을 또 했어요")
        out = self.extract()
        self.assertLessEqual(len(out["candidates"]), concepts.CANDIDATE_LIMIT)
        self.assertNotIn(self.level3[0]["id"], [c["id"] for c in out["candidates"]])


class SpokenTextTest(unittest.TestCase):
    def test_urls_are_not_matched_as_concepts(self):
        recs = [{"message": {"content": "문서는 https://example.com/a 에 있고 HTTPS 인증서를 물어봤어요"}}]
        text = sn.spoken_text(recs)
        self.assertNotIn("https://", text)
        self.assertIn("HTTPS 인증서", text)


class SkillDocsQueueTest(unittest.TestCase):
    def test_agents_stop_servers_by_pid_and_main_cleans_up(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('SERVER=$!', text)
        self.assertIn('kill "$SERVER"', text)
        self.assertIn('grep -qF "<TMP>/study-notes/"', text)

    def test_agents_and_main_do_not_give_up(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("guide 의 출력 전부", "Bash 전체가 막힌 것이 아닙니다", "남은 주제를 계속 띄운다",
                       "사용 한도나 비용을 짐작해", "`head`로 자르지 않는다", "분량 제한을 덧붙이지 않는다"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        self.assertNotIn('"설명 수준", "작성 규칙" 절과', text)

    def test_few_topics_still_use_agents(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("주제가 한두 개뿐이어도 직접 쓰지 말고 에이전트로 쓴다", text)

    def test_every_topic_in_bundle_has_a_link(self):
        bundle = json.loads((SKILL_DIR / "catalog.json").read_text(encoding="utf-8"))
        missing = [i["id"] for i in bundle["items"] if i["kind"] == "topic" and not i.get("refs")]
        self.assertEqual(missing, [])

    def test_skill_describes_options(self):
        text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        for marker in ("/study-notes u", "/study-notes c", "queue-add", "queue-next", "queue-done", "queue-bundle", "--all"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)

    def test_readme_describes_options(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for marker in ("/study-notes u", "/study-notes c", "최대 30개"):
            with self.subTest(marker=marker):
                self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
