"""세계 상태의 공통 데이터 모델 (docs/03-WORLD-MODEL.md).

도메인 의미(피킹·포장 등)는 여기에 두지 않는다. 코어는 capability 문자열만 비교한다.
상태 객체를 직접 고치는 곳은 `asel.core.world` 의 이벤트 reducer 하나뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskStatus(StrEnum):
    CREATED = "CREATED"
    WAITING = "WAITING"  # 선행 작업 미완료
    READY = "READY"  # 시작 가능, 자원 대기
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# 허용 상태 전이 표 (잠정). 표에 없는 전이는 모두 거절한다.
# 선행 작업이 없는 작업은 CREATED -> READY 로 바로 갈 수 있다.
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.WAITING, TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.WAITING: frozenset({TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.WAITING, TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})


def is_allowed_transition(src: TaskStatus, dst: TaskStatus) -> bool:
    return dst in ALLOWED_TRANSITIONS[src]


@dataclass
class Entity:
    id: str
    type: str
    capabilities: tuple[str, ...]
    properties: dict = field(default_factory=dict)


@dataclass
class Relation:
    source: str
    target: str
    kind: str


@dataclass
class Resource:
    """용량이 있는 자원. M1에서는 작업 셀마다 같은 id의 자원 하나를 둔다."""

    id: str
    capacity: int
    holders: list[str] = field(default_factory=list)  # 예약 중인 task id (예약 순서 유지)

    @property
    def reserved(self) -> int:
        return len(self.holders)

    @property
    def available(self) -> int:
        return self.capacity - self.reserved


@dataclass
class Task:
    id: str
    capability: str
    duration: float | None  # 실제 처리 시간 = 숨겨진 참값. 공개 로그만으로 재생하면 None
    predecessors: tuple[str, ...] = ()
    status: TaskStatus = TaskStatus.CREATED
    created_index: int = 0  # 생성 순번. FIFO 동률 처리용
    created_at: float = 0.0
    ready_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None
    assigned_entity: str | None = None
    tags: dict = field(default_factory=dict)  # 도메인 메타데이터(예: order id)


@dataclass
class WorldState:
    version: int = 0
    sim_time: float = 0.0
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)
    resources: dict[str, Resource] = field(default_factory=dict)
    tasks: dict[str, Task] = field(default_factory=dict)

    def snapshot(self) -> dict:
        """비교·해시용 정규화 표현. 키 순서와 무관하게 동일 상태면 동일 dict."""
        return {
            "version": self.version,
            "sim_time": self.sim_time,
            "entities": {
                k: {"type": e.type, "capabilities": list(e.capabilities), "properties": e.properties}
                for k, e in sorted(self.entities.items())
            },
            "relations": [
                {"source": r.source, "target": r.target, "kind": r.kind} for r in self.relations
            ],
            "resources": {
                k: {"capacity": r.capacity, "holders": list(r.holders)}
                for k, r in sorted(self.resources.items())
            },
            "tasks": {
                k: {
                    "capability": t.capability,
                    "duration": t.duration,
                    "predecessors": list(t.predecessors),
                    "status": str(t.status),
                    "created_index": t.created_index,
                    "created_at": t.created_at,
                    "ready_at": t.ready_at,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at,
                    "assigned_entity": t.assigned_entity,
                    "tags": t.tags,
                }
                for k, t in sorted(self.tasks.items())
            },
        }
