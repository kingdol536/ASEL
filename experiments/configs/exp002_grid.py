"""EXP-002 격자 시나리오 생성기 (계획서와 같은 커밋에 고정).

기준: scenarios/warehouse-reconfig-dev.yaml (개발 시나리오)
축:   급증 배율 {1.5, 2, 3} × 전환 시간 {30, 120, 300}s  → 9개 시나리오
급증 구간 1200~2400s 의 도착률 = 기본 1.5건/분 × 배율. 나머지 설정은 개발 시나리오와 같다.

    uv run python experiments/configs/exp002_grid.py   # scenarios/exp002/*.yaml 생성
"""

from __future__ import annotations

from pathlib import Path

import yaml

from asel.io.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "scenarios" / "warehouse-reconfig-dev.yaml"
OUT = ROOT / "scenarios" / "exp002"
SURGE = (1.5, 2.0, 3.0)
CHANGEOVER = (30, 120, 300)


def grid() -> list[Scenario]:
    base = load_scenario(BASE).model_dump(mode="json")
    out = []
    for m in SURGE:
        for co in CHANGEOVER:
            d = yaml.safe_load(yaml.safe_dump(base))
            d["scenario_id"] = f"exp002-s{str(m).replace('.', 'p')}-c{co}"
            d["notes"] = f"EXP-002 grid: surge x{m} in 1200-2400s, changeover {co}s (virtual values)"
            segs = d["workload"]["arrival_process"]["segments"]
            segs[1]["rate_per_min"] = 1.5 * m
            for e in d["entities"]:
                if e.get("reconfigurable"):
                    e["reconfigurable"]["changeover_s"] = co
            out.append(Scenario.model_validate(d))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for sc in grid():
        text = "# 생성 파일 — experiments/configs/exp002_grid.py 로 만든다. 직접 고치지 않는다.\n"
        text += yaml.safe_dump(sc.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
        (OUT / f"{sc.scenario_id}.yaml").write_text(text, encoding="utf-8", newline="\n")
        print(sc.scenario_id, sc.config_hash()[:8])


if __name__ == "__main__":
    main()
