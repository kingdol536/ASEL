"""일괄 실행기 (#5)."""

from __future__ import annotations

import json

import pytest

from asel.batch import parse_seeds, run_batch
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
    fault_rows = [l for l in csv_a.splitlines() if l.startswith("warehouse-fault-a,")]
    assert fault_rows and all(",2,0," in l for l in fault_rows)  # outages_started=2, violations=0
