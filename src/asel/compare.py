"""두 이벤트 로그 비교: 바이트 동일 / 논리적 동일(허용 오차 내) / 다름.

플랫폼 간 결정성 측정용 (docs/decisions/0001). 논리적 동일의 기준(잠정):
사건 개수·순서·종류·대상·주체·버전이 모두 같고, 수치 필드는 상대 오차 1e-9 이내.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from asel.core.events import Event

REL_TOL = 1e-9


@dataclass
class Comparison:
    byte_equal: bool
    logically_equal: bool
    max_rel_diff: float
    first_mismatch: str | None


def _cmp(a, b, path: str, worst: list[float]) -> str | None:
    if isinstance(a, bool) or isinstance(b, bool):
        return None if a == b else path
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if a == b:
            return None
        rel = abs(a - b) / max(abs(a), abs(b), 1e-300)
        worst[0] = max(worst[0], rel)
        return None if math.isclose(a, b, rel_tol=REL_TOL, abs_tol=0.0) else path
    if isinstance(a, dict) and isinstance(b, dict):
        if a.keys() != b.keys():
            return path + " (keys)"
        for k in sorted(a):
            m = _cmp(a[k], b[k], f"{path}.{k}", worst)
            if m:
                return m
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return path + " (length)"
        for i, (x, y) in enumerate(zip(a, b)):
            m = _cmp(x, y, f"{path}[{i}]", worst)
            if m:
                return m
        return None
    return None if a == b else path


def compare_logs(a: list[Event], b: list[Event], a_bytes: bytes, b_bytes: bytes) -> Comparison:
    worst = [0.0]
    mismatch = None
    if len(a) != len(b):
        mismatch = f"event count {len(a)} != {len(b)}"
    else:
        for i, (x, y) in enumerate(zip(a, b)):
            dx, dy = x.to_dict(), y.to_dict()
            dx.pop("run_id"), dy.pop("run_id")
            m = _cmp(dx, dy, f"event[{i}]", worst)
            if m:
                mismatch = m
                break
    return Comparison(
        byte_equal=a_bytes == b_bytes,
        logically_equal=mismatch is None,
        max_rel_diff=worst[0],
        first_mismatch=mismatch,
    )
