"""M5 코드 리뷰에서 고친 동작 (고아 작업 취소, 항목 하나 혼류, 천장에 막힌 옵션, 정규 형식)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from asel.core.actions import Action, ActionKind
from asel.core.model import TaskStatus
from asel.core.world import ENV_ACTOR
from asel.io.scenario import Scenario
from asel.runner import run_scenario
from conftest import create, make_world
from test_job_flow import SPLIT_JOIN, flow_scenario


def cancel(ids):
    return Action(ENV_ACTOR, ActionKind.CANCEL_TASKS, {"tasks": list(ids)})


def test_cancel_rejected_when_it_would_orphan_successors():
    w = make_world()
    w.submit(create("a", duration=10))
    w.submit(create("b", cap="pack", duration=5, preds=["a"]))
    r = w.submit(cancel(["a"]))
    assert not r.accepted and "orphaned" in r.reasons[0]
    assert w.state.tasks["b"].status == TaskStatus.WAITING
    assert w.submit(cancel(["a", "b"])).accepted
    assert w.state.tasks["a"].status == w.state.tasks["b"].status == TaskStatus.CANCELLED


def test_single_item_mix_still_tags_flow():
    d = flow_scenario(SPLIT_JOIN)
    flow = d["workload"].pop("flow")
    d["workload"]["mix"] = [{"weight": 1.0, "flow": {**flow, "instance_prefix": "only"}}]
    res = run_scenario(Scenario.model_validate(d), seed=1)
    tasks = list(res.world.state.tasks.values())
    assert tasks and all(t.tags.get("flow") == "only" for t in tasks)


def _blocked(space: bool) -> dict:
    d = flow_scenario([{"id": "s", "capability": "y", "service_time": {"type": "constant", "value_s": 5}}])
    d["entities"] = [{"id": "a", "type": "cell", "capabilities": ["x"], "capacity": 1,
                      "reconfigurable": {"options": [["x"], ["y"]], "changeover_s": 10}}]
    d["capability_space"] = {"y": {"height_m": 4.0}}
    if space:
        d["entities"][0]["space"] = {"x": 0, "y": 0, "width": 2, "depth": 2, "ceiling_m": 3.0}
    return d


def test_role_only_reachable_through_blocked_option_is_rejected():
    Scenario.model_validate(_blocked(space=False))  # 2D: 전환으로 제공 가능
    with pytest.raises(ValidationError, match="offers capability 'y'"):
        Scenario.model_validate(_blocked(space=True))  # 3D: 천장 3 m < 4 m 라 영원히 제공 불가


def test_canonical_dump_drops_empty_space_in_04():
    d = Scenario.model_validate(flow_scenario(SPLIT_JOIN)).canonical_dump()
    assert all("space" not in e for e in d["entities"])
