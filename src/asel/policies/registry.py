"""정책 이름 -> 생성기. 실행·일괄 실행에서 --policy 로 고른다."""

from __future__ import annotations

from collections.abc import Callable

from asel.policies.baselines import FirstCandidatePolicy, OrderAgePolicy
from asel.policies.fifo import FifoPolicy

POLICIES: dict[str, Callable[[], object]] = {
    "fifo": FifoPolicy,
    "order-age": OrderAgePolicy,
    "first-candidate": FirstCandidatePolicy,
}


def make_policy(name: str):
    if name not in POLICIES:
        raise ValueError(f"unknown policy {name!r}; choose from {sorted(POLICIES)}")
    return POLICIES[name]()
