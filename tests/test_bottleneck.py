"""병목 지표 (#23): 손으로 계산한 기대값과 대조."""

from __future__ import annotations

import pytest

from asel.core.actions import Action, ActionKind
from asel.core.world import ENV_ACTOR
from asel.evaluation.bottleneck import structure_metrics
from asel.io.eventlog import read_public
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from conftest import ROOT, create, start
from test_reconfiguration import DISP, done, req, world


def test_hand_example_loads_windows_and_reconfiguration_costs():
    """셀: pick-1, flex(pick, 재구성 100s), pack-1. 창 100s.
    t=0   : pack 작업 3개 READY (수요 pack 3, 가용 pack 1 → b_pack = 3), pick 수요 0
    t=0   : flex 를 pack 으로 요청 (비어 있음 → 즉시 전환 시작, 가용 pick 1)
    t=100 : 전환 완료 → 가용 pack 2 → b_pack = 1.5
    t=200 : 종료
    창0 [0,100): pack 평균 3.0 → 병목 pack / 창1 [100,200): pack 평균 1.5 → 병목 pack
    """
    w = world()
    for i in range(3):
        w.submit(create(f"k{i}", cap="pack", duration=1000))
    w.submit(req("flex", ["pack"]))
    w.advance_to(100)
    w.submit(done("flex"))
    w.advance_to(200)
    w.end_run(200)
    m = structure_metrics([e for e in w.log], window_s=100)
    assert m["bottleneck_by_window"] == ["pack", "pack"]
    assert m["load_mean"]["pack"] == pytest.approx((3.0 * 100 + 1.5 * 100) / 200)
    assert m["load_mean"]["pick"] == pytest.approx(0.0)
    assert m["reconfig_requested"] == m["reconfig_completed"] == 1
    assert m["draining_s_total"] == 0 and m["changeover_s_total"] == 100 and m["lost_capacity_s"] == 100
    assert m["bottleneck_shifts"] == 0


def test_shift_counting_and_zero_capacity():
    """pick 이 먼저 병목, pack 이 나중 병목 → 이동 1회. 고장으로 pack 가용 0 인 시간은 따로 센다."""
    w = world()
    for i in range(4):
        w.submit(create(f"p{i}", cap="pick", duration=1000))  # 창0: pick 수요 4 / 가용 2 = 2
    w.submit(start("p0", "pick-1", actor=DISP))
    w.submit(start("p1", "flex", actor=DISP))
    w.advance_to(100)
    w.submit(Action(ENV_ACTOR, ActionKind.BEGIN_OUTAGE, {"entity": "pack-1", "units": 1}, private={"cause": "t"}))
    for i in range(5):
        w.submit(create(f"k{i}", cap="pack", duration=10))  # 창1: pack 수요 5 / max(0,1) = 5 > pick 2
    w.advance_to(200)
    w.end_run(200)
    m = structure_metrics(w.log, window_s=100)
    assert m["bottleneck_by_window"] == ["pick", "pack"] and m["bottleneck_shifts"] == 1
    assert m["zero_capacity_s"] == {"pack": pytest.approx(100.0)}


def test_metrics_need_only_public_log(tmp_path):
    sc = load_scenario(ROOT / "scenarios" / "warehouse-reconfig-dev.yaml")
    res = run_scenario(sc, seed=2, structure_policy="p1")
    run_dir = write_run(res, tmp_path)
    (run_dir / "private_events.ndjson").unlink()
    m = structure_metrics(read_public(run_dir / "events.ndjson"))
    kinds = [e.event_type for e in res.events]
    assert m["reconfig_completed"] == kinds.count("ReconfigurationCompleted") > 0
    assert m["changeover_s_total"] == pytest.approx(120.0 * m["reconfig_completed"])
    assert len(m["bottleneck_by_window"]) == 12  # 3600s / 300s
