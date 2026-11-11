"""도메인 어댑터 레지스트리 (#33)."""

from __future__ import annotations

import pytest

from asel.domains import get_adapter, registered_domains
from asel.io.scenario import Scenario, load_scenario
from asel.runner import run_scenario
from conftest import SCENARIO_A


def test_warehouse_registered():
    assert "warehouse_like" in registered_domains()
    assert get_adapter("warehouse_like").name == "warehouse_like"


def test_unknown_domain_fails_at_run_time_with_clear_message():
    d = load_scenario(SCENARIO_A).model_dump(mode="json")
    d["domain"] = "no_such_domain"
    sc = Scenario.model_validate(d)  # 스키마는 이름 형식만 본다
    with pytest.raises(ValueError, match="unknown domain 'no_such_domain'"):
        run_scenario(sc, seed=0)


def test_runner_does_not_import_a_specific_domain():
    import pathlib

    import asel.runner as r

    text = pathlib.Path(r.__file__).read_text(encoding="utf-8")
    assert "warehouse" not in text.lower()
