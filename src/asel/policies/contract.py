"""정책 연결 규약 (티켓 #9, docs/04 §3~4).

    세계 상태 --project()--> Observation (허가된 공개 필드만, 화이트리스트)
                               |
                         affordances()  허용 행동과 후보
                               |
    PolicyAdapter.decide(obs, affordances) -> [ActionProposal]
                               |
    PolicyRuntime: actor_id 를 정책이 아니라 런타임이 붙이고 Action 으로 바꿔 World.submit 으로

정책은 World·WorldState·시나리오에 접근하지 않는다. 관측에는 실제 처리 시간,
미래 도착, 고장 원인·계획 종료 시각이 없다. 관측은 상태 객체를 참조하지 않는
순수 JSON 값(dict/list/str/수)으로만 만든다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from asel.core.actions import Action, ActionKind
from asel.core.model import EntityMode, TaskStatus, WorldState, roles_over_ceiling

OPEN_STATUSES = (TaskStatus.WAITING, TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.BLOCKED)


@dataclass(frozen=True)
class Observation:
    actor_id: str
    sim_time: float
    world_version: int
    cells: tuple[dict, ...]
    relations: tuple[dict, ...]
    open_tasks: tuple[dict, ...]
    completed_tasks: int
    structure_version: int | None = None  # 재구성 가능한 셀이 있는 세계에서만 채운다
    objective: dict | None = None  # 현재 운영 목표 (공개). 목표가 정해진 세계에서만

    def to_dict(self) -> dict:
        d = {
            "actor_id": self.actor_id,
            "sim_time": self.sim_time,
            "world_version": self.world_version,
            "cells": list(self.cells),
            "relations": list(self.relations),
            "open_tasks": list(self.open_tasks),
            "completed_tasks": self.completed_tasks,
        }
        if self.structure_version is not None:
            d["structure_version"] = self.structure_version
        if self.objective is not None:
            d["objective"] = self.objective
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class ActionSpec:
    """허용된 행동 종류와, 관측에서 계산한 유효 후보 (검증 통과를 보장하지는 않는다)."""

    kind: str
    description: str
    candidates: tuple[dict, ...] = ()

    def to_dict(self) -> dict:
        return {"kind": self.kind, "description": self.description, "candidates": list(self.candidates)}


@dataclass(frozen=True)
class ActionProposal:
    action_type: str
    params: dict
    reason: str | None = None


@dataclass(frozen=True)
class PolicyContext:
    """reset 때 정책에 주는 정보. 시나리오·시드·숨겨진 값은 넣지 않는다."""

    actor_id: str
    run_id: str
    permitted_actions: tuple[str, ...]


class PolicyAdapter(Protocol):
    name: str

    def reset(self, context: PolicyContext) -> None: ...

    def decide(self, observation: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]: ...

    def usage(self) -> dict:
        """manifest 에 남길 사용량(호출 수·토큰·비용 등). 없으면 빈 dict."""
        ...


# --------------------------------------------------------------------------- 투영


def _cell(state: WorldState, e) -> dict:
    res = state.resources.get(e.id)
    normal = e.mode == EntityMode.NORMAL
    d = {
        "id": e.id,
        "type": e.type,
        "capabilities": list(e.capabilities),
        "capacity": res.capacity if res else 0,
        "reserved": res.reserved if res else 0,
        "out_of_service": res.out_of_service if res else 0,
        # 새 작업에 쓸 수 있는 용량: 재구성 중(비우는 중·전환 중)이면 0
        "available": max(res.available, 0) if (res and normal) else 0,
    }
    if e.reconfig is not None:
        # 재구성 가능한 셀에만 붙인다 (재구성이 없는 세계의 관측은 M3 와 바이트 단위로 같게 유지)
        d["mode"] = e.mode
        d["target_capabilities"] = list(e.target_capabilities) if e.target_capabilities else None
        d["mode_since"] = e.mode_since
        d["reconfig"] = {"options": [list(o) for o in e.reconfig["options"]],
                         "changeover_s": e.reconfig["changeover_s"]}
    if e.space is not None:
        d["ceiling_m"] = e.space["ceiling_m"]
        # 이 셀이 가질 수 있는 역할 중 천장 높이를 넘는 것 (공개 설계 정보)
        d["blocked_roles"] = roles_over_ceiling(
            e.space, state.capability_space, {x for o in (e.reconfig or {}).get("options", []) for x in o}
        )
    return d


def project(state: WorldState, actor_id: str) -> Observation:
    """화이트리스트 투영: 여기 적은 필드만 관측에 들어간다."""
    cells = tuple(_cell(state, e) for e in sorted(state.entities.values(), key=lambda e: e.id))
    any_reconfig = any(e.reconfig is not None for e in state.entities.values())
    relations = tuple({"source": r.source, "target": r.target, "kind": r.kind} for r in state.relations)
    open_tasks = tuple(
        {
            "id": t.id,
            "capability": t.capability,
            "status": str(t.status),
            "order": t.tags.get("order"),
            **({"flow": t.tags["flow"]} if "flow" in t.tags else {}),  # 혼류에서만 (이전 관측 형식 유지)
            "step": t.tags.get("step"),
            "predecessors": list(t.predecessors),
            "created_at": t.created_at,
            "created_index": t.created_index,
            "ready_at": t.ready_at,
            "started_at": t.started_at,
            "assigned_entity": t.assigned_entity,
        }
        for t in sorted(state.tasks.values(), key=lambda t: t.created_index)
        if t.status in OPEN_STATUSES
    )
    completed = sum(1 for t in state.tasks.values() if t.status == TaskStatus.COMPLETED)
    return Observation(actor_id, state.sim_time, state.version, cells, relations, open_tasks, completed,
                       state.structure_version if any_reconfig else None,
                       dict(state.objective) if state.objective is not None else None)


def offered_after(cells: tuple[dict, ...], override: tuple[str, list[str]] | None = None) -> set[str]:
    """관측만으로 계산한 '전환이 끝났을 때 제공될 capability' (World.offered_capabilities 와 같은 규칙)."""
    out: set[str] = set()
    for c in cells:
        if c["capacity"] <= 0:
            continue
        caps = c["capabilities"]
        if c.get("mode", "normal") != "normal" and c.get("target_capabilities"):
            caps = c["target_capabilities"]
        if override and c["id"] == override[0]:
            caps = override[1]
        out.update(caps)
    return out


def affordances(obs: Observation, permitted: tuple[str, ...]) -> list[ActionSpec]:
    out: list[ActionSpec] = []
    if ActionKind.START_TASK in permitted:
        free = [c for c in obs.cells if c["available"] > 0]
        cands = tuple(
            {"task": t["id"], "entity": c["id"]}
            for t in obs.open_tasks
            if t["status"] == "READY"
            for c in free
            if t["capability"] in c["capabilities"]
        )
        out.append(
            ActionSpec(
                ActionKind.START_TASK,
                "READY 작업 하나를 해당 capability 가 있고 여유가 있는 셀에서 시작한다. "
                "셀 하나의 여유 용량을 넘겨 배정하면 거절된다.",
                cands,
            )
        )
    if ActionKind.REQUEST_RECONFIGURATION in permitted:
        base = offered_after(obs.cells)
        cands = []
        for c in obs.cells:
            if c.get("reconfig") is None or c.get("mode") != "normal":
                continue
            for opt in c["reconfig"]["options"]:
                target = sorted(opt)
                if target == sorted(c["capabilities"]):
                    continue
                if base - offered_after(obs.cells, (c["id"], target)):
                    continue  # 마지막 제공 셀을 없애는 전환은 후보에서 뺀다 (검증기도 거절)
                if set(target) & set(c.get("blocked_roles", [])):
                    continue  # 3D 높이 제약으로 불가능한 전환 (검증기도 거절)
                cands.append({"entity": c["id"], "capabilities": target})
        out.append(
            ActionSpec(
                ActionKind.REQUEST_RECONFIGURATION,
                "셀의 역할(capability)을 바꾼다. 셀은 새 작업을 받지 않다가, 진행 작업이 끝나면 "
                "changeover_s 동안 멈춘 뒤 새 역할이 된다. 취소할 수 없다.",
                tuple(cands),
            )
        )
    return out


# --------------------------------------------------------------------------- 런타임


@dataclass
class PolicyRuntime:
    """정책을 시뮬레이터의 배정기 자리에 끼운다 (Simulator 의 Dispatcher 규약 구현).

    - 결정 시점: 같은 시각 사건 처리 후. 유효 후보가 하나도 없으면 정책을 부르지 않는다.
    - actor_id 는 런타임이 붙인다. 정책이 다른 주체를 사칭할 수 없다.
    - 한 번의 결정에서 나온 제안들은 같은 관측 버전에서 계산된 것이다. 첫 제안에 그 버전을
      expected_version 으로 붙여, 관측 이후 세계가 바뀌었으면 거절되게 한다. 이어지는 제안은
      같은 결정의 일부이므로 버전 검사를 하지 않는다 (단일 스레드라 그 사이 다른 변경이 없다).
    """

    policy: Any
    actor_id: str
    permitted: tuple[str, ...] = (ActionKind.START_TASK,)
    decisions: int = 0
    skipped_no_candidates: int = 0
    _reset_done: bool = field(default=False, repr=False)

    def reset(self, run_id: str) -> None:
        self.policy.reset(PolicyContext(self.actor_id, run_id, self.permitted))
        self._reset_done = True

    def propose(self, state: WorldState) -> list[Action]:
        obs = project(state, self.actor_id)
        aff = affordances(obs, self.permitted)
        if not any(spec.candidates for spec in aff):
            self.skipped_no_candidates += 1
            return []
        self.decisions += 1
        proposals = self.policy.decide(obs, aff)
        actions = []
        for i, p in enumerate(proposals):
            params = dict(p.params) if isinstance(p.params, dict) else {"_invalid": True}
            actions.append(
                Action(
                    self.actor_id,
                    p.action_type,
                    params,
                    expected_version=obs.world_version if i == 0 else None,
                    reason=p.reason,
                )
            )
        return actions

    def usage(self) -> dict:
        u = dict(self.policy.usage() or {})
        u.update({"decisions": self.decisions, "skipped_no_candidates": self.skipped_no_candidates})
        return u
