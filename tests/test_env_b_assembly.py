"""환경 B 조립 라인 (#37): 기존 엔진·정책으로 합류·혼류·셋업(재구성)이 동작한다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asel.core.model import TaskStatus
from asel.io.eventlog import encode_events
from asel.io.scenario import Scenario, load_scenario
from asel.runner import run_scenario
from conftest import ROOT

B = load_scenario(ROOT / "scenarios" / "assembly-line-b.yaml")


@pytest.mark.parametrize("policy", ["fifo", "order-age"])
@pytest.mark.parametrize("structure", [None, "p0", "p1", "p2"])
def test_existing_policies_run_unchanged_on_b(policy, structure):
    res = run_scenario(B, seed=3, policy=policy, structure_policy=structure)
    s = res.summary()
    assert s["actions_rejected"] == 0 and s["invariant_violations"] == 0
    assert s["tasks_by_status"].get("COMPLETED", 0) > 0


def test_join_waits_for_all_branches_and_mix_is_roughly_70_30():
    st = run_scenario(B, seed=5).world.state
    n = {"prodA": 0, "prodB": 0}
    for t in st.tasks.values():
        if t.id.endswith("/assemble") and t.started_at is not None:
            inst = t.id.split("/")[0]
            press, motor = st.tasks[f"{inst}/press"], st.tasks[f"{inst}/motor"]
            assert t.started_at >= max(press.completed_at, motor.completed_at)
        if t.id.endswith("/frame"):
            n[t.tags["flow"]] += 1
            assert t.id.startswith(t.tags["flow"])
    share = n["prodA"] / (n["prodA"] + n["prodB"])
    assert 0.55 < share < 0.85
    # 제품별 프레스 공정이 다르다
    assert {st.tasks[i].capability for i in st.tasks if i.startswith("prodA") and i.endswith("/press")} == {"press-A"}


def test_setup_is_reconfiguration_and_helps_here():
    """제품 전환 셋업 = 프레스 역할 전환. P1 이 공용 프레스를 A 로 돌린다 (개발 시드 범위의 기능 확인, 가설 아님)."""
    res = run_scenario(B, seed=0, structure_policy="p1")
    st = res.world.state
    assert st.entities["press-2"].capabilities == ("press-A",)
    done = [t for t in st.tasks.values() if t.assigned_entity == "press-2" and t.capability == "press-A"
            and t.status == TaskStatus.COMPLETED]
    assert done


def test_b_reproducible():
    a, b = run_scenario(B, seed=7, structure_policy="p2"), run_scenario(B, seed=7, structure_policy="p2")
    assert encode_events(a.events) == encode_events(b.events)


def test_mix_validation():
    d = B.canonical_dump()
    d["workload"]["mix"][1]["flow"]["instance_prefix"] = "prodA"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)
    d = B.canonical_dump()
    d["schema_version"] = "0.3"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)
