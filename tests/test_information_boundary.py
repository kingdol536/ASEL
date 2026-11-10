"""정답 격리: 공개 로그에 숨겨진 참값이 나타나지 않는다 (docs/04 §7, 티켓 #2)."""

from __future__ import annotations

import json

from asel.core.world import replay
from asel.io.eventlog import PRIVATE_LOG, PUBLIC_LOG, encode_public, read_public
from asel.runner import run_scenario, write_run
from conftest import create, make_world

HIDDEN_KEYS = {"duration", "action_private"}


def _all_keys(obj, out: set):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(k)
            _all_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _all_keys(v, out)
    return out


def test_public_log_has_no_hidden_keys_or_values(scenario_a, tmp_path):
    res = run_scenario(scenario_a, seed=9)
    run_dir = write_run(res, tmp_path)
    text = (run_dir / PUBLIC_LOG).read_text(encoding="utf-8")
    keys = set()
    for line in text.splitlines():
        _all_keys(json.loads(line), keys)
    assert not (keys & HIDDEN_KEYS), keys & HIDDEN_KEYS
    # 실제 처리 시간 값 자체도 공개 로그 문자열에 나타나지 않는다
    durations = [t.duration for t in res.world.state.tasks.values()]
    assert durations and all(repr(d) not in text for d in durations)
    # 비공개 로그에는 있다
    assert '"duration"' in (run_dir / PRIVATE_LOG).read_text(encoding="utf-8")


def test_public_only_replay_hides_truth_but_keeps_structure(scenario_a, tmp_path):
    res = run_scenario(scenario_a, seed=9)
    run_dir = write_run(res, tmp_path)
    pub = replay(read_public(run_dir / PUBLIC_LOG))
    full = res.world.state
    assert set(pub.tasks) == set(full.tasks)
    for tid, t in pub.tasks.items():
        assert t.duration is None
        assert (t.status, t.started_at, t.completed_at, t.assigned_entity) == (
            full.tasks[tid].status,
            full.tasks[tid].started_at,
            full.tasks[tid].completed_at,
            full.tasks[tid].assigned_entity,
        )


def test_duration_in_public_params_is_rejected():
    w = make_world()
    bad = create("a")
    from asel.core.actions import Action

    leaky = Action(bad.actor_id, bad.kind, {**bad.params, "duration": 5.0}, private={"duration": 5.0})
    res = w.submit(leaky)
    assert not res.accepted
    assert any("hidden truth" in r for r in res.reasons)


def test_rejected_env_action_keeps_private_out_of_public_log():
    w = make_world()
    w.submit(create("a", duration=12.345678))
    w.submit(create("a", duration=98.7654321))  # 중복 id -> 거절
    text = encode_public(w.log).decode()
    assert "12.345678" not in text and "98.7654321" not in text
