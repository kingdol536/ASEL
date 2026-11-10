"""구조 제어 정책 P0 / P1 / P2 (티켓 #22). 관측만 읽고, 재구성 후보에서만 고른다.

압력(pressure): capability y 의 대기(READY) 작업 수 / y 를 지금 제공하는 정상 셀 용량 합(최소 1).
- P0 (fixed): 전환하지 않는다.
- P1 (reactive): 재구성 가능한 정상 셀의 현재 역할 X 보다 압력이 threshold 이상 높은 역할 Y 가 있으면 즉시 전환.
- P2 (cost-aware): P1 + (a) 최소 유지시간: 마지막 역할 변경 뒤 min_dwell_s 동안 다시 전환하지 않음,
  (b) 전환 비용 반영: 기준값에 changeover_s 1분당 cost_per_min 을 더함(히스테리시스 역할도 겸함).

기준값은 잠정이며 개발용 시나리오(warehouse-reconfig-dev, 전환 120s)와 개발 시드(0~9)로만 정했다
(조정 기록: experiments/reports/assets/M4/dev-tuning.md, #22). EXP-002 에 고정하며 평가 시드로는 조정하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

from asel.core.actions import ActionKind
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext


def pressures(obs: Observation) -> dict[str, float]:
    ready: dict[str, int] = {}
    for t in obs.open_tasks:
        if t["status"] == "READY":
            ready[t["capability"]] = ready.get(t["capability"], 0) + 1
    cap: dict[str, int] = {}
    for c in obs.cells:
        usable = max(c["capacity"] - c["out_of_service"], 0)
        if c.get("mode", "normal") == "normal":
            caps = c["capabilities"]
        else:
            # 이미 전환 중인 셀은 곧 제공될 목표 역할의 용량으로 센다 (같은 방향으로 여러 셀을 한꺼번에
            # 돌리는 과잉 반응 방지 — 코드 리뷰 지적. 재구성 셀이 하나인 M4 에서는 결과가 같다)
            caps = c.get("target_capabilities") or []
        for k in caps:
            cap[k] = cap.get(k, 0) + usable
    keys = set(ready) | set(cap)
    return {k: ready.get(k, 0) / max(cap.get(k, 0), 1) for k in keys}


class _Base:
    name = "base"

    def reset(self, context: PolicyContext) -> None:
        pass

    def usage(self) -> dict:
        return {}


class FixedStructure(_Base):
    """P0: 전환하지 않는다."""

    name = "p0"

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        return []


@dataclass
class ReactiveStructure(_Base):
    """P1: 압력 차이가 threshold 이상이면 즉시 전환."""

    threshold: float = 8.0  # 개발 시드 조정값 (후보 11개 중 최소 평균 처리 시간)
    name: str = "p1"

    def _threshold(self, cell: dict) -> float:
        return self.threshold

    def _allowed(self, cell: dict, obs: Observation) -> bool:
        return True

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        cands = [c for spec in affordances if spec.kind == ActionKind.REQUEST_RECONFIGURATION for c in spec.candidates]
        if not cands:
            return []
        p = pressures(obs)
        cells = {c["id"]: c for c in obs.cells}
        best = None
        for cand in cands:
            cell = cells[cand["entity"]]
            if not self._allowed(cell, obs):
                continue
            cur = max((p.get(k, 0.0) for k in cell["capabilities"]), default=0.0)
            new = max((p.get(k, 0.0) for k in cand["capabilities"]), default=0.0)
            gain = new - cur
            if gain >= self._threshold(cell) and (best is None or gain > best[0]):
                best = (gain, cand)
        if best is None:
            return []
        gain, cand = best
        return [ActionProposal(ActionKind.REQUEST_RECONFIGURATION, dict(cand),
                               f"pressure gain {gain:.2f} >= {self._threshold(cells[cand['entity']]):.2f}")]


@dataclass
class CostAwareStructure(ReactiveStructure):
    """P2: P1 + 최소 유지시간 + 전환 시간에 비례해 높아지는 기준값."""

    threshold: float = 3.0  # 개발 시드 조정값 (후보 27개 조합 중 최소 평균 처리 시간)
    min_dwell_s: float = 300.0
    cost_per_min: float = 2.0
    name: str = "p2"

    def _threshold(self, cell: dict) -> float:
        return self.threshold + self.cost_per_min * float(cell["reconfig"]["changeover_s"]) / 60.0

    def _allowed(self, cell: dict, obs: Observation) -> bool:
        since = cell.get("mode_since")
        # mode_since 는 마지막 모드 변경(전환 완료 포함) 시각. 한 번도 바뀐 적 없으면 None
        return since is None or obs.sim_time - since >= self.min_dwell_s


STRUCTURE_POLICIES = {
    "p0": FixedStructure,
    "p1": ReactiveStructure,
    "p2": CostAwareStructure,
}


def make_structure_policy(name: str):
    if name not in STRUCTURE_POLICIES:
        raise ValueError(f"unknown structure policy {name!r}; choose from {sorted(STRUCTURE_POLICIES)}")
    return STRUCTURE_POLICIES[name]()
