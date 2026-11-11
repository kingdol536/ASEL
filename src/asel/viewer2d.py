"""2D 재생 뷰어 (티켓 #6, 도구 선택 잠정).

실행 폴더의 **공개 로그(events.ndjson)만** 읽어 단일 HTML 을 만든다.
비공개 로그·scenario.json·final_state.json 은 읽지 않는다 (고장 원인 등 숨겨진 참값 포함).
뷰어는 로그를 읽기만 하므로 시뮬레이션 사건에 영향을 줄 수 없다.

보여주는 것:
- 셀 연결 그래프
- 셀별 작업 타임라인 (고장 구간 음영)
- capability 별 대기(READY) 작업 수 추이
- 거절된 행동 목록
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path

from asel.core.events import Event
from asel.io.eventlog import PUBLIC_LOG, read_public

PALETTE = ["#2f6fdf", "#d9772b", "#2a9d6a", "#a855c7", "#c23b52", "#6b7280",
           "#0e9aa7", "#b5892e", "#5b6ee1", "#d1497b"]


@dataclass
class _Bar:
    task: str
    capability: str
    start: float
    end: float | None


@dataclass
class _View:
    run_id: str = ""
    end_time: float = 0.0
    entities: list[dict] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    bars: dict[str, list[_Bar]] = field(default_factory=dict)
    outages: dict[str, list[list]] = field(default_factory=dict)  # entity -> [start, end|None, units]
    # 재구성: entity -> [kind('draining'|'changeover'), start, end|None, target capabilities]
    reconf: dict[str, list[list]] = field(default_factory=dict)
    ready_series: dict[str, list[tuple[float, int]]] = field(default_factory=dict)
    rejected: list[Event] = field(default_factory=list)
    n_events: int = 0
    # 공정 흐름(작업 묶음 종류별 첫 인스턴스의 단계 그래프), 목표 변경, 취소된 묶음 (#42)
    flows: dict[str, dict] = field(default_factory=dict)  # 접두어 -> {"inst", "nodes": {단계: 역할}, "edges": [(a, b)]}
    objectives: list[tuple[float, dict]] = field(default_factory=list)
    cancelled: dict[str, set] = field(default_factory=dict)  # 접두어 -> 취소된 인스턴스


def build_view(events: list[Event]) -> _View:
    v = _View(n_events=len(events))
    cap_of: dict[str, str] = {}
    running: dict[str, _Bar] = {}
    inst_of: dict[str, str] = {}
    ready_count: dict[str, int] = {}
    for ev in events:
        v.run_id = ev.run_id
        v.end_time = max(v.end_time, ev.sim_time)
        p = ev.payload
        et = ev.event_type
        if et == "WorldInitialized":
            v.entities = [dict(e) for e in p["entities"]]  # 이벤트 원본을 바꾸지 않도록 복사
            v.relations = p["relations"]
            for e in v.entities:
                v.bars[e["id"]] = []
                v.outages[e["id"]] = []
        elif et == "TaskCreated":
            inst = p.get("tags", {}).get("order")
            if inst and "/" in ev.entity_id:
                prefix = inst.rsplit("-", 1)[0]
                f = v.flows.setdefault(prefix, {"inst": inst, "nodes": {}, "edges": []})
                if f["inst"] == inst:  # 종류별 첫 인스턴스로 흐름 모양을 그린다
                    step = ev.entity_id.split("/", 1)[1]
                    f["nodes"][step] = p["capability"]
                    f["edges"] += [(q.split("/", 1)[1], step) for q in p["predecessors"] if "/" in q]
                inst_of[ev.entity_id] = inst
            cap_of[ev.entity_id] = p["capability"]
            ready_count.setdefault(p["capability"], 0)
            v.ready_series.setdefault(p["capability"], [(0.0, 0)])
        elif et == "TaskStateChanged":
            cap = cap_of.get(ev.entity_id, "?")
            if p["to"] == "READY":
                ready_count[cap] = ready_count.get(cap, 0) + 1
                v.ready_series.setdefault(cap, [(0.0, 0)]).append((ev.sim_time, ready_count[cap]))
            if p["from"] == "READY":
                ready_count[cap] -= 1
                v.ready_series[cap].append((ev.sim_time, ready_count[cap]))
            if p["to"] == "RUNNING":
                bar = _Bar(ev.entity_id, cap, ev.sim_time, None)
                running[ev.entity_id] = bar
                v.bars.setdefault(p["entity"], []).append(bar)
            elif p["to"] == "COMPLETED" and ev.entity_id in running:
                running.pop(ev.entity_id).end = ev.sim_time
            elif p["to"] == "CANCELLED" and ev.entity_id in inst_of:
                inst = inst_of[ev.entity_id]
                v.cancelled.setdefault(inst.rsplit("-", 1)[0], set()).add(inst)
        elif et == "ResourceOutageStarted":
            v.outages.setdefault(ev.entity_id, []).append([ev.sim_time, None, p["units"]])
        elif et == "ResourceOutageEnded":
            for o in v.outages.get(ev.entity_id, []):
                if o[1] is None:
                    o[1] = ev.sim_time
                    break
        elif et == "ReconfigurationRequested":
            v.reconf.setdefault(ev.entity_id, []).append(["draining", ev.sim_time, None, p["capabilities"]])
        elif et == "ReconfigurationStarted":
            segs = v.reconf.setdefault(ev.entity_id, [])
            target = segs[-1][3] if segs else []
            if segs and segs[-1][2] is None:
                segs[-1][2] = ev.sim_time
            segs.append(["changeover", ev.sim_time, None, target])
        elif et == "ReconfigurationCompleted":
            for ent in v.entities:  # 그래프는 실행 종료 시점의 역할로 그린다
                if ent["id"] == ev.entity_id:
                    ent["capabilities"] = list(p["capabilities"])
            segs = v.reconf.get(ev.entity_id, [])
            if segs and segs[-1][2] is None:
                segs[-1][2] = ev.sim_time
        elif et == "ObjectiveChanged":
            v.objectives.append((ev.sim_time, p["objective"]))
        elif et == "ActionRejected":
            v.rejected.append(ev)
    return v


# ---------------------------------------------------------------------------- SVG


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _x(t: float, t_end: float, x0: float, w: float) -> float:
    return x0 + (t / t_end) * w if t_end > 0 else x0


def _ticks(t_end: float) -> list[float]:
    step = 600.0 if t_end > 2400 else 300.0 if t_end > 600 else 60.0
    n = int(t_end // step)
    return [i * step for i in range(n + 1)]


def _cap_colors(v: _View) -> dict[str, str]:
    caps = sorted({c for e in v.entities for c in e["capabilities"]} | set(v.ready_series))
    return {c: PALETTE[i % len(PALETTE)] for i, c in enumerate(caps)}


def _graph_svg(v: _View, colors: dict[str, str]) -> str:
    # 첫 capability 가 등장하는 순서대로 열을 만든다 (예: pick -> pack)
    cols: list[str] = []
    for e in v.entities:
        c = e["capabilities"][0] if e["capabilities"] else "-"
        if c not in cols:
            cols.append(c)
    by_col = {c: [e for e in v.entities if (e["capabilities"] or ["-"])[0] == c] for c in cols}
    nw, nh, gx, gy = 150, 36, 90, 16
    height = max(len(es) for es in by_col.values()) * (nh + gy) + 20
    width = len(cols) * (nw + gx) + 20
    pos = {}
    for ci, c in enumerate(cols):
        es = by_col[c]
        col_h = len(es) * (nh + gy) - gy
        top = (height - col_h) / 2
        for ri, e in enumerate(es):
            pos[e["id"]] = (10 + ci * (nw + gx), top + ri * (nh + gy))
    parts = [
        f'<svg viewBox="0 0 {width} {height}" class="graph" role="img" aria-label="셀 연결 그래프">',
        '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="edge-head"/></marker></defs>',
    ]
    for r in v.relations:
        if r["source"] in pos and r["target"] in pos:
            sx, sy = pos[r["source"]]
            tx, ty = pos[r["target"]]
            parts.append(
                f'<line x1="{sx + nw:.1f}" y1="{sy + nh / 2:.1f}" x2="{tx - 2:.1f}" y2="{ty + nh / 2:.1f}" '
                f'class="edge" marker-end="url(#arr)"><title>{_esc(r["kind"])}</title></line>'
            )
    for e in v.entities:
        x, y = pos[e["id"]]
        col = colors.get((e["capabilities"] or ["-"])[0], "#888")
        parts.append(
            f'<g><rect x="{x}" y="{y:.1f}" width="{nw}" height="{nh}" rx="6" class="node" '
            f'style="stroke:{col}"/><text x="{x + 10}" y="{y + 15:.1f}" class="node-id">{_esc(e["id"])}</text>'
            f'<text x="{x + 10}" y="{y + 29:.1f}" class="node-cap">{_esc(", ".join(e["capabilities"]))}</text>'
            f"<title>{_esc(e['id'])} ({_esc(e['type'])})</title></g>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _gantt_svg(v: _View, colors: dict[str, str]) -> str:
    label_w, w, row_h, top = 120, 900, 26, 24
    ids = [e["id"] for e in v.entities]
    height = top + len(ids) * row_h + 10
    t_end = v.end_time or 1.0
    out = [f'<svg viewBox="0 0 {label_w + w + 10} {height}" class="gantt" role="img" aria-label="셀별 작업 타임라인">']
    for t in _ticks(t_end):
        x = _x(t, t_end, label_w, w)
        out.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{height - 10}" class="grid"/>')
        out.append(f'<text x="{x:.1f}" y="{top - 8}" class="tick">{int(t)}s</text>')
    for i, eid in enumerate(ids):
        y = top + i * row_h
        out.append(f'<text x="{label_w - 8}" y="{y + row_h * 0.62:.1f}" class="row-label">{_esc(eid)}</text>')
        for start, end, units in v.outages.get(eid, []):
            x1, x2 = _x(start, t_end, label_w, w), _x(end if end is not None else t_end, t_end, label_w, w)
            out.append(
                f'<rect x="{x1:.1f}" y="{y + 1}" width="{max(x2 - x1, 1):.1f}" height="{row_h - 2}" class="outage">'
                f"<title>고장 {int(start)}s–{'진행중' if end is None else f'{int(end)}s'} · 용량 {units}단위 감소</title></rect>"
            )
        for kind, start, end, target in v.reconf.get(eid, []):
            x1, x2 = _x(start, t_end, label_w, w), _x(end if end is not None else t_end, t_end, label_w, w)
            label = "작업 비우는 중" if kind == "draining" else "역할 전환 중"
            out.append(
                f'<rect x="{x1:.1f}" y="{y + 1}" width="{max(x2 - x1, 1):.1f}" height="{row_h - 2}" class="{kind}">'
                f"<title>{label} {int(start)}s–{'진행중' if end is None else f'{int(end)}s'} → {_esc(', '.join(target))}</title></rect>"
            )
            if kind == "changeover" and end is not None:
                out.append(f'<text x="{x2 + 2:.1f}" y="{y + row_h * 0.62:.1f}" class="reconf-label">→{_esc(",".join(target))}</text>')
        for b in v.bars.get(eid, []):
            x1 = _x(b.start, t_end, label_w, w)
            x2 = _x(b.end if b.end is not None else t_end, t_end, label_w, w)
            cls = "bar open" if b.end is None else "bar"
            end_txt = "진행 중" if b.end is None else f"{b.end:.1f}s"
            out.append(
                f'<rect x="{x1:.2f}" y="{y + 5}" width="{max(x2 - x1, 0.8):.2f}" height="{row_h - 10}" '
                f'class="{cls}" style="fill:{colors.get(b.capability, "#888")}">'
                f"<title>{_esc(b.task)} · {b.start:.1f}s → {end_txt}</title></rect>"
            )
    for t_obj, obj in v.objectives:
        x = _x(t_obj, t_end, label_w, w)
        out.append(f'<line x1="{x:.1f}" y1="{top - 4}" x2="{x:.1f}" y2="{height - 10}" class="objective">'
                   f'<title>목표 변경 {t_obj:.0f}s → {_esc(obj.get("id"))} ({_esc(obj.get("kind"))})</title></line>')
    out.append("</svg>")
    return "".join(out)


def _flows_svg(v: _View, colors: dict[str, str]) -> str:
    """작업 묶음 종류별 공정 흐름 (단계 DAG). 깊이(가장 긴 선행 경로)로 열을 나눈다."""
    if not v.flows:
        return '<p class="note">공정 흐름 정보 없음</p>'
    parts = []
    nw, nh, gx, gy = 110, 30, 46, 10
    for prefix, f in sorted(v.flows.items()):
        depth: dict[str, int] = {}
        for step in f["nodes"]:  # 단계는 선행 단계 뒤에 만들어지므로 순서대로 계산된다
            preds = [a for a, b in f["edges"] if b == step]
            depth[step] = 1 + max((depth.get(a, 0) for a in preds), default=-1)
        cols: dict[int, list[str]] = {}
        for step, d in depth.items():
            cols.setdefault(d, []).append(step)
        ncol, nrow = max(cols) + 1, max(len(x) for x in cols.values())
        width, height = ncol * (nw + gx) + 10, nrow * (nh + gy) + 10
        pos = {s: (5 + d * (nw + gx), 5 + r * (nh + gy)) for d, ss in cols.items() for r, s in enumerate(ss)}
        svg = [f'<svg viewBox="0 0 {width} {height}" class="flow" role="img" aria-label="{_esc(prefix)} 공정 흐름">',
               '<defs><marker id="farr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
               'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="edge-head"/></marker></defs>']
        for a, b in f["edges"]:
            (ax, ay), (bx, by) = pos[a], pos[b]
            svg.append(f'<line x1="{ax + nw}" y1="{ay + nh / 2}" x2="{bx - 2}" y2="{by + nh / 2}" class="edge" marker-end="url(#farr)"/>')
        for step, cap in f["nodes"].items():
            x, y = pos[step]
            svg.append(f'<g><rect x="{x}" y="{y}" width="{nw}" height="{nh}" rx="5" class="node" style="stroke:{colors.get(cap, "#888")}"/>'
                       f'<text x="{x + 8}" y="{y + 13}" class="node-id">{_esc(step)}</text>'
                       f'<text x="{x + 8}" y="{y + 25}" class="node-cap">{_esc(cap)}</text></g>')
        svg.append("</svg>")
        n_cancel = len(v.cancelled.get(prefix, ()))
        note = f" · 취소된 묶음 {n_cancel}개" if n_cancel else ""
        parts.append(f'<div class="flow-title">{_esc(prefix)}{note}</div>' + "".join(svg))
    return "".join(parts)


def _ready_svg(v: _View, colors: dict[str, str]) -> str:
    label_w, w, h, top = 120, 900, 160, 16
    t_end = v.end_time or 1.0
    ymax = max([n for s in v.ready_series.values() for _, n in s] + [1])
    out = [f'<svg viewBox="0 0 {label_w + w + 10} {h + top + 24}" class="ready" role="img" aria-label="대기 작업 수 추이">']
    for frac in (0, 0.5, 1):
        y = top + h - frac * h
        out.append(f'<line x1="{label_w}" y1="{y:.1f}" x2="{label_w + w}" y2="{y:.1f}" class="grid"/>')
        out.append(f'<text x="{label_w - 8}" y="{y + 4:.1f}" class="row-label">{round(frac * ymax)}</text>')
    for t in _ticks(t_end):
        x = _x(t, t_end, label_w, w)
        out.append(f'<text x="{x:.1f}" y="{top + h + 16}" class="tick">{int(t)}s</text>')
    for cap, series in sorted(v.ready_series.items()):
        pts = []
        prev_n = 0
        for t, n in series + [(t_end, series[-1][1] if series else 0)]:
            x = _x(t, t_end, label_w, w)
            pts.append(f"{x:.1f},{top + h - prev_n / ymax * h:.1f}")
            pts.append(f"{x:.1f},{top + h - n / ymax * h:.1f}")
            prev_n = n
        out.append(
            f'<polyline points="{" ".join(pts)}" class="line" style="stroke:{colors.get(cap, "#888")}">'
            f"<title>{_esc(cap)} 대기 작업 수</title></polyline>"
        )
    for t_obj, obj in v.objectives:
        x = _x(t_obj, t_end, label_w, w)
        out.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + h}" class="objective">'
                   f'<title>목표 변경 {t_obj:.0f}s → {_esc(obj.get("id"))} ({_esc(obj.get("kind"))})</title></line>')
    out.append("</svg>")
    return "".join(out)


CSS = """
:root{--bg:#ffffff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--panel:#f6f8fa;--node:#ffffff;--outage:rgba(194,59,82,.16);--draining:rgba(217,119,43,.14);--changeover:rgba(107,114,128,.32)}
@media (prefers-color-scheme: dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;--panel:#161b22;--node:#0d1117;--outage:rgba(248,81,73,.22);--draining:rgba(217,119,43,.22);--changeover:rgba(160,166,176,.32)}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px}
.meta{color:var(--muted);font-size:13px}.note{color:var(--muted);font-size:12px;margin-top:4px}
section{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px;overflow-x:auto}
svg{display:block;width:100%;height:auto;min-width:640px}.graph{max-width:640px;min-width:0}
.node{fill:var(--node);stroke-width:2}.node-id{font-size:12px;font-weight:600;fill:var(--fg)}.node-cap{font-size:11px;fill:var(--muted)}
.edge{stroke:var(--muted);stroke-width:1.4}.edge-head{fill:var(--muted)}
.grid{stroke:var(--line);stroke-width:1}.tick{font-size:10px;fill:var(--muted);text-anchor:middle}
.row-label{font-size:11px;fill:var(--fg);text-anchor:end}.bar{opacity:.9}.bar.open{opacity:.45}
.outage{fill:var(--outage)}.draining{fill:var(--draining)}.changeover{fill:var(--changeover)}
.reconf-label{font-size:9px;fill:var(--muted)}
.objective{stroke:var(--fg);stroke-width:1.2;stroke-dasharray:4 3;opacity:.7}
.flow{max-width:760px;min-width:0;margin-bottom:8px}.flow-title{font-size:12px;color:var(--muted);margin:6px 0 2px}.line{fill:none;stroke-width:1.6}
.legend{display:flex;gap:16px;flex-wrap:wrap;margin:6px 0 0;font-size:12px;color:var(--muted)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
"""


def render_html(v: _View) -> str:
    colors = _cap_colors(v)
    cap_legend = "".join(
        f'<span><span class="sw" style="background:{c}"></span>{_esc(k)}</span>' for k, c in colors.items()
    )
    legend = cap_legend + '<span><span class="sw" style="background:var(--outage)"></span>고장 구간</span>'
    if v.reconf:
        legend += ('<span><span class="sw" style="background:var(--draining)"></span>작업 비우는 중</span>'
                   '<span><span class="sw" style="background:var(--changeover)"></span>역할 전환 중</span>')
    n_cancel = sum(len(x) for x in v.cancelled.values())
    extra_meta = (f" · 취소된 작업 묶음 {n_cancel}개" if n_cancel else "") + (
        f" · 목표 변경 {len(v.objectives)}회 (점선)" if v.objectives else "")
    n_tasks = sum(len(b) for b in v.bars.values())
    if v.rejected:
        rows = "".join(
            f"<tr><td>{e.sim_time:.1f}s</td><td>{_esc(e.actor_id)}</td>"
            f"<td>{_esc(e.payload['action']['kind'])}</td><td>{_esc('; '.join(e.payload['reasons']))}</td></tr>"
            for e in v.rejected[:200]
        )
        rejected = (
            f"<table><thead><tr><th>시각</th><th>주체</th><th>행동</th><th>사유</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            + (f'<p class="note">처음 200건만 표시 (전체 {len(v.rejected)}건)</p>' if len(v.rejected) > 200 else "")
        )
    else:
        rejected = '<p class="note">거절된 행동 없음</p>'
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ASEL 실행 재생</title><style>{CSS}</style></head>
<body><main>
<h1>실행 재생 (2D)</h1>
<div class="meta">{_esc(v.run_id)} · 사건 {v.n_events}개 · 종료 {v.end_time:.0f}s · 시작된 작업 {n_tasks}개{extra_meta}</div>
<p class="note">공개 로그만으로 그린 화면입니다. 실제 처리 시간·고장 원인 같은 숨겨진 값은 포함하지 않습니다. 시나리오 수치는 가상 값입니다.</p>
<h2>셀 연결</h2><section>{_graph_svg(v, colors)}<p class="note">셀 역할은 실행 종료 시점 기준입니다.</p></section>
<h2>공정 흐름</h2><section>{_flows_svg(v, colors)}<p class="note">작업 묶음 종류별 첫 인스턴스의 단계와 선행관계입니다. 화살표가 모이는 단계는 앞 단계가 모두 끝나야 시작합니다.</p></section>
<h2>셀별 작업 타임라인</h2><section>{_gantt_svg(v, colors)}<div class="legend">{legend}</div>
<p class="note">막대에 마우스를 올리면 작업 id와 시각이 보입니다. 흐린 막대는 종료 시점에 진행 중이던 작업입니다.</p></section>
<h2>대기(READY) 작업 수</h2><section>{_ready_svg(v, colors)}<div class="legend">{cap_legend}</div></section>
<h2>거절된 행동</h2><section>{rejected}</section>
</main></body></html>
"""


def render_run(run_dir: Path, out: Path | None = None) -> Path:
    events = read_public(run_dir / PUBLIC_LOG)
    out = out or (run_dir / "view.html")
    out.write_text(render_html(build_view(events)), encoding="utf-8", newline="\n")
    return out
