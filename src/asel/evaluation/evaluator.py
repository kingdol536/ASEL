"""독립 평가기 (티켓 #12, EXP-001 §4 승인 지표).

실행이 끝난 뒤 실행 폴더를 읽어 evaluation.json 을 따로 쓴다. 운영 정책은 이 파일을 보지 않는다
(정책은 실행 중 관측만 받고, 평가는 실행 후에 일어난다).

- 운영 결과 지표는 **공개 로그만으로** 계산한다 (숨겨진 참값을 쓰지 않음).
- 비공개 로그는 H1(안전 경계) 검사에만 쓴다: 불변조건 재검사, 공개 로그에 숨겨진 값이 없는지.
- 결정 비용·대체 비율은 manifest 의 정책 사용량에서 읽는다.

분위수는 선형 보간(numpy 기본과 같은 방식)으로 계산한다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from asel.core.invariants import check_invariants
from asel.core.world import replay
from asel.core.events import Event
from asel.evaluation.bottleneck import structure_metrics
from asel.io.eventlog import PRIVATE_LOG, PUBLIC_LOG

EVALUATOR_VERSION = "eval-0.3"  # 0.2: 무효 제안 비율에서 대체 제안 분리 / 0.3: 병목·재구성 지표
HIDDEN_PUBLIC_KEYS = ("duration", "action_private", "cause", "planned_end_s", "fault_index")


def quantile(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    h = (len(s) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (h - lo) * (s[hi] - s[lo])


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def order_metrics(events) -> dict:
    arrival: dict[str, float] = {}
    last_step: dict[str, int] = {}
    task_order: dict[str, tuple[str, int]] = {}
    done_at: dict[str, float] = {}
    end_time = 0.0
    for e in events:
        end_time = max(end_time, e.sim_time)
        if e.event_type == "TaskCreated":
            tags = e.payload.get("tags", {})
            order, step = tags.get("order"), tags.get("step")
            if order is None or step is None:
                continue
            task_order[e.entity_id] = (order, step)
            arrival.setdefault(order, e.sim_time)
            last_step[order] = max(last_step.get(order, -1), step)
        elif e.event_type == "TaskStateChanged" and e.payload.get("to") == "COMPLETED":
            if e.entity_id in task_order:
                order, step = task_order[e.entity_id]
                if step == last_step[order]:
                    done_at[order] = e.sim_time
    flow = [done_at[o] - arrival[o] for o in done_at]
    open_ages = [end_time - arrival[o] for o in arrival if o not in done_at]
    return {
        "orders_arrived": len(arrival),
        "orders_completed": len(done_at),
        "completion_rate": (len(done_at) / len(arrival)) if arrival else None,
        "order_flow_time_s": {
            "mean": _mean(flow),
            "median": quantile(flow, 0.5),
            "p95": quantile(flow, 0.95),
            "max": max(flow) if flow else None,
            "n": len(flow),
        },
        # 끝나지 않은 주문(중도절단): 종료 시점까지의 경과 시간. 처리 시간 통계에 넣지 않고 따로 보고한다.
        "orders_censored": {"n": len(open_ages), "age_at_end_mean_s": _mean(open_ages),
                            "age_at_end_max_s": max(open_ages) if open_ages else None},
    }


def decision_metrics(events, policy_actor: str | None) -> dict:
    """정책 자신의 제안과, 정책이 실패해 대체 규칙(FIFO)이 낸 제안(reason == 'fallback')을 나눠 센다.
    무효 제안 비율은 정책 자신의 제안만으로 계산한다 (대체 제안은 항상 유효해 비율을 희석하므로)."""
    own = own_rej = fb = fb_rej = 0
    for e in events:
        if policy_actor and e.actor_id != policy_actor:
            continue
        if not (e.actor_id or "").startswith("policy."):
            continue
        if e.event_type not in ("ActionProposed", "ActionRejected"):
            continue
        is_fb = e.payload.get("action", {}).get("reason") == "fallback"
        if e.event_type == "ActionProposed":
            fb, own = (fb + 1, own) if is_fb else (fb, own + 1)
        else:
            fb_rej, own_rej = (fb_rej + 1, own_rej) if is_fb else (fb_rej, own_rej + 1)
    return {
        "proposals": own,
        "rejected": own_rej,
        "invalid_proposal_rate": (own_rej / own) if own else None,
        "fallback_proposals": fb,
        "fallback_rejected": fb_rej,
    }


def _keys(obj, out: set) -> set:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def evaluate_run(run_dir: Path) -> dict:
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    policy = manifest.get("policy", {})
    usage = policy.get("usage", {}) or {}

    # 공개 로그는 한 번만 읽는다: 숨김 키 검사(실제 JSON 키를 순회)와 공개 이벤트 복원에 같이 쓴다
    pub_dicts = [json.loads(line) for line in (run_dir / PUBLIC_LOG).read_text(encoding="utf-8").splitlines() if line]
    public = [Event.from_dict(d) for d in pub_dicts]
    leaked = sorted(_keys(pub_dicts, set()) & set(HIDDEN_PUBLIC_KEYS))

    # 운영 지표: 공개 로그만
    pub_state = replay(public)
    backlog_end = sum(1 for t in pub_state.tasks.values() if str(t.status) in ("READY", "WAITING"))

    # H1 안전 경계: 공개+비공개로 불변조건 재검사
    hidden = {}
    for line in (run_dir / PRIVATE_LOG).read_text(encoding="utf-8").splitlines():
        if line:
            rec = json.loads(line)
            hidden[rec["seq"]] = rec["private"]
    full_state = replay([Event.from_dict({**d, "private": hidden.get(d["seq"], {})}) for d in pub_dicts])
    violations = check_invariants(full_state)

    decisions = usage.get("decisions") or 0
    n_fallback = sum((usage.get("fallbacks") or {}).values())
    return {
        "evaluator_version": EVALUATOR_VERSION,
        "experiment": "EXP-001",
        "run_id": manifest.get("run_id"),
        "scenario_id": manifest.get("scenario_id"),
        "seed": manifest.get("seed"),
        "policy": policy.get("name"),
        "structure_policy": (manifest.get("structure_policy") or {}).get("name"),
        "events_sha256": manifest.get("events_sha256"),
        "orders": order_metrics(public),
        "decisions": decision_metrics(public, policy.get("actor_id")),
        "backlog_end": backlog_end,
        "structure": structure_metrics(public),
        "decision_cost": {
            k: usage.get(k)
            for k in ("model", "api_calls", "cache_hits", "input_tokens", "output_tokens",
                      "usd_estimate", "usd_charged_unknown", "latency_ms_total", "served_models")
            if k in usage
        },
        "policy_decisions": decisions,
        "fallback_rate": (n_fallback / decisions) if decisions else None,
        "fallbacks": usage.get("fallbacks", {}),
        "safety_boundary": {
            "invariant_violations": len(violations),
            "hidden_keys_in_public_log": leaked,
            "ok": not violations and not leaked,
        },
        "sources": {"metrics": PUBLIC_LOG, "boundary_check": [PUBLIC_LOG, PRIVATE_LOG], "cost": "manifest.json"},
    }


def write_evaluation(run_dir: Path) -> dict:
    ev = evaluate_run(run_dir)
    (run_dir / "evaluation.json").write_text(
        json.dumps(ev, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return ev


EVAL_COLUMNS = [
    "scenario_id", "policy", "structure", "seed", "orders_arrived", "orders_completed", "completion_rate",
    "flow_mean_s", "flow_median_s", "flow_p95_s", "censored_n", "backlog_end",
    "proposals", "invalid_proposal_rate", "fallback_proposals", "policy_decisions", "fallback_rate",
    "api_calls", "input_tokens", "output_tokens", "usd_estimate", "latency_ms_total", "boundary_ok",
    "reconf_completed", "draining_s_total", "changeover_s_total", "lost_capacity_s",
    "bottleneck_shifts", "bottleneck_seq",
]


def eval_row(ev: dict) -> dict:
    o, d, c = ev["orders"], ev["decisions"], ev["decision_cost"]
    return {
        "scenario_id": ev["scenario_id"], "policy": ev["policy"], "structure": ev.get("structure_policy") or "",
        "seed": ev["seed"],
        "orders_arrived": o["orders_arrived"], "orders_completed": o["orders_completed"],
        "completion_rate": o["completion_rate"],
        "flow_mean_s": o["order_flow_time_s"]["mean"], "flow_median_s": o["order_flow_time_s"]["median"],
        "flow_p95_s": o["order_flow_time_s"]["p95"], "censored_n": o["orders_censored"]["n"],
        "backlog_end": ev["backlog_end"], "proposals": d["proposals"],
        "invalid_proposal_rate": d["invalid_proposal_rate"], "fallback_proposals": d["fallback_proposals"],
        "policy_decisions": ev["policy_decisions"],
        "fallback_rate": ev["fallback_rate"], "api_calls": c.get("api_calls", 0),
        "input_tokens": c.get("input_tokens", 0), "output_tokens": c.get("output_tokens", 0),
        "usd_estimate": c.get("usd_estimate", 0.0), "latency_ms_total": c.get("latency_ms_total", 0.0),
        "boundary_ok": ev["safety_boundary"]["ok"],
        "reconf_completed": ev["structure"]["reconfig_completed"],
        "draining_s_total": ev["structure"]["draining_s_total"],
        "changeover_s_total": ev["structure"]["changeover_s_total"],
        "lost_capacity_s": ev["structure"]["lost_capacity_s"],
        "bottleneck_shifts": ev["structure"]["bottleneck_shifts"],
        "bottleneck_seq": "".join(x[:2] if x != "-" else "-" for x in ev["structure"]["bottleneck_by_window"]),
    }
