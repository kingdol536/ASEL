"""세계 상태의 유일한 변경 지점.

흐름: submit(action) -> ActionProposed 기록 -> validate -> (거절) ActionRejected
                                                   -> (승인) 효과 이벤트 계산 -> reducer 로 적용

상태는 `apply_event` reducer 를 통해서만 바뀐다. 재생(replay)도 같은 reducer 를 쓰므로
이벤트 로그만으로 같은 상태를 다시 만들 수 있다.

원자성: 효과 이벤트는 상태를 건드리기 전에 모두 계산한다. 검증을 통과한 효과를
reducer 가 적용하다 실패하면 그것은 코어 버그이므로 예외로 실행을 중단한다
(부분 적용을 성공으로 보고하지 않는다).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from asel.core.actions import KNOWN_ACTION_KINDS, Action, ActionKind, ActionResult
from asel.core.events import Event, EventType
from asel.core.model import (
    Entity,
    EntityMode,
    Relation,
    Resource,
    Task,
    TaskStatus,
    WorldState,
    is_allowed_transition,
)

ENV_ACTOR = "env"


class ReducerError(RuntimeError):
    """검증된 이벤트를 적용할 수 없음 = 코어 버그 또는 손상된 로그."""


# ---------------------------------------------------------------------------
# Reducer: 이벤트 -> 상태 변경. World 와 replay 가 공유한다.
# ---------------------------------------------------------------------------


def apply_event(state: WorldState, ev: Event) -> None:
    if ev.sim_time < state.sim_time:
        raise ReducerError(f"time went backwards: {ev.sim_time} < {state.sim_time}")
    if ev.world_version < state.version:
        raise ReducerError(f"version went backwards: {ev.world_version} < {state.version}")

    p = ev.payload
    et = ev.event_type

    if et == EventType.WORLD_INITIALIZED:
        if state.entities or state.tasks:
            raise ReducerError("world already initialized")
        for e in p["entities"]:
            state.entities[e["id"]] = Entity(
                id=e["id"],
                type=e["type"],
                capabilities=tuple(e["capabilities"]),
                properties=dict(e.get("properties", {})),
                reconfig=e.get("reconfig"),
            )
        for r in p["relations"]:
            state.relations.append(Relation(source=r["source"], target=r["target"], kind=r["kind"]))
        for r in p["resources"]:
            state.resources[r["id"]] = Resource(id=r["id"], capacity=int(r["capacity"]))

    elif et == EventType.TASK_CREATED:
        tid = ev.entity_id
        if tid in state.tasks:
            raise ReducerError(f"duplicate task {tid}")
        state.tasks[tid] = Task(
            id=tid,
            capability=p["capability"],
            duration=float(ev.private["duration"]) if "duration" in ev.private else None,
            predecessors=tuple(p["predecessors"]),
            status=TaskStatus.CREATED,
            created_index=int(p["created_index"]),
            created_at=ev.sim_time,
            tags=dict(p.get("tags", {})),
        )

    elif et == EventType.TASK_STATE_CHANGED:
        task = state.tasks.get(ev.entity_id)
        if task is None:
            raise ReducerError(f"unknown task {ev.entity_id}")
        src, dst = TaskStatus(p["from"]), TaskStatus(p["to"])
        if task.status != src:
            raise ReducerError(f"task {task.id} is {task.status}, event says {src}")
        if not is_allowed_transition(src, dst):
            raise ReducerError(f"illegal transition {src}->{dst} for {task.id}")
        task.status = dst
        if dst == TaskStatus.READY:
            task.ready_at = ev.sim_time
        elif dst == TaskStatus.RUNNING:
            task.started_at = ev.sim_time
            task.assigned_entity = p["entity"]
        elif dst == TaskStatus.COMPLETED:
            task.completed_at = ev.sim_time

    elif et == EventType.RESOURCE_RESERVED:
        res = state.resources.get(ev.entity_id)
        if res is None:
            raise ReducerError(f"unknown resource {ev.entity_id}")
        if res.available <= 0:
            raise ReducerError(f"resource {res.id} over capacity")
        if p["task"] in res.holders:
            raise ReducerError(f"double reservation {p['task']} on {res.id}")
        res.holders.append(p["task"])

    elif et == EventType.RESOURCE_RELEASED:
        res = state.resources.get(ev.entity_id)
        if res is None or p["task"] not in res.holders:
            raise ReducerError(f"release of non-held reservation {p.get('task')} on {ev.entity_id}")
        res.holders.remove(p["task"])

    elif et == EventType.RESOURCE_OUTAGE_STARTED:
        res = state.resources.get(ev.entity_id)
        if res is None or res.out_of_service + p["units"] > res.capacity:
            raise ReducerError(f"invalid outage start on {ev.entity_id}")
        res.out_of_service += p["units"]

    elif et == EventType.RESOURCE_OUTAGE_ENDED:
        res = state.resources.get(ev.entity_id)
        if res is None or p["units"] > res.out_of_service:
            raise ReducerError(f"invalid outage end on {ev.entity_id}")
        res.out_of_service -= p["units"]

    elif et == EventType.RECONFIGURATION_REQUESTED:
        ent = state.entities.get(ev.entity_id)
        if ent is None or ent.mode != EntityMode.NORMAL or ent.reconfig is None:
            raise ReducerError(f"invalid reconfiguration request on {ev.entity_id}")
        ent.mode = EntityMode.DRAINING
        ent.target_capabilities = tuple(p["capabilities"])
        ent.mode_since = ev.sim_time

    elif et == EventType.RECONFIGURATION_STARTED:
        ent = state.entities.get(ev.entity_id)
        res = state.resources.get(ev.entity_id)
        if ent is None or ent.mode != EntityMode.DRAINING or (res is not None and res.holders):
            raise ReducerError(f"invalid reconfiguration start on {ev.entity_id}")
        ent.mode = EntityMode.CHANGEOVER
        ent.mode_since = ev.sim_time

    elif et == EventType.RECONFIGURATION_COMPLETED:
        ent = state.entities.get(ev.entity_id)
        if ent is None or ent.mode != EntityMode.CHANGEOVER:
            raise ReducerError(f"invalid reconfiguration completion on {ev.entity_id}")
        if tuple(p["capabilities"]) != ent.target_capabilities:
            raise ReducerError(f"completion capabilities differ from request on {ev.entity_id}")
        ent.capabilities = ent.target_capabilities
        ent.target_capabilities = None
        ent.mode = EntityMode.NORMAL
        ent.mode_since = ev.sim_time
        state.structure_version += 1

    elif et in (EventType.ACTION_PROPOSED, EventType.ACTION_REJECTED, EventType.RUN_ENDED):
        pass  # 상태 변경 없음 (시각만 갱신)

    else:
        raise ReducerError(f"unknown event type {et}")

    state.sim_time = ev.sim_time
    state.version = ev.world_version


def _as_id(x: object) -> str | None:
    return x if isinstance(x, str) else None


def replay(events: Iterable[Event]) -> WorldState:
    """이벤트 로그만으로 상태를 재구성한다."""
    state = WorldState()
    for ev in events:
        apply_event(state, ev)
    return state


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


class World:
    def __init__(self, run_id: str, grants: Mapping[str, Iterable[str]]):
        """grants: actor_id -> 허용 action kind 집합 (최소 권한 표, 잠정)."""
        self.run_id = run_id
        self.grants = {a: frozenset(k) for a, k in grants.items()}
        self.state = WorldState()
        self.log: list[Event] = []
        self._seq = 0
        self._next_created_index = 0
        self._successors: dict[str, list[str]] = {}  # 파생 인덱스(상태 아님)
        self._initialized = False

    # -- 내부: 이벤트 발행 ------------------------------------------------

    def _emit(
        self,
        actor: str,
        etype: str,
        entity_id: str | None,
        payload: dict,
        version: int,
        private: dict | None = None,
    ) -> Event:
        ev = Event(
            run_id=self.run_id,
            seq=self._seq,
            sim_time=self.state.sim_time,
            world_version=version,
            actor_id=actor,
            event_type=etype,
            entity_id=entity_id,
            payload=payload,
            private=private or {},
        )
        apply_event(self.state, ev)
        self._seq += 1
        self.log.append(ev)
        return ev

    # -- 공개 API --------------------------------------------------------

    def initialize(
        self,
        entities: list[dict],
        relations: list[dict],
        resources: list[dict],
    ) -> None:
        if self._initialized:
            raise RuntimeError("already initialized")
        self._emit(
            ENV_ACTOR,
            EventType.WORLD_INITIALIZED,
            None,
            {"entities": entities, "relations": relations, "resources": resources},
            version=0,
        )
        self._initialized = True

    def advance_to(self, t: float) -> None:
        """시뮬레이션 시계를 앞으로만 옮긴다. 이벤트를 남기지 않는다."""
        if not math.isfinite(t) or t < self.state.sim_time:
            raise ValueError(f"cannot move clock from {self.state.sim_time} to {t}")
        self.state.sim_time = t

    def end_run(self, t: float) -> None:
        self.advance_to(t)
        self._emit(ENV_ACTOR, EventType.RUN_ENDED, None, {}, version=self.state.version)

    def submit(self, action: Action) -> ActionResult:
        if not self._initialized:
            raise RuntimeError("world not initialized")
        v = self.state.version
        hidden = {"action_private": dict(action.private)} if action.private else None
        self._emit(action.actor_id, EventType.ACTION_PROPOSED, None, {"action": action.to_dict()}, v, hidden)

        reasons = self.validate(action)
        if reasons:
            self._emit(
                action.actor_id,
                EventType.ACTION_REJECTED,
                None,
                {"action": action.to_dict(), "reasons": list(reasons)},
                v,
                hidden,
            )
            return ActionResult(accepted=False, reasons=tuple(reasons), world_version=v)

        effects = self._plan_effects(action)  # 상태를 바꾸기 전에 전부 계산
        new_v = v + 1
        for etype, entity_id, payload, private in effects:
            self._emit(action.actor_id, etype, entity_id, payload, new_v, private)
        if action.kind == ActionKind.CREATE_TASK:
            self._index_new_task(action.params)
        return ActionResult(accepted=True, world_version=new_v)

    # -- 검증 ------------------------------------------------------------

    def validate(self, action: Action) -> list[str]:
        """거절 사유 목록. 사유는 ActionRejected 의 공개 payload 로 기록되므로
        숨겨진 참값(처리 시간, 고장 원인 등)을 사유 문자열에 넣지 않는다."""
        r: list[str] = []
        if action.kind not in KNOWN_ACTION_KINDS:
            return [f"unknown action kind: {action.kind!r}"]
        if action.kind not in self.grants.get(action.actor_id, frozenset()):
            r.append(f"actor {action.actor_id!r} not permitted to {action.kind}")
        if action.expected_version is not None and action.expected_version != self.state.version:
            r.append(
                f"stale world version: expected {action.expected_version}, current {self.state.version}"
            )
        if not isinstance(action.params, dict) or not isinstance(action.private, dict):
            return r + ["params and private must be dicts"]

        if action.kind == ActionKind.CREATE_TASK:
            r += self._validate_create(action.params, action.private)
        elif action.kind == ActionKind.START_TASK:
            r += self._validate_start(action.params)
        elif action.kind == ActionKind.COMPLETE_TASK:
            r += self._validate_complete(action.params)
        elif action.kind in (ActionKind.BEGIN_OUTAGE, ActionKind.END_OUTAGE):
            r += self._validate_outage(action.kind, action.params)
        elif action.kind == ActionKind.REQUEST_RECONFIGURATION:
            r += self._validate_request_reconfiguration(action.params)
        elif action.kind == ActionKind.COMPLETE_RECONFIGURATION:
            r += self._validate_complete_reconfiguration(action.params)
        return r

    def offered_capabilities(self, override: tuple[str, tuple[str, ...]] | None = None) -> set[str]:
        """용량이 있는 셀이 (전환이 끝났을 때) 제공하게 될 capability 집합.
        전환 중이거나 작업을 비우는 셀은 목표 역할로 센다. 고장은 일시적이므로 세지 않는다."""
        out: set[str] = set()
        for e in self.state.entities.values():
            res = self.state.resources.get(e.id)
            if res is None or res.capacity <= 0:
                continue
            caps = e.target_capabilities if e.mode != EntityMode.NORMAL and e.target_capabilities else e.capabilities
            if override and e.id == override[0]:
                caps = override[1]
            out.update(caps)
        return out

    def _validate_request_reconfiguration(self, p: dict) -> list[str]:
        ent = self.state.entities.get(_as_id(p.get("entity")))
        if ent is None:
            return [f"request_reconfiguration: unknown entity {p.get('entity')!r}"]
        if ent.reconfig is None:
            return [f"request_reconfiguration: {ent.id} is not reconfigurable"]
        if ent.mode != EntityMode.NORMAL:
            return [f"request_reconfiguration: {ent.id} is already {ent.mode} (no cancel or chaining)"]
        caps = p.get("capabilities")
        if not isinstance(caps, list) or not all(isinstance(c, str) for c in caps):
            return ["request_reconfiguration: capabilities must be a list of strings"]
        target = tuple(sorted(caps))
        options = [tuple(sorted(o)) for o in ent.reconfig["options"]]
        if target not in options:
            return [f"request_reconfiguration: {list(target)} is not an option for {ent.id}"]
        if target == tuple(sorted(ent.capabilities)):
            return [f"request_reconfiguration: {ent.id} already has {list(target)}"]
        lost = self.offered_capabilities() - self.offered_capabilities((ent.id, target))
        if lost:
            # 교착 방지: 마지막 제공 셀의 역할을 빼면 그 capability 작업이 영원히 대기한다
            return [f"request_reconfiguration: no cell would offer {sorted(lost)} after the change"]
        return []

    def _validate_complete_reconfiguration(self, p: dict) -> list[str]:
        ent = self.state.entities.get(_as_id(p.get("entity")))
        if ent is None:
            return [f"complete_reconfiguration: unknown entity {p.get('entity')!r}"]
        if ent.mode != EntityMode.CHANGEOVER:
            return [f"complete_reconfiguration: {ent.id} is {ent.mode}, not changeover"]
        if self.state.sim_time < ent.mode_since + float(ent.reconfig["changeover_s"]):
            return [f"complete_reconfiguration: {ent.id} changeover not finished"]
        return []

    def _validate_outage(self, kind: str, p: dict) -> list[str]:
        res = self.state.resources.get(_as_id(p.get("entity")))
        if res is None:
            return [f"{kind}: unknown resource {p.get('entity')!r}"]
        units = p.get("units")
        if isinstance(units, bool) or not isinstance(units, int) or units < 1:
            return [f"{kind}: units must be a positive integer"]
        if kind == ActionKind.BEGIN_OUTAGE and res.out_of_service + units > res.capacity:
            return [f"{kind}: {res.id} cannot lose {units} more units (capacity {res.capacity})"]
        if kind == ActionKind.END_OUTAGE and units > res.out_of_service:
            return [f"{kind}: {res.id} has only {res.out_of_service} units out of service"]
        return []

    def _validate_create(self, p: dict, hidden: dict) -> list[str]:
        r = []
        if "duration" in p:
            # 숨겨진 참값이 공개 로그로 새지 않도록 제출 형식에서 강제한다
            r.append("create_task: duration is hidden truth; pass it in private, not params")
        tid = p.get("id")
        if not isinstance(tid, str) or not tid:
            return ["create_task: id must be a non-empty string"]
        if tid in self.state.tasks:
            r.append(f"create_task: task {tid} already exists")
        cap = p.get("capability")
        if not isinstance(cap, str) or not cap:
            r.append("create_task: capability must be a non-empty string")
        dur = hidden.get("duration")
        if isinstance(dur, bool) or not isinstance(dur, (int, float)) or not math.isfinite(dur) or dur <= 0:
            r.append("create_task: duration must be a finite positive number")
        preds = p.get("predecessors", [])
        if not isinstance(preds, (list, tuple)) or not all(isinstance(x, str) for x in preds):
            r.append("create_task: predecessors must be a list of task ids")
        else:
            if len(set(preds)) != len(preds):
                r.append("create_task: duplicate predecessors")
            for pid in preds:
                if pid == tid:
                    r.append("create_task: task cannot depend on itself")
                elif pid not in self.state.tasks:
                    # 선행 작업은 이미 존재해야 한다 -> 의존 그래프는 구성상 비순환
                    r.append(f"create_task: unknown predecessor {pid}")
        if not isinstance(p.get("tags", {}), dict):
            r.append("create_task: tags must be a dict")
        return r

    def _validate_start(self, p: dict) -> list[str]:
        task = self.state.tasks.get(_as_id(p.get("task")))
        ent = self.state.entities.get(_as_id(p.get("entity")))
        if task is None:
            return [f"start_task: unknown task {p.get('task')!r}"]
        if ent is None:
            return [f"start_task: unknown entity {p.get('entity')!r}"]
        r = []
        if ent.mode != EntityMode.NORMAL:
            r.append(f"start_task: entity {ent.id} is {ent.mode} (reconfiguration)")
        if task.status != TaskStatus.READY:
            r.append(f"start_task: task {task.id} is {task.status}, not READY")
        if task.capability not in ent.capabilities:
            r.append(f"start_task: entity {ent.id} lacks capability {task.capability}")
        res = self.state.resources.get(ent.id)
        if res is None:
            r.append(f"start_task: entity {ent.id} has no resource")
        elif res.available <= 0:
            r.append(f"start_task: resource {res.id} has no free capacity")
        for pid in task.predecessors:
            if self.state.tasks[pid].status != TaskStatus.COMPLETED:
                r.append(f"start_task: predecessor {pid} not completed")
        return r

    def _validate_complete(self, p: dict) -> list[str]:
        task = self.state.tasks.get(_as_id(p.get("task")))
        if task is None:
            return [f"complete_task: unknown task {p.get('task')!r}"]
        if task.status != TaskStatus.RUNNING:
            return [f"complete_task: task {task.id} is {task.status}, not RUNNING"]
        if self.state.sim_time < task.started_at + task.duration:
            # 사유 문자열은 공개 로그로 간다. 예정 완료 시각(= 처리 시간)을 넣으면 숨겨진 참값이 샌다.
            return [f"complete_task: task {task.id} not finished yet"]
        return []

    # -- 효과 계산 (상태 변경 없음) ---------------------------------------

    def _plan_effects(self, a: Action) -> list[tuple[str, str | None, dict, dict | None]]:
        p = a.params
        if a.kind == ActionKind.CREATE_TASK:
            preds = list(p.get("predecessors", []))
            all_done = all(self.state.tasks[x].status == TaskStatus.COMPLETED for x in preds)
            nxt = TaskStatus.READY if all_done else TaskStatus.WAITING
            return [
                (
                    EventType.TASK_CREATED,
                    p["id"],
                    {
                        "capability": p["capability"],
                        "predecessors": preds,
                        "created_index": self._next_created_index,
                        "tags": dict(p.get("tags", {})),
                    },
                    {"duration": float(a.private["duration"])},
                ),
                (EventType.TASK_STATE_CHANGED, p["id"], {"from": "CREATED", "to": str(nxt)}, None),
            ]

        if a.kind == ActionKind.START_TASK:
            return [
                (EventType.RESOURCE_RESERVED, p["entity"], {"task": p["task"]}, None),
                (
                    EventType.TASK_STATE_CHANGED,
                    p["task"],
                    {"from": "READY", "to": "RUNNING", "entity": p["entity"]},
                    None,
                ),
            ]

        if a.kind == ActionKind.COMPLETE_TASK:
            task = self.state.tasks[p["task"]]
            effects: list[tuple[str, str | None, dict, dict | None]] = [
                (EventType.TASK_STATE_CHANGED, task.id, {"from": "RUNNING", "to": "COMPLETED"}, None),
                (EventType.RESOURCE_RELEASED, task.assigned_entity, {"task": task.id}, None),
            ]
            for sid in self._successors.get(task.id, []):
                succ = self.state.tasks[sid]
                if succ.status != TaskStatus.WAITING:
                    continue
                others_done = all(
                    q == task.id or self.state.tasks[q].status == TaskStatus.COMPLETED
                    for q in succ.predecessors
                )
                if others_done:
                    effects.append(
                        (EventType.TASK_STATE_CHANGED, sid, {"from": "WAITING", "to": "READY"}, None)
                    )
            ent = self.state.entities.get(task.assigned_entity)
            res = self.state.resources.get(task.assigned_entity)
            if ent is not None and ent.mode == EntityMode.DRAINING and res is not None and res.holders == [task.id]:
                # 비우던 셀의 마지막 작업이 끝났다 → 전환 시작
                effects.append(
                    (EventType.RECONFIGURATION_STARTED, ent.id,
                     {"changeover_s": float(ent.reconfig["changeover_s"])}, None)
                )
            return effects

        if a.kind == ActionKind.BEGIN_OUTAGE:
            hidden = {"fault": dict(a.private)} if a.private else None
            return [(EventType.RESOURCE_OUTAGE_STARTED, p["entity"], {"units": p["units"]}, hidden)]

        if a.kind == ActionKind.END_OUTAGE:
            return [(EventType.RESOURCE_OUTAGE_ENDED, p["entity"], {"units": p["units"]}, None)]

        if a.kind == ActionKind.REQUEST_RECONFIGURATION:
            ent = self.state.entities[p["entity"]]
            res = self.state.resources.get(ent.id)
            effects = [(EventType.RECONFIGURATION_REQUESTED, ent.id, {"capabilities": sorted(p["capabilities"])}, None)]
            if res is None or not res.holders:
                effects.append(
                    (EventType.RECONFIGURATION_STARTED, ent.id,
                     {"changeover_s": float(ent.reconfig["changeover_s"])}, None)
                )
            return effects

        if a.kind == ActionKind.COMPLETE_RECONFIGURATION:
            ent = self.state.entities[p["entity"]]
            return [(EventType.RECONFIGURATION_COMPLETED, ent.id, {"capabilities": list(ent.target_capabilities)}, None)]

        raise AssertionError(f"unhandled kind {a.kind}")

    def _index_new_task(self, p: dict) -> None:
        self._next_created_index += 1
        for pid in p.get("predecessors", []):
            self._successors.setdefault(pid, []).append(p["id"])  # 생성 순서 = 결정적 순서
