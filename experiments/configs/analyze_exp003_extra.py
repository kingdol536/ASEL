"""EXP-003 탐색적 분석 (사전 고정 밖, 결과를 본 뒤 추가). 가설 판정에 쓰지 않는다.

    uv run python experiments/configs/analyze_exp003_extra.py [out.json]

1. C 배정 팔을 A-claude 가 끝낸 같은 시드(300~314)로 맞춘 기술 통계
2. C 실패 기전: app-2 가 app 역할을 못 하는 구간(비우기·전환·worker 역할)에 취소가 몰리는가, 역할 되돌리기 횟수
3. Sonnet C 탐색 실행(시드 300~309) 대 Haiku·P0·P1 (N=10, H6 판정에 쓰지 않음)
4. 팔별 비용·호출 수·실행 시간
5. Claude 구조 제어의 판단 이유 예시
모두 공개 로그(events.ndjson)·평가표·manifest 만 읽는다.
"""

from __future__ import annotations

import csv
import glob
import json
import sys
from datetime import datetime
from pathlib import Path

from asel.evaluation.paired import _num, bootstrap_ci

BASE = Path("experiments/batches/EXP-003")
SEEDS_C_DISPATCH = list(range(300, 315))
SEEDS_SONNET = list(range(300, 310))


def _eval_rows(phase: str, arm_dir: str) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(BASE / phase / arm_dir / "batch__*" / "batch_eval.csv"))):
        with open(f, encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def _label(r: dict) -> str:
    return f"S-{r['structure']}" if r["structure"] else f"A-{r['policy']}"


def _by_seed(rows: list[dict], label: str, metric: str) -> dict[int, float]:
    return {int(r["seed"]): _num(r[metric]) for r in rows if _label(r) == label}


def _paired(a: dict[int, float], b: dict[int, float], seeds: list[int]) -> dict:
    s = [x for x in seeds if x in a and x in b and a[x] is not None and b[x] is not None]
    d = [b[x] - a[x] for x in s]
    lo, hi = bootstrap_ci(d) if len(d) > 1 else (None, None)
    return {"n": len(d), "mean_a": sum(a[x] for x in s) / len(s), "mean_b": sum(b[x] for x in s) / len(s),
            "mean_diff": sum(d) / len(d), "ci95": [lo, hi], "b_better_seeds": sum(1 for v in d if v < 0)}


def matched_c_dispatch() -> dict:
    rows = _eval_rows("main", "a-free-C") + _eval_rows("main", "a-claude-C")
    out = {}
    for label in ("A-fifo", "A-order-age", "A-claude"):
        rs = [r for r in rows if _label(r) == label and int(r["seed"]) in SEEDS_C_DISPATCH]
        out[label] = {"n": len(rs), **{m: sum(_num(r[m]) for r in rs) / len(rs)
                                       for m in ("orders_cancelled", "flow_mean_s", "completion_rate", "flow_p95_s")}}
    return {"seeds": "300-314", "arms": out}


def _role_timeline(events_path: Path, cell: str = "app-2") -> tuple[list[tuple[float, float]], dict, float]:
    """cell 이 app 을 제공하지 않는 구간 목록, 전환 통계, 실행 종료 시각."""
    gaps, start, role, n_sw, n_back, prev_roles = [], None, None, 0, 0, []
    cancelled_at: dict[str, float] = {}
    t_end = 0.0
    with open(events_path, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            et, t = e["event_type"], e["sim_time"]
            t_end = max(t_end, t)
            if et == "WorldInitialized":
                caps = next(x["capabilities"] for x in e["payload"]["entities"] if x["id"] == cell)
                role = tuple(caps)
            elif et == "ReconfigurationRequested" and e["entity_id"] == cell:
                if role == ("app",) and start is None:
                    start = t  # 새 app 작업을 받지 않기 시작
                n_sw += 1
                new = tuple(e["payload"]["capabilities"])
                if prev_roles and new == prev_roles[-1]:
                    n_back += 1
                prev_roles.append(role)
            elif et == "ReconfigurationCompleted" and e["entity_id"] == cell:
                role = tuple(e["payload"]["capabilities"])
                if role == ("app",) and start is not None:
                    gaps.append((start, t))
                    start = None
            elif et == "TaskStateChanged" and e["payload"].get("to") == "CANCELLED":
                order = e["entity_id"].split("/")[0]
                cancelled_at.setdefault(order, t)
    if start is not None:
        gaps.append((start, t_end))
    return gaps, {"switches": n_sw, "reversals": n_back, "cancelled_at": cancelled_at}, t_end


def c_mechanism() -> dict:
    out = {}
    for phase, arm_dir, label in (("main", "s-free-C", "S-p0"), ("main", "s-free-C", "S-p1"),
                                  ("main", "s-free-C", "S-p2"), ("main", "s-claude-haiku-C", "S-claude-haiku"),
                                  ("exploratory", "s-claude-sonnet-C", "S-claude-sonnet")):
        struct = label[2:]
        runs = sorted(glob.glob(str(BASE / phase / arm_dir / "batch__*" / "runs" / "*" / f"*fifo+{struct}__*")))
        tot = {"runs": 0, "switches": 0, "reversals": 0, "cancelled": 0, "cancelled_in_gap": 0,
               "gap_s": 0.0, "run_s": 0.0}
        for d in runs:
            gaps, st, t_end = _role_timeline(Path(d) / "events.ndjson")
            tot["runs"] += 1
            tot["switches"] += st["switches"]
            tot["reversals"] += st["reversals"]
            tot["cancelled"] += len(st["cancelled_at"])
            tot["cancelled_in_gap"] += sum(1 for t in st["cancelled_at"].values() if any(a <= t < b for a, b in gaps))
            tot["gap_s"] += sum(b - a for a, b in gaps)
            tot["run_s"] += t_end
        n = tot["runs"] or 1
        gap_share = tot["gap_s"] / tot["run_s"] if tot["run_s"] else 0.0
        in_gap = tot["cancelled_in_gap"] / tot["cancelled"] if tot["cancelled"] else 0.0
        out[label] = {
            "runs": tot["runs"], "switches_per_run": tot["switches"] / n, "reversals_per_run": tot["reversals"] / n,
            "cancelled_per_run": tot["cancelled"] / n,
            "app2_not_serving_app_time_share": gap_share,
            "cancellations_in_that_time_share": in_gap,
            "concentration": (in_gap / gap_share) if gap_share else None,
        }
    return out


def sonnet_exploratory() -> dict:
    rows = (_eval_rows("main", "s-free-C") + _eval_rows("main", "s-claude-haiku-C")
            + _eval_rows("exploratory", "s-claude-sonnet-C"))
    m = "orders_cancelled"
    son = _by_seed(rows, "S-claude-sonnet", m)
    out = {"seeds": "300-309", "note": "탐색적 (사전 고정 밖, N=10). H6 판정에 쓰지 않는다."}
    for base in ("S-claude-haiku", "S-p0", "S-p1"):
        out[f"{base}-vs-S-claude-sonnet:{m}"] = _paired(_by_seed(rows, base, m), son, SEEDS_SONNET)
    sf = [_num(r["s_fallback_rate"]) for r in rows if _label(r) == "S-claude-sonnet"]
    si = [_num(r["s_invalid_rate"]) for r in rows if _label(r) == "S-claude-sonnet"]
    out["sonnet_fallback_rate_mean"] = sum(sf) / len(sf)
    out["sonnet_invalid_rate_mean"] = sum(si) / len(si)
    return out


def _run_seconds(batch: Path) -> float | None:
    """실행 1회의 평균 소요 시간 (manifest 의 시작·종료 시각). 병렬 배치의 '벽시계 ÷ 실행 수'와 다르다."""
    ds = []
    for mp in batch.glob("runs/*/*/manifest.json"):
        m = json.loads(mp.read_text(encoding="utf-8"))
        ds.append((datetime.fromisoformat(m["finished_utc"]) - datetime.fromisoformat(m["started_utc"])).total_seconds())
    return sum(ds) / len(ds) if ds else None


def costs() -> dict:
    out = {}
    for phase in ("pilot", "main", "exploratory"):
        for bd in sorted(glob.glob(str(BASE / phase / "*" / "batch__*"))):
            bd = Path(bd)
            arm = bd.parent.name
            if "claude" not in arm:
                continue
            with open(bd / "batch_eval.csv", encoding="utf-8") as fh:
                rs = list(csv.DictReader(fh))
            usd = sum((_num(r["usd_estimate"]) or 0) + (_num(r["s_usd_estimate"]) or 0) for r in rs)
            calls = sum((_num(r["api_calls"]) or 0) + (_num(r["s_api_calls"]) or 0) for r in rs)
            lat = sum(_num(r["latency_ms_total"]) or 0 for r in rs)
            sec = _run_seconds(bd)
            out[f"{phase}/{arm}"] = {
                "runs": len(rs), "usd": round(usd, 4), "usd_per_run": round(usd / len(rs), 4),
                "api_calls": int(calls), "calls_per_run": round(calls / len(rs), 1),
                "dispatch_latency_ms_per_call": round(lat / calls, 1) if lat and calls else None,
                "run_s_mean": round(sec, 1) if sec else None,
            }
    return out


def reasons(n_runs: int = 2, per_run: int = 2) -> dict:
    out = {}
    for env, arm_dir in (("B", "s-claude-haiku-B"), ("C", "s-claude-haiku-C")):
        ex = []
        for d in sorted(glob.glob(str(BASE / "main" / arm_dir / "batch__*" / "runs" / "*" / "*")))[:n_runs]:
            k = 0
            with open(Path(d) / "events.ndjson", encoding="utf-8") as f:
                for line in f:
                    e = json.loads(line)
                    if e["event_type"] == "ActionProposed" and e["actor_id"].startswith("structure.claude"):
                        a = e["payload"]["action"]
                        ex.append({"seed": int(d.split("__seed")[1].split("__")[0]), "sim_time": round(e["sim_time"], 1),
                                   "switch": f"{a['params']['entity']} -> {'/'.join(a['params']['capabilities'])}",
                                   "reason": a["reason"]})
                        k += 1
                        if k >= per_run:
                            break
        out[env] = ex
    return out


def main() -> None:
    out = {
        "note": "탐색적 분석 (사전 고정 밖). 가설 판정은 analysis.json 만 쓴다.",
        "matched_c_dispatch": matched_c_dispatch(),
        "c_mechanism": c_mechanism(),
        "sonnet_c": sonnet_exploratory(),
        "costs": costs(),
        "reason_examples": reasons(),
    }
    text = json.dumps(out, indent=2, ensure_ascii=False, default=float)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
