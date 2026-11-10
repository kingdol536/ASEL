"""이벤트 로그 NDJSON 직렬화. 바이트 단위로 결정적인 출력을 만든다.

실행 폴더에는 두 파일이 생긴다.
- events.ndjson          : 공개 로그. 운영 정책·뷰어가 읽어도 되는 부분만.
- private_events.ndjson  : 비공개 로그. {"seq", "private"} 만 담고 seq 로 공개 로그와 연결.
                           평가기·재생 검증 전용. 운영 정책에 넘기지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from asel.core.events import Event

PUBLIC_LOG = "events.ndjson"
PRIVATE_LOG = "private_events.ndjson"


def dumps_canonical(obj) -> str:
    # float 는 repr 로 직렬화되어 왕복 시 정확히 같은 값으로 복원된다.
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _lines(objs: Iterable[dict]) -> bytes:
    return "".join(dumps_canonical(o) + "\n" for o in objs).encode("utf-8")


def encode_events(events: Iterable[Event]) -> bytes:
    """공개+비공개 전체 (메모리 내 비교·해시용)."""
    return _lines(e.to_dict() for e in events)


def encode_public(events: Iterable[Event]) -> bytes:
    return _lines(e.to_public_dict() for e in events)


def encode_private(events: Iterable[Event]) -> bytes:
    return _lines({"seq": e.seq, "private": e.private} for e in events if e.private)


def events_sha256(events: Iterable[Event]) -> str:
    return hashlib.sha256(encode_events(events)).hexdigest()


def write_run_logs(events: list[Event], run_dir: Path) -> dict[str, str]:
    pub, priv = encode_public(events), encode_private(events)
    (run_dir / PUBLIC_LOG).write_bytes(pub)
    (run_dir / PRIVATE_LOG).write_bytes(priv)
    return {
        "events_sha256": hashlib.sha256(pub).hexdigest(),
        "private_events_sha256": hashlib.sha256(priv).hexdigest(),
    }


def _read_json_lines(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def read_public(path: Path) -> list[Event]:
    """공개 로그만 읽는다. private 는 모두 비어 있다."""
    return [Event.from_dict(d) for d in _read_json_lines(path)]


def read_full(public_path: Path, private_path: Path) -> list[Event]:
    """공개+비공개를 seq 로 합친다 (평가기·재생 검증 전용)."""
    hidden = {d["seq"]: d["private"] for d in _read_json_lines(private_path)}
    events = []
    for d in _read_json_lines(public_path):
        events.append(Event.from_dict({**d, "private": hidden.pop(d["seq"], {})}))
    if hidden:
        raise ValueError(f"private records without public event: seq {sorted(hidden)[:5]}")
    return events


def read_run(run_dir: Path) -> list[Event]:
    return read_full(run_dir / PUBLIC_LOG, run_dir / PRIVATE_LOG)
