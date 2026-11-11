"""AI 즉시 연결 (#39): 코드 수정 없이 Claude 정책(중립 프롬프트 v2)을 환경 B·C 에 연결한다.

실제 API 호출 없음 — 가짜 클라이언트와 녹화 응답만 쓴다 (실제 호출은 EXP-003 승인 후).
"""

from __future__ import annotations

import json

import pytest

from asel.agents.claude_policy import BudgetGuard, ClaudePolicy, ResponseCache
from asel.io.eventlog import encode_events
from asel.io.scenario import Scenario, load_scenario
from asel.runner import run_scenario
from conftest import ROOT
from test_claude_policy import FakeClient

B = load_scenario(ROOT / "scenarios" / "assembly-line-b.yaml").model_copy(update={"sim_time_limit": 900.0})
C = load_scenario(ROOT / "scenarios" / "it-service-c.yaml").model_copy(update={"sim_time_limit": 240.0})


def claude(tmp_path, client, mode="record"):
    return ClaudePolicy(mode=mode, client=client, prompt_version="v2-neutral",
                        cache=ResponseCache(tmp_path / "cache"), guard=BudgetGuard(tmp_path / "l.json", usd_cap=5.0))


@pytest.mark.parametrize("sc", [B, C], ids=["B-assembly", "C-it-service"])
def test_claude_connects_without_code_changes(tmp_path, sc):
    fake = FakeClient()
    res = run_scenario(sc, seed=1, policy=claude(tmp_path, fake))
    s, u = res.summary(), res.policy_usage
    assert s["invariant_violations"] == 0 and s["actions_rejected"] == 0
    assert u["llm_decisions"] == u["decisions"] > 0 and u["prompt_version"] == "v2-neutral"
    sent = json.dumps(fake.requests, ensure_ascii=False)
    assert "warehouse" not in sent.lower()  # 산업 중립 프롬프트
    # 숨겨진 참값(실제 처리 시간)이 프롬프트에 없다: 키 이름 + 우연히 겹칠 수 없는 긴 난수 값으로 확인
    # (0.2 같은 짧은 상수 처리 시간은 다른 시각 값의 일부로 우연히 나타날 수 있어 값 비교에서 뺀다)
    assert '"duration"' not in sent
    long_vals = [repr(t.duration) for t in res.world.state.tasks.values() if len(repr(t.duration)) >= 8]
    assert long_vals and not any(v in sent for v in long_vals)


def test_invalid_llm_proposals_rejected_on_new_env(tmp_path):
    res = run_scenario(B, seed=2, policy=claude(tmp_path, FakeClient(mistake_every=2)))
    assert res.summary()["actions_rejected"] > 0 and res.summary()["invariant_violations"] == 0


def test_record_then_replay_on_new_env(tmp_path):
    a = run_scenario(C, seed=3, policy=claude(tmp_path, FakeClient()))
    b = run_scenario(C, seed=3, policy=claude(tmp_path, FakeClient(raise_exc=AssertionError()), mode="replay"))
    assert encode_events(a.events) == encode_events(b.events)


def test_objective_reaches_llm_but_scores_do_not(tmp_path):
    d = B.canonical_dump()
    d["objective_schedule"] = [{"at_s": 0, "id": "rush-B", "kind": "priority", "params": {"flow": "prodB"}}]
    sc = Scenario.model_validate(d)
    fake = FakeClient()
    run_scenario(sc, seed=1, policy=claude(tmp_path, fake))
    sent = json.dumps(fake.requests, ensure_ascii=False)
    assert "rush-B" in sent and "prodB" in sent  # 목표는 공개 정보로 전달
    assert "target_flow_mean" not in sent and "completed_per_hour" not in sent  # 채점식·값은 없다


def test_claude_with_structure_controller_on_3d_env(tmp_path):
    sc = load_scenario(ROOT / "scenarios" / "assembly-line-b-3d.yaml").model_copy(update={"sim_time_limit": 900.0})
    res = run_scenario(sc, seed=0, policy=claude(tmp_path, FakeClient()), structure_policy="p1")
    assert res.summary()["invariant_violations"] == 0
    assert res.world.state.entities["press-2"].capabilities == ("press-B",)
