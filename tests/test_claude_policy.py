"""Claude 정책 어댑터 (#11). 실제 API 는 부르지 않는다 — 가짜 클라이언트와 녹화 응답만 쓴다.

여기서 쓰는 '응답'은 테스트용으로 만든 가짜 응답이며 실제 모델 출력이 아니다.
"""

from __future__ import annotations

import json
import time
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
    cap = 0.005  # 최악 비용 예약(약 $0.003) 기준으로 몇 번만 호출 가능한 상한
    res = run_scenario(SHORT, seed=5, policy=_policy(tmp_path, fake, usd_cap=cap))
    u = res.policy_usage
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    assert u["fallbacks"].get("budget_usd_cap", 0) > 0
    assert 0 < len(fake.requests) == u["api_calls"]
    assert ledger["usd_spent"] <= cap and ledger["usd_reserved"] == 0
    assert ledger["calls"] == 2 * len(fake.requests)  # 요청당 시도 수 = max_retries(1) + 1
    # 장부는 실행을 넘어 누적된다: 같은 장부로 다시 돌리면 더 호출하지 않는다
    fake2 = FakeClient()
    run_scenario(SHORT, seed=6, policy=_policy(tmp_path, fake2, usd_cap=cap))
    assert json.loads((tmp_path / "ledger.json").read_text())["usd_spent"] <= cap


def test_call_cap(tmp_path):
    fake = FakeClient()
    # 상한은 SDK 재시도까지 포함한 '시도 수'다: 요청당 2회 → 상한 6 이면 요청 3번
    res = run_scenario(SHORT, seed=5, policy=_policy(tmp_path, fake, call_cap=6))
    assert len(fake.requests) == 3 and res.policy_usage["fallbacks"].get("budget_call_cap", 0) > 0


class FlakyClient(FakeClient):
    """세 번째 요청마다 타임아웃."""

    def create(self, **req):
        if (len(self.requests) + 1) % 3 == 0:
            self.requests.append(req)
            raise anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.invalid"))
        return super().create(**req)


def test_replay_identical_even_when_record_run_had_failures(tmp_path):
    """녹화 중 실패(대체 결정)가 있었어도 재생 사건 로그가 바이트 동일하다 (리뷰 지적 #1)."""
    a = run_scenario(SHORT, seed=11, policy=_policy(tmp_path, FlakyClient()))
    assert a.policy_usage["fallbacks"].get("api_timeout", 0) > 0
    b = run_scenario(SHORT, seed=11, policy=_policy(tmp_path, FakeClient(raise_exc=AssertionError()), mode="replay"))
    assert b.policy_usage["fallbacks"].get("cache_miss", 0) == a.policy_usage["fallbacks"]["api_timeout"]
    assert encode_events(a.events) == encode_events(b.events)


def test_timeout_is_charged_conservatively(tmp_path):
    pol = _policy(tmp_path, FlakyClient())
    res = run_scenario(SHORT, seed=11, policy=pol)
    u = res.policy_usage
    ledger = json.loads((tmp_path / "ledger.json").read_text())
    # 타임아웃은 예약한 최악 비용 전부가 지출로 남는다 → 장부 지출 = 실제 사용량 추정 + 불명 비용
    assert u["usd_charged_unknown"] > 0
    assert ledger["usd_spent"] == pytest.approx(u["usd_estimate"] + u["usd_charged_unknown"], rel=1e-6)


def test_usage_resets_per_run_when_policy_object_is_reused(tmp_path):
    pol = _policy(tmp_path, FakeClient())
    a = run_scenario(SHORT, seed=1, policy=pol).policy_usage
    b = run_scenario(SHORT, seed=1, policy=pol).policy_usage  # 같은 객체, 두 번째는 캐시 적중
    assert b["api_calls"] == 0 and b["cache_hits"] == a["api_calls"] and b["decisions"] == a["decisions"]
    assert a["served_models"] == b["served_models"] == ["claude-haiku-5-5"]


def test_cache_tag_separates_recordings(tmp_path):
    run_scenario(SHORT, seed=1, policy=_policy(tmp_path, FakeClient()))
    pol = _policy(tmp_path, FakeClient(raise_exc=AssertionError()), mode="replay")
    pol.cache_tag = "v2"
    u = run_scenario(SHORT, seed=1, policy=pol).policy_usage
    assert u["cache_hits"] == 0 and u["fallbacks"].get("cache_miss", 0) > 0


def test_ledger_lock_serializes_reservations(tmp_path):
    """두 장부 객체(=두 프로세스 흉내)가 같은 파일에 예약해도 상한을 넘지 않는다."""
    g1 = BudgetGuard(tmp_path / "l.json", usd_cap=1.0)
    g2 = BudgetGuard(tmp_path / "l.json", usd_cap=1.0)
    ok1, rid1 = g1.reserve(0.6)
    assert ok1 is True
    assert g2.reserve(0.6) == (False, "usd_cap")  # 첫 예약이 장부에 반영되어 있다
    g1.settle(rid1, 0.1)
    assert g2.reserve(0.6)[0] is True


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


# ---- 병렬 실행 (#19) -------------------------------------------------------------

_WORKER = r"""
import sys
from pathlib import Path
from asel.agents.claude_policy import BudgetGuard
g = BudgetGuard(Path(sys.argv[1]), usd_cap=1.0)
ok = 0
for _ in range(60):
    good, rid = g.reserve(0.01)
    if good:
        g.settle(rid, 0.01)
        ok += 1
print(ok)
"""


def test_ledger_cap_holds_across_processes(tmp_path):
    """4개 프로세스가 동시에 예약해도 상한($1 = 0.01 x 100회)을 넘지 않는다 (Windows 포함)."""
    import subprocess
    import sys

    ledger = tmp_path / "ledger.json"
    procs = [subprocess.Popen([sys.executable, "-c", _WORKER, str(ledger)], stdout=subprocess.PIPE, text=True)
             for _ in range(4)]
    granted = sum(int(p.communicate(timeout=120)[0].strip()) for p in procs)
    s = json.loads(ledger.read_text())
    assert granted == 100  # 정확히 상한만큼만 승인
    assert s["usd_spent"] == pytest.approx(1.0) and s["usd_reserved"] == pytest.approx(0.0)


def test_cache_first_writer_wins(tmp_path):
    c = ResponseCache(tmp_path / "c")
    first, mine1 = c.put_if_absent("ab" * 32, {"v": 1})
    second, mine2 = c.put_if_absent("ab" * 32, {"v": 2})
    assert mine1 and not mine2 and first == second == {"v": 1} == c.get("ab" * 32)
    assert not list((tmp_path / "c").rglob("*.tmp"))


def test_race_loser_uses_stored_response_and_replay_matches(tmp_path):
    """다른 프로세스가 같은 요청을 먼저 기록한 상황을 흉내: 늦게 온 쪽은 저장된 응답을 쓰고, 재생과 일치한다."""
    cache = ResponseCache(tmp_path / "cache")
    # 1) 먼저 기록한 프로세스: '첫 후보' 응답
    a = run_scenario(SHORT, seed=4, policy=_policy(tmp_path, FakeClient(), cache=cache))

    # 2) 늦게 온 프로세스: 캐시 조회 시점엔 없었다고 보고 API 를 불렀지만(다른 응답), 기록할 땐 이미 있음
    class Racer(ResponseCache):
        def get(self, key):
            return None

    late = _policy(tmp_path, FakeClient(text_override='{"assignments": [], "reason": "late"}'),
                   cache=Racer(tmp_path / "cache"))
    b = run_scenario(SHORT, seed=4, policy=late)
    assert b.policy_usage.get("cache_race_lost", 0) == b.policy_usage["api_calls"] > 0
    assert encode_events(a.events) == encode_events(b.events)  # 저장된(먼저 온) 응답대로 행동


_HOLD_AND_DIE = r"""
import os, sys, time
from pathlib import Path
from asel.agents.claude_policy import _FileLock
lk = _FileLock(Path(sys.argv[1]))
lk.__enter__()
print("held", flush=True)
time.sleep(1.0)
os._exit(1)  # 잠금을 풀지 않고 죽는다
"""


def test_lock_released_when_holder_process_dies(tmp_path):
    """잠금을 쥔 프로세스가 죽으면 OS 가 잠금을 푼다 → 다른 프로세스가 오래 기다리지 않는다 (리뷰 지적)."""
    import subprocess
    import sys

    from asel.agents.claude_policy import _FileLock

    lock = tmp_path / "x.lock"
    p = subprocess.Popen([sys.executable, "-c", _HOLD_AND_DIE, str(lock)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        with _FileLock(lock, timeout_s=0.3):
            pass  # 살아 있는 동안은 못 잡는다
    p.wait(timeout=30)
    with _FileLock(lock, timeout_s=5.0):
        pass  # 죽은 뒤에는 바로 잡힌다
    assert time.monotonic() - t0 < 10


def test_expired_reservation_counts_as_spent_and_late_settle_corrects(tmp_path, monkeypatch):
    from asel.agents import claude_policy as cp

    g = BudgetGuard(tmp_path / "l.json", usd_cap=1.0)
    ok, rid = g.reserve(0.3)
    assert ok and g.state()["usd_reserved"] == pytest.approx(0.3)
    real_time = cp.time.time
    monkeypatch.setattr(cp.time, "time", lambda: real_time() + cp.RESERVATION_TTL_S + 1)
    assert g.reserve(0.01)[0]  # 이 시점에 만료 처리: 0.3 이 지출로
    s = g.state()
    assert s["expired_reservations"] == 1 and s["usd_spent"] == pytest.approx(0.3)
    g.settle(rid, 0.05)  # 늦게 도착한 정산: 차액 보정 대신 실제 비용을 더하지 않도록 0.05 만 기록
    assert g.state()["late_settlements"] == 1


def test_legacy_ledger_reserved_is_moved_to_spent(tmp_path):
    p = tmp_path / "l.json"
    p.write_text(json.dumps({"usd_spent": 1.0, "usd_reserved": 0.2, "calls": 4, "entries": 2}))
    s = BudgetGuard(p, usd_cap=10).state()
    assert s["usd_spent"] == pytest.approx(1.2) and s["usd_reserved"] == 0


_HEAVY_WORKER = r"""
import sys
from pathlib import Path
from asel.agents.claude_policy import BudgetGuard
g = BudgetGuard(Path(sys.argv[1]), usd_cap=1000.0)
for _ in range(300):
    good, rid = g.reserve(0.001)
    if good:
        g.settle(rid, 0.001)
print("ok")
"""


def test_ledger_survives_heavy_contention(tmp_path):
    """8개 프로세스가 촘촘하게 잠금을 잡고 놓아도 예외 없이 끝나고 합계가 맞는다."""
    import subprocess
    import sys

    ledger = tmp_path / "ledger.json"
    procs = [subprocess.Popen([sys.executable, "-c", _HEAVY_WORKER, str(ledger)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(8)]
    outs = [p.communicate(timeout=300) for p in procs]
    assert all(o[0].strip() == "ok" for o in outs), [o[1][-300:] for o in outs]
    s = json.loads(ledger.read_text())
    assert s["calls"] == 2400 and s["usd_spent"] == pytest.approx(2.4)


def test_prompt_versions_keep_old_recordings_and_neutral_prompt_has_no_industry_words(tmp_path):
    from asel.agents.claude_policy import PROMPTS

    assert ClaudePolicy(cache=ResponseCache(tmp_path), guard=BudgetGuard(tmp_path / "l", 1)).prompt_version == "v1-warehouse"
    assert "warehouse" not in PROMPTS["v2-neutral"].lower()
    with pytest.raises(ValueError):
        ClaudePolicy(prompt_version="v9", cache=ResponseCache(tmp_path), guard=BudgetGuard(tmp_path / "l", 1))
    # 버전이 다르면 요청(=캐시 키)이 달라 서로의 녹화를 쓰지 않는다
    a = run_scenario(SHORT, seed=1, policy=_policy(tmp_path, FakeClient()))
    pol = _policy(tmp_path, FakeClient(raise_exc=AssertionError()), mode="replay")
    pol.prompt_version = "v2-neutral"
    b = run_scenario(SHORT, seed=1, policy=pol)
    assert a.policy_usage["api_calls"] > 0 and b.policy_usage["cache_hits"] == 0
    assert b.policy_usage["prompt_version"] == "v2-neutral"
