"""개념사전 도구 단위 테스트. 표준 라이브러리 unittest만 쓴다.

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
CATALOG = ROOT / "catalog"

_spec = importlib.util.spec_from_file_location("catalog_tool", CATALOG / "tools" / "catalog.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


def topic(item_id: str, level: int = 2, importance: int = 1, **extra) -> dict:
    return {
        "id": item_id, "title": "HTTP 상태 코드", "en": "HTTP Status Codes", "kind": "topic",
        "level": level, "importance": importance, "group": "HTTP",
        "summary": "서버가 요청 결과를 세 자리 숫자로 알려 주는 약속이다.",
        "objectives": ["상태 코드를 구분할 수 있다", "오류의 원인을 가려낼 수 있다"],
        "aliases": [item_id, "상태 코드"], "refs": ["https://example.com/doc"], **extra,
    }


def term(item_id: str, level: int = 2, importance: int = 1, **extra) -> dict:
    return {
        "id": item_id, "title": "상태 코드", "en": "Status Code", "kind": "term",
        "level": level, "importance": importance, "group": "HTTP",
        "summary": "요청 결과를 알려 주는 세 자리 숫자다.", "aliases": [item_id], "refs": ["https://example.com/doc"], **extra,
    }


class CatalogTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "items").mkdir()
        (self.root / "VERSION").write_text("0.0.1\n", encoding="utf-8")
        for name in ("domains.json", "levels.json"):
            shutil.copy(CATALOG / name, self.root / name)

    def write(self, *items: dict, domain: str = "be") -> None:
        (self.root / "items" / f"{domain}.json").write_text(json.dumps(list(items), ensure_ascii=False), encoding="utf-8")

    def errors(self, *items: dict) -> list[str]:
        self.write(*items)
        return tool.check_catalog(tool.load_catalog(self.root))[0]

    def assert_rejected(self, expected: str, *items: dict) -> None:
        errors = self.errors(*items)
        self.assertTrue(any(expected in error for error in errors), errors)


class RealCatalogTest(unittest.TestCase):
    def test_real_catalog_has_no_errors(self) -> None:
        errors, _ = tool.check_catalog(tool.load_catalog(CATALOG))
        self.assertEqual(errors, [])

    def test_item_files_are_formatted(self) -> None:
        catalog = tool.load_catalog(CATALOG)
        for domain in catalog["domains"]:
            path = CATALOG / "items" / f"{domain['prefix']}.json"
            if path.exists():
                group = [tool.clean_item(item) for item in catalog["items"] if item["_domain"] == domain["prefix"]]
                self.assertEqual(path.read_text(encoding="utf-8"), json.dumps(group, ensure_ascii=False, indent=2) + "\n", path.name)

    def test_dist_is_up_to_date(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.cmd_build(CATALOG, check_only=True), 0)


class ItemRulesTest(CatalogTestCase):
    def test_valid_items_pass(self) -> None:
        self.assertEqual(self.errors(topic("be.http.status"), term("be.http.code", parent="be.http.status")), [])

    def test_id_must_be_unique(self) -> None:
        self.assert_rejected("id가 겹친다", topic("be.http.status"), topic("be.http.status"))

    def test_id_prefix_must_match_file(self) -> None:
        self.assert_rejected("접두사", topic("fe.http.status"))

    def test_id_format(self) -> None:
        self.assert_rejected("id 형식", topic("be.status"))

    def test_unknown_field_is_rejected(self) -> None:
        self.assert_rejected("알 수 없는 필드", topic("be.http.status", priority=1))

    def test_level_and_importance_range(self) -> None:
        self.assert_rejected("level", topic("be.http.status", level=6))
        self.assert_rejected("importance", topic("be.http.status", importance=4))

    def test_title_must_be_a_name_not_a_sentence(self) -> None:
        self.assert_rejected("제목", topic("be.http.status", title="서버가 숫자를 알려 준다"))
        self.assertEqual(self.errors(topic("be.http.status", title="람다")), [])
        self.assert_rejected("제목", topic("be.http.status", title="로그인은 왜 필요한가"))

    def test_objectives_rules(self) -> None:
        self.assert_rejected("~할 수 있다", topic("be.http.status", objectives=["상태 코드 이해", "오류를 가려낼 수 있다"]))
        self.assert_rejected("학습 목표", topic("be.http.status", objectives=["오류를 가려낼 수 있다"]))
        self.assert_rejected("용어에는", term("be.http.code", objectives=["구분할 수 있다", "말할 수 있다"]))

    def test_term_without_parent_needs_refs(self) -> None:
        item = term("be.http.code")
        del item["refs"]
        self.assert_rejected("부모 주제가 없는 용어", item)
        self.assertEqual(self.errors(topic("be.http.status"), {**item, "parent": "be.http.status"}), [])

    def test_every_topic_needs_refs(self) -> None:
        item = topic("be.http.status")
        del item["refs"]
        self.assert_rejected("refs", item)
        self.assertTrue(any("refs" in e for e in self.errors({**item, "level": 1})))

    def test_project_bound_expression_is_rejected(self) -> None:
        self.assert_rejected("묶인 표현", topic("be.http.status", summary="이 프로젝트에서 상태 코드를 쓰는 방법이다."))

    def test_volatile_needs_checked_date(self) -> None:
        self.assert_rejected("checked_at", topic("be.http.status", volatile=True))
        self.assertEqual(self.errors(topic("be.http.status", volatile=True, checked_at="2026-11-03")), [])


class RelationRulesTest(CatalogTestCase):
    def test_prerequisite_must_exist(self) -> None:
        self.assert_rejected("없는 항목", topic("be.http.status", prerequisites=["be.http.none"]))

    def test_prerequisite_must_not_be_higher_level(self) -> None:
        self.assert_rejected(
            "단계가 더 높다",
            topic("be.http.status", level=2, prerequisites=["be.http.deep"]),
            topic("be.http.deep", level=3),
        )

    def test_prerequisite_cycle_is_rejected(self) -> None:
        self.assert_rejected(
            "순환",
            topic("be.http.a", prerequisites=["be.http.b"]),
            topic("be.http.b", prerequisites=["be.http.a"]),
        )

    def test_parent_must_be_topic(self) -> None:
        self.assert_rejected("parent", term("be.http.a"), term("be.http.b", parent="be.http.a"))

    def test_file_order_is_level_then_topic_then_importance(self) -> None:
        self.assert_rejected("순서", topic("be.http.a", importance=2), topic("be.http.b", importance=1))
        self.assert_rejected("순서", term("be.http.a"), topic("be.http.b"))
        self.assert_rejected("순서", topic("be.http.a", level=3), topic("be.http.b", level=2))


class WarningsTest(CatalogTestCase):
    def test_widely_shared_alias_warns(self) -> None:
        items = [topic(f"be.http.a{i}", aliases=["API"]) for i in range(4)]
        self.write(*items)
        errors, warnings = tool.check_catalog(tool.load_catalog(self.root))
        self.assertEqual(errors, [])
        self.assertTrue(any("별칭" in warning for warning in warnings), warnings)

    def test_optional_item_with_many_dependents_warns(self) -> None:
        base = topic("be.http.base", level=1, importance=3)
        others = [topic(f"be.http.a{i}", prerequisites=["be.http.base"]) for i in range(3)]
        self.write(base, *others)
        _, warnings = tool.check_catalog(tool.load_catalog(self.root))
        self.assertTrue(any("중요도" in warning for warning in warnings), warnings)


    def test_required_item_with_lesser_prerequisite_warns(self) -> None:
        self.write(topic("be.http.base", level=1, importance=2), topic("be.http.a", prerequisites=["be.http.base"]))
        _, warnings = tool.check_catalog(tool.load_catalog(self.root))
        self.assertTrue(any("선수 개념" in warning for warning in warnings), warnings)


class StudyOrderTest(CatalogTestCase):
    def test_prerequisite_comes_before_more_important_item(self) -> None:
        self.write(
            topic("be.http.a", importance=1, prerequisites=["be.http.b"]),
            topic("be.http.c", importance=1),
            topic("be.http.b", importance=2),
        )
        catalog = tool.load_catalog(self.root)
        order = {domain["prefix"]: index for index, domain in enumerate(catalog["domains"])}
        self.assertEqual([item["id"] for item in tool.study_order(catalog["items"], order)], ["be.http.c", "be.http.b", "be.http.a"])

    def test_prerequisite_of_important_item_is_pulled_forward(self) -> None:
        self.write(
            topic("be.http.a", importance=1, prerequisites=["be.http.base"]),
            topic("be.http.base", importance=2),
            topic("be.http.other", importance=2),
        )
        catalog = tool.load_catalog(self.root)
        order = {domain["prefix"]: index for index, domain in enumerate(catalog["domains"])}
        self.assertEqual([item["id"] for item in tool.study_order(catalog["items"], order)], ["be.http.base", "be.http.a", "be.http.other"])

    def test_same_importance_keeps_file_order(self) -> None:
        self.write(topic("be.http.a"), topic("be.http.b"), topic("be.http.c"))
        catalog = tool.load_catalog(self.root)
        order = {domain["prefix"]: index for index, domain in enumerate(catalog["domains"])}
        self.assertEqual([item["id"] for item in tool.study_order(catalog["items"], order)], ["be.http.a", "be.http.b", "be.http.c"])


def good_note(title: str = "HTTP 상태 코드 (HTTP Status Codes)", item_id: str = "be.http.status") -> str:
    body = "설명 문장입니다. " * 300
    return f"""---
title: 노트
project: AX 개념노트
---
# 노트

> 설명

## 목차
| # | 주제 |
|---|---|
| 1 | 주제 |

---

## 1. {title}
> 한 줄 요약: 요약.

`유형` 개념 | `태그` http | `난이도` ★★ | `개념` {item_id} | `단계` 2단계 입문 | `중요도` ★★★

### 학습 목표
- 상태 코드를 구분할 수 있다
- 오류의 원인을 가려낼 수 있다

### 먼저 알아야 할 것
{body}

### 왜 필요한가
내용

### 핵심 개념
내용

### 예제로 이해하기
```text
## 코드 블록 안의 제목은 주제가 아니다
frontend/app/page.tsx
```

### 비슷한 개념과 차이
내용

### 흔한 실수
내용

### 직접 해 보기
내용

### 확인 문제
1. 질문?
2. 질문?

### 정답
1. 답.
2. 답.

### 공식 문서
- [문서](https://example.com)

### 만난 곳
2026-11-03 만남.
"""


class NoteLintTest(CatalogTestCase):
    def lint(self, text: str) -> list[str]:
        self.write(topic("be.http.status"))
        return tool.lint_note(text, tool.load_catalog(self.root))

    def test_good_note_passes_and_fence_is_ignored(self) -> None:
        self.assertEqual(self.lint(good_note()), [])

    def test_unknown_concept_id_is_rejected(self) -> None:
        self.assertTrue(any("사전에 없는" in e for e in self.lint(good_note(item_id="be.http.none"))))

    def test_title_must_come_from_catalog(self) -> None:
        self.assertTrue(any("제목" in e for e in self.lint(good_note(title="링크 하나 바꾸기와 세미콜론"))))

    def test_project_bound_expressions_are_rejected(self) -> None:
        for text in ("이번 대화에서 만난 오류다.", "frontend/app/page.tsx를 고쳤다.", "이 프로젝트에서는 이렇게 썼다."):
            errors = self.lint(good_note().replace("### 왜 필요한가\n내용", f"### 왜 필요한가\n{text}"))
            self.assertTrue(any("묶인 표현" in e for e in errors), text)

    def test_paths_inside_links_are_allowed(self) -> None:
        note = good_note().replace("- [문서](https://example.com)", "- [문서](https://example.com/docs/Web/HTTP)")
        self.assertEqual(self.lint(note), [])

    def test_missing_or_reordered_section_is_rejected(self) -> None:
        self.assertTrue(any("소제목" in e for e in self.lint(good_note().replace("### 흔한 실수\n내용\n\n", ""))))

    def test_objective_must_appear(self) -> None:
        self.assertTrue(any("학습 목표" in e for e in self.lint(good_note().replace("- 오류의 원인을 가려낼 수 있다\n", ""))))

    def test_answers_must_match_questions(self) -> None:
        self.assertTrue(any("정답의 수" in e for e in self.lint(good_note().replace("2. 답.\n", ""))))

    def test_official_docs_link_required(self) -> None:
        self.assertTrue(any("공식 문서" in e for e in self.lint(good_note().replace("- [문서](https://example.com)", "- 문서"))))

    def test_short_note_is_rejected(self) -> None:
        self.assertTrue(any("너무 짧다" in e for e in self.lint(good_note().replace("설명 문장입니다. ", "짧다. ", 299))))


class OutputsTest(CatalogTestCase):
    def test_format_uses_fixed_key_order_and_drops_empty_fields(self) -> None:
        item = topic("be.http.status", related=[], parent=None)
        self.write(dict(reversed(list(item.items()))))
        tool.format_items(self.root, tool.load_catalog(self.root))
        saved = json.loads((self.root / "items" / "be.json").read_text(encoding="utf-8"))[0]
        self.assertEqual(list(saved)[:3], ["id", "title", "en"])
        self.assertNotIn("related", saved)
        self.assertNotIn("parent", saved)

    def test_build_writes_each_level_and_catalog_json(self) -> None:
        self.write(topic("be.http.status", level=2), term("be.http.code", level=2, parent="be.http.status"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.cmd_build(self.root, check_only=False), 0)
            self.assertEqual(tool.cmd_build(self.root, check_only=True), 0)
        level_two = (self.root / "dist" / "2단계_입문.md").read_text(encoding="utf-8")
        self.assertIn("주제 1개 · 용어 1개", level_two)
        self.assertIn("be.http.status", level_two)
        payload = json.loads((self.root / "dist" / "catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], "0.0.1")
        self.assertEqual([item["domain"] for item in payload["items"]], ["be", "be"])

    def test_build_refuses_invalid_catalog(self) -> None:
        self.write(topic("be.http.status", level=9))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tool.cmd_build(self.root, check_only=False), 1)
        self.assertFalse((self.root / "dist").exists())


if __name__ == "__main__":
    unittest.main()
