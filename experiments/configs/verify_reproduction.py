"""기록된 실험을 지금 코드로 다시 실행해 사건 로그가 바이트 단위로 같은지 확인한다 (#35).

    uv run python experiments/configs/verify_reproduction.py experiments/batches/EXP-001-main/batch__*  [...]

- 각 실행 폴더의 manifest(시나리오 id·시드·정책·구조 정책)로 같은 조건을 다시 실행한다.
- Claude 정책은 replay 모드(저장된 응답만, API 호출 없음)로 실행한다.
- 공개·비공개 로그 해시를 manifest 의 기록과 비교한다.
"""

from __future__ import annotations

import glob
import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _scenario_paths() -> dict[str, Path]:
    from asel.io.scenario import load_scenario

    out = {}
    for p in list((ROOT / "scenarios").glob("*.yaml")) + list((ROOT / "scenarios").glob("*/*.yaml")):
        out[load_scenario(p).scenario_id] = p
    return out


def _check(run_dir: str) -> tuple[str, bool, str]:
    from asel.io.eventlog import encode_private, encode_public
    from asel.io.scenario import load_scenario
    from asel.runner import run_scenario

    m = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    paths = _scenario_paths()
    sc = load_scenario(paths[m["scenario_id"]])
    pol_name = m["policy"]["name"]
    if pol_name == "claude":
        from asel.agents.claude_policy import ClaudePolicy

        pol = ClaudePolicy(mode="replay", prompt_version=m["policy"]["usage"].get("prompt_version", "v1-warehouse"))
    else:
        pol = pol_name
    struct = (m.get("structure_policy") or {}).get("name")
    res = run_scenario(sc, seed=m["seed"], policy=pol, structure_policy=struct)
    pub = hashlib.sha256(encode_public(res.events)).hexdigest()
    priv = hashlib.sha256(encode_private(res.events)).hexdigest()
    ok = pub == m["events_sha256"] and priv == m["private_events_sha256"] and res.run_id == m["run_id"]
    why = "" if ok else f"run_id {res.run_id} vs {m['run_id']}; pub {pub[:8]} vs {m['events_sha256'][:8]}"
    return run_dir, ok, why


def main() -> None:
    dirs = []
    for b in sys.argv[1:]:
        dirs += sorted(glob.glob(str(Path(b) / "runs" / "*" / "*")))
    with ProcessPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(_check, dirs))
    bad = [r for r in results if not r[1]]
    print(json.dumps({"checked": len(results), "identical": len(results) - len(bad),
                      "mismatches": [f"{Path(d).name}: {w}" for d, _, w in bad[:10]]}, indent=2, ensure_ascii=False))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
