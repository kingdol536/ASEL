"""3D 장면 데이터 (#57): 공개 로그만 읽고, 천장 판정은 엔진 결과(roles_over_ceiling)를 그대로 쓴다."""

from __future__ import annotations

import shutil

import pytest

from asel.core.actions import Action, ActionKind
from asel.core.world import ENV_ACTOR, World
from asel.io.eventlog import PUBLIC_LOG, encode_public
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from asel.scene3d import dumps, scene_for_run
from conftest import ROOT

B2P = ROOT / "scenarios" / "assembly-line-b.yaml"
B3P = ROOT / "scenarios" / "assembly-line-b-3d.yaml"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = tmp_path_factory.mktemp("runs")
    b2 = write_run(run_scenario(load_scenario(B2P), seed=0, structure_policy="p1"), out)
    b3 = write_run(run_scenario(load_scenario(B3P), seed=0, structure_policy="p1"), out)
    return b2, b3


def test_cells_match_scenario_layout(runs):
    scene = scene_for_run(runs[1])
    sc = load_scenario(B3P).canonical_dump()
    assert [c["id"] for c in scene["cells"]] == [e["id"] for e in sc["entities"]]
    assert {c["id"]: c["space"] for c in scene["cells"]} == {e["id"]: e["space"] for e in sc["entities"]}
    assert scene["capability_space"] == sc["capability_space"] and scene["layout"] == "run"


def test_2d_switch_clashes_on_3d_layout_but_not_in_3d_run(runs):
    b2, b3 = runs
    s2 = scene_for_run(b2, B3P)
    assert s2["layout"] == "assembly-line-b-3d" and s2["clashes"]
    c = s2["clashes"][0]
    assert (c["cell"], c["roles"], c["need_m"], c["ceiling_m"]) == ("press-2", ["press-A"], 3.8, 3.2)
    # 충돌 시각 = 2D 실행에서 press-2 의 셋업이 끝나 press-A 가 된 시각
    p2 = next(x for x in s2["cells"] if x["id"] == "press-2")
    assert [c["t"], ["press-A"]] in p2["roles"]
    s3 = scene_for_run(b3)
    assert s3["clashes"] == []
    p3 = next(x for x in s3["cells"] if x["id"] == "press-2")
    assert p3["blocked_options"] == [["press-A"]] and len(p3["roles"]) == 1  # 3D 에서는 전환 자체가 없다


def test_reads_only_public_log(runs, tmp_path):
    d = tmp_path / "only_public"
    d.mkdir()
    shutil.copy(runs[1] / PUBLIC_LOG, d / PUBLIC_LOG)  # 비공개 로그·최종 상태·시나리오 파일 없이
    assert dumps(scene_for_run(d)) == dumps(scene_for_run(runs[1]))
    assert '"duration"' not in dumps(scene_for_run(d))


def test_same_input_gives_same_bytes(runs, tmp_path):
    again = write_run(run_scenario(load_scenario(B3P), seed=0, structure_policy="p1"), tmp_path)
    assert dumps(scene_for_run(again)) == dumps(scene_for_run(runs[1]))


def test_layout_errors(runs):
    with pytest.raises(ValueError, match="no 3D space"):
        scene_for_run(runs[0])  # 공간 정보가 없는 2D 실행은 배치 시나리오가 필요하다
    with pytest.raises(ValueError, match="layout cells differ"):
        scene_for_run(runs[0], ROOT / "scenarios" / "it-service-c.yaml")


def test_engine_rejection_of_blocked_switch_is_shown(tmp_path):
    """실행기는 천장에 막힌 전환을 후보에서 빼므로 정책이 제안할 수 없다. 그래서 엔진에 직접 제출해
    거절 사건을 만들고, 그 공개 로그로 장면을 만든다."""
    grants = {ENV_ACTOR: {ActionKind.CREATE_TASK, ActionKind.COMPLETE_RECONFIGURATION},
              "structure.t": {ActionKind.REQUEST_RECONFIGURATION}}
    w = World("t", grants)
    sp = {"y": 0, "width": 1, "depth": 1}
    w.initialize(
        [{"id": "x", "type": "m", "capabilities": ["a"], "reconfig": {"options": [["a"], ["b"]], "changeover_s": 10.0},
          "space": {"x": 0, **sp, "ceiling_m": 3.0}},
         {"id": "y", "type": "m", "capabilities": ["b"], "space": {"x": 2, **sp, "ceiling_m": 6.0}},
         {"id": "z", "type": "m", "capabilities": ["a"], "space": {"x": 4, **sp, "ceiling_m": 6.0}}],
        [], [{"id": c, "capacity": 1} for c in "xyz"], {"a": {"height_m": 2.0}, "b": {"height_m": 4.0}},
    )
    r = w.submit(Action("structure.t", ActionKind.REQUEST_RECONFIGURATION, {"entity": "x", "capabilities": ["b"]}))
    assert not r.accepted
    (tmp_path / PUBLIC_LOG).write_bytes(encode_public(w.log))
    scene = scene_for_run(tmp_path)
    assert scene["clashes"] == []  # 엔진이 거절했으므로 역할은 바뀌지 않았다
    (rej,) = scene["rejected_switches"]
    assert (rej["cell"], rej["capabilities"], rej["actor"]) == ("x", ["b"], "structure.t")
    assert any("clearance" in m for m in rej["reasons"])
    x = next(c for c in scene["cells"] if c["id"] == "x")
    assert x["blocked_options"] == [["b"]]
