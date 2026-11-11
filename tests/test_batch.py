"""일괄 실행기 (#5)."""

from __future__ import annotations

import csv
import io
import json
import shutil

import pytest

from asel.batch import finalize_interrupted_batch, parse_seeds, run_batch
from conftest import ROOT

SCENARIOS = [str(ROOT / "scenarios" / n) for n in ("warehouse-small-a.yaml", "warehouse-fault-a.yaml")]


def test_parse_seeds():
    assert parse_seeds("0-3") == [0, 1, 2, 3]
    assert parse_seeds("1,5, 7-8") == [1, 5, 7, 8]
    for bad in ("", "3-1", "1,1", "-2"):
        with pytest.raises(ValueError):
            parse_seeds(bad)


def test_batch_summary_is_deterministic_and_parallel_safe(tmp_path):
    a = run_batch(SCENARIOS, [0, 1, 2], tmp_path / "a", jobs=1)
    b = run_batch(SCENARIOS, [0, 1, 2], tmp_path / "b", jobs=2)
    csv_a = (a / "batch_summary.csv").read_text(encoding="utf-8")
    assert csv_a == (b / "batch_summary.csv").read_text(encoding="utf-8")
    assert csv_a.count("\n") == 1 + 6  # 헤더 + 2 시나리오 x 3 시드

    info = json.loads((a / "batch.json").read_text(encoding="utf-8"))
    assert info["n_runs"] == 6
    assert info["invariant_violations_total"] == 0
    assert info["throughput"]["runs_per_min"] > 0
    assert len(list((a / "runs").glob("*/*/manifest.json"))) == 6
    # 고장 시나리오 행에는 고장이 2건 기록된다
    rows = list(csv.DictReader(io.StringIO(csv_a)))
    fault_rows = [r for r in rows if r["scenario_id"] == "warehouse-fault-a"]
    assert len(fault_rows) == 3
    assert all(r["outages_started"] == "2" and r["invariant_violations"] == "0" for r in fault_rows)
    assert all(r["outages_started"] == "0" for r in rows if r["scenario_id"] == "warehouse-small-a")


def test_batch_rejects_duplicate_scenarios(tmp_path):
    with pytest.raises(ValueError):
        run_batch([SCENARIOS[0], SCENARIOS[0]], [0], tmp_path)


def _rows(path):
    with open(path, encoding="utf-8") as f:
        return sorted(csv.DictReader(f), key=lambda r: (r["scenario_id"], r["policy"], r["structure"], int(r["seed"])))


def test_finalize_interrupted_batch_matches_normal_batch(tmp_path):
    """중단된 배치를 끝난 실행만으로 마무리하면, 정상 배치의 같은 실행 행과 똑같은 표가 나온다."""
    full = run_batch(SCENARIOS, [0, 1, 2], tmp_path / "full", jobs=1)
    cut = tmp_path / "cut" / full.name
    shutil.copytree(full, cut)
    for name in ("batch.json", "batch_summary.csv", "batch_eval.csv"):
        (cut / name).unlink()
    # 끝나지 않은 실행은 실행 폴더 자체가 없다 (폴더는 실행이 끝난 뒤에만 쓰인다)
    gone = next((cut / "runs" / "warehouse-fault-a").glob("*seed2__*"))
    shutil.rmtree(gone)

    finalize_interrupted_batch(cut, planned_seeds=[0, 1, 2], note="test")

    for name in ("batch_summary.csv", "batch_eval.csv"):
        expect = [r for r in _rows(full / name) if not (r["scenario_id"] == "warehouse-fault-a" and r["seed"] == "2")]
        assert _rows(cut / name) == expect
    info = json.loads((cut / "batch.json").read_text(encoding="utf-8"))
    assert info["interrupted"] is True and info["n_runs"] == 5
    assert info["completed_seeds"] == [0, 1, 2] and info["missing_seeds"] == []  # 시드 2 는 다른 시나리오에 남음
    assert info["invariant_violations_total"] == 0 and info["safety_boundary_all_ok"] is True
    with pytest.raises(ValueError):
        finalize_interrupted_batch(cut, planned_seeds=[0, 1, 2], note="again")  # 이미 마무리됨
