"""EXP-003 표본 크기 규칙 (계획서 §3.4) 을 파일럿 결과에 기계적으로 적용한다.

    uv run python experiments/configs/size_exp003.py <jobs> <deadline_utc ISO> [out.json]
"""

from __future__ import annotations

import csv
import glob
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

from asel.agents.claude_policy import default_llm_dir

PILOT = Path("experiments/batches/EXP-003/pilot")
CAP, MARGIN, SAFETY = 55.0, 3.0, 1.2
PRIORITY = [("s-claude-haiku", "B"), ("s-claude-haiku", "C"), ("a-claude", "B"), ("a-claude", "C"),
            ("s-claude-sonnet", "B"), ("s-claude-sonnet", "C")]


def pilot_stats(arm: str, env: str) -> dict:
    bds = sorted(glob.glob(str(PILOT / f"{arm}-{env}" / "batch__*")))
    bd = Path(bds[-1])
    rows = list(csv.DictReader(open(bd / "batch_eval.csv", encoding="utf-8")))
    info = json.loads((bd / "batch.json").read_text(encoding="utf-8"))
    usd = [float(r["usd_estimate"] or 0) + float(r["s_usd_estimate"] or 0) for r in rows]
    wall = info["throughput"]["wall_s"]
    return {"batch": bd.name, "n": len(rows), "usd_per_run": sum(usd) / len(usd),
            "wall_s_per_run": wall * info["jobs"] / len(rows)}  # 한 작업자 기준 실행당 시간


def main() -> None:
    jobs = int(sys.argv[1])
    deadline = datetime.fromisoformat(sys.argv[2])
    ledger = json.loads((default_llm_dir() / "ledger.json").read_text(encoding="utf-8"))
    spent = ledger["usd_spent"] + ledger.get("usd_reserved", 0.0)
    remaining = CAP - spent - MARGIN
    now = datetime.now(UTC)
    time_left_s = (deadline - now).total_seconds() * jobs  # 작업자-초
    plan, out = {}, {"ledger_spent_after_pilot": spent, "budget_R": remaining, "jobs": jobs,
                     "deadline_utc": deadline.isoformat(), "computed_utc": now.isoformat(timespec="seconds")}
    for arm, env in PRIORITY:
        st = pilot_stats(arm, env)
        c = st["usd_per_run"]
        n = 30 if c <= 0 else min(30, math.floor(remaining / (SAFETY * c)))
        n = max(n, 0)
        remaining -= n * SAFETY * c
        plan[f"{arm}-{env}"] = {**st, "N": n}
    # 시간 제한: 넘으면 낮은 우선순위부터 줄인다
    need = sum(p["N"] * p["wall_s_per_run"] for p in plan.values())
    for key in reversed(list(plan)):
        if need <= time_left_s:
            break
        p = plan[key]
        cut = min(p["N"], math.ceil((need - time_left_s) / p["wall_s_per_run"]))
        p["N"] -= cut
        need -= cut * p["wall_s_per_run"]
        p["time_cut"] = cut
    for p in plan.values():
        p["status"] = "skip (N<3)" if p["N"] < 3 else ("descriptive only (N<10)" if p["N"] < 10 else "confirmatory")
        p["seeds"] = f"300-{300 + p['N'] - 1}" if p["N"] >= 3 else None
    out["arms"] = plan
    out["budget_left_after_plan"] = remaining
    out["worker_seconds_needed"] = need
    out["worker_seconds_available"] = time_left_s
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).parent.mkdir(parents=True, exist_ok=True)
        Path(sys.argv[3]).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
