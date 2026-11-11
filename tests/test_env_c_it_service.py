"""환경 C IT 서비스 (#41): 미공개 이식성 시험 — 시간 초과(cancel_tasks)를 포함한 이식."""

from __future__ import annotations

import pytest

from asel.core.actions import Action, ActionKind
from asel.core.invariants import check_invariants
from asel.core.model import TaskStatus
from asel.core.world import ENV_ACTOR, replay
from asel.evaluation.evaluator import order_metrics
from asel.io.eventlog import encode_events
from asel.io.scenario import load_scenario
from asel.runner import run_scenario
from conftest import ROOT, create, make_world, start

C = load_scenario(ROOT / "scenarios" / "it-service-c.yaml").model_copy(update={"sim_time_limit": 420.0})


def cancel(ids, actor=ENV_ACTOR):
    return Action(actor, ActionKind.CANCEL_TASKS, {"tasks": list(ids)})


def test_cancel_only_not_started_tasks_running_ones_finish():
    w = make_world()
    w.submit(create("a", duration=10))
    w.submit(create("b", cap="pack", duration=5, preds=["a"]))
    w.submit(create("c", duration=5))
    w.submit(start("a", "pick-1"))
    assert w.submit(cancel(["a", "b", "c"])).accepted
    st = w.state.tasks
    assert st["a"].status == TaskStatus.RUNNING  # 진행 중은 끝까지
    assert st["b"].status == st["c"].status == TaskStatus.CANCELLED
    w.advance_to(10)
    assert w.submit(Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": "a"})).accepted
    assert st["b"].status == TaskStatus.CANCELLED  # 취소된 후속 작업은 다시 열리지 않는다
    assert check_invariants(w.state) == []
    w.end_run(10)
    assert replay(w.log).snapshot() == w.state.snapshot()


def test_cancel_validation_and_permission():
    w = make_world()
    w.submit(create("a"))
    for bad in (cancel([]), cancel(["ghost"]), cancel(["a", "a"]), cancel(["a"], actor="dispatcher.test")):
        assert not w.submit(bad).accepted
    assert w.state.tasks["a"].status == TaskStatus.READY
    v = w.state.version
    w.submit(Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": "a"}))  # 거절됨 (RUNNING 아님)
    assert w.submit(cancel(["a"])).accepted and w.state.version == v + 1


@pytest.mark.parametrize("structure", [None, "p0", "p1", "p2"])
def test_c_runs_with_existing_policies(structure):
    res = run_scenario(C, seed=1, structure_policy=structure)
    s = res.summary()
    assert s["actions_rejected"] == 0 and s["invariant_violations"] == 0


def test_timeouts_cancel_requests_and_are_counted():
    res = run_scenario(C, seed=0)
    m = order_metrics(res.events)
    st = res.world.state
    cancelled_inst = {t.tags["order"] for t in st.tasks.values() if t.status == TaskStatus.CANCELLED}
    assert m["orders_cancelled"] == len(cancelled_inst) > 0
    # 시간 초과가 없는 배치 작업은 취소되지 않는다
    assert not any(i.startswith("batch") for i in cancelled_inst)
    # 취소는 도착 후 timeout_s 시점에만 일어난다
    for t in st.tasks.values():
        if t.status == TaskStatus.CANCELLED:
            limit = 15 if t.id.startswith("write") else 10
            assert t.created_at + limit <= C.sim_time_limit


def test_c_reproducible():
    a, b = run_scenario(C, seed=3, structure_policy="p1"), run_scenario(C, seed=3, structure_policy="p1")
    assert encode_events(a.events) == encode_events(b.events)
