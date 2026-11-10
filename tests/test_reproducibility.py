"""재현성: 같은 설정·시드 -> 같은 이벤트 로그 바이트, 로그 -> 같은 최종 상태."""

from __future__ import annotations

from asel.core.actions import Action, ActionKind
from asel.core.model import TaskStatus
from asel.core.simulator import Simulator
from asel.core.world import ENV_ACTOR, World, replay
from asel.domains.warehouse import WarehouseWorkload, world_init_payload
from asel.io.eventlog import encode_events, encode_public, events_sha256, read_public, read_run
from asel.runner import run_scenario, write_run


def test_same_seed_same_event_bytes(scenario_a):
    a = run_scenario(scenario_a, seed=42)
    b = run_scenario(scenario_a, seed=42)
    assert encode_events(a.events) == encode_events(b.events)
    assert a.world.state.snapshot() == b.world.state.snapshot()


def test_different_seed_different_log(scenario_a):
    assert events_sha256(run_scenario(scenario_a, seed=1).events) != events_sha256(
        run_scenario(scenario_a, seed=2).events
    )


def test_replay_from_written_log_matches_final_state(scenario_a, tmp_path):
    res = run_scenario(scenario_a, seed=7)
    run_dir = write_run(res, tmp_path)
    events = read_run(run_dir)
    assert encode_events(events) == encode_events(res.events)  # 공개+비공개 파일 왕복 무손실
    assert replay(events).snapshot() == res.world.state.snapshot()


def test_invariant_checking_does_not_change_events(scenario_a):
    """검사 켜기/끄기(관찰 장치)가 논리 사건을 바꾸지 않는다."""
    on = run_scenario(scenario_a, seed=3, check_invariants=True)
    off = run_scenario(scenario_a, seed=3, check_invariants=False)
    assert encode_events(on.events) == encode_events(off.events)


class _LifoDispatcher:
    """비교용: 가장 늦게 준비된 작업부터, id 역순 셀에 배정."""

    actor_id = "dispatcher.lifo"

    def propose(self, state):
        ready = sorted(
            (t for t in state.tasks.values() if t.status == TaskStatus.READY),
            key=lambda t: (t.ready_at, t.created_index),
            reverse=True,
        )
        free = {rid: r.available for rid, r in state.resources.items()}
        out = []
        for t in ready:
            for e in sorted(state.entities.values(), key=lambda e: e.id, reverse=True):
                if t.capability in e.capabilities and free[e.id] > 0:
                    free[e.id] -= 1
                    out.append(Action(self.actor_id, ActionKind.START_TASK, {"task": t.id, "entity": e.id}))
                    break
        return out


def _run_with(sc, dispatcher, seed):
    from asel.runner import default_grants

    w = World("x", default_grants(dispatcher.actor_id))
    w.initialize(*world_init_payload(sc))
    Simulator(w, WarehouseWorkload(sc, seed), dispatcher).run(sc.sim_time_limit)
    return w.state


def test_workload_is_independent_of_dispatch_policy(scenario_a):
    """대응 비교의 전제: 정책이 달라도 같은 시드면 같은 주문·같은 처리 시간."""
    from asel.policies.fifo import FifoDispatcher

    fifo = _run_with(scenario_a, FifoDispatcher(), seed=11)
    lifo = _run_with(scenario_a, _LifoDispatcher(), seed=11)
    sig = lambda s: {k: (t.created_at, t.duration, t.predecessors) for k, t in s.tasks.items()}
    assert sig(fifo) == sig(lifo)
    # 배정 결과는 실제로 달라야 비교가 의미 있다
    assign = lambda s: {k: t.assigned_entity for k, t in s.tasks.items()}
    assert assign(fifo) != assign(lifo)


def test_compare_logs_byte_and_logical(scenario_a):
    from asel.compare import compare_logs
    from asel.core.events import Event

    a = run_scenario(scenario_a, seed=42).events
    b = run_scenario(scenario_a, seed=42).events
    c = compare_logs(a, b, encode_events(a), encode_events(b))
    assert c.byte_equal and c.logically_equal and c.max_rel_diff == 0.0

    # 마지막 자리 수준의 차이는 논리적으로 같다고 판정, 큰 차이는 다르다고 판정
    i = next(i for i, e in enumerate(b) if e.event_type == "TaskCreated")
    dur = b[i].private["duration"]
    for hidden, expect in (({"duration": dur * (1 + 1e-15)}, True), ({"duration": dur + 1.0}, False)):
        d = b[i].to_dict() | {"private": hidden}
        bb = b[:i] + [Event.from_dict(d)] + b[i + 1 :]
        r = compare_logs(a, bb, encode_events(a), encode_events(bb))
        assert not r.byte_equal
        assert r.logically_equal is expect
