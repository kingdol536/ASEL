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


class ObjectiveAwarePolicy:
    """목표를 읽는 기준 정책 (#38, 잠정). 관측의 objective 만 본다 (채점식은 모른다).

    - kind == "priority": params.flow 에 해당하는 작업 묶음을 먼저 (그 안에서는 준비 순서)
    - 그 밖(예: "throughput"): FIFO 와 같다
    """

    name = "objective-aware"

    def reset(self, context: PolicyContext) -> None:
        pass

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        obj = obs.objective or {}
        target = obj.get("params", {}).get("flow") if obj.get("kind") == "priority" else None
        ready = sorted(
            (t for t in obs.open_tasks if t["status"] == "READY"),
            key=lambda t: (target is not None and t.get("flow") != target, t["ready_at"], t["created_index"]),
        )
        return greedy_assign(obs, ready, sorted(obs.cells, key=lambda c: c["id"]))

    def usage(self) -> dict:
        return {}
