"""Claude 구조 제어 정책 (EXP-003 #45). 실제 API 호출 없음 — 가짜 클라이언트만 쓴다.

여기서 쓰는 '응답'은 테스트용으로 만든 가짜 응답이며 실제 모델 출력이 아니다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from asel.agents.claude_policy import BudgetGuard, ResponseCache
from asel.agents.claude_structure import ClaudeStructurePolicy
from asel.evaluation.evaluator import EVAL_COLUMNS, eval_row, evaluate_run
from asel.io.eventlog import encode_events
from asel.io.scenario import load_scenario
from asel.policies.structure import make_structure_policy
from asel.runner import run_scenario, write_run
from conftest import ROOT

B = load_scenario(ROOT / "scenarios" / "assembly-line-b.yaml").model_copy(update={"sim_time_limit": 900.0})
C = load_scenario(ROOT / "scenarios" / "it-service-c.yaml").model_copy(update={"sim_time_limit": 400.0})


class FakeStructureClient:
    """처음 보는 후보로 전환하거나(switch_first), 아무것도 안 하거나, 정해진 텍스트를 돌려준다."""

    def __init__(self, behaviour="switch_first", text=None):
        self.behaviour, self.text, self.requests = behaviour, text, []
        self.messages = self

    def create(self, **req):
        self.requests.append(req)
        payload = json.loads(req["messages"][0]["content"])
        cands = [c for s in payload["allowed_actions"] for c in s["candidates"]]
        if self.text is not None:
            text = self.text
        elif self.behaviour == "switch_first" and cands:
            text = json.dumps({"decision": "switch", "entity": cands[0]["entity"],
                               "capabilities": cands[0]["capabilities"], "reason": "fake"})
        elif self.behaviour == "bogus":
            text = json.dumps({"decision": "switch", "entity": "nope", "capabilities": ["x"], "reason": "fake"})
        else:
            text = json.dumps({"decision": "none", "entity": "", "capabilities": [], "reason": "fake"})
        return SimpleNamespace(
            model=req["model"], stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=50, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0),
        )


def spol(tmp_path, client, mode="record", interval=30.0, model="claude-haiku-5-5"):
    return ClaudeStructurePolicy(model=model, name="claude-haiku", mode=mode, client=client,
                                 decision_interval_s=interval, cache=ResponseCache(tmp_path / "cache"),
                                 guard=BudgetGuard(tmp_path / "l.json", usd_cap=5.0))


def test_switch_is_applied_and_calls_are_rate_limited(tmp_path):
    fake = FakeStructureClient("switch_first")
    res = run_scenario(B, seed=1, structure_policy=spol(tmp_path, fake))
    s, u = res.summary(), res.structure_usage
    assert s["invariant_violations"] == 0 and s["actions_rejected"] == 0
    assert any(e.event_type == "ReconfigurationCompleted" for e in res.events)
    # 호출 사이 모의 시간 간격 >= 30s
    times = [json.loads(r["messages"][0]["content"])["observation"]["sim_time"] for r in fake.requests]
    assert times and all(b - a >= 30.0 for a, b in zip(times, times[1:]))
    assert u["api_calls"] == len(fake.requests)
    sent = json.dumps(fake.requests, ensure_ascii=False)
    assert '"duration"' not in sent and "warehouse" not in sent.lower()


@pytest.mark.parametrize("text", ["[]", '"none"', "3"])
def test_non_object_json_output_falls_back_instead_of_crashing(tmp_path, text):
    """형식은 JSON 이지만 객체가 아닌 응답도 '형식 오류'로 대체한다 (실행 전체가 멈추면 안 된다)."""
    res = run_scenario(C, seed=5, structure_policy=spol(tmp_path, FakeStructureClient(text=text)))
    u = res.structure_usage
    assert u["fallbacks"].get("bad_output", 0) == u["api_calls"] > 0
    assert not any(e.event_type.startswith("Reconfiguration") for e in res.events)


def test_request_time_limits_are_not_sent_to_claude(tmp_path):
    """C 의 요청 시간 제한(흐름별 timeout_s)은 구조 제어 프롬프트에 없다 (EXP-003 계획서 §3.2 의 정보 조건)."""
    assert '"timeout_s"' in json.dumps(C.canonical_dump()["workload"])  # C 에는 시간 제한이 있다
    fake = FakeStructureClient("none")
    run_scenario(C, seed=4, structure_policy=spol(tmp_path, fake))
    sent = json.dumps(fake.requests, ensure_ascii=False).lower()
    assert fake.requests and "timeout" not in sent and "deadline" not in sent


def test_none_decision_keeps_structure_fixed(tmp_path):
    fake = FakeStructureClient("none")
    res = run_scenario(C, seed=2, structure_policy=spol(tmp_path, fake))
    assert not any(e.event_type.startswith("Reconfiguration") for e in res.events)
    # 후보는 사건마다 있지만 묻는 것은 30s 에 한 번: 400s 면 많아야 14번
    assert 0 < len(fake.requests) <= 14 and res.structure_usage["skipped_interval"] > 0


def test_invalid_switch_rejected_and_counted(tmp_path):
    res = run_scenario(B, seed=3, structure_policy=spol(tmp_path, FakeStructureClient("bogus")))
    assert res.summary()["actions_rejected"] > 0 and res.summary()["invariant_violations"] == 0
    run_dir = write_run(res, tmp_path / "runs")
    ev = evaluate_run(run_dir)
    sc = ev["structure_control"]
    assert sc["decisions"]["invalid_proposal_rate"] == 1.0 and sc["cost"]["api_calls"] > 0
    row = eval_row(ev)
    assert set(row) == set(EVAL_COLUMNS) and row["s_invalid_rate"] == 1.0


@pytest.mark.parametrize("text", ["not json", json.dumps({"decision": "maybe", "entity": "", "capabilities": [], "reason": ""})])
def test_bad_output_falls_back_to_no_switch(tmp_path, text):
    res = run_scenario(B, seed=4, structure_policy=spol(tmp_path, FakeStructureClient(text=text)))
    assert not any(e.event_type.startswith("Reconfiguration") for e in res.events)
    assert res.structure_usage["fallbacks"].get("bad_output", 0) > 0


def test_record_then_replay_is_byte_identical(tmp_path):
    a = run_scenario(C, seed=5, structure_policy=spol(tmp_path, FakeStructureClient("switch_first")))
    b = run_scenario(C, seed=5, structure_policy=spol(tmp_path, FakeStructureClient(text="unused"), mode="replay"))
    assert encode_events(a.events) == encode_events(b.events)
    assert b.structure_usage["api_calls"] == 0 and b.structure_usage["cache_hits"] > 0


def test_registry_names_and_default_replay(monkeypatch, tmp_path):
    monkeypatch.setenv("ASEL_LLM_DIR", str(tmp_path))
    monkeypatch.delenv("ASEL_LLM_MODE", raising=False)
    p = make_structure_policy("claude-sonnet")
    assert p.model == "claude-sonnet-5-5" and p.mode == "replay" and p.name == "claude-sonnet"
    res = run_scenario(C, seed=1, structure_policy=p)  # 캐시 없음 → 전부 '전환 안 함', 호출 0
    assert res.structure_usage["api_calls"] == 0
    assert not any(e.event_type.startswith("Reconfiguration") for e in res.events)
