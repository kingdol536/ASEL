"""정책 연결 규약과 정답 누출 테스트 (#9, docs/04 §7) + 기준선 정책 (#10)."""

from __future__ import annotations

import json

import pytest

from asel.core.actions import ActionKind
from asel.core.model import TaskStatus
from asel.io.eventlog import encode_public
from asel.io.scenario import load_scenario
from asel.policies.baselines import FirstCandidatePolicy, OrderAgePolicy
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext
from asel.policies.fifo import FifoPolicy
from asel.runner import run_scenario
from conftest import ROOT
from test_reproducibility import _run_with, fifo_runtime

SCEN = {n: load_scenario(ROOT / "scenarios" / f"warehouse-{n}-a.yaml") for n in ("small", "surge", "fault")}

HIDDEN_KEYS = {"duration", "cause", "planned_end_s", "fault", "fault_index", "action_private", "private"}
SCENARIO_KEYS = {"rate_per_min", "segments", "arrival_process", "faults", "service_time", "mean_s"}


class Recorder:
    """다른 정책을 감싸 정책이 받은 입력을 모두 기록한다."""

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.calls: list[tuple[Observation, list[ActionSpec]]] = []
        self.context: PolicyContext | None = None

    def reset(self, context):
        self.context = context
        self.inner.reset(context)

    def decide(self, obs, aff):
        self.calls.append((obs, aff))
        return self.inner.decide(obs, aff)

    def usage(self):
        return {}


def _keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _keys(v, out)
    return out


def _only_json_values(obj) -> bool:
    if isinstance(obj, dict):
        return all(isinstance(k, str) and _only_json_values(v) for k, v in obj.items())
    if isinstance(obj, (list, tuple)):
        return all(_only_json_values(v) for v in obj)
    return obj is None or isinstance(obj, (str, int, float, bool))


@pytest.fixture(scope="module")
def recorded():
    out = {}
    for name, sc in SCEN.items():
        rec = Recorder(FifoPolicy())
        res = run_scenario(sc, seed=5, policy=rec)
        out[name] = (rec, res)
    return out


# ---- docs/04 §7 정보 유출 자동 테스트 4종 -----------------------------------------


def test_leak1_observation_has_no_private_keys_or_values(recorded):
    for name, (rec, res) in recorded.items():
        assert rec.calls, name
        durations = [repr(t.duration) for t in res.world.state.tasks.values()]
        causes = [f.cause for f in SCEN[name].faults]
        for obs, aff in rec.calls:
            payload = {"obs": obs.to_dict(), "aff": [a.to_dict() for a in aff]}
            assert not (_keys(payload, set()) & HIDDEN_KEYS), name
            text = json.dumps(payload, ensure_ascii=False)
            assert not any(d in text for d in durations), name
            assert not any(c in text for c in causes), name


def test_leak2_policy_gets_only_plain_values_no_state_access(recorded):
    """정책 입력은 순수 JSON 값뿐이다. World·WorldState·Task 객체 참조나 숨겨진 상태 조회 수단이 없다."""
    for name, (rec, _) in recorded.items():
        assert rec.context is not None and set(vars(rec.context)) == {"actor_id", "run_id", "permitted_actions"}
        for obs, aff in rec.calls:
            assert type(obs) is Observation and all(type(a) is ActionSpec for a in aff)
            assert _only_json_values(obs.to_dict()) and _only_json_values([a.to_dict() for a in aff])
    for cls in (Observation, ActionSpec, PolicyContext):
        assert not any("hidden" in m or "state" in m for m in dir(cls) if not m.startswith("_"))


def test_leak3_no_future_information(recorded):
    """관측에는 이미 일어난 일만 있다: 아직 도착하지 않은 주문, 도착률·고장 일정이 없다."""
    for name, (rec, _) in recorded.items():
        for obs, _aff in rec.calls:
            assert all(t["created_at"] <= obs.sim_time for t in obs.open_tasks)
            assert all(t["started_at"] is None or t["started_at"] <= obs.sim_time for t in obs.open_tasks)
            assert not (_keys(obs.to_dict(), set()) & SCENARIO_KEYS)
    # 고장 구간이 '계획된 종료'를 드러내지 않는다: 고장 중 관측은 고장 단위 수만 보인다
    rec, _ = recorded["fault"]
    in_outage = [o for o, _ in rec.calls if 1200 <= o.sim_time < 1500]
    assert in_outage and all(
        next(c for c in o.cells if c["id"] == "cell-pack-1")["out_of_service"] == 1 for o in in_outage
    )


def test_leak4_public_log_of_policy_run_has_no_private(recorded):
    for name, (_rec, res) in recorded.items():
        text = encode_public(res.events).decode()
        assert not any(f'"{k}"' in text for k in ("duration", "cause", "planned_end_s", "action_private")), name


# ---- 런타임 규약 ------------------------------------------------------------------


class Malicious:
    """권한 밖 행동·잘못된 형식을 제안하는 정책. 모두 검증기에서 거절돼야 한다."""

    name = "malicious"

    def reset(self, context):
        pass

    def decide(self, obs, aff):
        tid = next(t["id"] for t in obs.open_tasks if t["status"] == "READY")
        return [
            ActionProposal(ActionKind.COMPLETE_TASK, {"task": tid}),
            ActionProposal(ActionKind.BEGIN_OUTAGE, {"entity": "cell-pack-1", "units": 1}),
            ActionProposal(ActionKind.CREATE_TASK, {"id": "x", "capability": "pick"}),
            ActionProposal("teleport", {}),
            ActionProposal(ActionKind.START_TASK, ["not", "a", "dict"]),
        ]

    def usage(self):
        return {}


def test_malicious_policy_cannot_change_world():
    res = run_scenario(SCEN["small"], seed=1, policy=Malicious())
    st = res.world.state
    assert res.summary()["invariant_violations"] == 0
    assert all(t.status in (TaskStatus.READY, TaskStatus.WAITING) for t in st.tasks.values())
    assert all(r.out_of_service == 0 for r in st.resources.values())
    assert res.summary()["actions_rejected"] > 0
    # 행동 주체는 런타임이 붙인다
    assert {e.actor_id for e in res.events if e.event_type == "ActionRejected"} == {"policy.malicious"}


def test_fifo_policy_equals_legacy_state_dispatcher():
    """관측 기반 FIFO 가 M1/M2 의 상태 기반 FIFO 와 같은 결과를 낸다 (이전 결과와의 연속성)."""

    class LegacyFifo:
        actor_id = "policy.fifo"

        def propose(self, state):
            from asel.core.actions import Action

            ready = sorted(
                (t for t in state.tasks.values() if t.status == TaskStatus.READY),
                key=lambda t: (t.ready_at, t.created_index),
            )
            free = {rid: r.available for rid, r in state.resources.items()}
            out = []
            for t in ready:
                for e in sorted(state.entities.values(), key=lambda e: e.id):
                    if t.capability in e.capabilities and free.get(e.id, 0) > 0:
                        free[e.id] -= 1
                        out.append(Action(self.actor_id, ActionKind.START_TASK, {"task": t.id, "entity": e.id}))
                        break
            return out

    for sc in SCEN.values():
        for seed in (0, 7):
            a = _run_with(sc, LegacyFifo(), seed)
            b = _run_with(sc, fifo_runtime(), seed)
            assert a.snapshot() == b.snapshot()


def test_no_policy_call_without_candidates(recorded):
    for _name, (rec, _res) in recorded.items():
        for _obs, aff in rec.calls:
            assert any(spec.candidates for spec in aff)


# ---- 기준선 정책 (#10) -------------------------------------------------------------


@pytest.mark.parametrize("policy", ["fifo", "order-age", "first-candidate"])
@pytest.mark.parametrize("scen", ["small", "surge", "fault"])
def test_baselines_run_clean(policy, scen):
    res = run_scenario(SCEN[scen], seed=3, policy=policy)
    s = res.summary()
    assert s["invariant_violations"] == 0 and s["actions_rejected"] == 0
    assert s["tasks_by_status"].get("COMPLETED", 0) > 0


def test_order_age_differs_from_fifo_but_same_workload():
    sc = SCEN["surge"]
    a = run_scenario(sc, seed=2, policy="fifo").world.state
    b = run_scenario(sc, seed=2, policy="order-age").world.state
    assert {k: (t.created_at, t.duration) for k, t in a.tasks.items()} == {
        k: (t.created_at, t.duration) for k, t in b.tasks.items()
    }
    assert {k: t.started_at for k, t in a.tasks.items()} != {k: t.started_at for k, t in b.tasks.items()}


def test_order_age_prefers_oldest_order():
    obs = Observation(
        "p",
        100.0,
        5,
        cells=({"id": "pack", "type": "w", "capabilities": ["pack"], "capacity": 1, "reserved": 0,
                "out_of_service": 0, "available": 1},),
        relations=(),
        open_tasks=(
            {"id": "new/1-pack", "capability": "pack", "status": "READY", "order": "new", "step": 1,
             "predecessors": [], "created_at": 50.0, "created_index": 9, "ready_at": 60.0,
             "started_at": None, "assigned_entity": None},
            {"id": "old/1-pack", "capability": "pack", "status": "READY", "order": "old", "step": 1,
             "predecessors": [], "created_at": 10.0, "created_index": 3, "ready_at": 90.0,
             "started_at": None, "assigned_entity": None},
        ),
        completed_tasks=0,
    )
    assert OrderAgePolicy().decide(obs, [])[0].params["task"] == "old/1-pack"
    assert FifoPolicy().decide(obs, [])[0].params["task"] == "new/1-pack"


def test_first_candidate_never_overbooks():
    for seed in range(5):
        res = run_scenario(SCEN["fault"], seed=seed, policy=FirstCandidatePolicy())
        assert res.summary()["actions_rejected"] == 0
