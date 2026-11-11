"""환경 A: 모듈형 물류 작업 셀 어댑터 (잠정, docs/03 §6).

- 주문 도착: 포아송 과정 또는 구간별 포아송 과정 (stream "arrivals").
  구간 경계를 넘으면 경계 시각에서 새 도착률로 다시 뽑는다(지수분포의 무기억성으로 정확).
  난수 사용 횟수는 도착 과정에만 의존하고 배정 정책과 무관하다.
- 주문 하나 = job_template 의 단계들을 선행관계 사슬로 만든 작업들.
- 셀 고장: 시나리오의 faults 를 시작/종료 사건으로 예약한다. 원인·계획 종료 시각은 비공개.
  고장 중에는 새 작업을 시작할 수 없고 진행 중 작업은 끝까지 처리한다 (docs/decisions/0003, 잠정).
- 처리 시간은 주문 생성 시점에 미리 뽑는다 (stream "service").
  -> 배정 정책이 달라도 같은 시드면 같은 주문이 같은 처리 시간을 갖는다(대응 비교의 전제).
"""

from __future__ import annotations

import math

from asel.core.actions import Action, ActionKind
from asel.core.rng import RngStreams, exponential, uniform
from asel.core.world import ENV_ACTOR
from asel.io.scenario import (
    ConstantDist,
    ExponentialDist,
    PiecewisePoissonArrival,
    Scenario,
    UniformDist,
)


def world_init_payload(sc: Scenario) -> tuple[list[dict], list[dict], list[dict]]:
    entities = []
    for e in sc.entities:
        d = {"id": e.id, "type": e.type, "capabilities": list(e.capabilities), "properties": dict(e.properties)}
        if e.reconfigurable is not None:
            d["reconfig"] = {
                "options": [sorted(o) for o in e.reconfigurable.options],
                "changeover_s": float(e.reconfigurable.changeover_s),
            }
        entities.append(d)
    relations = [{"source": r.source, "target": r.target, "kind": r.kind} for r in sc.relations]
    resources = [{"id": e.id, "capacity": e.capacity} for e in sc.entities]
    return entities, relations, resources


class WarehouseWorkload:
    def __init__(self, sc: Scenario, seed: int):
        self.sc = sc
        rng = RngStreams(seed)
        self._arrivals = rng.get("arrivals")
        self._service = rng.get("service")
        ap = sc.workload.arrival_process
        if isinstance(ap, PiecewisePoissonArrival):
            starts = [s.start_s for s in ap.segments]
            self._segments = [
                (start, end, (60.0 / s.rate_per_min) if s.rate_per_min > 0 else None)
                for s, start, end in zip(ap.segments, starts, starts[1:] + [math.inf])
            ]
        else:
            self._segments = [(0.0, math.inf, 60.0 / ap.rate_per_min)]
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
        t = self._next_arrival_time(now)
        return [] if t is None else [(t, ("arrival", self._count))]

    def _next_arrival_time(self, now: float) -> float | None:
        t = now
        for start, end, mean_gap in self._segments:
            if end <= t:
                continue
            t = max(t, start)
            if mean_gap is not None:
                cand = t + exponential(self._arrivals, mean_gap)
                if cand < end:
                    return cand
            t = end
        return None

    def initial_schedule(self) -> list[tuple[float, tuple]]:
        sched: list[tuple[float, tuple]] = list(self._next_arrival(0.0))
        # 같은 시각이면 종료를 시작보다 먼저 예약한다 (시나리오 검증의 겹침 판정과 같은 규칙).
        # 시뮬레이터는 같은 시각 사건을 예약 순서대로 처리한다.
        fault_events = []
        for i, f in enumerate(self.sc.faults):
            fault_events.append((f.start_s, 1, i, ("fault_start", i)))
            fault_events.append((f.end_s, 0, i, ("fault_end", i)))
        sched += [(t, data) for t, _, _, data in sorted(fault_events)]
        return sched

    def _fault_action(self, kind: str, i: int) -> Action:
        f = self.sc.faults[i]
        units = f.units or next(e.capacity for e in self.sc.entities if e.id == f.entity)
        if kind == "fault_start":
            return Action(
                ENV_ACTOR,
                ActionKind.BEGIN_OUTAGE,
                {"entity": f.entity, "units": units},
                private={"fault_index": i, "cause": f.cause, "planned_end_s": f.end_s},
            )
        return Action(ENV_ACTOR, ActionKind.END_OUTAGE, {"entity": f.entity, "units": units})

    def on_external(self, data: tuple, now: float):
        kind, n = data
        if kind in ("fault_start", "fault_end"):
            return [self._fault_action(kind, n)], []
        assert kind == "arrival", kind
        order_no = n
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
                        "predecessors": [prev] if prev else [],
                        "tags": {"order": order_id, "step": i},
                    },
                    private={"duration": self._sample(step.service_time)},
                )
            )
            prev = tid
        return actions, self._next_arrival(now)


class WarehouseAdapter:
    """환경 A 어댑터 (레지스트리 등록용)."""

    name = "warehouse_like"

    def world_init_payload(self, sc: Scenario):
        return world_init_payload(sc)

    def workload(self, sc: Scenario, seed: int) -> WarehouseWorkload:
        return WarehouseWorkload(sc, seed)


from asel.domains import register as _register  # noqa: E402

_register(WarehouseAdapter())
