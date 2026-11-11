"""공통 언어 v0 (#31): 코드와 문서가 어긋나면 실패한다."""

from __future__ import annotations

import dataclasses

from asel import vocabulary as v
from asel.core import model


def test_every_code_concept_is_documented_and_vice_versa():
    assert set(v.code_concepts()) == set(v.CONCEPTS)


def test_every_action_and_event_is_documented():
    assert sorted(v.ACTIONS) == v.code_actions()
    assert sorted(v.EVENTS) == v.code_events()


def test_link_source_fields_exist_in_code():
    known = set(v.CONCEPTS) | set(v.VALUE_CONCEPTS)
    for src, fld, dst, _ in v.LINKS:
        fields = {f.name for f in dataclasses.fields(getattr(model, src))}
        assert fld in fields, (src, fld)
        assert dst in known, dst


def test_generated_doc_is_up_to_date():
    assert v.DOC_PATH.read_text(encoding="utf-8") == v.render_markdown(), (
        "docs/11-COMMON-LANGUAGE.md 가 코드와 다르다: uv run python -m asel.vocabulary 로 다시 만든다"
    )


def test_core_has_no_industry_words():
    """코어에는 산업 단어가 없다 (pick/pack/order/warehouse 는 시나리오·어댑터에만)."""
    import pathlib

    core = pathlib.Path(model.__file__).parent
    for p in core.glob("*.py"):
        text = p.read_text(encoding="utf-8").lower()
        for w in ("warehouse", "pick", "pack", "order"):
            # 주석의 예시 문구는 허용하지 않는다: 코어는 산업 중립
            assert f'"{w}' not in text and f"'{w}" not in text, (p.name, w)
