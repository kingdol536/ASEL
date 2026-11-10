"""행동 요청과 검증 결과 (docs/02 §4 의 propose/validate 계약)."""

from __future__ import annotations

from dataclasses import dataclass, field


class ActionKind:
    CREATE_TASK = "create_task"
    START_TASK = "start_task"
    COMPLETE_TASK = "complete_task"


KNOWN_ACTION_KINDS = frozenset(
    {ActionKind.CREATE_TASK, ActionKind.START_TASK, ActionKind.COMPLETE_TASK}
)


@dataclass(frozen=True)
class Action:
    actor_id: str
    kind: str
    params: dict = field(default_factory=dict)
    expected_version: int | None = None  # 지정하면 현재 world_version 과 같아야 적용
    # 제출자가 숨겨야 할 값(예: 환경이 만드는 작업의 실제 처리 시간). 비공개 로그로만 간다.
    private: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """공개 부분만. private 는 포함하지 않는다."""
        return {
            "actor_id": self.actor_id,
            "kind": self.kind,
            "params": self.params,
            "expected_version": self.expected_version,
        }


@dataclass(frozen=True)
class ActionResult:
    accepted: bool
    reasons: tuple[str, ...] = ()
    world_version: int = 0
