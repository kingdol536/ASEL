"""Claude 정책 어댑터 (티켓 #11, 결정 0004).

PolicyAdapter 규약을 따른다: 관측(Observation)과 허용 행동 후보만 받아 제안을 낸다.
제안은 검증기를 거쳐야만 세계에 적용된다.

모드 (기본값 replay — 실수로 비용이 나가지 않게):
- replay : 저장된 응답(캐시)만 쓴다. 캐시에 없으면 대체 정책(FIFO)으로 결정한다. API 호출 없음.
- record : 캐시에 없으면 API 를 호출하고 응답을 저장한다. 예산 가드를 통과해야 호출한다.

비용·보안 규칙:
- 예산 가드: 호출 전 최악 비용(입력 추정 + max_tokens 전부 출력)을 남은 예산과 비교하고,
  호출 후 실제 사용량으로 누적 장부(저장소 밖 파일)를 갱신한다. 상한에 닿으면 더 호출하지 않는다.
- API 키는 환경변수(ANTHROPIC_ASEL_API_KEY)에서 클라이언트 생성 시에만 읽는다.
  키를 로그·manifest·캐시·사용량 기록에 남기지 않는다.
- 캐시·장부 기본 위치는 저장소 밖(%LOCALAPPDATA%\\asel\\llm). 프롬프트·응답이 공개 저장소로 가지 않는다.
- 정책 실패(타임아웃·연결 오류·거절·형식 오류)는 그 결정만 대체 정책으로 처리하고 사유별로 센다.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from asel.core.actions import ActionKind
from asel.policies.contract import ActionProposal, ActionSpec, Observation, PolicyContext
from asel.policies.fifo import FifoPolicy

API_KEY_ENV = "ANTHROPIC_ASEL_API_KEY"

# 1M 토큰당 USD. 출처: claude-api 스킬 모델 표 (캐시 기준일 2026-11-03).
# Haiku 5.5 는 프롬프트 100K 초과 시 $0.50/$2.50. 캐시 읽기 단가가 표에 없는 모델은
# 입력 단가로 계산한다(가드가 비용을 과대평가하는 쪽 = 안전한 쪽).
PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "input_long": 0.50, "output_long": 2.50, "long_from": 100_000},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.10},
}
PRICES_AS_OF = "2026-11-03"
CACHE_WRITE_MULT = 1.25

SYSTEM_PROMPT = """You dispatch work in a simulated warehouse made of work cells.
Each decision you see the current observation: cells (capabilities, free capacity) and open tasks.
Choose which READY tasks to start now and on which cell, using only the listed candidate pairs.
Rules:
- Use each task at most once.
- Do not assign more tasks to a cell than its "available" count.
- You may choose fewer assignments than possible, or none, if you have a reason.
Task processing times are not visible to you. Base decisions only on the observation.
Reply with the JSON object described by the output schema. Keep "reason" to one short sentence."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "assignments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"task": {"type": "string"}, "entity": {"type": "string"}},
                "required": ["task", "entity"],
                "additionalProperties": False,
            },
        },
        "reason": {"type": "string"},
    },
    "required": ["assignments", "reason"],
    "additionalProperties": False,
}


def default_llm_dir() -> Path:
    base = os.environ.get("ASEL_LLM_DIR") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share"), "asel", "llm"
    )
    return Path(base)


def read_api_key(env_name: str = API_KEY_ENV) -> str | None:
    """프로세스 환경변수, 없으면 (Windows) 사용자 환경변수 레지스트리에서 읽는다.
    사용자가 세션 시작 뒤에 등록한 변수도 쓸 수 있게 하기 위함이다. 값은 반환만 하고 기록하지 않는다."""
    v = os.environ.get(env_name)
    if v:
        return v
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                return winreg.QueryValueEx(k, env_name)[0] or None
        except OSError:
            return None
    return None


def make_client(timeout_s: float = 30.0, max_retries: int = 1):
    """실제 Anthropic 클라이언트. record 모드에서만 만든다."""
    import anthropic

    key = read_api_key()
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set")
    return anthropic.Anthropic(api_key=key, timeout=timeout_s, max_retries=max_retries)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int,
                      cache_read: int = 0, cache_write: int = 0) -> float:
    p = PRICES[model]
    long_ctx = "long_from" in p and (input_tokens + cache_read + cache_write) > p["long_from"]
    pin = p["input_long"] if long_ctx else p["input"]
    pout = p["output_long"] if long_ctx else p["output"]
    pread = p.get("cache_read", pin)
    usd = (input_tokens * pin + cache_write * pin * CACHE_WRITE_MULT + cache_read * pread + output_tokens * pout) / 1e6
    return usd


# --------------------------------------------------------------------------- 예산 장부


class _FileLock:
    """여러 프로세스가 같은 장부를 쓸 때의 배타 잠금 (O_EXCL 잠금 파일, 오래된 잠금은 정리)."""

    def __init__(self, path: Path, timeout_s: float = 30.0, stale_s: float = 120.0):
        self.path, self.timeout_s, self.stale_s = path, timeout_s, stale_s

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale_s:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"budget ledger lock busy: {self.path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


@dataclass
class BudgetGuard:
    """누적 비용 장부. 여러 실행·배치·프로세스에 걸쳐 같은 파일을 쓴다.

    호출 전에 최악 비용을 '예약'하고(상한 검사와 예약을 잠금 안에서 한 번에), 호출 뒤 실제 비용으로
    '정산'한다. 실제 비용을 알 수 없는 실패(타임아웃 등)는 예약액 전부를 지출로 남긴다(보수적).
    calls 는 성공 여부와 관계없이 API 요청 시도 수다."""

    ledger_path: Path
    usd_cap: float
    call_cap: int | None = None

    def _lock(self) -> _FileLock:
        return _FileLock(self.ledger_path.with_suffix(".lock"))

    def _load(self) -> dict:
        if self.ledger_path.exists():
            s = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            s.setdefault("usd_reserved", 0.0)
            return s
        return {"usd_spent": 0.0, "usd_reserved": 0.0, "calls": 0, "entries": 0}

    def _save(self, s: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(s, indent=2), encoding="utf-8")
        tmp.replace(self.ledger_path)

    def state(self) -> dict:
        return self._load()

    def reserve(self, usd_worst_case: float, attempts: int = 1) -> tuple[bool, str]:
        with self._lock():
            s = self._load()
            if self.call_cap is not None and s["calls"] + attempts > self.call_cap:
                return False, "call_cap"
            if s["usd_spent"] + s["usd_reserved"] + usd_worst_case > self.usd_cap:
                return False, "usd_cap"
            s["usd_reserved"] = round(s["usd_reserved"] + usd_worst_case, 8)
            s["calls"] += attempts
            self._save(s)
            return True, ""

    def settle(self, reserved: float, actual: float | None) -> float:
        """actual=None 이면 실제 비용을 모르므로 예약액 전부를 지출로 기록한다. 기록한 금액을 돌려준다."""
        charged = reserved if actual is None else actual
        with self._lock():
            s = self._load()
            s["usd_reserved"] = max(0.0, round(s["usd_reserved"] - reserved, 8))
            s["usd_spent"] = round(s["usd_spent"] + charged, 8)
            s["entries"] += 1
            self._save(s)
        return charged


# --------------------------------------------------------------------------- 응답 캐시


@dataclass
class ResponseCache:
    root: Path

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict | None:
        p = self._path(key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def put_if_absent(self, key: str, entry: dict) -> tuple[dict, bool]:
        """먼저 기록된 응답이 이긴다. 반환: (캐시에 남은 응답, 내가 기록했는지).

        임시 파일을 다 쓴 뒤 하드 링크로 최종 이름을 만든다. 링크는 대상이 있으면 실패하므로
        두 프로세스가 같은 요청을 동시에 기록해도 하나만 남고, 읽는 쪽은 항상 완성된 파일을 본다.
        늦게 온 쪽은 저장된 응답을 그대로 써야 재생 때 같은 사건 로그가 나온다."""
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        tmp.write_text(json.dumps(entry, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        try:
            os.link(tmp, p)
            return entry, True
        except FileExistsError:
            return json.loads(p.read_text(encoding="utf-8")), False
        finally:
            tmp.unlink(missing_ok=True)

    def put(self, key: str, entry: dict) -> None:
        self.put_if_absent(key, entry)


# --------------------------------------------------------------------------- 정책


@dataclass
class ClaudePolicy:
    model: str = "claude-haiku-5-5"
    mode: str = "replay"  # replay | record
    effort: str = "low"
    max_tokens: int = 2048
    timeout_s: float = 30.0
    max_retries: int = 1  # SDK 자동 재시도. 예산 예약은 (max_retries + 1) 회 시도분으로 잡는다
    cache_tag: str = "v1"  # 녹화 묶음 이름. 다시 녹화할 때 바꾸면 이전 응답과 섞이지 않는다
    client: object | None = None  # 테스트에서는 가짜 클라이언트를 넣는다
    cache: ResponseCache | None = None
    guard: BudgetGuard | None = None
    name: str = "claude"
    _fallback: FifoPolicy = field(default_factory=FifoPolicy, repr=False)
    _u: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        if self.mode not in ("replay", "record"):
            raise ValueError("mode must be 'replay' or 'record'")
        if self.model not in PRICES:
            raise ValueError(f"no price entry for {self.model}; add it before use")
        llm_dir = default_llm_dir()
        self.cache = self.cache or ResponseCache(llm_dir / "cache")
        self.guard = self.guard or BudgetGuard(llm_dir / "ledger.json", usd_cap=55.0)
        self._reset_usage()

    def _reset_usage(self) -> None:
        self._served_models: set[str] = set()
        self._u = {
            "model": self.model, "mode": self.mode, "effort": self.effort, "max_tokens": self.max_tokens,
            "prices_as_of": PRICES_AS_OF, "api_calls": 0, "cache_hits": 0, "llm_decisions": 0,
            "fallbacks": {}, "input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0, "usd_estimate": 0.0, "usd_charged_unknown": 0.0,
            "latency_ms_total": 0.0, "api_key_env": API_KEY_ENV, "cache_tag": self.cache_tag,
        }

    # -- 규약 --------------------------------------------------------------------
    def reset(self, context: PolicyContext) -> None:
        """실행마다 호출된다. 사용량은 실행 단위로 다시 센다 (같은 객체를 여러 실행에 써도 섞이지 않게)."""
        self._reset_usage()
        self._fallback.reset(context)

    def usage(self) -> dict:
        u = dict(self._u)
        u["fallbacks"] = dict(sorted(self._u["fallbacks"].items()))
        u["usd_estimate"] = round(u["usd_estimate"], 6)
        u["usd_charged_unknown"] = round(u["usd_charged_unknown"], 6)
        u["served_models"] = sorted(self._served_models)  # 캐시 응답 포함, 실제로 응답한 모델 버전
        u["latency_ms_total"] = round(u["latency_ms_total"], 1)
        return u

    def decide(self, obs: Observation, affordances: list[ActionSpec]) -> list[ActionProposal]:
        user = self._user_message(obs, affordances)
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        }
        key_src = {"cache_tag": self.cache_tag, "request": request}
        key = hashlib.sha256(json.dumps(key_src, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

        entry = self.cache.get(key)
        if entry is not None:
            self._u["cache_hits"] += 1
        elif self.mode == "replay":
            return self._fall_back("cache_miss", obs, affordances)
        else:
            entry, reason = self._call(request, user)
            if entry is None:
                return self._fall_back(reason, obs, affordances)
            entry, mine = self.cache.put_if_absent(key, entry)
            if not mine:
                # 다른 프로세스가 같은 요청의 응답을 먼저 기록했다 → 그 응답을 쓴다 (재생 일치)
                self._u["cache_race_lost"] = self._u.get("cache_race_lost", 0) + 1

        self._served_models.add(str(entry.get("model")))
        if entry.get("stop_reason") not in ("end_turn", "stop_sequence"):
            return self._fall_back(f"stop_{entry.get('stop_reason')}", obs, affordances)
        try:
            data = json.loads(entry["text"])
            assignments = data["assignments"]
            reason = str(data.get("reason", ""))[:300]
            props = [
                ActionProposal(ActionKind.START_TASK, {"task": str(a["task"]), "entity": str(a["entity"])}, reason)
                for a in assignments
            ]
        except (ValueError, KeyError, TypeError):
            return self._fall_back("bad_output", obs, affordances)
        self._u["llm_decisions"] += 1
        return props

    # -- 내부 --------------------------------------------------------------------
    def _user_message(self, obs: Observation, affordances: list[ActionSpec]) -> str:
        # 시각·버전처럼 매번 바뀌는 값은 그대로 넣는다(결정에 필요). 키 정렬로 같은 관측 = 같은 문자열.
        payload = {"observation": obs.to_dict(), "allowed_actions": [a.to_dict() for a in affordances]}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def _fall_back(self, reason: str, obs, affordances) -> list[ActionProposal]:
        # 공개 로그의 이유는 'fallback' 하나로 둔다. 자세한 사유(타임아웃·예산·캐시 없음 등)는 사용량에만.
        # 녹화 실행의 실패와 재생 실행의 캐시 없음이 같은 사건 로그를 내도록 하기 위함이다.
        self._u["fallbacks"][reason] = self._u["fallbacks"].get(reason, 0) + 1
        return [ActionProposal(p.action_type, p.params, "fallback") for p in self._fallback.decide(obs, affordances)]

    def _call(self, request: dict, user: str) -> tuple[dict | None, str]:
        # 최악 비용: 입력은 문자 수/2 토큰으로 넉넉히 추정(실제보다 크게), 출력은 max_tokens 전부
        est_in = (len(SYSTEM_PROMPT) + len(user)) // 2 + 500
        attempts = self.max_retries + 1
        worst = estimate_cost_usd(self.model, est_in, self.max_tokens) * attempts
        ok, why = self.guard.reserve(worst, attempts=attempts)
        if not ok:
            return None, f"budget_{why}"
        if self.client is None:
            self.client = make_client(self.timeout_s, self.max_retries)

        import anthropic

        def unknown_cost(reason: str):
            # 서버에서 처리됐는지 알 수 없다 → 예약한 최악 비용 전부를 지출로 남긴다 (보수적)
            self._u["usd_charged_unknown"] += self.guard.settle(worst, None)
            return None, reason

        t0 = time.perf_counter()
        try:
            resp = self.client.messages.create(**request)
        except anthropic.APITimeoutError:
            return unknown_cost("api_timeout")
        except anthropic.RateLimitError:
            self.guard.settle(worst, 0.0)  # 429 는 처리되지 않은 요청
            return None, "api_rate_limit"
        except anthropic.APIStatusError as e:
            if e.status_code >= 500:
                return unknown_cost(f"api_status_{e.status_code}")
            self.guard.settle(worst, 0.0)  # 4xx: 처리 전 거절
            return None, f"api_status_{e.status_code}"
        except anthropic.APIConnectionError:
            return unknown_cost("api_connection")
        except BaseException:
            unknown_cost("unexpected")
            raise
        latency_ms = (time.perf_counter() - t0) * 1000

        u = resp.usage
        inp, out = u.input_tokens or 0, u.output_tokens or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        usd = estimate_cost_usd(self.model, inp, out, cr, cw)
        self.guard.settle(worst, usd)
        self._u["api_calls"] += 1
        self._u["input_tokens"] += inp
        self._u["output_tokens"] += out
        self._u["cache_read_input_tokens"] += cr
        self._u["cache_creation_input_tokens"] += cw
        self._u["usd_estimate"] += usd
        self._u["latency_ms_total"] += latency_ms

        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        return {
            "model": getattr(resp, "model", self.model),
            "stop_reason": resp.stop_reason,
            "text": text,
            "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr,
                      "cache_creation_input_tokens": cw},
            "usd_estimate": usd,
            "latency_ms": round(latency_ms, 1),
        }, ""
