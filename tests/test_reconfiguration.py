"""재구성 규칙과 핵심 기능 (#20, 결정 0005)."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from asel.core.actions import Action, ActionKind
from asel.core.events import EventType
from asel.core.invariants import check_invariants
from asel.core.model import EntityMode, TaskStatus
from asel.core.world import ENV_ACTOR, World, replay
from conftest import create, start

STRUCT = "structure.test"
DISP = "dispatcher.test"
GRANTS = {
    ENV_ACTOR: {ActionKind.CREATE_TASK, ActionKind.COMPLETE_TASK, ActionKind.BEGIN_OUTAGE,
                ActionKind.END_OUTAGE, ActionKind.COMPLETE_RECONFIGURATION},
    DISP: {ActionKind.START_TASK},
    STRUCT: {ActionKind.REQUEST_RECONFIGURATION},
}
RECONF = {"options": [["pick"], ["pack"]], "changeover_s": 100.0}


def world(cells=None) -> World:
    cells = cells or [
        ("pick-1", ["pick"], 1, None),
        ("flex", ["pick"], 1, RECONF),
        ("pack-1", ["pack"], 1, None),
    ]
    w = World("t", GRANTS)
    ents = []
    for cid, caps, _cap, rc in cells:
        d = {"id": cid, "type": "workstation", "capabilities": caps}
        if rc:
            d["reconfig"] = rc
        ents.append(d)
    w.initialize(ents, [], [{"id": c, "capacity": cap} for c, _, cap, _ in cells])
    return w


def req(entity, caps, actor=STRUCT):
    return Action(actor, ActionKind.REQUEST_RECONFIGURATION, {"entity": entity, "capabilities": caps})


def done(entity):
    return Action(ENV_ACTOR, ActionKind.COMPLETE_RECONFIGURATION, {"entity": entity})


def complete(tid):
    return Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": tid})


def _rejected_unchanged(w, action):
    before = w.state.snapshot()
    res = w.submit(action)
    assert not res.accepted
    assert w.state.snapshot() == before
    return res.reasons


def test_drain_then_changeover_then_new_role():
    w = world()
    w.submit(create("a", duration=10))
    w.submit(create("b", duration=10))
    w.submit(start("a", "flex", actor=DISP))
    assert w.submit(req("flex", ["pack"])).accepted
    ent = w.state.entities["flex"]
    assert ent.mode == EntityMode.DRAINING and ent.capabilities == ("pick",)
    # 비우는 중에는 새 작업을 받지 않는다
    assert any("draining" in r for r in _rejected_unchanged(w, start("b", "flex", actor=DISP)))
    w.advance_to(10)
    n0 = len(w.log)
    assert w.submit(complete("a")).accepted
    assert EventType.RECONFIGURATION_STARTED in [e.event_type for e in w.log[n0:]]
    assert ent.mode == EntityMode.CHANGEOVER and ent.capabilities == ("pick",)  # 역할은 아직 그대로
    w.advance_to(109.9)
    assert any("not finished" in r for r in _rejected_unchanged(w, done("flex")))
    w.advance_to(110)
    assert w.submit(done("flex")).accepted
    assert ent.mode == EntityMode.NORMAL and ent.capabilities == ("pack",) and w.state.structure_version == 1
    assert check_invariants(w.state) == []
    w.end_run(110)
    assert replay(w.log).snapshot() == w.state.snapshot()


def test_idle_cell_starts_changeover_immediately():
    w = world()
    n0 = len(w.log)
    assert w.submit(req("flex", ["pack"])).accepted
    kinds = [e.event_type for e in w.log[n0:]]
    assert EventType.RECONFIGURATION_REQUESTED in kinds and EventType.RECONFIGURATION_STARTED in kinds
    assert w.state.entities["flex"].mode == EntityMode.CHANGEOVER


def test_change_that_removes_last_provider_is_rejected():
    """교착 방지: 유일한 pack 제공 셀을 pick 으로 바꾸면 pack 작업이 영원히 대기한다 → 거절."""
    w = world([("pick-1", ["pick"], 1, None), ("flex", ["pack"], 1, RECONF)])
    reasons = _rejected_unchanged(w, req("flex", ["pick"]))
    assert any("no cell would offer ['pack']" in r for r in reasons)


def test_capacity_zero_cells_do_not_count_as_providers():
    w = world([("pick-1", ["pick"], 1, None), ("ghost-pack", ["pack"], 0, None), ("flex", ["pack"], 1, RECONF)])
    assert _rejected_unchanged(w, req("flex", ["pick"]))


def test_pending_target_counts_for_coverage():
    """전환 중인 셀은 목표 역할로 센다: a(pick→pack 예정)가 있으면 b(pack→pick)도 허용된다."""
    w = world([("a", ["pick"], 1, RECONF), ("b", ["pack"], 1, RECONF), ("c", ["pick"], 1, None)])
    assert w.submit(req("a", ["pack"])).accepted
    assert w.submit(req("b", ["pick"])).accepted  # pack 은 a 의 목표 역할로 계속 제공됨
    assert w.offered_capabilities() == {"pick", "pack"}
    # 반대로 a 가 목표를 갖기 전이라면 b 를 바꾸는 순간 pack 이 사라진다
    w2 = world([("a", ["pick"], 1, RECONF), ("b", ["pack"], 1, RECONF)])
    assert _rejected_unchanged(w2, req("b", ["pick"]))
    assert _rejected_unchanged(w2, req("a", ["pack"]))  # pick 이 사라짐


def test_request_validation():
    w = world()
    assert any("not reconfigurable" in r for r in _rejected_unchanged(w, req("pick-1", ["pack"])))
    assert any("not an option" in r for r in _rejected_unchanged(w, req("flex", ["weld"])))
    assert any("already has" in r for r in _rejected_unchanged(w, req("flex", ["pick"])))
    assert any("not permitted" in r for r in _rejected_unchanged(w, req("flex", ["pack"], actor=DISP)))
    assert _rejected_unchanged(w, req("flex", "pack"))
    assert w.submit(req("flex", ["pack"])).accepted
    assert any("no cancel" in r for r in _rejected_unchanged(w, req("flex", ["pick"])))
    # 배정 주체는 재구성 완료를 대신할 수 없다
    assert _rejected_unchanged(w, Action(DISP, ActionKind.COMPLETE_RECONFIGURATION, {"entity": "flex"}))


def test_fault_and_reconfiguration_overlap():
    """고장(용량 감소)과 전환은 독립: 고장 중 전환 완료 가능, 고장은 전환 후에도 유지된다."""
    w = world()
    w.submit(Action(ENV_ACTOR, ActionKind.BEGIN_OUTAGE, {"entity": "flex", "units": 1}, private={"cause": "x"}))
    assert w.submit(req("flex", ["pack"])).accepted
    w.advance_to(100)
    assert w.submit(done("flex")).accepted
    flex, res = w.state.entities["flex"], w.state.resources["flex"]
    assert flex.capabilities == ("pack",) and res.out_of_service == 1 and res.available == 0
    w.submit(Action(ENV_ACTOR, ActionKind.END_OUTAGE, {"entity": "flex", "units": 1}))
    w.submit(create("p", cap="pack", duration=5))
    assert w.submit(start("p", "flex", actor=DISP)).accepted
    assert check_invariants(w.state) == []


# ---- 시뮬레이터 경로: 전환 완료 자동 예약, 재현·재생 ----------------------------------


class ScriptedStructureFifo:
    """t>=600 에서 flex 를 pack 으로 한 번 전환 요청하고, 나머지는 모드를 지키는 FIFO 배정."""

    actor_id = "policy.script"

    def __init__(self):
        self.requested = False

    def propose(self, state):
        out = []
        if not self.requested and state.sim_time >= 600:
            self.requested = True
            out.append(Action(STRUCT, ActionKind.REQUEST_RECONFIGURATION, {"entity": "cell-flex-1", "capabilities": ["pack"]}))
        ready = sorted((t for t in state.tasks.values() if t.status == TaskStatus.READY),
                       key=lambda t: (t.ready_at, t.created_index))
        free = {rid: r.available for rid, r in state.resources.items()}
        for t in ready:
            for e in sorted(state.entities.values(), key=lambda e: e.id):
                if e.mode == EntityMode.NORMAL and t.capability in e.capabilities and free[e.id] > 0:
                    free[e.id] -= 1
                    out.append(Action(DISP, ActionKind.START_TASK, {"task": t.id, "entity": e.id}))
                    break
        return out


def _reconf_scenario():
    from asel.io.scenario import Scenario, load_scenario
    from conftest import SCENARIO_A

    d = load_scenario(SCENARIO_A).model_dump(mode="json")
    d["schema_version"] = "0.3"
    for e in d["entities"]:
        if e["id"] == "cell-flex-1":
            e["reconfigurable"] = {"options": [["pick"], ["pack"]], "changeover_s": 120}
    return Scenario.model_validate(d)


def _run(seed):
    from asel.core.simulator import Simulator
    from asel.domains.warehouse import WarehouseWorkload, world_init_payload

    sc = _reconf_scenario()
    w = World(f"r{seed}", GRANTS | {"policy.script": set()})
    w.initialize(*world_init_payload(sc))
    Simulator(w, WarehouseWorkload(sc, seed), ScriptedStructureFifo()).run(sc.sim_time_limit)
    return w


def test_simulator_schedules_changeover_completion_and_replays():
    from asel.io.eventlog import encode_events

    for seed in (0, 1, 2):
        a, b = _run(seed), _run(seed)
        assert encode_events(a.log) == encode_events(b.log)
        kinds = [e.event_type for e in a.log]
        assert kinds.count(EventType.RECONFIGURATION_COMPLETED) == 1
        st_ev = next(e for e in a.log if e.event_type == EventType.RECONFIGURATION_STARTED)
        done_ev = next(e for e in a.log if e.event_type == EventType.RECONFIGURATION_COMPLETED)
        assert done_ev.sim_time == st_ev.sim_time + 120
        assert a.state.entities["cell-flex-1"].capabilities == ("pack",)
        assert check_invariants(a.state) == []
        assert replay(a.log).snapshot() == a.state.snapshot()
        # 전환 후 flex 에서 pack 작업이 실제로 처리된다
        assert any(t.assigned_entity == "cell-flex-1" and t.capability == "pack" for t in a.state.tasks.values())


def test_reconfig_scenario_schema():
    import pytest
    from pydantic import ValidationError

    from asel.io.scenario import Scenario

    d = _reconf_scenario().model_dump(mode="json")
    for bad in (
        {"options": [["pick"]], "changeover_s": 10},  # 옵션 1개
        {"options": [["pack"], ["weld"]], "changeover_s": 10},  # 현재 역할이 옵션에 없음
        {"options": [["pick"], ["pick"]], "changeover_s": 10},  # 중복
        {"options": [["pick"], ["pack"]], "changeover_s": -1},
    ):
        dd = {**d, "entities": [dict(e, reconfigurable=bad) if e["id"] == "cell-flex-1" else e for e in d["entities"]]}
        with pytest.raises(ValidationError):
            Scenario.model_validate(dd)
    with pytest.raises(ValidationError):
        Scenario.model_validate({**d, "schema_version": "0.2"})


# ---- 무작위 행동열 --------------------------------------------------------------------


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_random_sequences_with_reconfiguration_keep_invariants(data):
    w = world([("a", ["pick"], 1, RECONF), ("b", ["pack"], 2, RECONF), ("c", ["pick"], 1, None)])
    for _ in range(data.draw(st.integers(0, 70))):
        k = data.draw(st.sampled_from(["create", "start", "complete", "req", "done", "tick", "outage"]))
        tasks = sorted(w.state.tasks)
        if k == "tick":
            w.advance_to(w.state.sim_time + data.draw(st.floats(0, 60)))
            continue
        if k == "create" or not tasks:
            a = create(f"t{len(tasks)}", cap=data.draw(st.sampled_from(["pick", "pack"])),
                       duration=data.draw(st.floats(0.5, 30)),
                       preds=data.draw(st.lists(st.sampled_from(tasks), max_size=1)) if tasks else ())
        elif k == "start":
            a = start(data.draw(st.sampled_from(tasks)), data.draw(st.sampled_from(["a", "b", "c"])), actor=DISP)
        elif k == "complete":
            a = complete(data.draw(st.sampled_from(tasks)))
        elif k == "req":
            a = req(data.draw(st.sampled_from(["a", "b", "c"])), [data.draw(st.sampled_from(["pick", "pack"]))])
        elif k == "done":
            a = done(data.draw(st.sampled_from(["a", "b", "c"])))
        else:
            a = Action(ENV_ACTOR, data.draw(st.sampled_from([ActionKind.BEGIN_OUTAGE, ActionKind.END_OUTAGE])),
                       {"entity": data.draw(st.sampled_from(["a", "b", "c"])), "units": 1}, private={"cause": "r"})
        before, v0 = w.state.snapshot(), w.state.version
        res = w.submit(a)
        if not res.accepted:
            assert w.state.snapshot() == before and w.state.version == v0
        assert check_invariants(w.state) == [], check_invariants(w.state)
        # 교착 방지 불변: pick·pack 제공 셀(목표 역할 포함)이 항상 하나 이상
        assert {"pick", "pack"} <= w.offered_capabilities()
    w.end_run(w.state.sim_time)
    assert replay(w.log).snapshot() == w.state.snapshot()
