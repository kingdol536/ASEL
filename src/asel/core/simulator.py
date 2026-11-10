"""자체 이산 사건 루프 (결정: docs/decisions/0001-own-event-loop.md, 잠정).

- 대기열 정렬 키: (시각, 예약 순번). 같은 시각 사건은 예약된 순서대로 처리한다.
- 같은 시각의 사건을 모두 처리한 뒤 배정기(dispatcher)를 한 번 호출한다.
- 모든 상태 변경은 World.submit 을 거친다. 시뮬레이터는 상태를 직접 고치지 않는다.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Any, Protocol

from asel.core.actions import Action, ActionKind
from asel.core.invariants import check_invariants
from asel.core.model import WorldState
from asel.core.world import ENV_ACTOR, World


class InvariantViolation(RuntimeError):
    pass


class WorkloadSource(Protocol):
    """도메인 어댑터가 제공하는 외부 사건 발생기."""

    def initial_schedule(self) -> list[tuple[float, Any]]: ...

    def on_external(self, data: Any, now: float) -> tuple[list[Action], list[tuple[float, Any]]]:
        """외부 사건 처리 -> (제출할 행동, 새로 예약할 (시각, data))."""
        ...


class Dispatcher(Protocol):
    actor_id: str

    def propose(self, state: WorldState) -> list[Action]: ...


@dataclass(order=True)
class _Item:
    time: float
    seq: int
    kind: str  # "complete" | "external"
    data: Any = None


class Simulator:
    def __init__(
        self,
        world: World,
        source: WorkloadSource,
        dispatcher: Dispatcher,
        check_invariants: bool = True,
    ):
        self.world = world
        self.source = source
        self.dispatcher = dispatcher
        self.check = check_invariants
        self._queue: list[_Item] = []
        self._seq = 0

    def schedule(self, t: float, kind: str, data: Any = None) -> None:
        heapq.heappush(self._queue, _Item(t, self._seq, kind, data))
        self._seq += 1

    def _submit(self, action: Action) -> None:
        res = self.world.submit(action)
        if res.accepted and action.kind == ActionKind.START_TASK:
            task = self.world.state.tasks[action.params["task"]]
            self.schedule(task.started_at + task.duration, "complete", task.id)

    def _check(self) -> None:
        if self.check:
            v = check_invariants(self.world.state)
            if v:
                raise InvariantViolation(f"t={self.world.state.sim_time}: " + "; ".join(v))

    def _dispatch(self) -> None:
        for action in self.dispatcher.propose(self.world.state):
            self._submit(action)
        self._check()

    def run(self, until: float) -> None:
        for t, data in self.source.initial_schedule():
            self.schedule(t, "external", data)
        self._dispatch()

        while self._queue and self._queue[0].time <= until:
            now = self._queue[0].time
            self.world.advance_to(now)
            while self._queue and self._queue[0].time == now:
                item = heapq.heappop(self._queue)
                if item.kind == "complete":
                    self._submit(Action(ENV_ACTOR, ActionKind.COMPLETE_TASK, {"task": item.data}))
                elif item.kind == "external":
                    actions, later = self.source.on_external(item.data, now)
                    for a in actions:
                        self._submit(a)
                    for t, d in later:
                        if t < now:
                            raise ValueError(f"source scheduled into the past: {t} < {now}")
                        self.schedule(t, "external", d)
                else:
                    raise AssertionError(item.kind)
            self._check()
            self._dispatch()

        self.world.end_run(until)
