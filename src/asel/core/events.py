"""이벤트 레코드 (docs/02-SYSTEM-ARCHITECTURE.md §5).

공개 부분(payload)과 비공개 부분(private)을 한 레코드에 담고, 저장할 때 두 파일로 나눈다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "0.2"  # 0.2: 공개/비공개 분리


class EventType:
    WORLD_INITIALIZED = "WorldInitialized"
    ACTION_PROPOSED = "ActionProposed"
    ACTION_REJECTED = "ActionRejected"
    TASK_CREATED = "TaskCreated"
    TASK_STATE_CHANGED = "TaskStateChanged"
    RESOURCE_RESERVED = "ResourceReserved"
    RESOURCE_RELEASED = "ResourceReleased"
    RESOURCE_OUTAGE_STARTED = "ResourceOutageStarted"  # 공개: 증상(쓸 수 없는 단위 수). 원인은 비공개
    RESOURCE_OUTAGE_ENDED = "ResourceOutageEnded"
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
    # 숨겨진 참값(실제 처리 시간, 고장 원인 등). 공개 로그에는 쓰지 않고 평가기 전용
    # 비공개 로그에만 seq 로 연결해 기록한다. 운영 정책에 전달하지 않는다.
    private: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """공개+비공개 전체 (내부 비교·해시용)."""
        return asdict(self)

    def to_public_dict(self) -> dict:
        d = asdict(self)
        del d["private"]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Event:
        return cls(**d)
