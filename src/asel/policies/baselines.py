"""기준선 정책 (티켓 #10). 모두 관측만 읽는다.

- FirstCandidatePolicy (테스트용, 결정적): 허용 행동 후보를 주어진 순서대로 겹치지 않게 고른다.
- OrderAgePolicy (P-RULE, 잠정): 가장 오래된 주문의 작업부터 배정한다.
  같은 주문이면 뒷 단계(포장)를 먼저. 실제 처리 시간은 숨겨져 있으므로 쓰지 않는다.
"""

from __future__ import annotations

from asel.core.actions import ActionKind
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext
from asel.policies.fifo import greedy_assign


class FirstCandidatePolicy:
    name = "first-candidate"

    def reset(self, context: PolicyContext) -> None:
        pass

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        free = {c["id"]: c["available"] for c in obs.cells}
        used_tasks: set[str] = set()
        out = []
        for spec in affordances:
            if spec.kind != ActionKind.START_TASK:
                continue
            for cand in spec.candidates:
                if cand["task"] not in used_tasks and free.get(cand["entity"], 0) > 0:
                    free[cand["entity"]] -= 1
                    used_tasks.add(cand["task"])
                    out.append(ActionProposal(ActionKind.START_TASK, dict(cand)))
        return out

    def usage(self) -> dict:
        return {}


class OrderAgePolicy:
    name = "order-age"

    def reset(self, context: PolicyContext) -> None:
        pass

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        ready = sorted(
            (t for t in obs.open_tasks if t["status"] == "READY"),
            key=lambda t: (t["created_at"], -(t["step"] or 0), t["created_index"]),
        )
        return greedy_assign(obs, ready, sorted(obs.cells, key=lambda c: c["id"]))

    def usage(self) -> dict:
        return {}
