"""이벤트 로그 NDJSON 직렬화. 바이트 단위로 결정적인 출력을 만든다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from asel.core.events import Event


def dumps_canonical(obj) -> str:
    # float 는 repr 로 직렬화되어 왕복 시 정확히 같은 값으로 복원된다.
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def encode_events(events: Iterable[Event]) -> bytes:
    return "".join(dumps_canonical(e.to_dict()) + "\n" for e in events).encode("utf-8")


def events_sha256(events: Iterable[Event]) -> str:
    return hashlib.sha256(encode_events(events)).hexdigest()


def write_ndjson(events: Iterable[Event], path: Path) -> str:
    data = encode_events(events)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_ndjson(path: Path) -> list[Event]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(Event.from_dict(json.loads(line)))
    return out
