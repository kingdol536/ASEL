"""Claude 구조 제어 정책 (EXP-003 #45, 잠정).

배정 정책(ClaudePolicy)의 예산 가드·응답 캐시·재생을 그대로 쓰고, 판단 대상만 바꾼다:
'전환 안 함' 또는 '재구성 가능한 셀 하나를 옵션 중 하나로 전환'.

- 관측은 다른 구조 정책(P0/P1/P2)과 같은 공개 관측 + 허용 전환 후보다 (정보 공정성).
- 호출 빈도: 전환 후보가 있을 때만, 모의 시간 decision_interval_s 에 한 번 이하 (비용 상한).
  P1/P2 는 사건마다 판단하므로 **판단 기회가 다르다** — 계획서(EXP-003)에 한계로 적는다.
- 실패(예산·타임아웃·형식 오류 등)는 그 판단만 '전환 안 함'(P0)으로 대체한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from asel.agents.claude_policy import ClaudePolicy
from asel.core.actions import ActionKind
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext

STRUCTURE_PROMPT_V1 = """You control the structure of a simulated work system made of cells (stations).
Some cells can switch their role (capabilities) to another listed option. A switch first drains the cell:
it stops taking new tasks and finishes its running ones; then it is unavailable for changeover_s seconds;
then it offers the new role. A switch cannot be cancelled once requested.
Each decision you see the current observation (cells with modes and options, open tasks) and the allowed switches.
Decide whether to request one switch now, or none.
Aim for low job completion time across all job types. Weigh the capacity lost while draining and changing over
against the expected benefit, and consider that load can change over time.
Rules:
- Choose "switch" only with an entity and capabilities exactly as listed in allowed_actions; otherwise choose "none"
  (then use an empty entity "" and empty capabilities []).
Task processing times are not visible to you. Base decisions only on the observation.
Reply with the JSON object described by the output schema. Keep "reason" to one short sentence."""

STRUCTURE_PROMPTS = {"s1-neutral": STRUCTURE_PROMPT_V1}

STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["none", "switch"]},
        "entity": {"type": "string"},
        "capabilities": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["decision", "entity", "capabilities", "reason"],
    "additionalProperties": False,
}


@dataclass
class ClaudeStructurePolicy(ClaudePolicy):
    name: str = "claude-structure"
    structure_prompt: str = "s1-neutral"
    decision_interval_s: float = 30.0  # 모의 시간 이 간격에 한 번 이하로 묻는다

    def __post_init__(self):
        if self.structure_prompt not in STRUCTURE_PROMPTS:
            raise ValueError(f"unknown structure_prompt {self.structure_prompt!r}")
        super().__post_init__()

    def _reset_usage(self) -> None:
        super()._reset_usage()
        self._u.pop("prompt_version", None)
        self._u["structure_prompt"] = self.structure_prompt
        self._u["decision_interval_s"] = self.decision_interval_s
        self._u["skipped_interval"] = 0
        self._next_at = 0.0

    def reset(self, context: PolicyContext) -> None:
        self._reset_usage()

    def _system_prompt(self) -> str:
        return STRUCTURE_PROMPTS[self.structure_prompt]

    def _output_schema(self) -> dict:
        return STRUCTURE_SCHEMA

    def _should_call(self, obs: Observation, affordances: list[ActionSpec]) -> bool:
        has = any(s.kind == ActionKind.REQUEST_RECONFIGURATION and s.candidates for s in affordances)
        if not has:
            return False
        if obs.sim_time < self._next_at:
            self._u["skipped_interval"] += 1
            return False
        self._next_at = obs.sim_time + self.decision_interval_s
        return True

    def _parse(self, data: dict) -> list[ActionProposal]:
        reason = str(data.get("reason", ""))[:300]
        if data["decision"] == "none":
            return []
        if data["decision"] != "switch":
            raise ValueError("bad decision")
        caps = data["capabilities"]
        if not isinstance(caps, list):
            raise TypeError("capabilities")
        return [ActionProposal(ActionKind.REQUEST_RECONFIGURATION,
                               {"entity": str(data["entity"]), "capabilities": [str(c) for c in caps]}, reason)]

    def _fallback_proposals(self, obs, affordances) -> list[ActionProposal]:
        return []  # 실패하면 그 판단은 전환하지 않는다 (P0)
