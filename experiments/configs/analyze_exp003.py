"""EXP-003 사전 고정 분석 (계획서 §5). 본 실험 배치들의 평가표를 합쳐 가설 H1~H6 을 판정한다.

    uv run python experiments/configs/analyze_exp003.py [out.json]
"""

from __future__ import annotations

import csv
import glob
import json
import sys
from pathlib import Path

from asel.evaluation.paired import _num, bootstrap_ci

ROOT = Path("experiments/batches/EXP-003/main")
MAIN = {"assembly-line-b": "flow_mean_s", "it-service-c": "orders_cancelled"}
ENV = {"assembly-line-b": "B", "it-service-c": "C"}
MIN_N = 10


def arm_of(r: dict) -> str:
    return f"S-{r['structure']}" if r["structure"] else f"A-{r['policy']}"


def load() -> tuple[list[dict], dict]:
    rows, excluded = [], {}
    for bd in sorted(glob.glob(str(ROOT / "*" / "batch__*"))):
        bd = Path(bd)
        with open(bd / "batch_eval.csv", encoding="utf-8") as f:
            batch_rows = list(csv.DictReader(f))
        # 예산 부족으로 대체된 판단이 있는 실행은 뺀다 (계획서 §7)
        budget_hit = set()
        for ev_path in glob.glob(str(bd / "runs" / "*" / "*" / "evaluation.json")) + glob.glob(str(bd / "runs" / "*" / "evaluation.json")):
            ev = json.loads(Path(ev_path).read_text(encoding="utf-8"))
            fb = dict(ev.get("fallbacks") or {})
            fb.update((ev.get("structure_control") or {}).get("fallbacks") or {})
            if any(k.startswith("budget_") for k in fb):
                budget_hit.add((ev["scenario_id"], int(ev["seed"]), ev["policy"], ev.get("structure_policy") or ""))
        for r in batch_rows:
            key = (r["scenario_id"], int(r["seed"]), r["policy"], r["structure"])
            if key in budget_hit:
                excluded.setdefault(arm_of(r), []).append(key)
                continue
            r["arm"] = arm_of(r)
            rows.append(r)
    return rows, excluded


def paired(rows, scen, metric, a, b):
    by = {(r["arm"], int(r["seed"])): _num(r[metric]) for r in rows if r["scenario_id"] == scen}
    seeds = sorted({s for (arm, s) in by if arm == a} & {s for (arm, s) in by if arm == b})
    pairs = [(by[(a, s)], by[(b, s)]) for s in seeds if by[(a, s)] is not None and by[(b, s)] is not None]
    if not pairs:
        return {"n": 0}
    diffs = [vb - va for va, vb in pairs]
    lo, hi = bootstrap_ci(diffs) if len(diffs) > 1 else (diffs[0], diffs[0])
    return {"n": len(diffs), "a": a, "b": b, "metric": metric, "mean_a": sum(v for v, _ in pairs) / len(pairs),
            "mean_b": sum(v for _, v in pairs) / len(pairs), "mean_diff": sum(diffs) / len(diffs),
            "ci95": [lo, hi], "min_diff": min(diffs), "max_diff": max(diffs)}


def rate(rows, scen, arm, num_col, den_col):
    """시드 합산 비율. num_col 이 비율 열이면 den_col 로 가중한다."""
    num = den = 0.0
    for r in rows:
        if r["scenario_id"] == scen and r["arm"] == arm:
            n, d = _num(r[num_col]), _num(r[den_col])
            if n is not None and d:
                num += n * d
                den += d
    return num / den if den else None


def verdict(cmp, rule, margin=None):
    if cmp.get("n", 0) < MIN_N:
        return "판정 불가 (N<10)"
    lo, hi = cmp["ci95"]
    if rule == "lower":
        return "지지" if hi < 0 else "반증"
    if rule == "noninferior":
        return "지지" if hi <= margin else "반증"
    raise ValueError(rule)


def fallback_rate(rows, scen, arm, structure=False):
    if not structure:
        return rate(rows, scen, arm, "fallback_rate", "policy_decisions")
    # 구조 제어: 실행별 대체 비율의 평균 (재생 실행에서도 같은 값이 나오도록 호출 수로 가중하지 않음)
    vals = [_num(r["s_fallback_rate"]) for r in rows if r["scenario_id"] == scen and r["arm"] == arm]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def main() -> None:
    rows, excluded = load()
    out = {"excluded_budget_runs": {k: len(v) for k, v in excluded.items()}, "hypotheses": {}, "arms": {}}
    for scen in MAIN:
        for arm in sorted({r["arm"] for r in rows if r["scenario_id"] == scen}):
            rs = [r for r in rows if r["scenario_id"] == scen and r["arm"] == arm]
            out["arms"][f"{ENV[scen]}:{arm}"] = {
                "n": len(rs),
                **{m: sum(_num(r[m]) or 0 for r in rs) / len(rs) for m in
                   ("flow_mean_s", "orders_cancelled", "completion_rate", "flow_p95_s", "reconf_completed",
                    "lost_capacity_s", "bottleneck_shifts")},
                "usd_total": sum((_num(r["usd_estimate"]) or 0) + (_num(r["s_usd_estimate"]) or 0) for r in rs),
                "boundary_all_ok": all(r["boundary_ok"] == "True" for r in rs),
            }
    h = out["hypotheses"]
    # H1 배정 타당성
    for scen in MAIN:
        inv = rate(rows, scen, "A-claude", "invalid_proposal_rate", "proposals")
        fb = fallback_rate(rows, scen, "A-claude")
        n = sum(1 for r in rows if r["scenario_id"] == scen and r["arm"] == "A-claude")
        ok = inv is not None and inv < 0.01 and fb is not None and fb < 0.05
        h[f"H1-{ENV[scen]}"] = {"n": n, "invalid_rate": inv, "fallback_rate": fb,
                                "verdict": ("판정 불가 (N<10)" if n < MIN_N else ("지지" if ok else "반증"))}
    # H2 배정 비열등
    for scen, m in MAIN.items():
        c = paired(rows, scen, m, "A-fifo", "A-claude")
        fb = fallback_rate(rows, scen, "A-claude")
        v = verdict(c, "noninferior", 0.10 * c["mean_a"]) if c.get("n") else "판정 불가 (N<10)"
        if fb is not None and fb > 0.05:
            v = "판정 불가 (대체 > 5%)"
        h[f"H2-{ENV[scen]}"] = {**c, "margin": 0.10 * c.get("mean_a", 0), "verdict": v}
    sfb = {s: fallback_rate(rows, s, a, True) for s in MAIN for a in ("S-claude-haiku",)}
    # H3 / H4 (C)
    c3 = paired(rows, "it-service-c", "orders_cancelled", "S-p1", "S-claude-haiku")
    h["H3"] = {**c3, "verdict": verdict(c3, "lower") if c3.get("n") else "판정 불가 (N<10)"}
    c4 = paired(rows, "it-service-c", "orders_cancelled", "S-p0", "S-claude-haiku")
    h["H4"] = {**c4, "margin": 0.10 * c4.get("mean_a", 0),
               "verdict": verdict(c4, "noninferior", 0.10 * c4["mean_a"]) if c4.get("n") else "판정 불가 (N<10)"}
    # H5 (B)
    c5 = paired(rows, "assembly-line-b", "flow_mean_s", "S-p0", "S-claude-haiku")
    h["H5"] = {**c5, "verdict": verdict(c5, "lower") if c5.get("n") else "판정 불가 (N<10)"}
    for k, s in (("H3", "it-service-c"), ("H4", "it-service-c"), ("H5", "assembly-line-b")):
        h[k]["structure_fallback_rate"] = sfb[s]
        if sfb[s] is not None and sfb[s] > 0.05:
            h[k]["verdict"] = "판정 불가 (대체 > 5%)"
    # H6 모델 크기
    h6 = {}
    for scen, m in MAIN.items():
        c = paired(rows, scen, m, "S-claude-haiku", "S-claude-sonnet")
        h6[ENV[scen]] = {**c, "verdict": verdict(c, "lower") if c.get("n") else "판정 불가 (N<10)",
                         "sonnet_fallback_rate": fallback_rate(rows, scen, "S-claude-sonnet", True)}
    vs = [x["verdict"] for x in h6.values()]
    h["H6"] = {"by_env": h6, "verdict": "지지" if "지지" in vs else ("판정 불가" if all("불가" in v for v in vs) else "반증")}
    # 탐색적: P2 와의 비교, 보조 지표
    out["exploratory"] = {
        f"{ENV[s]}:{a}-vs-{b}:{m}": paired(rows, s, m, a, b)
        for s in MAIN for (a, b) in (("S-p2", "S-claude-haiku"), ("S-p0", "S-p1"), ("S-p0", "S-claude-sonnet"),
                                     ("A-order-age", "A-claude"))
        for m in ("flow_mean_s", "orders_cancelled", "completion_rate")
    }
    text = json.dumps(out, indent=2, ensure_ascii=False, default=float)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
