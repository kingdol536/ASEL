"""EXP-002 실행 스크립트 (재현용). 계획서 커밋 해시를 manifest 에 남긴다.

    uv run python experiments/configs/run_exp002.py <plan_commit>
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

from asel.batch import parse_seeds, run_batch


def main() -> None:
    plan = sys.argv[1]
    scen = sorted(glob.glob("scenarios/exp002/*.yaml"))
    bd = run_batch(
        scen, parse_seeds("200-229"), Path("experiments/batches/EXP-002"), jobs=6,
        policies=["fifo"], structure_policies=["p0", "p1", "p2"],
        extra_manifest={"experiment": "EXP-002", "plan_commit": plan, "status": "provisional until user approval"},
    )
    info = json.loads((bd / "batch.json").read_text(encoding="utf-8"))
    print(bd)
    print(json.dumps({k: info[k] for k in ("n_runs", "throughput", "invariant_violations_total",
                                          "safety_boundary_all_ok", "code")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
