"""이벤트 레코드 (docs/02-SYSTEM-ARCHITECTURE.md §5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "0.1"


class EventType:
    WORLD_INITIALIZED = "WorldInitialized"
    ACTION_PROPOSED = "ActionProposed"
    ACTION_REJECTED = "ActionRejected"
    TASK_CREATED = "TaskCreated"
    TASK_STATE_CHANGED = "TaskStateChanged"
    RESOURCE_RESERVED = "ResourceReserved"
    RESOURCE_RELEASED = "ResourceReleased"
    RUN_ENDED = "RunEnded"


@dataclass(frozen=True)
class Event:
    run_id: str
    seq: int
    sim_time: float
    world_version: int
    actor_id: str
    event_type: str
    entity_id: str | None
    payload: dict = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(**d)
