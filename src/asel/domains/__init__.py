"""도메인 어댑터 레지스트리 (티켓 #33).

시나리오의 `domain` 값으로 어댑터를 고른다. 실행기는 특정 산업 코드를 직접 부르지 않는다.
어댑터는 두 가지만 제공한다:
- world_init_payload(scenario) -> (entities, relations, resources)   세계 초기 구성
- workload(scenario, seed) -> WorkloadSource                          외부 사건(작업 도착·고장 등) 발생기
"""

from __future__ import annotations

from typing import Any, Protocol


class DomainAdapter(Protocol):
    name: str

    def world_init_payload(self, sc: Any) -> tuple[list[dict], list[dict], list[dict]]: ...

    def workload(self, sc: Any, seed: int) -> Any: ...


_REGISTRY: dict[str, DomainAdapter] = {}


def register(adapter: DomainAdapter, *aliases: str) -> None:
    for name in (adapter.name, *aliases):
        if name in _REGISTRY and _REGISTRY[name] is not adapter:
            raise ValueError(f"domain {name!r} already registered")
        _REGISTRY[name] = adapter


def get_adapter(domain: str) -> DomainAdapter:
    _load_builtin()
    if domain not in _REGISTRY:
        raise ValueError(f"unknown domain {domain!r}; registered: {sorted(_REGISTRY)}")
    return _REGISTRY[domain]


def registered_domains() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def _load_builtin() -> None:
    # 내장 어댑터는 처음 쓸 때 등록한다 (io.scenario ↔ domains 순환 import 방지)
    if "job_flow" not in _REGISTRY:
        from asel.domains.job_flow import JobFlowAdapter

        # 환경 A(물류)는 별도 코드 없이 범용 흐름 어댑터의 별칭이다 (#35)
        register(JobFlowAdapter(), "warehouse_like")
