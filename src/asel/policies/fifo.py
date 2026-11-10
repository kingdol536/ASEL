"""고정 FIFO 배정 규칙 — 비교 정책 P-FIFO (잠정).

READY 작업을 (준비 시각, 생성 순번) 순으로, capability 가 맞고 여유가 있는 셀 중
id 가 가장 앞선 셀에 배정한다. 관측(Observation)만 읽는다.
"""

from __future__ import annotations

from asel.core.actions import ActionKind
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext


def greedy_assign(obs: Observation, ordered_ready: list[dict], cells: list[dict]) -> list[ActionProposal]:
    """정렬된 READY 작업을 순서대로, 주어진 셀 순서에서 처음 맞는 여유 셀에 배정한다."""
    free = {c["id"]: c["available"] for c in obs.cells}
    out: list[ActionProposal] = []
    for t in ordered_ready:
        for c in cells:
            if t["capability"] in c["capabilities"] and free[c["id"]] > 0:
                free[c["id"]] -= 1
                out.append(ActionProposal(ActionKind.START_TASK, {"task": t["id"], "entity": c["id"]}))
                break
    return out


class FifoPolicy:
    name = "fifo"

    def reset(self, context: PolicyContext) -> None:
        pass

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        ready = sorted(
            (t for t in obs.open_tasks if t["status"] == "READY"),
            key=lambda t: (t["ready_at"], t["created_index"]),
        )
        return greedy_assign(obs, ready, sorted(obs.cells, key=lambda c: c["id"]))

    def usage(self) -> dict:
        return {}
