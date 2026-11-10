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
