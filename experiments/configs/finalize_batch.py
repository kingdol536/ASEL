"""중간에 멈춘 배치를 끝난 실행만으로 마무리한다 (시뮬레이션·API 호출 없음).

    uv run python experiments/configs/finalize_batch.py <batch_dir> <계획 시드> "<중단 사유>"

EXP-003 A-claude C (계획 300-316, 사용자 지시로 15회에서 중단)에 썼다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from asel.batch import finalize_interrupted_batch, parse_seeds


def main() -> None:
    bd, seeds, note = Path(sys.argv[1]), parse_seeds(sys.argv[2]), sys.argv[3]
    finalize_interrupted_batch(bd, planned_seeds=seeds, note=note)
    info = json.loads((bd / "batch.json").read_text(encoding="utf-8"))
    print(json.dumps({k: info[k] for k in ("n_runs", "completed_seeds", "missing_seeds", "invariant_violations_total",
                                          "safety_boundary_all_ok")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
