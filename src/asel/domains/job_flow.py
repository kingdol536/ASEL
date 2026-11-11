"""범용 '작업 흐름' 어댑터 (티켓 #34) — 산업 단어 없이 설정 파일의 부품 조합만으로 현장을 표현한다.

- 작업 묶음(job) 도착: 포아송 또는 구간별 포아송 (stream "arrivals"). 구간 경계에서는 무기억성으로 재추출.
- 작업 묶음 하나 = workload 의 공정 흐름(job_template 사슬 또는 flow DAG)을 작업들로 펼친 것.
  flow 는 갈라짐·합침을 지원한다 (코어의 다중 선행관계를 그대로 쓴다).
- 처리 시간은 묶음 생성 시점에 단계 순서대로 미리 뽑는다 (stream "service") → 정책이 달라도 같은 시드면 같은 수요.
- 고장: 시나리오 faults 를 시작/종료 사건으로 예약 (원인·계획 종료는 비공개, 결정 0003).

작업 태그의 "order" 키는 '작업 묶음 인스턴스 id' 를 뜻한다 (환경 A 에서 쓰던 이름을 재현성 때문에 유지).
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


def _flow_steps(flow) -> list[tuple[str, str, object, list[str]]]:
    return [(s.id, s.capability, s.service_time, list(s.after)) for s in flow.steps]


def resolved_flows(sc: Scenario) -> list[tuple[float, str, list[tuple[str, str, object, list[str]]]]]:
    """[(비율, 인스턴스 접두어, 단계 목록)]. 혼류가 아니면 항목 하나 (비율 1)."""
    wl = sc.workload
    if wl.mix is not None:
        return [(m.weight, m.flow.instance_prefix, _flow_steps(m.flow)) for m in wl.mix]
    prefix, steps = resolved_steps(sc)
    return [(1.0, prefix, steps)]


def resolved_steps(sc: Scenario) -> tuple[str, list[tuple[str, str, object, list[str]]]]:
    """(인스턴스 접두어, [(단계 id, capability, 처리시간 분포, 선행 단계 id들)]).

    job_template(사슬)은 0.1~0.3 시나리오와 사건 로그가 바이트 단위로 같도록 예전 이름 규칙을 쓴다."""
    wl = sc.workload
    if wl.flow is not None:
        return wl.flow.instance_prefix, _flow_steps(wl.flow)
    out, prev = [], None
    for i, s in enumerate(wl.job_template):
        sid = f"{i}-{s.capability}"
        out.append((sid, s.capability, s.service_time, [prev] if prev else []))
        prev = sid
    return "order", out


class JobFlowWorkload:
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
        self._flows = resolved_flows(sc)
        wl = sc.workload
        flows = [m.flow for m in wl.mix] if wl.mix is not None else [wl.flow]
        self._timeouts = [f.timeout_s if f is not None else None for f in flows]
        self._mix = rng.get("mix") if len(self._flows) > 1 else None  # 혼류일 때만 쓰는 별도 난수 스트림
        self._total_w = sum(w for w, _, _ in self._flows)
        self._count = 0

    def _sample(self, dist) -> float:
        if isinstance(dist, ExponentialDist):
            return exponential(self._service, dist.mean_s)
        if isinstance(dist, UniformDist):
            return uniform(self._service, dist.low_s, dist.high_s)
        if isinstance(dist, ConstantDist):
            return float(dist.value_s)
        raise TypeError(dist)

    def _next_arrival(self, now: float) -> list[tuple[float, tuple]]:
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
        # 같은 시각이면 종료를 시작보다 먼저 예약한다 (시나리오 검증의 겹침 판정과 같은 규칙)
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
        if kind == "timeout":
            return [Action(ENV_ACTOR, ActionKind.CANCEL_TASKS, {"tasks": list(n)})], []
        assert kind == "arrival", kind
        self._count += 1
        if self._mix is None:
            _, prefix, steps = self._flows[0]
            extra = {}
            timeout = self._timeouts[0]
        else:
            u, acc = self._mix.random() * self._total_w, 0.0
            for k, (w, prefix, steps) in enumerate(self._flows):
                acc += w
                if u < acc:
                    break
            timeout = self._timeouts[k]
            extra = {"flow": prefix}  # 혼류에서만 붙인다 (기존 시나리오 사건 로그 불변)
        inst = f"{prefix}-{n:05d}"
        actions: list[Action] = []
        for i, (sid, capability, dist, after) in enumerate(steps):
            actions.append(
                Action(
                    ENV_ACTOR,
                    ActionKind.CREATE_TASK,
                    {
                        "id": f"{inst}/{sid}",
                        "capability": capability,
                        "predecessors": [f"{inst}/{a}" for a in after],
                        "tags": {"order": inst, "step": i, **extra},
                    },
                    private={"duration": self._sample(dist)},
                )
            )
        later = self._next_arrival(now)
        if timeout is not None:
            later.append((now + timeout, ("timeout", tuple(a.params["id"] for a in actions))))
        return actions, later


class JobFlowAdapter:
    """범용 작업 흐름 어댑터. 물류(warehouse_like)도 이 어댑터의 별칭이다 (#35)."""

    name = "job_flow"

    def world_init_payload(self, sc: Scenario):
        return world_init_payload(sc)

    def workload(self, sc: Scenario, seed: int) -> JobFlowWorkload:
        return JobFlowWorkload(sc, seed)
