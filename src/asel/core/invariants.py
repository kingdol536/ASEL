"""상태 불변조건 검사 (docs/03-WORLD-MODEL.md §8).

위반 목록을 돌려준다. 빈 목록이면 통과.
"""

from __future__ import annotations

from asel.core.model import EntityMode, TaskStatus, WorldState, roles_over_ceiling

_DONE_OR_RUNNING = {TaskStatus.RUNNING, TaskStatus.COMPLETED}


def check_invariants(state: WorldState) -> list[str]:
    v: list[str] = []
    holder_of: dict[str, str] = {}

    # 1. 자원: 0 <= reserved <= capacity, 중복 예약 없음, 예약자는 RUNNING 작업
    for res in state.resources.values():
        if res.capacity < 0:
            v.append(f"resource {res.id}: negative capacity {res.capacity}")
        if not 0 <= res.out_of_service <= res.capacity:
            v.append(f"resource {res.id}: out_of_service {res.out_of_service} outside [0, {res.capacity}]")
        if res.reserved > res.capacity:
            v.append(f"resource {res.id}: reserved {res.reserved} > capacity {res.capacity}")
        if len(set(res.holders)) != len(res.holders):
            v.append(f"resource {res.id}: duplicate holders {res.holders}")
        for tid in res.holders:
            if tid in holder_of:
                v.append(f"task {tid}: holds both {holder_of[tid]} and {res.id}")
            holder_of[tid] = res.id
            t = state.tasks.get(tid)
            if t is None:
                v.append(f"resource {res.id}: holder {tid} does not exist")
            elif t.status != TaskStatus.RUNNING:
                v.append(f"resource {res.id}: holder {tid} is {t.status}, not RUNNING")

    # 0. 재구성 상태: 전환 중 셀에는 작업이 없고, 비우는 중 셀의 작업은 요청 전에 시작된 것뿐
    for e in state.entities.values():
        res = state.resources.get(e.id)
        holders = res.holders if res else []
        if e.mode == EntityMode.CHANGEOVER and holders:
            v.append(f"entity {e.id}: changeover with running tasks {holders}")
        if e.mode == EntityMode.DRAINING:
            for tid in holders:
                t = state.tasks.get(tid)
                if t is not None and t.started_at is not None and t.started_at > e.mode_since:
                    v.append(f"entity {e.id}: task {tid} started after drain request")
        if e.mode == EntityMode.NORMAL and e.target_capabilities is not None:
            v.append(f"entity {e.id}: normal mode with pending target")
        if e.mode != EntityMode.NORMAL and e.target_capabilities is None:
            v.append(f"entity {e.id}: {e.mode} without target")
        # 3D 공간: 개체의 역할(과 전환 목표)이 그 자리 천장 높이 안에 들어간다 (#40)
        for c in roles_over_ceiling(e.space, state.capability_space,
                                    set(e.capabilities) | set(e.target_capabilities or ())):
            v.append(f"entity {e.id}: role {c} does not fit under ceiling {e.space['ceiling_m']} m")

    for t in state.tasks.values():
        preds = [state.tasks.get(p) for p in t.predecessors]
        if any(p is None for p in preds):
            v.append(f"task {t.id}: unknown predecessor")
            continue
        preds_done = all(p.status == TaskStatus.COMPLETED for p in preds)

        # 2. RUNNING 작업은 정확히 하나의 자원을 쥐고 있고, 그 자원은 배정된 셀이다
        if t.status == TaskStatus.RUNNING:
            if holder_of.get(t.id) != t.assigned_entity:
                v.append(f"task {t.id}: RUNNING on {t.assigned_entity} but holds {holder_of.get(t.id)}")

        # 3. 선행관계: 시작·완료한 작업의 선행 작업은 모두 완료
        if t.status in _DONE_OR_RUNNING and not preds_done:
            v.append(f"task {t.id}: {t.status} before predecessors completed")
        if t.status == TaskStatus.READY and not preds_done:
            v.append(f"task {t.id}: READY with unfinished predecessors")
        if t.status == TaskStatus.WAITING and preds_done:
            v.append(f"task {t.id}: WAITING although predecessors are completed")

        # 4. 배정된 셀은 작업에 필요한 capability 를 가진다 (진행 중 작업만: 완료된 작업의 셀은
        #    그 뒤 재구성으로 역할이 바뀌었을 수 있다. 시작 시점의 일치는 검증기가 보장)
        if t.status == TaskStatus.RUNNING:
            ent = state.entities.get(t.assigned_entity or "")
            if ent is None:
                v.append(f"task {t.id}: assigned to unknown entity {t.assigned_entity}")
            elif t.capability not in ent.capabilities:
                v.append(f"task {t.id}: entity {ent.id} lacks capability {t.capability}")

        # 5. 시간 순서: 생성 <= 준비 <= 시작, 완료 = 시작 + 처리시간 이상
        if t.started_at is not None and t.ready_at is not None and t.started_at < t.ready_at:
            v.append(f"task {t.id}: started before ready")
        if t.status == TaskStatus.COMPLETED:
            if t.started_at is None or t.completed_at is None:
                v.append(f"task {t.id}: COMPLETED without timestamps")
            elif t.duration is not None and t.completed_at < t.started_at + t.duration:
                v.append(f"task {t.id}: completed early")

    # 6. 선행 작업의 시작은 후속 작업보다 앞선다 (완료 시각 기준)
    for t in state.tasks.values():
        if t.started_at is None:
            continue
        for pid in t.predecessors:
            p = state.tasks[pid]
            if p.completed_at is None or p.completed_at > t.started_at:
                v.append(f"task {t.id}: started at {t.started_at} before predecessor {pid} completed")

    return v
