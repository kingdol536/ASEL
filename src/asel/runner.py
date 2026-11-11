"""headless 실행: scenario + seed -> 이벤트 로그 / 최종 상태 / manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from asel.core.actions import ActionKind
from asel.core.events import SCHEMA_VERSION, Event, EventType
from asel.core.invariants import check_invariants
from asel.core.simulator import Simulator
from asel.core.world import ENV_ACTOR, World
from asel.domains import get_adapter
from asel.io.eventlog import dumps_canonical, events_sha256, write_run_logs
from asel.io.manifest import code_revision, environment_info
from asel.io.scenario import Scenario
from asel.policies.contract import PolicyRuntime
from asel.policies.registry import make_policy

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RunResult:
    run_id: str
    scenario: Scenario
    seed: int
    world: World
    started_utc: str
    finished_utc: str
    policy_name: str = "fifo"
    policy_actor: str = "policy.fifo"
    policy_usage: dict | None = None
    structure_name: str | None = None
    structure_actor: str | None = None
    structure_usage: dict | None = None

    @property
    def events(self) -> list[Event]:
        return self.world.log

    def summary(self) -> dict:
        """단순 집계(평가 지표 아님). 평가는 M3 의 독립 평가기 몫이다."""
        st = self.world.state
        by_status: dict[str, int] = {}
        for t in st.tasks.values():
            by_status[str(t.status)] = by_status.get(str(t.status), 0) + 1
        etypes: dict[str, int] = {}
        for e in self.events:
            etypes[e.event_type] = etypes.get(e.event_type, 0) + 1
        return {
            "sim_time_end": st.sim_time,
            "world_version": st.version,
            "events": len(self.events),
            "event_types": dict(sorted(etypes.items())),
            "tasks_by_status": dict(sorted(by_status.items())),
            "actions_rejected": etypes.get(EventType.ACTION_REJECTED, 0),
            "invariant_violations": len(check_invariants(st)),
        }


ENV_ACTIONS = frozenset(
    {
        ActionKind.CREATE_TASK,
        ActionKind.COMPLETE_TASK,
        ActionKind.BEGIN_OUTAGE,
        ActionKind.END_OUTAGE,
        ActionKind.COMPLETE_RECONFIGURATION,
    }
)
DISPATCH_ACTIONS = (ActionKind.START_TASK,)
STRUCTURE_ACTIONS = (ActionKind.REQUEST_RECONFIGURATION,)


def default_grants(dispatcher_id: str, structure_id: str | None = None) -> dict[str, frozenset[str]]:
    """최소 권한 표 (잠정, 결정 0006): 환경은 작업 생성·완료·고장·전환 완료, 배정기는 작업 시작만,
    구조 제어 주체는 재구성 요청만. 역할 구성은 설정이며 코어에 고정하지 않는다."""
    g = {ENV_ACTOR: ENV_ACTIONS, dispatcher_id: frozenset(DISPATCH_ACTIONS)}
    if structure_id:
        g[structure_id] = frozenset(STRUCTURE_ACTIONS)
    return g


def make_run_id(sc: Scenario, seed: int, policy_name: str = "fifo") -> str:
    return f"{sc.scenario_id}__{policy_name}__seed{seed}__cfg{sc.config_hash()[:8]}"


def run_scenario(
    sc: Scenario,
    seed: int | None = None,
    check_invariants: bool = True,
    policy: str | object = "fifo",
    structure_policy: str | object | None = None,
) -> RunResult:
    """policy: 배정 정책(이름 또는 객체). structure_policy: 구조 제어 정책(선택, #21).
    두 정책은 서로 다른 주체로 실행되고 각자 관측만 받는다. 구조 제어가 먼저 결정한다."""
    seed = sc.seed if seed is None else seed
    pol = make_policy(policy) if isinstance(policy, str) else policy
    spol = None
    if structure_policy is not None:
        from asel.policies.structure import make_structure_policy

        spol = make_structure_policy(structure_policy) if isinstance(structure_policy, str) else structure_policy
    run_id = make_run_id(sc, seed, pol.name if spol is None else f"{pol.name}+{spol.name}")
    started = datetime.now(UTC).isoformat(timespec="seconds")

    runtime = PolicyRuntime(pol, actor_id=f"policy.{pol.name}", permitted=DISPATCH_ACTIONS)
    sruntime = (
        PolicyRuntime(spol, actor_id=f"structure.{spol.name}", permitted=STRUCTURE_ACTIONS) if spol else None
    )
    world = World(run_id, grants=default_grants(runtime.actor_id, sruntime.actor_id if sruntime else None))
    adapter = get_adapter(sc.domain)  # 도메인 어댑터 (#33)
    world.initialize(*adapter.world_init_payload(sc))
    runtime.reset(run_id)
    if sruntime:
        sruntime.reset(run_id)
    deciders = [sruntime, runtime] if sruntime else runtime
    sim = Simulator(world, adapter.workload(sc, seed), deciders, check_invariants=check_invariants)
    sim.run(until=sc.sim_time_limit)

    finished = datetime.now(UTC).isoformat(timespec="seconds")
    return RunResult(
        run_id, sc, seed, world, started, finished, pol.name, runtime.actor_id, runtime.usage(),
        spol.name if spol else None, sruntime.actor_id if sruntime else None, sruntime.usage() if sruntime else None,
    )


def write_run(res: RunResult, out_root: Path, code: dict | None = None) -> Path:
    return write_run_detailed(res, out_root, code)[0]


def write_run_detailed(
    res: RunResult, out_root: Path, code: dict | None = None, extra: dict | None = None
) -> tuple[Path, dict]:
    """실행 폴더를 쓰고 (경로, manifest) 를 돌려준다.
    code: 코드 리비전. 배치처럼 여러 실행을 쓸 때는 한 번만 구해서 넘긴다(git 조회 반복 방지)."""
    stamp = datetime.fromisoformat(res.started_utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_root / res.scenario.scenario_id / f"{res.run_id}__{stamp}"
    run_dir.mkdir(parents=True, exist_ok=False)

    log_hashes = write_run_logs(res.events, run_dir)
    (run_dir / "final_state.json").write_text(
        dumps_canonical(res.world.state.snapshot()) + "\n", encoding="utf-8", newline="\n"
    )
    (run_dir / "scenario.json").write_text(
        dumps_canonical(res.scenario.canonical_dump()) + "\n", encoding="utf-8", newline="\n"
    )
    manifest = {
        "run_id": res.run_id,
        "scenario_id": res.scenario.scenario_id,
        "seed": res.seed,
        "config_hash": res.scenario.config_hash(),
        "event_schema_version": SCHEMA_VERSION,
        "scenario_schema_version": res.scenario.schema_version,
        **log_hashes,
        "code": code if code is not None else code_revision(REPO_ROOT),
        "environment": environment_info(),
        "policy": {"name": res.policy_name, "actor_id": res.policy_actor, "usage": res.policy_usage or {}},
        "structure_policy": (
            {"name": res.structure_name, "actor_id": res.structure_actor, "usage": res.structure_usage or {}}
            if res.structure_name else None
        ),
        "evaluator": None,  # M3 에서 도입
        "started_utc": res.started_utc,
        "finished_utc": res.finished_utc,
        "summary": res.summary(),
    }
    if extra:
        manifest["extra"] = extra  # 예: 실험 계획서 커밋 해시 (EXP-002 사전 고정 증거)
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return run_dir, manifest


def check_events_hash(res: RunResult) -> str:
    return events_sha256(res.events)
