from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from asel.cli import main
from asel.core.world import ReducerError
from asel.io.scenario import Scenario
from conftest import SCENARIO_A


def _base(**over):
    d = {
        "schema_version": "0.1",
        "scenario_id": "t",
        "domain": "warehouse_like",
        "seed": 1,
        "sim_time_limit": 100,
        "entities": [{"id": "a", "type": "workstation", "capabilities": ["pick"], "capacity": 1}],
        "workload": {
            "arrival_process": {"type": "poisson", "rate_per_min": 1},
            "job_template": [{"capability": "pick", "service_time": {"type": "constant", "value_s": 5}}],
        },
    }
    d.update(over)
    return d


def test_valid_base():
    Scenario.model_validate(_base())


@pytest.mark.parametrize(
    "over",
    [
        {"schema_version": "9.9"},
        {"entities": [{"id": "a", "type": "w", "capabilities": ["pick"], "capacity": -1}]},
        {"relations": [{"source": "a", "target": "nope", "kind": "flow"}]},
        {"unknown_field": 1},
        {"sim_time_limit": 0},
        {
            "workload": {
                "arrival_process": {"type": "poisson", "rate_per_min": 1},
                "job_template": [{"capability": "weld", "service_time": {"type": "constant", "value_s": 5}}],
            }
        },
    ],
)
def test_invalid_scenarios_rejected(over):
    with pytest.raises(ValidationError):
        Scenario.model_validate(_base(**over))


def test_config_hash_ignores_seed_only():
    a = Scenario.model_validate(_base(seed=1))
    b = Scenario.model_validate(_base(seed=2))
    c = Scenario.model_validate(_base(sim_time_limit=200))
    assert a.config_hash() == b.config_hash() != c.config_hash()


def test_cli_run_and_replay_check(tmp_path, capsys):
    assert main(["run", str(SCENARIO_A), "--seed", "5", "--out", str(tmp_path)]) == 0
    run_dirs = list((tmp_path / "warehouse-small-a").iterdir())
    assert len(run_dirs) == 1
    d = run_dirs[0]
    for name in ("events.ndjson", "final_state.json", "manifest.json", "scenario.json"):
        assert (d / name).is_file()
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    for key in ("run_id", "seed", "config_hash", "events_sha256", "code", "environment", "summary"):
        assert key in m
    assert m["seed"] == 5
    assert m["summary"]["invariant_violations"] == 0

    assert main(["replay-check", str(d)]) == 0

    # 로그 변조 1: 처리 시간 값을 바꾸면 재생은 되지만 기록된 최종 상태와 달라야 한다
    path = d / "events.ndjson"
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    idx = next(i for i, l in enumerate(lines) if '"TaskCreated"' in l)
    ev = json.loads(lines[idx])
    ev["payload"]["duration"] += 1.0
    lines[idx] = json.dumps(ev)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["replay-check", str(d)]) == 1

    # 로그 변조 2: 작업 생성 이벤트를 지우면 이후 이벤트를 적용할 수 없다
    lines = original.splitlines()
    del lines[idx]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ReducerError):
        main(["replay-check", str(d)])
