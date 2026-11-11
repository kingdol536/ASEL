"""선언형 공정 흐름 (#34): 갈라짐·합침 DAG 를 설정 파일에서 조립."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asel.core.model import TaskStatus
from asel.evaluation.evaluator import order_metrics
from asel.io.scenario import Scenario
from asel.runner import run_scenario

C = {"type": "constant"}


def flow_scenario(steps, **over) -> dict:
    d = {
        "schema_version": "0.4",
        "scenario_id": "flow-test",
        "domain": "job_flow",
        "seed": 1,
        "sim_time_limit": 600,
        "entities": [
            {"id": "a", "type": "cell", "capabilities": ["x"], "capacity": 1},
            {"id": "b", "type": "cell", "capabilities": ["y"], "capacity": 1},
            {"id": "c", "type": "cell", "capabilities": ["z"], "capacity": 1},
        ],
        "workload": {"arrival_process": {"type": "poisson", "rate_per_min": 1.0}, "flow": {"steps": steps}},
    }
    d.update(over)
    return d


SPLIT_JOIN = [
    {"id": "left", "capability": "x", "service_time": {**C, "value_s": 10}},
    {"id": "right", "capability": "y", "service_time": {**C, "value_s": 30}},
    {"id": "join", "capability": "z", "service_time": {**C, "value_s": 5}, "after": ["left", "right"]},
]


def test_split_join_runs_and_join_waits_for_both():
    sc = Scenario.model_validate(flow_scenario(SPLIT_JOIN))
    res = run_scenario(sc, seed=2)
    st = res.world.state
    assert res.summary()["invariant_violations"] == 0 and res.summary()["actions_rejected"] == 0
    joins = [t for t in st.tasks.values() if t.id.endswith("/join") and t.started_at is not None]
    assert joins
    for j in joins:
        inst = j.id.split("/")[0]
        left, right = st.tasks[f"{inst}/left"], st.tasks[f"{inst}/right"]
        assert j.predecessors == (left.id, right.id)
        assert j.started_at >= max(left.completed_at, right.completed_at)
    assert all(t.id.startswith("job-") for t in st.tasks.values())


def test_order_completion_needs_all_tasks_including_parallel_branches():
    sc = Scenario.model_validate(flow_scenario(SPLIT_JOIN))
    res = run_scenario(sc, seed=2)
    m = order_metrics(res.events)
    done = {t.tags["order"] for t in res.world.state.tasks.values() if t.status == TaskStatus.COMPLETED and t.id.endswith("/join")}
    assert m["orders_completed"] == len(done)


@pytest.mark.parametrize(
    "steps",
    [
        [{"id": "a", "capability": "x", "service_time": {**C, "value_s": 1}, "after": ["b"]},
         {"id": "b", "capability": "y", "service_time": {**C, "value_s": 1}}],  # 뒤에 있는 단계에 의존
        [{"id": "a", "capability": "x", "service_time": {**C, "value_s": 1}},
         {"id": "a", "capability": "y", "service_time": {**C, "value_s": 1}}],  # 중복 id
        [{"id": "a", "capability": "w", "service_time": {**C, "value_s": 1}}],  # 제공 셀 없음
    ],
)
def test_bad_flows_rejected(steps):
    with pytest.raises(ValidationError):
        Scenario.model_validate(flow_scenario(steps))


def test_flow_requires_schema_04_and_exactly_one_form():
    with pytest.raises(ValidationError):
        Scenario.model_validate(flow_scenario(SPLIT_JOIN, schema_version="0.3"))
    d = flow_scenario(SPLIT_JOIN)
    d["workload"]["job_template"] = [{"capability": "x", "service_time": {**C, "value_s": 1}}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)


def test_legacy_hash_unchanged_by_new_optional_field():
    from asel.io.scenario import load_scenario
    from conftest import SCENARIO_A

    sc = load_scenario(SCENARIO_A)
    assert "flow" not in sc.canonical_dump()["workload"]
    assert sc.config_hash().startswith("0b9292b2")  # EXP-001 run_id 에 기록된 해시


def test_config_hashes_match_recorded_experiment_run_ids():
    """기록된 실험의 run_id 에 들어 있는 설정 해시가 지금 코드로도 같다 (재현성 회귀 방지).
    EXP-001(시나리오 0.1/0.2) 과 EXP-002(0.3) 를 모두 확인한다."""
    import glob

    from asel.io.scenario import load_scenario
    from conftest import ROOT

    expected = {
        "warehouse-small-a": "0b9292b2",
        "exp002-s1p5-c30": "99881302",
        "exp002-s3p0-c300": "937eda01",
    }
    paths = {p.stem: p for p in list((ROOT / "scenarios").glob("*.yaml")) + list((ROOT / "scenarios" / "exp002").glob("*.yaml"))}
    for sid, h in expected.items():
        assert load_scenario(paths[sid]).config_hash().startswith(h), sid
