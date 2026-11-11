from __future__ import annotations

from pathlib import Path

import pytest

from asel.core.actions import Action, ActionKind
from asel.core.world import ENV_ACTOR, World
from asel.io.scenario import load_scenario

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_A = ROOT / "scenarios" / "warehouse-small-a.yaml"

DISPATCHER = "dispatcher.test"
GRANTS = {
    ENV_ACTOR: {
        ActionKind.CREATE_TASK,
        ActionKind.COMPLETE_TASK,
        ActionKind.BEGIN_OUTAGE,
        ActionKind.END_OUTAGE,
        ActionKind.CANCEL_TASKS,
        ActionKind.SET_OBJECTIVE,
    },
    DISPATCHER: {ActionKind.START_TASK},
}


def make_world(cells: list[tuple[str, list[str], int]] | None = None) -> World:
    cells = cells or [("pick-1", ["pick"], 1), ("pack-1", ["pack"], 1)]
    w = World("test-run", GRANTS)
    w.initialize(
        entities=[{"id": c, "type": "workstation", "capabilities": caps} for c, caps, _ in cells],
        relations=[],
        resources=[{"id": c, "capacity": cap} for c, _, cap in cells],
    )
    return w


def create(tid: str, cap: str = "pick", duration: float = 10.0, preds=()) -> Action:
    return Action(
        ENV_ACTOR,
        ActionKind.CREATE_TASK,
        {"id": tid, "capability": cap, "predecessors": list(preds)},
        private={"duration": duration},
    )


def start(tid: str, entity: str, actor: str = DISPATCHER, expected_version=None) -> Action:
    return Action(actor, ActionKind.START_TASK, {"task": tid, "entity": entity}, expected_version)


def complete(tid: str) -> Action:
    return Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": tid})


@pytest.fixture
def scenario_a():
    return load_scenario(SCENARIO_A)
