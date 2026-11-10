"""M2 시나리오: 수요 급증(#3), 셀 고장(#4)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from asel.io.eventlog import encode_events
from asel.io.scenario import Scenario, load_scenario
from asel.runner import run_scenario
from conftest import ROOT
from test_reproducibility import _LifoDispatcher, _run_with

SURGE = ROOT / "scenarios" / "warehouse-surge-a.yaml"


@pytest.fixture
def surge():
    return load_scenario(SURGE)


def _order_arrivals(state) -> list[float]:
    return sorted(t.created_at for t in state.tasks.values() if t.tags.get("step") == 0)


def test_surge_reproducible(surge):
    a, b = run_scenario(surge, seed=4), run_scenario(surge, seed=4)
    assert encode_events(a.events) == encode_events(b.events)


def test_surge_doubles_arrival_rate_in_window(surge):
    """급증 구간(1200~2400s) 도착 수가 앞 구간의 약 2배 (시드 20개 합계, 통계적 확인)."""
    before = during = 0
    for seed in range(20):
        times = _order_arrivals(run_scenario(surge, seed=seed).world.state)
        before += sum(1 for t in times if t < 1200)
        during += sum(1 for t in times if 1200 <= t < 2400)
    # 기대값 600 vs 1200. 넓은 허용 범위로 우연 실패를 피한다.
    assert 1.6 < during / before < 2.5


def test_surge_workload_independent_of_policy(surge):
    """급증 시나리오에서도 정책이 달라도 같은 주문·처리 시간 (대응 비교 전제 재확인)."""
    from asel.policies.fifo import FifoDispatcher

    fifo = _run_with(surge, FifoDispatcher(), seed=13)
    lifo = _run_with(surge, _LifoDispatcher(), seed=13)
    sig = lambda s: {k: (t.created_at, t.duration) for k, t in s.tasks.items()}
    assert sig(fifo) == sig(lifo)


def test_zero_rate_segment_has_no_arrivals(surge):
    d = surge.model_dump(mode="json")
    d["workload"]["arrival_process"]["segments"] = [
        {"start_s": 0, "rate_per_min": 2.0},
        {"start_s": 600, "rate_per_min": 0.0},
        {"start_s": 1800, "rate_per_min": 2.0},
    ]
    sc = Scenario.model_validate(d)
    times = _order_arrivals(run_scenario(sc, seed=1).world.state)
    assert times and not any(600 <= t < 1800 for t in times)
    assert any(t >= 1800 for t in times)


@pytest.mark.parametrize(
    "segments",
    [
        [{"start_s": 5, "rate_per_min": 1}],
        [{"start_s": 0, "rate_per_min": 1}, {"start_s": 0, "rate_per_min": 2}],
        [{"start_s": 0, "rate_per_min": -1}],
    ],
)
def test_bad_segments_rejected(surge, segments):
    d = surge.model_dump(mode="json")
    d["workload"]["arrival_process"]["segments"] = segments
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)


# --------------------------------------------------------------------------- 고장 (#4)

FAULT = ROOT / "scenarios" / "warehouse-fault-a.yaml"


@pytest.fixture
def fault():
    return load_scenario(FAULT)


def _starts_on(events, entity):
    return [
        e.sim_time
        for e in events
        if e.event_type == "TaskStateChanged" and e.payload.get("to") == "RUNNING" and e.payload.get("entity") == entity
    ]


def test_fault_reproducible(fault):
    a, b = run_scenario(fault, seed=4), run_scenario(fault, seed=4)
    assert encode_events(a.events) == encode_events(b.events)


def test_no_new_starts_during_outage_and_recovery_after(fault):
    for seed in range(10):
        res = run_scenario(fault, seed=seed)
        assert res.summary()["invariant_violations"] == 0
        for f in fault.faults:
            starts = _starts_on(res.events, f.entity)
            assert not any(f.start_s <= t < f.end_s for t in starts), (seed, f.entity)
            assert any(t >= f.end_s for t in starts), (seed, f.entity)  # 복구 후 다시 일함


def test_running_task_finishes_through_outage(fault):
    """진행 중 작업은 고장이 나도 끝까지 처리된다 (결정 0003, 잠정). 시드 여러 개 중 사례가 있어야 한다."""
    f = fault.faults[0]
    seen = 0
    for seed in range(20):
        st = run_scenario(fault, seed=seed).world.state
        for t in st.tasks.values():
            if t.assigned_entity == f.entity and t.started_at is not None and t.started_at < f.start_s:
                if t.completed_at is not None and t.completed_at > f.start_s:
                    seen += 1
    assert seen > 0


def test_fault_cause_is_private(fault, tmp_path):
    from asel.io.eventlog import PRIVATE_LOG, PUBLIC_LOG
    from asel.runner import write_run

    run_dir = write_run(run_scenario(fault, seed=2), tmp_path)
    pub = (run_dir / PUBLIC_LOG).read_text(encoding="utf-8")
    priv = (run_dir / PRIVATE_LOG).read_text(encoding="utf-8")
    assert "ResourceOutageStarted" in pub and "ResourceOutageEnded" in pub
    for secret in ("conveyor jam", "motor overheat", "planned_end_s", "cause"):
        assert secret not in pub
    assert "conveyor jam" in priv and "planned_end_s" in priv


def _fault_doc(fault, faults):
    d = fault.model_dump(mode="json")
    d["faults"] = faults
    return d


@pytest.mark.parametrize(
    "faults",
    [
        [{"entity": "nope", "start_s": 0, "end_s": 10, "cause": "x"}],
        [{"entity": "cell-pack-1", "start_s": 10, "end_s": 10, "cause": "x"}],
        [{"entity": "cell-pack-1", "start_s": 0, "end_s": 10, "units": 2, "cause": "x"}],
        [
            {"entity": "cell-pack-1", "start_s": 0, "end_s": 10, "cause": "x"},
            {"entity": "cell-pack-1", "start_s": 5, "end_s": 15, "cause": "y"},
        ],
    ],
)
def test_bad_faults_rejected(fault, faults):
    with pytest.raises(ValidationError):
        Scenario.model_validate(_fault_doc(fault, faults))


def test_back_to_back_faults_allowed(fault):
    Scenario.model_validate(
        _fault_doc(
            fault,
            [
                {"entity": "cell-pack-1", "start_s": 0, "end_s": 10, "cause": "x"},
                {"entity": "cell-pack-1", "start_s": 10, "end_s": 20, "cause": "y"},
            ],
        )
    )


def test_back_to_back_faults_listed_in_reverse_order_both_apply(fault):
    """같은 셀의 연속 고장이 역순으로 적혀 있어도 둘 다 적용된다 (리뷰 지적 #2)."""
    sc = Scenario.model_validate(
        _fault_doc(
            fault,
            [
                {"entity": "cell-pack-1", "start_s": 1000, "end_s": 1100, "cause": "second"},
                {"entity": "cell-pack-1", "start_s": 900, "end_s": 1000, "cause": "first"},
            ],
        )
    )
    res = run_scenario(sc, seed=0)
    kinds = [e.event_type for e in res.events]
    assert kinds.count("ResourceOutageStarted") == 2
    assert kinds.count("ResourceOutageEnded") == 2
    assert res.summary()["actions_rejected"] == 0


def test_v01_scenario_cannot_use_v02_features(fault):
    d = fault.model_dump(mode="json")
    d["schema_version"] = "0.1"
    with pytest.raises(ValidationError):
        Scenario.model_validate(d)
