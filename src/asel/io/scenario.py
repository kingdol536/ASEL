"""시나리오 파일 스키마 (docs/03-WORLD-MODEL.md §5, schema 0.1).

입력 경계에서만 Pydantic 으로 검증하고, 코어에는 평범한 dict/dataclass 로 넘긴다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, model_validator

SCENARIO_SCHEMA_VERSION = "0.4"  # 0.2: faults, piecewise_poisson / 0.3: reconfigurable / 0.4: workload.flow


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReconfigSpec(_Strict):
    """셀 역할 전환 옵션 (공개 설계 정보, 결정 0005)."""

    options: list[list[str]] = Field(min_length=2)
    changeover_s: float = Field(ge=0)

    @model_validator(mode="after")
    def _distinct(self):
        norm = [tuple(sorted(o)) for o in self.options]
        if any(not o for o in norm) or len(set(norm)) != len(norm):
            raise ValueError("reconfig options must be non-empty and distinct")
        return self


class EntitySpec(_Strict):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    capabilities: list[str]
    capacity: int = Field(ge=0)
    properties: dict = Field(default_factory=dict)
    reconfigurable: ReconfigSpec | None = None

    @model_validator(mode="after")
    def _current_is_option(self):
        if self.reconfigurable is not None:
            if tuple(sorted(self.capabilities)) not in [tuple(sorted(o)) for o in self.reconfigurable.options]:
                raise ValueError(f"{self.id}: current capabilities must be one of its reconfig options")
        return self


class RelationSpec(_Strict):
    source: str
    target: str
    kind: str


class ExponentialDist(_Strict):
    type: Literal["exponential"]
    mean_s: PositiveFloat


class UniformDist(_Strict):
    type: Literal["uniform"]
    low_s: PositiveFloat
    high_s: PositiveFloat

    @model_validator(mode="after")
    def _order(self):
        if self.high_s < self.low_s:
            raise ValueError("high_s must be >= low_s")
        return self


class ConstantDist(_Strict):
    type: Literal["constant"]
    value_s: PositiveFloat


Distribution = Annotated[ExponentialDist | UniformDist | ConstantDist, Field(discriminator="type")]


class PoissonArrival(_Strict):
    type: Literal["poisson"]
    rate_per_min: PositiveFloat


class RateSegment(_Strict):
    start_s: float = Field(ge=0)
    rate_per_min: float = Field(ge=0)  # 0 이면 그 구간에는 도착 없음


class PiecewisePoissonArrival(_Strict):
    """구간별로 도착률이 다른 포아송 과정 (수요 급증 등)."""

    type: Literal["piecewise_poisson"]
    segments: list[RateSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered(self):
        starts = [s.start_s for s in self.segments]
        if starts[0] != 0:
            raise ValueError("first segment must start at 0")
        if any(b <= a for a, b in zip(starts, starts[1:])):
            raise ValueError("segment starts must be strictly increasing")
        return self


ArrivalProcess = Annotated[PoissonArrival | PiecewisePoissonArrival, Field(discriminator="type")]


class JobStep(_Strict):
    capability: str = Field(min_length=1)
    service_time: Distribution


class FlowStep(_Strict):
    """공정 흐름의 한 단계 (부품). after 에 적은 단계가 모두 끝나야 시작할 수 있다."""

    id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")
    capability: str = Field(min_length=1)
    service_time: Distribution
    after: list[str] = Field(default_factory=list)


class JobFlow(_Strict):
    """작업 묶음 하나의 공정 흐름 (갈라짐·합침 가능한 DAG, #34).

    단계는 자기보다 **앞에 적힌** 단계에만 의존할 수 있다 → 순환이 생기지 않는다."""

    steps: list[FlowStep] = Field(min_length=1)
    instance_prefix: str = Field(default="job", pattern=r"^[A-Za-z0-9_-]+$")
    # 도착 뒤 이 시간이 지나면 아직 시작하지 않은 단계를 포기한다 (예: 요청 시간 초과, #41). None = 기한 없음
    timeout_s: PositiveFloat | None = None

    @model_validator(mode="after")
    def _dag(self):
        seen: set[str] = set()
        for s in self.steps:
            if s.id in seen:
                raise ValueError(f"duplicate flow step id {s.id!r}")
            if len(set(s.after)) != len(s.after):
                raise ValueError(f"step {s.id!r} lists a predecessor twice")
            for a in s.after:
                if a not in seen:
                    raise ValueError(f"step {s.id!r} depends on {a!r}, which is not an earlier step")
            seen.add(s.id)
        return self


class MixItem(_Strict):
    """혼류의 한 흐름과 비율 (#37). 도착마다 비율에 따라 흐름을 고른다."""

    weight: PositiveFloat
    flow: JobFlow


class Workload(_Strict):
    arrival_process: ArrivalProcess
    # 셋 중 하나: job_template(일직선 사슬, 0.1~0.3 호환) / flow(갈라짐·합침, 0.4) / mix(여러 흐름 혼류, 0.4)
    job_template: list[JobStep] | None = Field(default=None, min_length=1)  # 앞 단계가 다음 단계의 선행 작업
    flow: JobFlow | None = None
    mix: list[MixItem] | None = Field(default=None, min_length=1)
    max_arrivals: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one_flow(self):
        if sum(x is not None for x in (self.job_template, self.flow, self.mix)) != 1:
            raise ValueError("workload needs exactly one of job_template, flow, mix")
        if self.mix is not None:
            prefixes = [m.flow.instance_prefix for m in self.mix]
            if len(set(prefixes)) != len(prefixes):
                raise ValueError("mix flows need distinct instance_prefix values")
        return self

    def capabilities(self) -> list[str]:
        if self.mix is not None:
            return [s.capability for m in self.mix for s in m.flow.steps]
        if self.flow is not None:
            return [s.capability for s in self.flow.steps]
        return [s.capability for s in self.job_template]


class FaultSpec(_Strict):
    """셀 고장 (숨겨진 참값). 원인과 계획된 종료 시각은 운영 주체에게 공개하지 않는다."""

    entity: str
    start_s: float = Field(ge=0)
    end_s: float
    units: int | None = Field(default=None, ge=1)  # None = 셀 용량 전체
    cause: str = Field(min_length=1)

    @model_validator(mode="after")
    def _order(self):
        if self.end_s <= self.start_s:
            raise ValueError("fault end_s must be after start_s")
        return self


class ConstraintSpec(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    kind: str


class ObjectiveSpec(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    kind: str


class Scenario(_Strict):
    schema_version: Literal["0.1", "0.2", "0.3", "0.4"]
    scenario_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    domain: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_.-]+$")  # 어댑터는 실행 시 레지스트리에서 고른다 (#33)
    seed: int
    sim_time_limit: PositiveFloat
    entities: list[EntitySpec] = Field(min_length=1)
    relations: list[RelationSpec] = Field(default_factory=list)
    workload: Workload
    faults: list[FaultSpec] = Field(default_factory=list)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    objectives: list[ObjectiveSpec] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _version_features(self):
        if self.schema_version == "0.1" and (
            self.faults or isinstance(self.workload.arrival_process, PiecewisePoissonArrival)
        ):
            raise ValueError("faults / piecewise_poisson require schema_version '0.2'")
        if self.schema_version not in ("0.3", "0.4") and any(e.reconfigurable for e in self.entities):
            raise ValueError("reconfigurable entities require schema_version '0.3' or later")
        if self.schema_version != "0.4" and (self.workload.flow is not None or self.workload.mix is not None):
            raise ValueError("workload.flow / workload.mix require schema_version '0.4'")
        return self

    @model_validator(mode="after")
    def _references(self):
        ids = [e.id for e in self.entities]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate entity ids")
        for r in self.relations:
            if r.source not in ids or r.target not in ids:
                raise ValueError(f"relation {r.source}->{r.target} references unknown entity")
        cap = {e.id: e.capacity for e in self.entities}
        for i, f in enumerate(self.faults):
            if f.entity not in cap:
                raise ValueError(f"fault {i} references unknown entity {f.entity!r}")
            if (f.units or cap[f.entity]) > cap[f.entity]:
                raise ValueError(f"fault {i} takes more units than {f.entity} has")
        # 같은 셀의 고장이 겹칠 때 합계가 용량을 넘지 않는지 (시각 순 스윕)
        for ent in cap:
            edges = []
            for f in self.faults:
                if f.entity == ent:
                    u = f.units or cap[ent]
                    edges += [(f.start_s, 1, u), (f.end_s, 0, -u)]  # 같은 시각이면 종료(0) 먼저
            load = 0
            for _, _, du in sorted(edges):
                load += du
                if load > cap[ent]:
                    raise ValueError(f"overlapping faults exceed capacity of {ent}")
        offered = {c for e in self.entities if e.capacity > 0 for c in e.capabilities}
        for capability in self.workload.capabilities():
            # 재구성으로만 제공 가능한 역할도 인정한다 (옵션에 있으면)
            options = {c for e in self.entities if e.reconfigurable for o in e.reconfigurable.options for c in o}
            if capability not in offered and capability not in options:
                raise ValueError(f"no entity with capacity offers capability {capability!r}")
        return self

    def canonical_dump(self) -> dict:
        """설정의 정규 표현. 나중에 추가된 선택 항목이 비어 있으면 빼서, 예전 시나리오의
        해시(→ run_id → 사건 로그 바이트)가 스키마 확장 전과 같게 유지한다 (#34)."""
        d = self.model_dump(mode="json")
        wl = d["workload"]
        for k in ("flow", "job_template", "mix"):
            if wl.get(k) is None:
                wl.pop(k, None)
        # 정규 형식은 시나리오가 선언한 스키마 버전을 따른다: 그 버전 뒤에 생긴 항목은 넣지 않는다.
        # (0.3 에서 생긴 entities[].reconfigurable 이 0.1/0.2 시나리오 해시를 바꿔 EXP-001 run_id·사건 로그
        #  바이트 재현을 깬 회귀를 바로잡음 — M5 #35 재현성 점검에서 발견)
        if self.schema_version in ("0.1", "0.2"):
            for e in d["entities"]:
                if e.get("reconfigurable") is None:
                    e.pop("reconfigurable", None)
        return d

    def config_hash(self) -> str:
        """시드를 제외한 설정의 해시. 시드는 manifest 에 따로 기록한다."""
        d = self.canonical_dump()
        d.pop("seed", None)
        blob = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_scenario(path: str | Path) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Scenario.model_validate(data)
