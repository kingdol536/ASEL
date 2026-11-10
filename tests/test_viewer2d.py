"""2D 재생 뷰어 (#6): 공개 로그만 읽고, 사건을 바꾸지 않는다."""

from __future__ import annotations

from asel.io.eventlog import PUBLIC_LOG
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from asel.viewer2d import build_view, render_run
from conftest import ROOT


def test_view_from_public_log_only(tmp_path):
    sc = load_scenario(ROOT / "scenarios" / "warehouse-fault-a.yaml")
    run_dir = write_run(run_scenario(sc, seed=3), tmp_path)
    before = (run_dir / PUBLIC_LOG).read_bytes()
    # 숨겨진 참값이 든 파일을 모두 치워도 뷰어는 동작해야 한다
    for name in ("private_events.ndjson", "scenario.json", "final_state.json", "manifest.json"):
        (run_dir / name).unlink()
    out = render_run(run_dir)
    page = out.read_text(encoding="utf-8")
    assert (run_dir / PUBLIC_LOG).read_bytes() == before  # 뷰어가 로그를 바꾸지 않음
    assert page.startswith("<!doctype html>") and page.count("<svg") == 3
    for eid in ("cell-pick-1", "cell-pack-1", "cell-flex-1"):
        assert eid in page
    assert 'class="outage"' in page
    for secret in ("conveyor jam", "motor overheat", "planned_end"):
        assert secret not in page


def test_view_intervals_match_state(tmp_path):
    from asel.io.eventlog import read_public

    sc = load_scenario(ROOT / "scenarios" / "warehouse-small-a.yaml")
    res = run_scenario(sc, seed=8)
    run_dir = write_run(res, tmp_path)
    v = build_view(read_public(run_dir / PUBLIC_LOG))
    bars = {b.task: (eid, b.start, b.end) for eid, bs in v.bars.items() for b in bs}
    for t in res.world.state.tasks.values():
        if t.started_at is not None:
            assert bars[t.id] == (t.assigned_entity, t.started_at, t.completed_at)
    # READY 수 추이의 마지막 값 = 종료 시점 READY 작업 수
    for cap, series in v.ready_series.items():
        n_ready = sum(1 for t in res.world.state.tasks.values() if t.capability == cap and t.status == "READY")
        assert series[-1][1] == n_ready


def test_view_shows_reconfiguration(tmp_path):
    sc = load_scenario(ROOT / "scenarios" / "warehouse-reconfig-dev.yaml")
    res = run_scenario(sc, seed=2, structure_policy="p1")
    run_dir = write_run(res, tmp_path)
    before = (run_dir / PUBLIC_LOG).read_bytes()
    page = render_run(run_dir).read_text(encoding="utf-8")
    assert (run_dir / PUBLIC_LOG).read_bytes() == before
    n = sum(1 for e in res.events if e.event_type == "ReconfigurationCompleted")
    assert page.count('class="changeover"') == n > 0
    assert "역할 전환 중" in page and "→pack" in page
