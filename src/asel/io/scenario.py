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

SCENARIO_SCHEMA_VERSION = "0.3"  # 0.2: faults, piecewise_poisson / 0.3: reconfigurable


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


class Workload(_Strict):
    arrival_process: ArrivalProcess
    job_template: list[JobStep] = Field(min_length=1)  # 앞 단계가 다음 단계의 선행 작업
    max_arrivals: int | None = Field(default=None, ge=0)


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
    schema_version: Literal["0.1", "0.2", "0.3"]
    scenario_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    domain: Literal["warehouse_like"]
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
        if self.schema_version != "0.3" and any(e.reconfigurable for e in self.entities):
            raise ValueError("reconfigurable entities require schema_version '0.3'")
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
        for step in self.workload.job_template:
            if step.capability not in offered:
                raise ValueError(f"no entity with capacity offers capability {step.capability!r}")
        return self

    def config_hash(self) -> str:
        """시드를 제외한 설정의 해시. 시드는 manifest 에 따로 기록한다."""
        d = self.model_dump(mode="json", exclude={"seed"})
        blob = json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_scenario(path: str | Path) -> Scenario:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Scenario.model_validate(data)
