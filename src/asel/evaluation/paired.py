"""정책 간 대응 비교 (EXP-001 §6, 사전 고정 분석).

같은 시나리오·시드끼리 짝을 지어 (B - A) 차이를 구하고, 평균 차이의 부트스트랩 95% 신뢰구간을 낸다.
재표본 10,000회, 난수 시드 고정(재현 가능). 지표를 하나의 점수로 합치지 않는다.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

N_BOOT = 10_000
BOOT_SEED = 20261111


def _num(x):
    if x in (None, "", "None"):
        return None
    if x in ("True", "False"):
        return 1.0 if x == "True" else 0.0
    return float(x)


def bootstrap_ci(diffs: list[float], n_boot: int = N_BOOT, seed: int = BOOT_SEED) -> tuple[float, float]:
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def paired_compare(rows: list[dict], metric: str, a: str, b: str) -> list[dict]:
    """rows: batch_eval.csv 행. 시나리오별로 (B - A) 대응 차이를 요약한다."""
    by = {}
    for r in rows:
        by[(r["scenario_id"], r["policy"], int(r["seed"]))] = _num(r[metric])
    out = []
    for scen in sorted({k[0] for k in by}):
        seeds = sorted({k[2] for k in by if k[0] == scen})
        diffs, missing = [], 0
        for s in seeds:
            va, vb = by.get((scen, a, s)), by.get((scen, b, s))
            if va is None or vb is None:
                missing += 1
                continue
            diffs.append(vb - va)
        if not diffs:
            out.append({"scenario_id": scen, "metric": metric, "a": a, "b": b, "n_pairs": 0, "missing": missing})
            continue
        lo, hi = bootstrap_ci(diffs) if len(diffs) > 1 else (diffs[0], diffs[0])
        out.append({
            "scenario_id": scen, "metric": metric, "a": a, "b": b, "n_pairs": len(diffs), "missing": missing,
            "mean_diff": sum(diffs) / len(diffs), "ci95_low": lo, "ci95_high": hi,
            "min_diff": min(diffs), "max_diff": max(diffs),
            "ci_excludes_zero": (lo > 0 or hi < 0) if len(diffs) > 1 else None,
        })
    return out


def load_eval_rows(batch_dir: Path) -> list[dict]:
    with open(batch_dir / "batch_eval.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))
