"""World.submit 의 검증·적용 규칙 단위 테스트."""

from __future__ import annotations

import pytest

from asel.core.actions import Action
from asel.core.events import EventType
from asel.core.invariants import check_invariants
from asel.core.model import ALLOWED_TRANSITIONS, TaskStatus, is_allowed_transition
from conftest import complete, create, make_world, start


def _rejected_without_change(w, action) -> tuple[str, ...]:
    before = w.state.snapshot()
    n_events = len(w.log)
    res = w.submit(action)
    assert not res.accepted
    after = w.state.snapshot()
    after["sim_time"] = before["sim_time"]  # 시각은 제출 시점 그대로
    assert after == before, "rejected action must not change world state"
    # 거절은 ActionProposed + ActionRejected 두 이벤트만 남긴다
    assert [e.event_type for e in w.log[n_events:]] == [
        EventType.ACTION_PROPOSED,
        EventType.ACTION_REJECTED,
    ]
    return res.reasons


# -- 상태 전이 표 ------------------------------------------------------------


def test_terminal_states_have_no_exits():
    for s in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert ALLOWED_TRANSITIONS[s] == frozenset()


@pytest.mark.parametrize(
    "src,dst",
    [
        (TaskStatus.CREATED, TaskStatus.RUNNING),
        (TaskStatus.WAITING, TaskStatus.RUNNING),
        (TaskStatus.READY, TaskStatus.COMPLETED),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.RUNNING, TaskStatus.READY),
    ],
)
def test_illegal_transitions(src, dst):
    assert not is_allowed_transition(src, dst)


# -- 정상 흐름 ---------------------------------------------------------------


def test_happy_path_lifecycle_and_versions():
    w = make_world()
    assert w.submit(create("a")).accepted
    assert w.state.tasks["a"].status == TaskStatus.READY
    assert w.state.version == 1

    assert w.submit(create("b", cap="pack", preds=["a"])).accepted
    assert w.state.tasks["b"].status == TaskStatus.WAITING

    assert w.submit(start("a", "pick-1")).accepted
    assert w.state.resources["pick-1"].holders == ["a"]
    assert w.state.tasks["a"].status == TaskStatus.RUNNING

    w.advance_to(10.0)
    assert w.submit(complete("a")).accepted
    assert w.state.tasks["a"].status == TaskStatus.COMPLETED
    assert w.state.resources["pick-1"].holders == []
    assert w.state.tasks["b"].status == TaskStatus.READY  # 후속 작업 해제
    assert w.state.version == 4
    assert check_invariants(w.state) == []


# -- 거절 규칙 ---------------------------------------------------------------


def test_reject_start_when_resource_full():
    w = make_world()
    w.submit(create("a"))
    w.submit(create("b"))
    assert w.submit(start("a", "pick-1")).accepted
    reasons = _rejected_without_change(w, start("b", "pick-1"))
    assert any("no free capacity" in r for r in reasons)


def test_reject_start_with_unfinished_predecessor():
    w = make_world()
    w.submit(create("a"))
    w.submit(create("b", cap="pack", preds=["a"]))
    reasons = _rejected_without_change(w, start("b", "pack-1"))
    assert any("not READY" in r for r in reasons)
    assert any("predecessor a not completed" in r for r in reasons)


def test_reject_start_on_wrong_capability():
    w = make_world()
    w.submit(create("a", cap="pick"))
    reasons = _rejected_without_change(w, start("a", "pack-1"))
    assert any("lacks capability" in r for r in reasons)


def test_reject_complete_before_duration_elapsed():
    w = make_world()
    w.submit(create("a", duration=10.0))
    w.submit(start("a", "pick-1"))
    w.advance_to(9.999)
    reasons = _rejected_without_change(w, complete("a"))
    assert any("not finished" in r for r in reasons)


def test_reject_complete_of_not_running_task():
    w = make_world()
    w.submit(create("a"))
    reasons = _rejected_without_change(w, complete("a"))
    assert any("not RUNNING" in r for r in reasons)


def test_reject_stale_expected_version():
    w = make_world()
    w.submit(create("a"))
    w.submit(create("b"))
    reasons = _rejected_without_change(w, start("a", "pick-1", expected_version=1))
    assert any("stale world version" in r for r in reasons)
    assert w.submit(start("a", "pick-1", expected_version=w.state.version)).accepted


def test_reject_unpermitted_actor():
    w = make_world()
    w.submit(create("a"))
    reasons = _rejected_without_change(w, start("a", "pick-1", actor="intruder"))
    assert any("not permitted" in r for r in reasons)
    # 배정기는 작업을 완료 처리할 권한이 없다
    w.submit(start("a", "pick-1"))
    w.advance_to(100)
    bad = Action("dispatcher.test", "complete_task", {"task": "a"})
    assert any("not permitted" in r for r in _rejected_without_change(w, bad))


def test_reject_unknown_kind_and_bad_params():
    w = make_world()
    assert _rejected_without_change(w, Action("env", "teleport", {}))
    assert _rejected_without_change(w, Action("env", "create_task", {"id": "x"}))
    assert _rejected_without_change(w, create("a", duration=-1))
    assert _rejected_without_change(w, create("a", duration=float("nan")))
    assert _rejected_without_change(w, create("a", preds=["ghost"]))
    assert _rejected_without_change(w, create("a", preds=["a"]))
    assert _rejected_without_change(w, Action("dispatcher.test", "start_task", {"task": ["x"]}))


def test_reject_duplicate_task_id():
    w = make_world()
    w.submit(create("a"))
    assert any("already exists" in r for r in _rejected_without_change(w, create("a")))


def test_clock_cannot_go_backwards():
    w = make_world()
    w.advance_to(5.0)
    with pytest.raises(ValueError):
        w.advance_to(4.0)
