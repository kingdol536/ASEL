"""3D 장면 데이터 (티켓 #57, 결정 0007 재검토). 공개 사건 로그 → 3D 재생용 장면 JSON.

설계 경계 (CLAUDE.md §3):
- **읽기 전용 재생기.** 실행 폴더의 공개 로그(events.ndjson)만 읽는다. 비공개 로그·최종 상태는 열지 않는다.
- **상태 권위는 엔진 하나.** 셀의 위치·크기는 시나리오의 정적 배치(사건 로그의 WorldInitialized)이고, 이 모듈은
  위치를 계산하거나 갱신하지 않는다. 천장 충돌 판정은 엔진 함수 `roles_over_ceiling` 의 결과를 그대로 쓴다.
- 물리 엔진 없음. 그래픽은 엔진 판정을 보여주는 시각화일 뿐이다.

배치 겹쳐 보기(layout): 공간 정보가 없는 2D 실행을 같은 셀 구성의 3D 배치 시나리오 위에 재생하면,
2D 에서 일어난 역할 전환 가운데 3D 에서는 천장 때문에 불가능한 것을 '충돌'로 표시한다 (M5 §3.4 의 화면판).
"""

from __future__ import annotations

import json
from pathlib import Path

from asel.core.events import Event
from asel.core.model import roles_over_ceiling
from asel.io.eventlog import PUBLIC_LOG, read_public
from asel.io.scenario import load_scenario
from asel.viewer2d import build_view

SCENE_VERSION = "scene-0.1"


def layout_from_scenario(path: str | Path) -> dict:
    """시나리오 파일의 정적 3D 배치 (셀별 공간 + 역할별 필요 높이). 설정 파일이므로 공개 정보다."""
    sc = load_scenario(path)
    d = sc.canonical_dump()
    return {"id": sc.scenario_id, "space": {e["id"]: e.get("space") for e in d["entities"]},
            "capability_space": d.get("capability_space") or {}}


def build_scene(events: list[Event], layout: dict | None = None) -> dict:
    """공개 사건 목록 → 장면 dict. layout 을 주면 실행 자체의 공간 정보 대신 그 배치를 쓴다."""
    init = next(e for e in events if e.event_type == "WorldInitialized").payload
    v = build_view(events)
    ids = [e["id"] for e in init["entities"]]
    if layout is None:
        spaces = {e["id"]: e.get("space") for e in init["entities"]}
        cap_space = init.get("capability_space") or {}
        layout_src = "run"
    else:
        if set(layout["space"]) != set(ids):
            raise ValueError(f"layout cells differ from the run: {sorted(set(layout['space']) ^ set(ids))}")
        spaces, cap_space, layout_src = layout["space"], layout["capability_space"], layout["id"]
    missing = [i for i in ids if not spaces.get(i)]
    if missing:
        raise ValueError(f"no 3D space for cells {missing}; pass a layout scenario with a static 3D layout")

    end = v.end_time
    cells, clashes = [], []
    for ent in init["entities"]:
        cid, sp = ent["id"], spaces[ent["id"]]
        # 역할 타임라인: 처음 역할 + 전환이 끝난 시각마다 새 역할 (요청·비우기·셋업 중에는 이전 역할로 센다)
        roles = [[0.0, list(ent["capabilities"])]]
        for kind, _s, e, target in v.reconf.get(cid, []):
            if kind == "changeover" and e is not None:
                roles.append([e, list(target)])
        for t, caps in roles:
            over = roles_over_ceiling(sp, cap_space, caps)  # 엔진 판정
            if over:
                clashes.append({"cell": cid, "t": t, "roles": over, "ceiling_m": float(sp["ceiling_m"]),
                                "need_m": max(float(cap_space[c]["height_m"]) for c in over)})
        opts = (ent.get("reconfig") or {}).get("options") or []
        cells.append({
            "id": cid, "type": ent["type"], "space": sp, "roles": roles, "options": opts,
            "blocked_options": [o for o in opts if roles_over_ceiling(sp, cap_space, o)],
            "busy": [[b.start, b.end if b.end is not None else end, b.capability] for b in v.bars.get(cid, [])],
            "reconf": [[k, s, e if e is not None else end, list(t)] for k, s, e, t in v.reconf.get(cid, [])],
            "outages": [[s, e if e is not None else end, u] for s, e, u in v.outages.get(cid, [])],
        })
    rejected = []
    for ev in v.rejected:
        a = ev.payload.get("action") or {}
        if a.get("kind") == "request_reconfiguration":
            rejected.append({"t": ev.sim_time, "cell": (a.get("params") or {}).get("entity"),
                             "capabilities": (a.get("params") or {}).get("capabilities"),
                             "actor": a.get("actor_id"), "reasons": ev.payload.get("reasons")})
    return {"scene_version": SCENE_VERSION, "run_id": v.run_id, "end_time": end, "layout": layout_src,
            "capability_space": cap_space, "relations": init["relations"], "cells": cells,
            "clashes": clashes, "rejected_switches": rejected}


def dumps(scene: dict) -> str:
    """같은 장면 → 같은 바이트 (키 정렬, 공백 없음)."""
    return json.dumps(scene, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def scene_for_run(run_dir: str | Path, layout_path: str | Path | None = None) -> dict:
    events = read_public(Path(run_dir) / PUBLIC_LOG)  # 공개 로그만
    return build_scene(events, layout_from_scenario(layout_path) if layout_path else None)
