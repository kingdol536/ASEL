"""행동 요청과 검증 결과 (docs/02 §4 의 propose/validate 계약)."""

from __future__ import annotations

from dataclasses import dataclass, field


class ActionKind:
    CREATE_TASK = "create_task"
    START_TASK = "start_task"
    COMPLETE_TASK = "complete_task"
    BEGIN_OUTAGE = "begin_outage"
    END_OUTAGE = "end_outage"
    REQUEST_RECONFIGURATION = "request_reconfiguration"
    COMPLETE_RECONFIGURATION = "complete_reconfiguration"


KNOWN_ACTION_KINDS = frozenset(
    {
        ActionKind.CREATE_TASK,
        ActionKind.START_TASK,
        ActionKind.COMPLETE_TASK,
        ActionKind.BEGIN_OUTAGE,
        ActionKind.END_OUTAGE,
        ActionKind.REQUEST_RECONFIGURATION,
        ActionKind.COMPLETE_RECONFIGURATION,
    }
)


@dataclass(frozen=True)
class Action:
    actor_id: str
    kind: str
    params: dict = field(default_factory=dict)
    expected_version: int | None = None  # 지정하면 현재 world_version 과 같아야 적용
    # 제출자가 숨겨야 할 값(예: 환경이 만드는 작업의 실제 처리 시간). 비공개 로그로만 간다.
    private: dict = field(default_factory=dict)
    reason: str | None = None  # 제안 주체가 밝힌 이유 (공개). 정책 설명 기록용

    def to_dict(self) -> dict:
        """공개 부분만. private 는 포함하지 않는다."""
        d = {
            "actor_id": self.actor_id,
            "kind": self.kind,
            "params": self.params,
            "expected_version": self.expected_version,
        }
        if self.reason is not None:
            d["reason"] = self.reason
        return d


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    reasons: tuple[str, ...] = ()
    world_version: int = 0
