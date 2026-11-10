"""관측의 재구성 상태·구조 제어 주체 분리 (#21), 구조 정책 P0/P1/P2 (#22)."""

from __future__ import annotations

import pytest

from asel.core.actions import ActionKind
from asel.io.eventlog import encode_events
from asel.io.scenario import load_scenario
from asel.policies.contract import ActionProposal, affordances, project
from asel.policies.structure import CostAwareStructure, ReactiveStructure, pressures
from asel.runner import run_scenario
from conftest import ROOT

DEV = load_scenario(ROOT / "scenarios" / "warehouse-reconfig-dev.yaml")
PLAIN = load_scenario(ROOT / "scenarios" / "warehouse-surge-a.yaml")
M3_CELL_KEYS = {"id", "type", "capabilities", "capacity", "reserved", "out_of_service", "available"}


def test_observation_unchanged_for_worlds_without_reconfiguration():
    """재구성이 없는 세계의 관측은 M3 와 같은 키만 갖는다 (EXP-001 캐시·재생 유지)."""
    st = run_scenario(PLAIN, seed=0).world.state
    obs = project(st, "policy.x")
    assert all(set(c) == M3_CELL_KEYS for c in obs.cells)
    assert "structure_version" not in obs.to_dict()


def test_observation_shows_reconfiguration_state_and_blocks_new_work():
    res = run_scenario(DEV, seed=0, structure_policy="p1")
    # 재생하며 비우는 중·전환 중 시점의 관측을 확인
    from asel.core.world import apply_event
    from asel.core.model import WorldState

    st = WorldState()
    seen = set()
    for ev in res.events:
        apply_event(st, ev)
        if ev.event_type in ("ReconfigurationRequested", "ReconfigurationStarted"):
            obs = project(st, "p")
            flex = next(c for c in obs.cells if c["id"] == "cell-flex-1")
            assert flex["mode"] in ("draining", "changeover") and flex["available"] == 0
            assert flex["target_capabilities"] and flex["reconfig"]["changeover_s"] == 120
            assert obs.structure_version == st.structure_version
            seen.add(flex["mode"])
            aff = {a.kind: a for a in affordances(obs, (ActionKind.START_TASK, ActionKind.REQUEST_RECONFIGURATION))}
            assert all(c["entity"] != "cell-flex-1" for c in aff[ActionKind.START_TASK].candidates)
            assert all(c["entity"] != "cell-flex-1" for c in aff[ActionKind.REQUEST_RECONFIGURATION].candidates)
    assert seen  # 실제로 전환이 일어났다


def test_reconfig_candidates_exclude_last_provider():
    st = run_scenario(DEV.model_copy(update={"sim_time_limit": 10.0}), seed=0).world.state
    st.entities["cell-pack-1"].capabilities = ("pick",)  # pack 제공 셀이 flex 하나뿐인 상황을 만든다
    st.entities["cell-flex-1"].capabilities = ("pack",)
    obs = project(st, "s")
    cands = affordances(obs, (ActionKind.REQUEST_RECONFIGURATION,))[0].candidates
    assert not any(c["entity"] == "cell-flex-1" and c["capabilities"] == ["pick"] for c in cands)


class _Bad:
    def __init__(self, name, proposals):
        self.name, self._p = name, proposals

    def reset(self, ctx):
        pass

    def usage(self):
        return {}


class StructureThatAssigns(_Bad):
    def decide(self, obs, aff):
        ready = [t for t in obs.open_tasks if t["status"] == "READY"]
        return [ActionProposal(ActionKind.START_TASK, {"task": ready[0]["id"], "entity": "cell-pick-1"})] if ready else []


class DispatcherThatReconfigures(_Bad):
    def decide(self, obs, aff):
        return [ActionProposal(ActionKind.REQUEST_RECONFIGURATION, {"entity": "cell-flex-1", "capabilities": ["pack"]})]


def test_role_separation_enforced_by_permissions():
    short = DEV.model_copy(update={"sim_time_limit": 600.0})
    a = run_scenario(short, seed=1, structure_policy=StructureThatAssigns("rogue", None))
    rej = [e for e in a.events if e.event_type == "ActionRejected" and e.actor_id == "structure.rogue"]
    assert rej and all(any("not permitted" in r for r in e.payload["reasons"]) for e in rej)

    b = run_scenario(short, seed=1, policy=DispatcherThatReconfigures("rogue", None))
    kinds = [e.event_type for e in b.events]
    assert "ReconfigurationRequested" not in kinds
    assert a.summary()["invariant_violations"] == b.summary()["invariant_violations"] == 0


def test_structure_runs_before_dispatch_and_is_deterministic():
    a = run_scenario(DEV, seed=3, structure_policy="p2")
    b = run_scenario(DEV, seed=3, structure_policy="p2")
    assert encode_events(a.events) == encode_events(b.events)
    assert a.structure_actor == "structure.p2" and a.policy_actor == "policy.fifo"


@pytest.mark.parametrize("sp", ["p0", "p1", "p2"])
def test_structure_policies_run_clean_on_dev_seeds(sp):
    total_reconf = 0
    for seed in range(0, 10, 3):
        res = run_scenario(DEV, seed=seed, structure_policy=sp)
        s = res.summary()
        assert s["actions_rejected"] == 0 and s["invariant_violations"] == 0
        total_reconf += s["event_types"].get("ReconfigurationCompleted", 0)
    if sp == "p0":
        assert total_reconf == 0
    else:
        assert total_reconf > 0


def test_p2_threshold_scales_with_changeover_but_p1_does_not():
    cell = lambda cs: {"reconfig": {"options": [["pick"], ["pack"]], "changeover_s": cs}}
    p1, p2 = ReactiveStructure(), CostAwareStructure()
    assert p1._threshold(cell(30)) == p1._threshold(cell(300)) == 8.0
    assert p2._threshold(cell(30)) == pytest.approx(3.0 + 2.0 * 0.5)
    assert p2._threshold(cell(300)) == pytest.approx(3.0 + 2.0 * 5.0)


def test_pressure_and_thresholds():
    from asel.policies.contract import Observation

    cells = (
        {"id": "pick", "type": "w", "capabilities": ["pick"], "capacity": 2, "reserved": 0, "out_of_service": 0, "available": 2},
        {"id": "pack", "type": "w", "capabilities": ["pack"], "capacity": 1, "reserved": 1, "out_of_service": 0, "available": 0},
        {"id": "flex", "type": "w", "capabilities": ["pick"], "capacity": 1, "reserved": 0, "out_of_service": 0,
         "available": 1, "mode": "normal", "target_capabilities": None, "mode_since": None,
         "reconfig": {"options": [["pick"], ["pack"]], "changeover_s": 120.0}},
    )
    tasks = tuple({"id": f"k{i}", "capability": "pack", "status": "READY", "order": None, "step": 1,
                   "predecessors": [], "created_at": 0.0, "created_index": i, "ready_at": 0.0,
                   "started_at": None, "assigned_entity": None} for i in range(4))
    obs = Observation("s", 1000.0, 1, cells, (), tasks, 0, 0)
    assert pressures(obs) == {"pick": 0.0, "pack": 4.0}
    aff = affordances(obs, (ActionKind.REQUEST_RECONFIGURATION,))
    assert ReactiveStructure(threshold=2.0).decide(obs, aff)[0].params == {"entity": "flex", "capabilities": ["pack"]}
    assert ReactiveStructure(threshold=5.0).decide(obs, aff) == []
    # P2: 기준값 = 2 + 1.0 * 120/60 = 4 → 압력 차 4 면 전환, 최소 유지시간 안이면 보류
    assert CostAwareStructure(threshold=2.0, cost_per_min=1.0).decide(obs, aff)
    cells2 = cells[:2] + (dict(cells[2], mode_since=900.0),)
    obs2 = Observation("s", 1000.0, 1, cells2, (), tasks, 0, 0)
    assert CostAwareStructure(threshold=2.0, min_dwell_s=600).decide(obs2, aff) == []
