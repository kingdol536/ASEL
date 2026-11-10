"""일괄 실행기: 시나리오 × 시드 N 개 (티켓 #5).

결과 폴더:
    <out>/<batch_id>/runs/<scenario_id>/<run_dir>/   실행별 로그·manifest
    <out>/<batch_id>/batch_summary.csv              실행별 단순 집계 (시각 필드 없음 -> 같은 입력이면 동일)
    <out>/<batch_id>/batch.json                     배치 정보 + 처리량(runs/min, events/s) 측정

집계 열은 상태별 작업 수 같은 단순 개수다. 평가 지표가 아니다 (지표는 EXP-001 승인 후 평가기에서).
"""

from __future__ import annotations

import csv
import io
import json
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from asel.io.manifest import code_revision, environment_info
from asel.io.scenario import load_scenario
from asel.runner import REPO_ROOT, run_scenario, write_run

COLUMNS = [
    "scenario_id",
    "seed",
    "run_id",
    "events",
    "world_version",
    "tasks_completed",
    "tasks_running",
    "tasks_ready",
    "tasks_waiting",
    "actions_rejected",
    "outages_started",
    "invariant_violations",
    "events_sha256",
    "private_events_sha256",
]


def parse_seeds(spec: str) -> list[int]:
    """'1-30', '1,2,5', '0-4,10' 형식. 시드는 0 이상의 정수."""
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            lo, hi = int(a), int(b)
            if hi < lo:
                raise ValueError(f"bad seed range {part!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError("no seeds")
    if min(out) < 0:
        raise ValueError("seeds must be >= 0")
    if len(set(out)) != len(out):
        raise ValueError("duplicate seeds")
    return out


def _one(args: tuple[str, int, str, bool]) -> tuple[dict, float, int]:
    scenario_path, seed, runs_root, check = args
    sc = load_scenario(scenario_path)
    t0 = time.perf_counter()
    res = run_scenario(sc, seed=seed, check_invariants=check)
    sim_s = time.perf_counter() - t0
    run_dir = write_run(res, Path(runs_root))
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    s = m["summary"]
    by = s["tasks_by_status"]
    row = {
        "scenario_id": sc.scenario_id,
        "seed": seed,
        "run_id": res.run_id,
        "events": s["events"],
        "world_version": s["world_version"],
        "tasks_completed": by.get("COMPLETED", 0),
        "tasks_running": by.get("RUNNING", 0),
        "tasks_ready": by.get("READY", 0),
        "tasks_waiting": by.get("WAITING", 0),
        "actions_rejected": s["actions_rejected"],
        "outages_started": s["event_types"].get("ResourceOutageStarted", 0),
        "invariant_violations": s["invariant_violations"],
        "events_sha256": m["events_sha256"],
        "private_events_sha256": m["private_events_sha256"],
    }
    return row, sim_s, s["events"]


def summary_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def run_batch(
    scenario_paths: list[str],
    seeds: list[int],
    out_root: Path,
    jobs: int = 1,
    check_invariants: bool = True,
) -> Path:
    started = datetime.now(UTC)
    batch_id = "batch__" + started.strftime("%Y%m%dT%H%M%S%fZ")
    batch_dir = out_root / batch_id
    runs_root = batch_dir / "runs"
    runs_root.mkdir(parents=True, exist_ok=False)

    scenarios = [load_scenario(p) for p in scenario_paths]
    tasks = [(str(p), seed, str(runs_root), check_invariants) for p in scenario_paths for seed in seeds]

    t0 = time.perf_counter()
    if jobs <= 1:
        results = [_one(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(_one, tasks))  # 입력 순서 유지
    wall_s = time.perf_counter() - t0

    rows = [r for r, _, _ in results]
    (batch_dir / "batch_summary.csv").write_text(summary_csv(rows), encoding="utf-8", newline="\n")

    total_events = sum(n for _, _, n in results)
    sim_s = sum(s for _, s, _ in results)
    info = {
        "batch_id": batch_id,
        "started_utc": started.isoformat(timespec="seconds"),
        "scenarios": [
            {"scenario_id": sc.scenario_id, "path": str(p), "config_hash": sc.config_hash()}
            for sc, p in zip(scenarios, scenario_paths)
        ],
        "seeds": seeds,
        "n_runs": len(rows),
        "jobs": jobs,
        "check_invariants": check_invariants,
        "throughput": {
            "wall_s": round(wall_s, 3),
            "runs_per_min": round(len(rows) / wall_s * 60, 2) if wall_s > 0 else None,
            "events_per_s_wall": round(total_events / wall_s, 1) if wall_s > 0 else None,
            "simulate_s_sum": round(sim_s, 3),
            "note": "wall_s 는 로그·manifest 쓰기와 git 조회를 포함한다. simulate_s_sum 은 시뮬레이션만.",
        },
        "invariant_violations_total": sum(r["invariant_violations"] for r in rows),
        "code": code_revision(REPO_ROOT),
        "environment": environment_info(),
    }
    (batch_dir / "batch.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return batch_dir
