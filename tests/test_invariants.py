"""불변조건 검사기가 실제로 위반을 잡아내는지 확인 (검사기가 늘 통과만 하면 무의미)."""

from __future__ import annotations

from asel.core.invariants import check_invariants
from asel.core.model import TaskStatus
from conftest import create, make_world, start


def _world_with_running_task():
    w = make_world()
    w.submit(create("a"))
    w.submit(create("b", cap="pack", preds=["a"]))
    w.submit(start("a", "pick-1"))
    assert check_invariants(w.state) == []
    return w


def test_detects_over_reservation():
    w = _world_with_running_task()
    w.state.resources["pick-1"].holders.append("b")
    assert any("reserved 2 > capacity 1" in v for v in check_invariants(w.state))


def test_detects_running_without_reservation():
    w = _world_with_running_task()
    w.state.resources["pick-1"].holders.clear()
    assert any("RUNNING on pick-1 but holds None" in v for v in check_invariants(w.state))


def test_detects_precedence_violation():
    w = _world_with_running_task()
    w.state.tasks["b"].status = TaskStatus.READY
    assert any("READY with unfinished predecessors" in v for v in check_invariants(w.state))


def test_detects_early_completion():
    w = _world_with_running_task()
    t = w.state.tasks["a"]
    w.state.resources["pick-1"].holders.clear()
    t.status = TaskStatus.COMPLETED
    t.completed_at = t.started_at + t.duration / 2
    assert any("completed early" in v for v in check_invariants(w.state))


def test_detects_holder_not_running():
    w = _world_with_running_task()
    w.state.tasks["a"].status = TaskStatus.READY
    assert any("not RUNNING" in v for v in check_invariants(w.state))
