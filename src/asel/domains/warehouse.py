"""환경 A: 모듈형 물류 작업 셀 어댑터 (잠정, docs/03 §6).

- 주문 도착: 포아송 과정 (stream "arrivals").
- 주문 하나 = job_template 의 단계들을 선행관계 사슬로 만든 작업들.
- 처리 시간은 주문 생성 시점에 미리 뽑는다 (stream "service").
  -> 배정 정책이 달라도 같은 시드면 같은 주문이 같은 처리 시간을 갖는다(대응 비교의 전제).
"""

from __future__ import annotations

from asel.core.actions import Action, ActionKind
from asel.core.rng import RngStreams, exponential, uniform
from asel.core.world import ENV_ACTOR
from asel.io.scenario import ConstantDist, ExponentialDist, Scenario, UniformDist


def world_init_payload(sc: Scenario) -> tuple[list[dict], list[dict], list[dict]]:
    entities = [
        {"id": e.id, "type": e.type, "capabilities": list(e.capabilities), "properties": dict(e.properties)}
        for e in sc.entities
    ]
    relations = [{"source": r.source, "target": r.target, "kind": r.kind} for r in sc.relations]
    resources = [{"id": e.id, "capacity": e.capacity} for e in sc.entities]
    return entities, relations, resources


class OrderArrivals:
    def __init__(self, sc: Scenario, seed: int):
        self.sc = sc
        rng = RngStreams(seed)
        self._arrivals = rng.get("arrivals")
        self._service = rng.get("service")
        self._mean_gap_s = 60.0 / sc.workload.arrival_process.rate_per_min
        self._count = 0

    def _sample(self, dist) -> float:
        if isinstance(dist, ExponentialDist):
            return exponential(self._service, dist.mean_s)
        if isinstance(dist, UniformDist):
            return uniform(self._service, dist.low_s, dist.high_s)
        if isinstance(dist, ConstantDist):
            return float(dist.value_s)
        raise TypeError(dist)

    def _next_arrival(self, now: float) -> list[tuple[float, int]]:
        cap = self.sc.workload.max_arrivals
        if cap is not None and self._count >= cap:
            return []
        t = now + exponential(self._arrivals, self._mean_gap_s)
        return [(t, self._count)]

    def initial_schedule(self) -> list[tuple[float, int]]:
        return self._next_arrival(0.0)

    def on_external(self, order_no: int, now: float):
        self._count += 1
        order_id = f"order-{order_no:05d}"
        actions: list[Action] = []
        prev: str | None = None
        for i, step in enumerate(self.sc.workload.job_template):
            tid = f"{order_id}/{i}-{step.capability}"
            actions.append(
                Action(
                    ENV_ACTOR,
                    ActionKind.CREATE_TASK,
                    {
                        "id": tid,
                        "capability": step.capability,
                        "duration": self._sample(step.service_time),
                        "predecessors": [prev] if prev else [],
                        "tags": {"order": order_id, "step": i},
                    },
                )
            )
            prev = tid
        return actions, self._next_arrival(now)
