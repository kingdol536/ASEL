"""정책 이름 -> 생성기. 실행·일괄 실행에서 --policy 로 고른다."""

from __future__ import annotations

from collections.abc import Callable

from asel.policies.baselines import FirstCandidatePolicy, ObjectiveAwarePolicy, OrderAgePolicy
from asel.policies.fifo import FifoPolicy

POLICIES: dict[str, Callable[[], object]] = {
    "fifo": FifoPolicy,
    "order-age": OrderAgePolicy,
    "first-candidate": FirstCandidatePolicy,
    "objective-aware": ObjectiveAwarePolicy,
}


def _claude_from_env():
    """환경변수로 설정. 기본은 replay(캐시만, 비용 0). 비용이 드는 record 는 명시해야 한다.
    ASEL_LLM_MODE=replay|record, ASEL_LLM_MODEL, ASEL_LLM_BUDGET_USD, ASEL_LLM_CALL_CAP, ASEL_LLM_DIR"""
    import os

    from asel.agents.claude_policy import BudgetGuard, ClaudePolicy, default_llm_dir

    cap_calls = os.environ.get("ASEL_LLM_CALL_CAP")
    guard = BudgetGuard(
        default_llm_dir() / "ledger.json",
        usd_cap=float(os.environ.get("ASEL_LLM_BUDGET_USD", "55")),
        call_cap=int(cap_calls) if cap_calls else None,
    )
    return ClaudePolicy(
        model=os.environ.get("ASEL_LLM_MODEL", "claude-haiku-5-5"),
        mode=os.environ.get("ASEL_LLM_MODE", "replay"),
        prompt_version=os.environ.get("ASEL_LLM_PROMPT", "v1-warehouse"),
        guard=guard,
    )


POLICIES["claude"] = _claude_from_env


def make_policy(name: str):
    if name not in POLICIES:
        raise ValueError(f"unknown policy {name!r}; choose from {sorted(POLICIES)}")
    return POLICIES[name]()
