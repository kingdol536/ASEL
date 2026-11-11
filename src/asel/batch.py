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

from asel.evaluation.evaluator import EVAL_COLUMNS, eval_row, write_evaluation
from asel.io.manifest import code_revision, environment_info
from asel.io.scenario import load_scenario
from asel.runner import REPO_ROOT, run_scenario, write_run_detailed

COLUMNS = [
    "scenario_id",
    "policy",
    "structure",
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


def _summary_row(m: dict) -> dict:
    """실행 manifest 로 batch_summary.csv 한 행을 만든다 (실행 직후와 중단된 배치 마무리에서 같은 값)."""
    s = m["summary"]
    by = s["tasks_by_status"]
    return {
        "scenario_id": m["scenario_id"],
        "policy": m["policy"]["name"],
        "structure": (m.get("structure_policy") or {}).get("name") or "",
        "seed": m["seed"],
        "run_id": m["run_id"],
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


def _one(args: tuple) -> tuple[dict, float, int, dict]:
    scenario_path, seed, runs_root, check, code, policy, structure, extra = args
    sc = load_scenario(scenario_path)
    t0 = time.perf_counter()
    res = run_scenario(sc, seed=seed, check_invariants=check, policy=policy, structure_policy=structure)
    sim_s = time.perf_counter() - t0
    run_dir, m = write_run_detailed(res, Path(runs_root), code=code, extra=extra)
    ev = write_evaluation(run_dir)  # 실행이 끝난 뒤 평가 (정책은 평가 결과를 보지 않는다)
    return _summary_row(m), sim_s, m["summary"]["events"], eval_row(ev)


def summary_csv(rows: list[dict], columns: list[str] = COLUMNS) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def reevaluate_batch(batch_dir: Path) -> Path:
    """기존 배치의 실행들을 현재 평가기로 다시 평가해 batch_eval.csv 를 새로 쓴다 (시뮬레이션은 다시 하지 않음).
    행 순서는 batch_summary.csv 를 따른다."""
    with open(batch_dir / "batch_summary.csv", encoding="utf-8") as f:
        order = [(r["scenario_id"], r["run_id"]) for r in csv.DictReader(f)]
    rows = []
    for scenario_id, run_id in order:
        matches = sorted((batch_dir / "runs" / scenario_id).glob(f"{run_id}__*"))
        if len(matches) != 1:
            raise ValueError(f"expected one run dir for {run_id}, found {len(matches)}")
        rows.append(eval_row(write_evaluation(matches[0])))
    out = batch_dir / "batch_eval.csv"
    out.write_text(summary_csv(rows, EVAL_COLUMNS), encoding="utf-8", newline="\n")
    return out


def finalize_interrupted_batch(batch_dir: Path, planned_seeds: list[int], note: str) -> Path:
    """중간에 멈춘 배치(batch.json 없음)를 끝난 실행만으로 마무리한다. 시뮬레이션은 다시 하지 않는다.

    실행 폴더는 실행이 끝난 뒤에만 쓰이므로 manifest.json 이 있는 실행만 끝난 것으로 본다.
    행 순서: (scenario_id, policy, structure, seed). batch.json 에 중단 사실과 빠진 시드를 남긴다.
    """
    if (batch_dir / "batch.json").exists():
        raise ValueError(f"{batch_dir} already has batch.json (not interrupted)")
    run_dirs = [p.parent for p in (batch_dir / "runs").glob("*/*/manifest.json")]
    if not run_dirs:
        raise ValueError(f"no finished runs in {batch_dir}")
    done = []
    for d in run_dirs:
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        done.append((_summary_row(m), d, m))
    done.sort(key=lambda x: (x[0]["scenario_id"], x[0]["policy"], x[0]["structure"], x[0]["seed"]))
    rows = [r for r, _, _ in done]
    eval_rows = [eval_row(write_evaluation(d)) for _, d, _ in done]
    (batch_dir / "batch_summary.csv").write_text(summary_csv(rows), encoding="utf-8", newline="\n")
    (batch_dir / "batch_eval.csv").write_text(summary_csv(eval_rows, EVAL_COLUMNS), encoding="utf-8", newline="\n")

    codes = {json.dumps(m["code"], sort_keys=True) for _, _, m in done}
    if len(codes) != 1:
        raise ValueError(f"runs in {batch_dir} come from different code revisions")
    completed = sorted({r["seed"] for r in rows})
    first = done[0][2]
    info = {
        "batch_id": batch_dir.name,
        "interrupted": True,
        "note": note,
        "planned_seeds": planned_seeds,
        "completed_seeds": completed,
        "missing_seeds": sorted(set(planned_seeds) - set(completed)),
        "scenarios": sorted({r["scenario_id"] for r in rows}),
        "policies": sorted({r["policy"] for r in rows}),
        "structure_policies": sorted({r["structure"] or "" for r in rows}),
        "extra": first.get("extra"),
        "n_runs": len(rows),
        "throughput": None,
        "invariant_violations_total": sum(r["invariant_violations"] for r in rows),
        "safety_boundary_all_ok": all(e["boundary_ok"] for e in eval_rows),
        "code": first["code"],
        "environment": first.get("environment"),
    }
    (batch_dir / "batch.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return batch_dir


def run_batch(
    scenario_paths: list[str],
    seeds: list[int],
    out_root: Path,
    jobs: int = 1,
    check_invariants: bool = True,
    policies: list[str] | None = None,
    structure_policies: list[str | None] | None = None,
    extra_manifest: dict | None = None,
) -> Path:
    """policies: 등록된 정책 이름 목록. 정책마다 같은 시나리오·시드로 실행한다 (대응 비교)."""
    policies = policies or ["fifo"]
    structure_policies = structure_policies or [None]
    if len(set(policies)) != len(policies) or len(set(structure_policies)) != len(structure_policies):
        raise ValueError("duplicate policies")
    # claude 정책도 병렬 가능: 예산 장부는 잠금 안에서 예약·정산하고, 응답 캐시는 먼저 기록한 응답이 이긴다 (#19)
    resolved = [str(Path(p).resolve()) for p in scenario_paths]
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate scenario paths")
    scenarios = [load_scenario(p) for p in scenario_paths]
    ids = [(sc.scenario_id, sc.config_hash()) for sc in scenarios]
    if len(set(ids)) != len(ids):
        raise ValueError("two scenario files have the same scenario_id and config (run ids would collide)")

    started = datetime.now(UTC)
    batch_id = "batch__" + started.strftime("%Y%m%dT%H%M%S%fZ")
    batch_dir = out_root / batch_id
    runs_root = batch_dir / "runs"
    runs_root.mkdir(parents=True, exist_ok=False)

    code = code_revision(REPO_ROOT)  # 배치 동안 코드는 바뀌지 않는다
    tasks = [
        (str(p), seed, str(runs_root), check_invariants, code, pol, spol, extra_manifest)
        for p in scenario_paths
        for pol in policies
        for spol in structure_policies
        for seed in seeds
    ]

    t0 = time.perf_counter()
    if jobs <= 1:
        results = [_one(t) for t in tasks]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(_one, tasks))  # 입력 순서 유지
    wall_s = time.perf_counter() - t0

    rows = [r for r, _, _, _ in results]
    (batch_dir / "batch_summary.csv").write_text(summary_csv(rows), encoding="utf-8", newline="\n")
    eval_rows = [e for _, _, _, e in results]
    (batch_dir / "batch_eval.csv").write_text(summary_csv(eval_rows, EVAL_COLUMNS), encoding="utf-8", newline="\n")

    total_events = sum(n for _, _, n, _ in results)
    sim_s = sum(s for _, s, _, _ in results)
    info = {
        "batch_id": batch_id,
        "started_utc": started.isoformat(timespec="seconds"),
        "scenarios": [
            {"scenario_id": sc.scenario_id, "path": str(p), "config_hash": sc.config_hash()}
            for sc, p in zip(scenarios, scenario_paths)
        ],
        "seeds": seeds,
        "policies": policies,
        "structure_policies": structure_policies,
        "extra": extra_manifest,
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
        "safety_boundary_all_ok": all(e["boundary_ok"] for e in eval_rows),
        "code": code,
        "environment": environment_info(),
    }
    (batch_dir / "batch.json").write_text(
        json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return batch_dir
