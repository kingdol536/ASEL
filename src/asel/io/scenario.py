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

SCENARIO_SCHEMA_VERSION = "0.1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntitySpec(_Strict):
    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    capabilities: list[str]
    capacity: int = Field(ge=0)
    properties: dict = Field(default_factory=dict)


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


class JobStep(_Strict):
    capability: str = Field(min_length=1)
    service_time: Distribution


class Workload(_Strict):
    arrival_process: PoissonArrival
    job_template: list[JobStep] = Field(min_length=1)  # 앞 단계가 다음 단계의 선행 작업
    max_arrivals: int | None = Field(default=None, ge=0)


class ConstraintSpec(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    kind: str


class ObjectiveSpec(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    kind: str


class Scenario(_Strict):
    schema_version: Literal["0.1"]
    scenario_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9._-]+$")
    domain: Literal["warehouse_like"]
    seed: int
    sim_time_limit: PositiveFloat
    entities: list[EntitySpec] = Field(min_length=1)
    relations: list[RelationSpec] = Field(default_factory=list)
    workload: Workload
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    objectives: list[ObjectiveSpec] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="after")
    def _references(self):
        ids = [e.id for e in self.entities]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate entity ids")
        for r in self.relations:
            if r.source not in ids or r.target not in ids:
                raise ValueError(f"relation {r.source}->{r.target} references unknown entity")
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
