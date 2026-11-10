"""Claude 정책 어댑터 (#11). 실제 API 는 부르지 않는다 — 가짜 클라이언트와 녹화 응답만 쓴다.

여기서 쓰는 '응답'은 테스트용으로 만든 가짜 응답이며 실제 모델 출력이 아니다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from asel.agents.claude_policy import (
    API_KEY_ENV,
    BudgetGuard,
    ClaudePolicy,
    ResponseCache,
    estimate_cost_usd,
)
from asel.io.eventlog import encode_events, encode_public
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from conftest import ROOT

SCEN = load_scenario(ROOT / "scenarios" / "warehouse-fault-a.yaml")
SHORT = SCEN.model_copy(update={"sim_time_limit": 900.0})


class FakeClient:
    """messages.create 를 흉내 낸다. 받은 요청을 기록하고, 후보에서 겹치지 않게 고른 응답을 만든다."""

    def __init__(self, mistake_every: int = 0, raise_exc=None, stop_reason="end_turn", text_override=None):
        self.requests: list[dict] = []
        self.mistake_every = mistake_every
        self.raise_exc = raise_exc
        self.stop_reason = stop_reason
        self.text_override = text_override
        self.messages = self

    def create(self, **req):
        self.requests.append(req)
        if self.raise_exc is not None:
            raise self.raise_exc
        payload = json.loads(req["messages"][0]["content"])
        free = {c["id"]: c["available"] for c in payload["observation"]["cells"]}
        used, picks = set(), []
        for spec in payload["allowed_actions"]:
            for cand in spec["candidates"]:
                if cand["task"] not in used and free.get(cand["entity"], 0) > 0:
                    free[cand["entity"]] -= 1
                    used.add(cand["task"])
                    picks.append(cand)
        n = len(self.requests)
        if self.mistake_every and n % self.mistake_every == 0 and picks:
            picks.append(dict(picks[0]))  # 같은 작업을 두 번 → 두 번째는 검증기가 거절해야 한다
        text = self.text_override or json.dumps({"assignments": picks, "reason": "fake: first fit"})
        return SimpleNamespace(
            model=req["model"],
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=900, output_tokens=60, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0),
        )


def _policy(tmp_path, client=None, mode="record", usd_cap=55.0, call_cap=None, cache=None):
    return ClaudePolicy(
        mode=mode,
        client=client,
        cache=cache or ResponseCache(tmp_path / "cache"),
        guard=BudgetGuard(tmp_path / "ledger.json", usd_cap=usd_cap, call_cap=call_cap),
    )


def test_default_mode_is_replay_and_needs_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    p = ClaudePolicy(cache=ResponseCache(tmp_path / "c"), guard=BudgetGuard(tmp_path / "l.json", 1.0))
    assert p.mode == "replay"
    res = run_scenario(SHORT, seed=1, policy=p)  # 캐시가 비었으니 전부 대체 정책, API 호출 0
    u = res.policy_usage
    assert u["api_calls"] == 0 and u["fallbacks"].get("cache_miss", 0) == u["decisions"] > 0


def test_record_then_replay_reproduces_events_without_api(tmp_path):
    fake = FakeClient()
    a = run_scenario(SHORT, seed=2, policy=_policy(tmp_path, fake))
    assert a.policy_usage["api_calls"] == len(fake.requests) > 0
    assert a.policy_usage["llm_decisions"] == a.policy_usage["decisions"]
    assert a.summary()["invariant_violations"] == 0 and a.summary()["actions_rejected"] == 0

    broken = FakeClient(raise_exc=AssertionError("replay must not call the API"))
    b = run_scenario(SHORT, seed=2, policy=_policy(tmp_path, broken, mode="replay"))
    assert encode_events(a.events) == encode_events(b.events)
    assert b.policy_usage["api_calls"] == 0 and b.policy_usage["cache_hits"] == a.policy_usage["api_calls"]


def test_invalid_proposals_are_rejected_not_applied(tmp_path):
    res = run_scenario(SHORT, seed=3, policy=_policy(tmp_path, FakeClient(mistake_every=2)))
    s = res.summary()
    assert s["actions_rejected"] > 0 and s["invariant_violations"] == 0


def test_prompt_contains_no_hidden_truth(tmp_path):
    fake = FakeClient()
    res = run_scenario(SCEN, seed=4, policy=_policy(tmp_path, fake))
    durations = [repr(t.duration) for t in res.world.state.tasks.values()]
    sent = json.dumps(fake.requests, ensure_ascii=False)
    for secret in ("conveyor jam", "motor overheat", "planned_end_s", '"duration"', "rate_per_min"):
        assert secret not in sent
    assert not any(d in sent for d in durations)


def test_budget_guard_stops_calls_and_never_exceeds_cap(tmp_path):
    fake = FakeClient()
    cap = 0.0012  # 가짜 사용량 기준 몇 번만 호출 가능한 상한
    res = run_scenario(SHORT, seed=5, policy=_policy(tmp_path, fake, usd_cap=cap))
    u = res.policy_usage
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert u["fallbacks"].get("budget_usd_cap", 0) > 0
    assert ledger["usd_spent"] <= cap and ledger["calls"] == u["api_calls"] == len(fake.requests)
    # 장부는 실행을 넘어 누적된다: 같은 장부로 다시 돌리면 더 호출하지 않는다
    fake2 = FakeClient()
    run_scenario(SHORT, seed=6, policy=_policy(tmp_path, fake2, usd_cap=cap))
    assert json.loads((tmp_path / "ledger.json").read_text())["usd_spent"] <= cap


def test_call_cap(tmp_path):
    fake = FakeClient()
    res = run_scenario(SHORT, seed=5, policy=_policy(tmp_path, fake, call_cap=3))
    assert len(fake.requests) == 3 and res.policy_usage["fallbacks"].get("budget_call_cap", 0) > 0


@pytest.mark.parametrize(
    "exc,reason",
    [
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.invalid")), "api_timeout"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.invalid")), "api_connection"),
    ],
)
def test_api_errors_fall_back(tmp_path, exc, reason):
    res = run_scenario(SHORT, seed=7, policy=_policy(tmp_path, FakeClient(raise_exc=exc)))
    u = res.policy_usage
    assert u["fallbacks"].get(reason, 0) == u["decisions"] > 0 and u["api_calls"] == 0
    assert res.summary()["invariant_violations"] == 0


@pytest.mark.parametrize("kw,reason", [({"stop_reason": "refusal"}, "stop_refusal"),
                                       ({"stop_reason": "max_tokens"}, "stop_max_tokens"),
                                       ({"text_override": "not json"}, "bad_output")])
def test_bad_responses_fall_back(tmp_path, kw, reason):
    res = run_scenario(SHORT, seed=8, policy=_policy(tmp_path, FakeClient(**kw)))
    assert res.policy_usage["fallbacks"].get(reason, 0) > 0


def test_api_key_never_written(tmp_path, monkeypatch):
    secret = "sk-ant-TEST-do-not-log-0123456789"
    monkeypatch.setenv(API_KEY_ENV, secret)
    from asel.agents.claude_policy import make_client

    client = make_client()  # 실제 클라이언트 객체 생성만 (네트워크 호출 없음)
    pol = _policy(tmp_path, FakeClient())
    res = run_scenario(SHORT, seed=9, policy=pol)
    run_dir = write_run(res, tmp_path / "runs")
    blobs = [p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()]
    assert all(secret.encode() not in b for b in blobs)
    assert secret not in json.dumps(pol.usage()) and secret not in repr(pol)
    assert secret not in encode_public(res.events).decode()
    assert client is not None and (run_dir / "manifest.json").exists()


def test_cost_estimate_uses_price_table():
    # Haiku 5.5: 프롬프트 100K 이하 $0.10/$0.50, 초과 $0.50/$2.50 (1M 토큰당)
    assert estimate_cost_usd("claude-haiku-5-5", 50_000, 0) == pytest.approx(0.005)
    assert estimate_cost_usd("claude-haiku-5-5", 1_000, 1_000_000) == pytest.approx(0.5001)
    assert estimate_cost_usd("claude-haiku-5-5", 200_000, 0) == pytest.approx(0.10)  # 상위 단가 0.50 x 0.2
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000) == pytest.approx(12.0)
    with pytest.raises(ValueError):
        ClaudePolicy(model="claude-unknown")


def test_manifest_records_policy_usage(tmp_path):
    res = run_scenario(SHORT, seed=1, policy=_policy(tmp_path, FakeClient()))
    m = json.loads((write_run(res, tmp_path / "runs") / "manifest.json").read_text(encoding="utf-8"))
    assert m["policy"]["name"] == "claude" and m["policy"]["usage"]["model"] == "claude-haiku-5-5"
    assert m["policy"]["usage"]["api_key_env"] == API_KEY_ENV
