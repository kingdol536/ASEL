"""명령행 진입점.

    asel run scenarios/warehouse-small-a.yaml [--seed 7] [--out experiments/runs]
    asel replay-check experiments/runs/<scenario>/<run_dir>
    asel compare-logs <run_dir_a> <run_dir_b>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from asel.core.world import replay
from asel.io.eventlog import PRIVATE_LOG, PUBLIC_LOG, dumps_canonical, encode_events, read_run
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run


def _cmd_run(args: argparse.Namespace) -> int:
    sc = load_scenario(args.scenario)
    res = run_scenario(sc, seed=args.seed, check_invariants=not args.no_invariants)
    run_dir = write_run(res, Path(args.out))
    print(f"run_dir: {run_dir}")
    print(json.dumps(res.summary(), indent=2, ensure_ascii=False))
    return 0


def _cmd_replay_check(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    events = read_run(run_dir)
    rebuilt = dumps_canonical(replay(events).snapshot())
    recorded = (run_dir / "final_state.json").read_text(encoding="utf-8").strip()
    if rebuilt == recorded:
        print(f"OK: {len(events)} events replay to the recorded final state")
        return 0
    print("MISMATCH: replayed state differs from final_state.json", file=sys.stderr)
    return 1


def _cmd_compare_logs(args: argparse.Namespace) -> int:
    from asel.compare import compare_logs

    da, db = Path(args.a), Path(args.b)
    ea, eb = read_run(da), read_run(db)
    raw = lambda d: (d / PUBLIC_LOG).read_bytes() + b"\0" + (d / PRIVATE_LOG).read_bytes()
    c = compare_logs(ea, eb, raw(da), raw(db))
    print(json.dumps(c.__dict__, indent=2))
    return 0 if c.logically_equal else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="asel")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a scenario headless")
    r.add_argument("scenario")
    r.add_argument("--seed", type=int, default=None, help="override scenario seed")
    r.add_argument("--out", default="experiments/runs")
    r.add_argument("--no-invariants", action="store_true", help="skip per-step invariant checks")
    r.set_defaults(func=_cmd_run)

    c = sub.add_parser("replay-check", help="rebuild state from events.ndjson and compare")
    c.add_argument("run_dir")
    c.set_defaults(func=_cmd_replay_check)

    m = sub.add_parser("compare-logs", help="compare two run dirs (byte / logical equality)")
    m.add_argument("a")
    m.add_argument("b")
    m.set_defaults(func=_cmd_compare_logs)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
