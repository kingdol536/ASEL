"""EXP-003 실행 스크립트 (재현용). 계획서: experiments/plans/EXP-003.md

    uv run python experiments/configs/run_exp003.py <plan_commit> <arm> <env> <seeds> [jobs]

arm : a-free | s-free | a-claude | s-claude-haiku | s-claude-sonnet
env : B | C
seeds: 예) 0-1 (파일럿), 300-329 (평가)

API 팔은 ASEL_LLM_MODE=record 로 실행한다 (실제 호출, 예산 장부 상한 적용).
같은 명령을 replay 로 다시 돌리면 녹화된 응답으로 사건 로그가 바이트 단위로 재현된다:
    ASEL_EXP003_MODE=replay uv run python experiments/configs/run_exp003.py ...

계획서 밖 탐색적 실행은 ASEL_EXP003_PHASE=exploratory 로 따로 둔다 (사전 고정 분석에 섞이지 않음).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from asel.batch import parse_seeds, run_batch

SCEN = {"B": "scenarios/assembly-line-b.yaml", "C": "scenarios/it-service-c.yaml"}
ARMS = {
    "a-free": {"policies": ["fifo", "order-age"], "structures": None},
    "s-free": {"policies": ["fifo"], "structures": ["p0", "p1", "p2"]},
    "a-claude": {"policies": ["claude"], "structures": None},
    "s-claude-haiku": {"policies": ["fifo"], "structures": ["claude-haiku"]},
    "s-claude-sonnet": {"policies": ["fifo"], "structures": ["claude-sonnet"]},
}


SIZING = Path("experiments/reports/assets/EXP-003/sizing.json")


def check_seeds(phase: str, arm: str, env: str, seeds: list[int]) -> None:
    """본 실험(main)은 계획서 §3.3 평가 시드 중 sizing.json 의 N 안에서만 돌린다. 탐색(exploratory)은 제한 없음."""
    if phase == "main":
        allowed = set(range(300, 330))
        if "claude" in arm:
            sized = json.loads(SIZING.read_text(encoding="utf-8"))["arms"].get(f"{arm}-{env}")
            allowed = set(range(300, 300 + (sized["N"] if sized else 0)))
        bad = sorted(set(seeds) - allowed)
        if bad:
            raise SystemExit(f"main 단계에 허용되지 않은 시드 {bad} ({arm}-{env}, 계획서 §3.3·§3.4, sizing.json)")
    elif phase == "pilot":
        if max(seeds) >= 100:
            raise SystemExit("pilot 단계는 개발 시드(100 미만)만 쓴다")
    elif phase != "exploratory":
        raise SystemExit(f"알 수 없는 단계 {phase!r} (pilot | main | exploratory)")


def main() -> None:
    plan, arm, env, seeds = sys.argv[1:5]
    jobs = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    cfg = ARMS[arm]
    if "claude" in arm:
        os.environ["ASEL_LLM_MODE"] = os.environ.get("ASEL_EXP003_MODE", "record")
        os.environ["ASEL_LLM_PROMPT"] = "v2-neutral"  # 배정 팔의 산업 중립 프롬프트 (계획서 §3.2)
        os.environ["ASEL_LLM_MODEL"] = "claude-haiku-5-5"
    # 탐색적 추가 실행(사전 고정 분석 밖)은 ASEL_EXP003_PHASE=exploratory 로 main 과 분리한다
    phase = os.environ.get("ASEL_EXP003_PHASE") or ("pilot" if parse_seeds(seeds)[0] < 100 else "main")
    check_seeds(phase, arm, env, parse_seeds(seeds))
    bd = run_batch(
        [SCEN[env]], parse_seeds(seeds), Path("experiments/batches/EXP-003") / phase / f"{arm}-{env}", jobs=jobs,
        policies=cfg["policies"], structure_policies=cfg["structures"],
        extra_manifest={"experiment": "EXP-003", "plan_commit": plan, "arm": arm, "env": env, "phase": phase},
    )
    info = json.loads((bd / "batch.json").read_text(encoding="utf-8"))
    print(bd)
    print(json.dumps({k: info.get(k) for k in ("n_runs", "throughput", "invariant_violations_total",
                                              "safety_boundary_all_ok")}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
