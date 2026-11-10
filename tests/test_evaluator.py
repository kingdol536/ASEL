"""독립 평가기 (#12)와 대응 비교."""

from __future__ import annotations

import json

import pytest

from asel.batch import run_batch
from asel.evaluation.evaluator import evaluate_run, order_metrics, quantile
from asel.evaluation.paired import bootstrap_ci, load_eval_rows, paired_compare
from asel.io.eventlog import PUBLIC_LOG, read_public
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from conftest import ROOT

SURGE = ROOT / "scenarios" / "warehouse-surge-a.yaml"


def test_quantile_linear():
    assert quantile([], 0.5) is None
    assert quantile([1, 2, 3, 4], 0.5) == 2.5
    assert quantile([10], 0.95) == 10
    assert quantile(list(range(101)), 0.95) == pytest.approx(95)


def test_order_flow_time_matches_true_state(tmp_path):
    sc = load_scenario(SURGE)
    res = run_scenario(sc, seed=3)
    run_dir = write_run(res, tmp_path)
    m = order_metrics(read_public(run_dir / PUBLIC_LOG))
    # 실제 상태(정답)로 독립 계산한 값과 일치해야 한다
    orders: dict[str, list] = {}
    for t in res.world.state.tasks.values():
        orders.setdefault(t.tags["order"], []).append(t)
    done = [max(ts, key=lambda t: t.tags["step"]) for ts in orders.values()]
    flows = [d.completed_at - min(t.created_at for t in orders[d.tags["order"]]) for d in done if d.completed_at]
    assert m["orders_arrived"] == len(orders)
    assert m["orders_completed"] == len(flows)
    assert m["order_flow_time_s"]["mean"] == pytest.approx(sum(flows) / len(flows))
    assert m["orders_censored"]["n"] == len(orders) - len(flows)


def test_evaluation_uses_public_metrics_and_checks_boundary(tmp_path):
    res = run_scenario(load_scenario(SURGE), seed=1, policy="order-age")
    run_dir = write_run(res, tmp_path)
    ev = evaluate_run(run_dir)
    assert ev["safety_boundary"]["ok"] and ev["policy"] == "order-age"
    assert ev["decisions"]["invalid_proposal_rate"] == 0.0
    assert ev["sources"]["metrics"] == PUBLIC_LOG
    # 공개 로그에 숨겨진 키를 심으면 경계 검사가 실패한다
    p = run_dir / PUBLIC_LOG
    lines = p.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])  # WorldInitialized: reducer 가 모르는 키는 무시하므로 재생은 그대로 된다
    first["payload"]["duration"] = 1.0
    p.write_text("\n".join([json.dumps(first)] + lines[1:]) + "\n", encoding="utf-8")
    ev2 = evaluate_run(run_dir)
    assert ev2["safety_boundary"]["ok"] is False and ev2["safety_boundary"]["hidden_keys_in_public_log"] == ["duration"]


def test_bootstrap_ci_deterministic_and_sane():
    d = [1.0, 2.0, 3.0, 4.0, 5.0]
    a, b = bootstrap_ci(d), bootstrap_ci(d)
    assert a == b and a[0] <= 3.0 <= a[1]
    assert bootstrap_ci([2.0, 2.0, 2.0]) == (2.0, 2.0)


def test_batch_writes_eval_and_paired_compare(tmp_path):
    bd = run_batch([str(SURGE)], [0, 1, 2], tmp_path, policies=["fifo", "order-age"])
    rows = load_eval_rows(bd)
    assert len(rows) == 6 and all(r["boundary_ok"] == "True" for r in rows)
    out = paired_compare(rows, "flow_mean_s", "fifo", "order-age")
    assert out[0]["n_pairs"] == 3 and out[0]["ci95_low"] <= out[0]["mean_diff"] <= out[0]["ci95_high"]
    assert json.loads((bd / "batch.json").read_text(encoding="utf-8"))["safety_boundary_all_ok"] is True


def test_invalid_rate_excludes_fallback_proposals(tmp_path):
    """대체(FIFO) 제안은 정책 자신의 무효 제안 비율에 섞이지 않는다 (리뷰 지적)."""
    from test_claude_policy import FakeClient, FlakyClient, _policy  # noqa: F401

    sc = load_scenario(ROOT / "scenarios" / "warehouse-small-a.yaml").model_copy(update={"sim_time_limit": 900.0})

    class FlakyMistakes(FlakyClient):
        def __init__(self):
            super().__init__(mistake_every=2)

    res = run_scenario(sc, seed=3, policy=_policy(tmp_path, FlakyMistakes()))
    ev = evaluate_run(write_run(res, tmp_path / "runs"))
    d = ev["decisions"]
    assert d["fallback_proposals"] > 0 and d["rejected"] > 0
    own_props = [e for e in res.events if e.event_type == "ActionProposed" and e.actor_id == "policy.claude"
                 and e.payload["action"].get("reason") != "fallback"]
    assert d["proposals"] == len(own_props)
    assert d["invalid_proposal_rate"] == pytest.approx(d["rejected"] / d["proposals"])


def test_cli_run_writes_evaluation(tmp_path):
    from asel.cli import main

    assert main(["run", str(SURGE), "--seed", "1", "--out", str(tmp_path)]) == 0
    assert list(tmp_path.glob("*/*/evaluation.json"))
