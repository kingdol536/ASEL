"""기록된 실험을 지금 코드로 다시 실행해 사건 로그가 바이트 단위로 같은지 대조한다 (M6 #50).

원자료(배치 폴더) 없이도 된다: 저장소에 커밋된 실행 목록(runs_index.csv)만 있으면 된다.

    # 실행 목록 만들기 (원자료가 있는 사람만, 실험 직후 1회)
    uv run python experiments/configs/reproduce.py index EXP-003 experiments/batches/EXP-003/main/*/batch__*

    # 재현 (누구나). Claude 실행은 녹화된 응답 캐시가 필요하다 → README '재현' 절 참고
    uv run python experiments/configs/reproduce.py check EXP-001 EXP-002 EXP-003 [--sample 20] [--jobs 6]

Claude 실행은 replay(저장된 응답만, API 호출 0)로 다시 돌린다. 캐시 폴더는 ASEL_LLM_DIR 로 지정한다.
캐시가 없으면 Claude 실행은 건너뛰고 그 수를 따로 보고한다 (실패로 세지 않는다).
"""

from __future__ import annotations

import csv
import functools
import glob
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "experiments" / "reports" / "assets"
INDEX_DIR = {"EXP-001": ASSETS / "M3", "EXP-002": ASSETS / "M4", "EXP-003": ASSETS / "EXP-003"}
COLS = ["run_id", "scenario_id", "seed", "policy", "prompt_version", "model", "structure", "events_sha256",
        "private_events_sha256"]
# 재현은 항상 녹화된 응답만 쓴다. 환경에 record 가 남아 있어도 유료 호출이 나가지 않게 덮어쓴다
os.environ["ASEL_LLM_MODE"] = "replay"


def _uses_claude(row: dict) -> bool:
    return row["policy"] == "claude" or row["structure"].startswith("claude")


def make_index(exp: str, batch_dirs: list[str]) -> Path:
    rows = []
    for b in batch_dirs:
        for d in sorted(glob.glob(str(Path(b) / "runs" / "*" / "*"))):
            m = json.loads((Path(d) / "manifest.json").read_text(encoding="utf-8"))
            rows.append({
                "run_id": m["run_id"], "scenario_id": m["scenario_id"], "seed": m["seed"],
                "policy": m["policy"]["name"],
                "prompt_version": (m["policy"].get("usage") or {}).get("prompt_version", ""),
                "model": (m["policy"].get("usage") or {}).get("model", ""),
                "structure": (m.get("structure_policy") or {}).get("name") or "",
                "events_sha256": m["events_sha256"], "private_events_sha256": m["private_events_sha256"],
            })
    rows.sort(key=lambda r: r["run_id"])
    out = INDEX_DIR[exp] / "runs_index.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return out


@functools.lru_cache(maxsize=1)
def _scenario_paths() -> dict[str, Path]:
    from asel.io.scenario import load_scenario

    out = {}
    for p in sorted((ROOT / "scenarios").glob("*.yaml")) + sorted((ROOT / "scenarios").glob("*/*.yaml")):
        out[load_scenario(p).scenario_id] = p
    return out


def _check(row: dict) -> tuple[str, bool, str]:
    from asel.io.eventlog import encode_private, encode_public
    from asel.io.scenario import load_scenario
    from asel.runner import run_scenario

    sc = load_scenario(_scenario_paths()[row["scenario_id"]])
    pol = row["policy"]
    if pol == "claude":
        from asel.agents.claude_policy import ClaudePolicy

        kw = {"model": row["model"]} if row.get("model") else {}  # 옛 실행 목록에는 모델 열이 없다 → 기본 모델
        pol = ClaudePolicy(mode="replay", prompt_version=row["prompt_version"] or "v1-warehouse", **kw)
    res = run_scenario(sc, seed=int(row["seed"]), policy=pol, structure_policy=row["structure"] or None)
    pub = hashlib.sha256(encode_public(res.events)).hexdigest()
    priv = hashlib.sha256(encode_private(res.events)).hexdigest()
    ok = res.run_id == row["run_id"] and pub == row["events_sha256"] and priv == row["private_events_sha256"]
    return row["run_id"], ok, "" if ok else f"run_id={res.run_id} pub={pub[:10]} expected {row['events_sha256'][:10]}"


def _cache_available() -> bool:
    from asel.agents.claude_policy import default_llm_dir

    d = default_llm_dir() / "cache"
    return d.is_dir() and any(d.iterdir())


def check(exps: list[str], sample: int | None, jobs: int) -> int:
    rows = []
    for exp in exps:
        with open(INDEX_DIR[exp] / "runs_index.csv", encoding="utf-8") as f:
            exp_rows = list(csv.DictReader(f))
        if sample:
            # 시나리오·정책·구조 조합마다 앞에서부터 고르게 뽑는다 (결정적)
            groups: dict[tuple, list] = {}
            for r in exp_rows:
                groups.setdefault((r["scenario_id"], r["policy"], r["structure"]), []).append(r)
            per = max(1, sample // max(len(groups), 1))
            exp_rows = [r for g in groups.values() for r in sorted(g, key=lambda r: int(r["seed"]))[:per]]
        rows += [(exp, r) for r in exp_rows]
    has_cache = _cache_available()
    todo = [(e, r) for e, r in rows if has_cache or not _uses_claude(r)]
    skipped = len(rows) - len(todo)
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        results = list(ex.map(_check, [r for _, r in todo]))
    bad = [x for x in results if not x[1]]
    by_exp: dict[str, dict] = {}
    for (e, _), (_, ok, _) in zip(todo, results):
        s = by_exp.setdefault(e, {"checked": 0, "identical": 0})
        s["checked"] += 1
        s["identical"] += ok
    print(json.dumps({"by_experiment": by_exp, "checked": len(results), "identical": len(results) - len(bad),
                      "skipped_claude_runs_without_cache": skipped,
                      "mismatches": [f"{rid}: {why}" for rid, _, why in bad[:10]]}, indent=2, ensure_ascii=False))
    return 1 if bad else 0


def main() -> None:
    cmd = sys.argv[1]
    if cmd == "index":
        print(make_index(sys.argv[2], sys.argv[3:]))
        return
    args, sample, jobs = [], None, 6
    it = iter(sys.argv[2:])
    for a in it:
        if a == "--sample":
            sample = int(next(it))
        elif a == "--jobs":
            jobs = int(next(it))
        else:
            args.append(a)
    sys.exit(check(args or list(INDEX_DIR), sample, jobs))


if __name__ == "__main__":
    main()
