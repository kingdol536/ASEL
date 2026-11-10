"""고정 FIFO 배정 규칙 — 비교 정책 P0 의 자리 (잠정).

READY 작업을 (준비 시각, 생성 순번) 순으로, capability 가 맞고 여유가 있는 셀 중
id 가 가장 앞선 셀에 배정한다. M1에서는 전체 상태를 읽는다.
관측 투영(허가된 관측만 전달)은 M3의 PolicyAdapter 에서 도입한다.
"""

from __future__ import annotations

from asel.core.actions import Action, ActionKind
from asel.core.model import TaskStatus, WorldState


class FifoDispatcher:
    actor_id = "dispatcher.fifo"

    def propose(self, state: WorldState) -> list[Action]:
        ready = sorted(
            (t for t in state.tasks.values() if t.status == TaskStatus.READY),
            key=lambda t: (t.ready_at, t.created_index),
        )
        if not ready:
            return []
        free = {rid: r.available for rid, r in state.resources.items()}
        cells = sorted(state.entities.values(), key=lambda e: e.id)
        out: list[Action] = []
        for t in ready:
            for e in cells:
                if t.capability in e.capabilities and free.get(e.id, 0) > 0:
                    free[e.id] -= 1
                    out.append(
                        Action(self.actor_id, ActionKind.START_TASK, {"task": t.id, "entity": e.id})
                    )
                    break
        return out
