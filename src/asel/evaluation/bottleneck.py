"""병목 지표 (티켓 #23, 평가기 0.3). 공개 로그만 사용한다.

docs/06 §5 의 후보 정의 b_i(t) = 수요 / 가용 처리능력 을 capability 단위로 구현한다.
- 수요_c(t): capability c 가 필요한 작업 중 READY + RUNNING 수 (그 단계에 '들어와 있는' 일)
- 가용 처리능력_c(t): c 를 제공하는 셀의 처리 가능 용량 합.
  정상 셀 = 용량 − 고장 단위, 비우는 중 셀 = 아직 처리 중인 작업 수(그만큼은 실제로 일하고 있음), 전환 중 셀 = 0.
  (평가기 0.4: 0.3 은 비우는 중 셀을 0 으로 세어, 그 셀의 진행 작업이 수요에만 들어가 부하가 부풀었다 — 코드 리뷰 지적)
- b_c(t) = 수요_c / max(가용_c, 1). 분모 하한 1 은 docs/06 정의에서 벗어나는 구현 선택이다:
  가용 0 인 구간(고장·전환)에서 무한대가 되는 것을 막고, 그 구간은 zero_capacity_s 로 따로 보고한다.

창(window) 단위로 b_c 의 시간 가중 평균을 내고, 가장 큰 capability 를 그 창의 병목으로 본다.
최댓값이 1 미만이면 병목 없음('-'). 병목 이동 횟수 = 연속한 두 창의 병목이 서로 다른 capability 인 횟수('-' 제외).
"""

from __future__ import annotations

from asel.core.model import EntityMode, TaskStatus, WorldState
from asel.core.world import apply_event

WINDOW_S = 300.0


def _loads(st: WorldState) -> tuple[dict[str, float], dict[str, bool]]:
    demand: dict[str, int] = {}
    for t in st.tasks.values():
        if t.status in (TaskStatus.READY, TaskStatus.RUNNING):
            demand[t.capability] = demand.get(t.capability, 0) + 1
    cap: dict[str, int] = {}
    for e in st.entities.values():
        res = st.resources.get(e.id)
        if res is None:
            continue
        if e.mode == EntityMode.NORMAL:
            usable = max(res.capacity - res.out_of_service, 0)
        elif e.mode == EntityMode.DRAINING:
            usable = min(res.reserved, max(res.capacity - res.out_of_service, 0))
        else:
            usable = 0
        for c in e.capabilities:
            cap[c] = cap.get(c, 0) + usable
    keys = set(demand) | set(cap)
    loads = {c: demand.get(c, 0) / max(cap.get(c, 0), 1) for c in keys}
    starved = {c: demand.get(c, 0) > 0 and cap.get(c, 0) == 0 for c in keys}
    return loads, starved


def _idle_reconfig_capacity(st: WorldState) -> float:
    """재구성 때문에 놀고 있는 용량: 전환 중 셀의 용량 전부 + 비우는 중 셀의 (용량 − 처리 중 작업)."""
    lost = 0.0
    for e in st.entities.values():
        res = st.resources.get(e.id)
        if res is None:
            continue
        usable = max(res.capacity - res.out_of_service, 0)
        if e.mode == EntityMode.CHANGEOVER:
            lost += usable
        elif e.mode == EntityMode.DRAINING:
            lost += max(usable - res.reserved, 0)
    return lost


def structure_metrics(public_events, window_s: float = WINDOW_S) -> dict:
    st = WorldState()
    integ: dict[int, dict[str, float]] = {}  # 창 번호 -> capability -> ∫b dt
    total: dict[str, float] = {}
    zero_cap_s: dict[str, float] = {}
    prev_t = 0.0
    prev_loads: dict[str, float] = {}
    prev_starved: dict[str, bool] = {}
    prev_idle = 0.0
    end_t = 0.0
    req_at: dict[str, float] = {}
    start_at: dict[str, float] = {}
    draining_s = changeover_s = 0.0
    n_req = n_done = 0
    lost_capacity_s = 0.0

    def accumulate(t0: float, t1: float):
        # [t0, t1) 구간을 창 경계로 잘라 직전 부하를 적분한다
        nonlocal lost_capacity_s
        lost_capacity_s += prev_idle * (t1 - t0)
        t = t0
        while t < t1:
            w = int(t // window_s)
            seg_end = min(t1, (w + 1) * window_s)
            dt = seg_end - t
            bucket = integ.setdefault(w, {})
            for c, b in prev_loads.items():
                bucket[c] = bucket.get(c, 0.0) + b * dt
                total[c] = total.get(c, 0.0) + b * dt
                if prev_starved.get(c):
                    zero_cap_s[c] = zero_cap_s.get(c, 0.0) + dt
            t = seg_end

    for ev in public_events:
        if ev.sim_time > prev_t:
            accumulate(prev_t, ev.sim_time)
            prev_t = ev.sim_time
        apply_event(st, ev)
        end_t = max(end_t, ev.sim_time)
        et, eid = ev.event_type, ev.entity_id
        if et == "ReconfigurationRequested":
            n_req += 1
            req_at[eid] = ev.sim_time
        elif et == "ReconfigurationStarted":
            d = ev.sim_time - req_at.get(eid, ev.sim_time)
            draining_s += d
            start_at[eid] = ev.sim_time
        elif et == "ReconfigurationCompleted":
            n_done += 1
            d = ev.sim_time - start_at.get(eid, ev.sim_time)
            changeover_s += d
        prev_loads, prev_starved = _loads(st)
        prev_idle = _idle_reconfig_capacity(st)

    labels = []
    for w in range(int(end_t // window_s) + (1 if end_t % window_s else 0)):
        span = min(window_s, end_t - w * window_s)
        means = {c: v / span for c, v in integ.get(w, {}).items()} if span > 0 else {}
        if not means:
            labels.append("-")
            continue
        c, b = max(sorted(means.items()), key=lambda kv: kv[1])
        labels.append(c if b >= 1.0 else "-")
    shifts = sum(1 for a, b in zip(labels, labels[1:]) if a != "-" and b != "-" and a != b)
    return {
        "definition": "b_c = (READY+RUNNING of c) / max(normal-mode usable capacity of c, 1); docs/06 §5",
        "window_s": window_s,
        "load_mean": {c: v / end_t for c, v in sorted(total.items())} if end_t > 0 else {},
        "bottleneck_by_window": labels,
        "bottleneck_shifts": shifts,
        "zero_capacity_s": dict(sorted(zero_cap_s.items())),
        "reconfig_requested": n_req,
        "reconfig_completed": n_done,
        "draining_s_total": draining_s,
        "changeover_s_total": changeover_s,
        "lost_capacity_s": lost_capacity_s,
    }
