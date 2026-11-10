"""속성 기반 테스트: 무작위 행동열·무작위 시나리오에서도 불변조건이 깨지지 않는다."""

from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from asel.core.actions import Action, ActionKind
from asel.core.invariants import check_invariants
from asel.core.world import ENV_ACTOR, replay
from asel.io.scenario import Scenario
from asel.runner import run_scenario
from conftest import DISPATCHER, make_world

TASK_IDS = [f"t{i}" for i in range(6)]
CELLS = ["c-pick", "c-pack", "c-both", "c-ghost"]  # c-ghost 는 존재하지 않는 셀
CAPS = ["pick", "pack", "weld"]  # weld 는 아무 셀도 제공하지 않음

_actor = st.sampled_from([ENV_ACTOR, DISPATCHER, "intruder"])
_create = st.builds(
    lambda actor, tid, cap, dur, preds: Action(
        actor, ActionKind.CREATE_TASK,
        {"id": tid, "capability": cap, "predecessors": preds},
        private={"duration": dur},
    ),
    _actor,
    st.sampled_from(TASK_IDS),
    st.sampled_from(CAPS),
    st.one_of(st.floats(min_value=0.5, max_value=50), st.just(0.0), st.just(-3.0)),
    st.lists(st.sampled_from(TASK_IDS), max_size=2),
)
_start = st.builds(
    lambda actor, tid, cell, ev: Action(actor, ActionKind.START_TASK, {"task": tid, "entity": cell}, ev),
    _actor,
    st.sampled_from(TASK_IDS),
    st.sampled_from(CELLS),
    st.one_of(st.none(), st.integers(min_value=0, max_value=30)),
)
_complete = st.builds(
    lambda actor, tid: Action(actor, ActionKind.COMPLETE_TASK, {"task": tid}),
    _actor,
    st.sampled_from(TASK_IDS),
)
def _plausible_action(data, w) -> Action:
    """현재 상태를 보고 '그럴듯한' 행동을 만든다. 순수 무작위만으로는 대부분 거절되어
    시작·완료 경로를 거의 시험하지 못한다(실측: 300개 사례 중 start 승인 0건)."""
    tasks = sorted(w.state.tasks)
    kind = data.draw(st.sampled_from(["create", "start", "complete", "outage"]))
    if kind == "outage":
        return Action(
            ENV_ACTOR,
            data.draw(st.sampled_from([ActionKind.BEGIN_OUTAGE, ActionKind.END_OUTAGE])),
            {"entity": data.draw(st.sampled_from(CELLS[:3])), "units": data.draw(st.integers(1, 2))},
            private={"cause": "random"},
        )
    if kind == "create" or not tasks:
        preds = data.draw(st.lists(st.sampled_from(tasks), max_size=2, unique=True)) if tasks else []
        return Action(
            ENV_ACTOR,
            ActionKind.CREATE_TASK,
            {
                "id": f"n{len(tasks)}",
                "capability": data.draw(st.sampled_from(["pick", "pack"])),
                "predecessors": preds,
            },
            private={"duration": data.draw(st.floats(min_value=0.5, max_value=20))},
        )
    tid = data.draw(st.sampled_from(tasks))
    if kind == "start":
        cell = data.draw(st.sampled_from(CELLS[:3]))
        return Action(DISPATCHER, ActionKind.START_TASK, {"task": tid, "entity": cell})
    return Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": tid})


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.data())
def test_random_action_sequences_preserve_invariants(data):
    w = make_world([("c-pick", ["pick"], 1), ("c-pack", ["pack"], 1), ("c-both", ["pick", "pack"], 2)])
    n_steps = data.draw(st.integers(min_value=0, max_value=80))
    for _ in range(n_steps):
        mode = data.draw(st.sampled_from(["plausible", "plausible", "plausible", "noise", "tick"]))
        if mode == "tick":
            w.advance_to(w.state.sim_time + data.draw(st.floats(min_value=0, max_value=15)))
            continue
        x = _plausible_action(data, w) if mode == "plausible" else data.draw(
            st.one_of(_create, _start, _complete)
        )
        before = w.state.snapshot()
        v0 = w.state.version
        res = w.submit(x)
        if res.accepted:
            assert w.state.version == v0 + 1
        else:
            assert w.state.version == v0
            assert w.state.snapshot() == before
        assert check_invariants(w.state) == [], (x, check_invariants(w.state))
    # 이벤트 로그만으로 같은 상태가 재구성된다
    w.end_run(w.state.sim_time)
    assert replay(w.log).snapshot() == w.state.snapshot()


_cell = st.tuples(
    st.lists(st.sampled_from(["pick", "pack"]), min_size=1, max_size=2, unique=True),
    st.integers(min_value=1, max_value=3),
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    cells=st.lists(_cell, min_size=1, max_size=5),
    rate=st.floats(min_value=0.2, max_value=6.0),
    seed=st.integers(min_value=0, max_value=2**31),
)
def test_random_scenarios_run_without_violations(cells, rate, seed):
    offered = {c for caps, _ in cells for c in caps}
    steps = [s for s in ("pick", "pack") if s in offered]
    sc = Scenario.model_validate(
        {
            "schema_version": "0.1",
            "scenario_id": "prop",
            "domain": "warehouse_like",
            "seed": seed,
            "sim_time_limit": 900,
            "entities": [
                {"id": f"cell-{i}", "type": "workstation", "capabilities": caps, "capacity": cap}
                for i, (caps, cap) in enumerate(cells)
            ],
            "workload": {
                "arrival_process": {"type": "poisson", "rate_per_min": rate},
                "job_template": [
                    {"capability": s, "service_time": {"type": "exponential", "mean_s": 40}}
                    for s in steps
                ],
            },
        }
    )
    res = run_scenario(sc)  # 매 단계 불변조건 검사 (위반 시 예외)
    assert res.summary()["invariant_violations"] == 0
    assert res.summary()["actions_rejected"] == 0  # FIFO 는 유효한 행동만 제안해야 한다
