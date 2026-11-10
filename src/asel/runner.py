"""headless 실행: scenario + seed -> 이벤트 로그 / 최종 상태 / manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from asel.core.actions import ActionKind
from asel.core.events import SCHEMA_VERSION, Event, EventType
from asel.core.invariants import check_invariants
from asel.core.simulator import Simulator
from asel.core.world import ENV_ACTOR, World
from asel.domains.warehouse import OrderArrivals, world_init_payload
from asel.io.eventlog import dumps_canonical, events_sha256, write_ndjson
from asel.io.manifest import code_revision, environment_info
from asel.io.scenario import Scenario
from asel.policies.fifo import FifoDispatcher

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RunResult:
    run_id: str
    scenario: Scenario
    seed: int
    world: World
    started_utc: str
    finished_utc: str

    @property
    def events(self) -> list[Event]:
        return self.world.log

    def summary(self) -> dict:
        """단순 집계(평가 지표 아님). 평가는 M3 의 독립 평가기 몫이다."""
        st = self.world.state
        by_status: dict[str, int] = {}
        for t in st.tasks.values():
            by_status[str(t.status)] = by_status.get(str(t.status), 0) + 1
        etypes: dict[str, int] = {}
        for e in self.events:
            etypes[e.event_type] = etypes.get(e.event_type, 0) + 1
        return {
            "sim_time_end": st.sim_time,
            "world_version": st.version,
            "events": len(self.events),
            "event_types": dict(sorted(etypes.items())),
            "tasks_by_status": dict(sorted(by_status.items())),
            "actions_rejected": etypes.get(EventType.ACTION_REJECTED, 0),
            "invariant_violations": len(check_invariants(st)),
        }


def make_run_id(sc: Scenario, seed: int) -> str:
    return f"{sc.scenario_id}__seed{seed}__cfg{sc.config_hash()[:8]}"


def run_scenario(sc: Scenario, seed: int | None = None, check_invariants: bool = True) -> RunResult:
    seed = sc.seed if seed is None else seed
    run_id = make_run_id(sc, seed)
    started = datetime.now(UTC).isoformat(timespec="seconds")

    dispatcher = FifoDispatcher()
    world = World(
        run_id,
        grants={
            ENV_ACTOR: {ActionKind.CREATE_TASK, ActionKind.COMPLETE_TASK},
            dispatcher.actor_id: {ActionKind.START_TASK},
        },
    )
    world.initialize(*world_init_payload(sc))
    sim = Simulator(world, OrderArrivals(sc, seed), dispatcher, check_invariants=check_invariants)
    sim.run(until=sc.sim_time_limit)

    finished = datetime.now(UTC).isoformat(timespec="seconds")
    return RunResult(run_id, sc, seed, world, started, finished)


def write_run(res: RunResult, out_root: Path) -> Path:
    stamp = datetime.fromisoformat(res.started_utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_root / res.scenario.scenario_id / f"{res.run_id}__{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    events_hash = write_ndjson(res.events, run_dir / "events.ndjson")
    (run_dir / "final_state.json").write_text(
        dumps_canonical(res.world.state.snapshot()) + "\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "scenario.json").write_text(
        dumps_canonical(res.scenario.model_dump(mode="json")) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "run_id": res.run_id,
        "scenario_id": res.scenario.scenario_id,
        "seed": res.seed,
        "config_hash": res.scenario.config_hash(),
        "event_schema_version": SCHEMA_VERSION,
        "scenario_schema_version": res.scenario.schema_version,
        "events_sha256": events_hash,
        "code": code_revision(REPO_ROOT),
        "environment": environment_info(),
        "policy": {"dispatcher": "dispatcher.fifo", "version": "0.1"},
        "evaluator": None,  # M3 에서 도입
        "started_utc": res.started_utc,
        "finished_utc": res.finished_utc,
        "summary": res.summary(),
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return run_dir


def check_events_hash(res: RunResult) -> str:
    return events_sha256(res.events)
