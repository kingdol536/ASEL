"""용도별로 분리한 난수 스트림.

- 스트림 시드 = sha256(f"{seed}/{name}") 이므로 스트림을 하나 추가해도 다른 스트림 값은 그대로다.
- `random.Random(int)` 시딩과 `.random()` 출력은 Python 버전 간 동일함이 보장된다.
  분포 변환은 직접 구현해 라이브러리 버전 변화의 영향을 받지 않게 한다.
- `math.log` 는 플랫폼 libm 을 쓰므로 OS 간 마지막 자리 차이 가능성은 남는다(미검증).
"""

from __future__ import annotations

import hashlib
import math
import random


def stream_seed(seed: int, name: str) -> int:
    digest = hashlib.sha256(f"{seed}/{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class RngStreams:
    def __init__(self, seed: int):
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def get(self, name: str) -> random.Random:
        if name not in self._streams:
            self._streams[name] = random.Random(stream_seed(self.seed, name))
        return self._streams[name]


def exponential(rng: random.Random, mean: float) -> float:
    return -mean * math.log(1.0 - rng.random())  # random() in [0,1) -> log 인자 (0,1]


def uniform(rng: random.Random, low: float, high: float) -> float:
    return low + (high - low) * rng.random()
