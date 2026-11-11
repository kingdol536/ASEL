"""정적 3D 공간 제약 (#40, 결정 0007 안 A): 2D 에서 가능한 재구성이 높이 제약으로 불가능해진다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asel.core.actions import Action, ActionKind
from asel.core.invariants import check_invariants
from asel.core.world import ENV_ACTOR, World, replay
from asel.io.scenario import Scenario, load_scenario
from asel.policies.contract import affordances, project
from asel.runner import run_scenario
from conftest import ROOT

B2 = load_scenario(ROOT / "scenarios" / "assembly-line-b.yaml")
B3 = load_scenario(ROOT / "scenarios" / "assembly-line-b-3d.yaml")
GR = {ENV_ACTOR: {ActionKind.CREATE_TASK, ActionKind.COMPLETE_RECONFIGURATION}, "s": {ActionKind.REQUEST_RECONFIGURATION}}
RC = {"options": [["a"], ["b"]], "changeover_s": 10.0}


def world(ceiling):
    w = World("t", GR)
    w.initialize(
        [{"id": "x", "type": "m", "capabilities": ["a"], "reconfig": RC,
          "space": {"x": 0, "y": 0, "width": 1, "depth": 1, "ceiling_m": ceiling}},
         {"id": "y", "type": "m", "capabilities": ["b"]},
         {"id": "z", "type": "m", "capabilities": ["a"]}],  # 교착 방지 규칙에 걸리지 않도록 a 제공 셀 하나 더
        [], [{"id": "x", "capacity": 1}, {"id": "y", "capacity": 1}, {"id": "z", "capacity": 1}],
        {"a": {"height_m": 2.0}, "b": {"height_m": 4.0}},
    )
    return w


def test_reconfiguration_rejected_when_role_does_not_fit_under_ceiling():
    low, high = world(3.0), world(5.0)
    req = Action("s", ActionKind.REQUEST_RECONFIGURATION, {"entity": "x", "capabilities": ["b"]})
    r = low.submit(req)
    assert not r.accepted and any("insufficient clearance" in m for m in r.reasons)
    assert high.submit(req).accepted
    assert check_invariants(low.state) == check_invariants(high.state) == []
    high.end_run(0)
    assert replay(high.log).snapshot() == high.state.snapshot()


def test_2d_valid_switch_becomes_infeasible_in_3d():
    """같은 정책(P1)·같은 시드: 2D 에서는 press-2 를 press-A 로 돌리지만, 3D 에서는 높이 제약으로 못 돌린다."""
    for seed in (0, 1, 2):
        r2 = run_scenario(B2, seed=seed, structure_policy="p1")
        r3 = run_scenario(B3, seed=seed, structure_policy="p1")
        assert r2.world.state.entities["press-2"].capabilities == ("press-A",)
        assert r3.world.state.entities["press-2"].capabilities == ("press-B",)
        assert r3.summary()["actions_rejected"] == 0  # 정책 후보에서 미리 빠져 거절도 없다
        assert r3.summary()["invariant_violations"] == 0


def test_observation_and_candidates_reflect_clearance():
    st = run_scenario(B3.model_copy(update={"sim_time_limit": 60.0}), seed=0).world.state
    obs = project(st, "s")
    p2 = next(c for c in obs.cells if c["id"] == "press-2")
    assert p2["ceiling_m"] == 3.2 and p2["blocked_roles"] == ["press-A"]
    cands = affordances(obs, (ActionKind.REQUEST_RECONFIGURATION,))[0].candidates
    assert not any(c["entity"] == "press-2" and c["capabilities"] == ["press-A"] for c in cands)
    # 공간 정보가 없는 세계(2D)의 관측에는 공간 키가 없다
    obs2 = project(run_scenario(B2.model_copy(update={"sim_time_limit": 60.0}), seed=0).world.state, "s")
    assert all("ceiling_m" not in c for c in obs2.cells)


def _with(**changes):
    d = B3.canonical_dump()
    for e in d["entities"]:
        if e["id"] in changes:
            e["space"].update(changes[e["id"]])
    return d


def test_layout_validation_overlap_and_initial_fit():
    with pytest.raises(ValidationError):
        Scenario.model_validate(_with(**{"press-2": {"x": 6, "y": 0}}))  # press-1 과 바닥이 겹침
    with pytest.raises(ValidationError):
        Scenario.model_validate(_with(**{"press-1": {"ceiling_m": 3.0}}))  # 시작 역할 press-A(3.8m)가 안 들어감
    d = B3.canonical_dump()
    d["schema_version"] = "0.3"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)


def test_2d_scenarios_keep_old_formats():
    sc = load_scenario(ROOT / "scenarios" / "exp002" / "exp002-s2p0-c120.yaml")
    assert "space" not in sc.canonical_dump()["entities"][0]
    assert sc.config_hash().startswith("9a45be1b")
