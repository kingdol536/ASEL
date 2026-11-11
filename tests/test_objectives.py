"""목표 변경 (#38): 목표는 공개 정보, 채점식은 평가기 전용."""

from __future__ import annotations

import json

from asel.core.events import EventType
from asel.evaluation.evaluator import objective_segments
from asel.io.scenario import Scenario, load_scenario
from asel.policies.contract import project
from asel.runner import run_scenario
from conftest import ROOT

B = load_scenario(ROOT / "scenarios" / "assembly-line-b.yaml")


def with_schedule(sc, schedule):
    d = sc.canonical_dump()
    d["objective_schedule"] = schedule
    return Scenario.model_validate(d)


SCHED = [
    {"at_s": 0, "id": "volume", "kind": "throughput"},
    {"at_s": 1200, "id": "rush-B", "kind": "priority", "params": {"flow": "prodB"}},
]


def test_objective_change_is_public_and_observed():
    sc = with_schedule(B, SCHED)
    res = run_scenario(sc, seed=1)
    ev = [e for e in res.events if e.event_type == EventType.OBJECTIVE_CHANGED]
    assert [e.sim_time for e in ev] == [0, 1200] and ev[1].payload["objective"]["kind"] == "priority"
    obs = project(res.world.state, "p")
    assert obs.objective == {"id": "rush-B", "kind": "priority", "params": {"flow": "prodB"}}
    text = json.dumps(obs.to_dict())
    assert "score" not in text and "target_flow_mean" not in text  # 채점식·채점값은 관측에 없다


def test_objective_aware_policy_prioritises_target_flow_after_change():
    sc = with_schedule(B, SCHED)
    fifo = objective_segments(run_scenario(sc, seed=4, policy="fifo").events)
    aware = objective_segments(run_scenario(sc, seed=4, policy="objective-aware").events)
    f, a = fifo[1]["score"]["target_flow_mean_s"], aware[1]["score"]["target_flow_mean_s"]
    assert a < f  # 우선 목표 묶음(prodB)이 더 빨리 끝난다 (기능 확인, 개발 시드)
    assert fifo[0]["score"]["completed_per_hour"] > 0


def test_worlds_without_objectives_keep_old_formats():
    sc = load_scenario(ROOT / "scenarios" / "warehouse-small-a.yaml")
    res = run_scenario(sc, seed=0)
    assert "objective" not in res.world.state.snapshot()
    assert "objective" not in project(res.world.state, "p").to_dict()
    assert "objective_schedule" not in sc.canonical_dump()


def test_schedule_validation():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        with_schedule(B, [{"at_s": 10, "id": "a", "kind": "x"}, {"at_s": 5, "id": "b", "kind": "y"}])
    w = None
    from asel.core.actions import Action, ActionKind
    from asel.core.world import ENV_ACTOR
    from conftest import make_world

    w = make_world()
    for bad in ({"id": "a", "kind": "x"}, {"id": "", "kind": "x", "params": {}}, "nope"):
        assert not w.submit(Action(ENV_ACTOR, ActionKind.SET_OBJECTIVE, {"objective": bad})).accepted
    assert not w.submit(Action("dispatcher.test", ActionKind.SET_OBJECTIVE,
                               {"objective": {"id": "a", "kind": "x", "params": {}}})).accepted
