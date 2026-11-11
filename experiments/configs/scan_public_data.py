"""공개 전 검사 (M6 #51): 올릴 폴더에 키·개인 경로·이메일이 없는지 찾는다.

    uv run python experiments/configs/scan_public_data.py <폴더> [<폴더> ...]

찾은 내용 자체는 출력하지 않는다 (키일 수 있으므로). 파일 경로와 패턴 이름, 개수만 보고한다.
하나라도 있으면 종료 코드 1.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _patterns() -> dict[str, re.Pattern]:
    home = str(Path.home())
    variants = {home, home.replace("\\", "/"), home.replace("\\", "\\\\")}
    return {
        "anthropic_api_key": re.compile(rb"sk-ant-[A-Za-z0-9_\-]{8,}"),
        "generic_secret_assignment": re.compile(rb"(?i)(api[_-]?key|secret|password|token)\"?\s*[:=]\s*\"[A-Za-z0-9_\-]{16,}\""),
        "home_path": re.compile(b"|".join(re.escape(v.encode()) for v in sorted(variants))),
        "email": re.compile(rb"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+\.[A-Za-z0-9.\-]*[A-Za-z]{2,}"),
    }


def scan(roots: list[Path]) -> dict:
    pats = _patterns()
    hits: dict[str, dict[str, int]] = {}
    n_files = n_bytes = 0
    for root in roots:
        for p in sorted(x for x in root.rglob("*") if x.is_file()):
            data = p.read_bytes()
            n_files += 1
            n_bytes += len(data)
            for name, rx in pats.items():
                c = len(rx.findall(data))
                if c:
                    hits.setdefault(str(p), {})[name] = c
    return {"files": n_files, "bytes": n_bytes, "files_with_hits": len(hits),
            "hits": dict(list(hits.items())[:50])}


def main() -> None:
    out = scan([Path(a) for a in sys.argv[1:]])
    print(json.dumps(out, indent=2, ensure_ascii=False))
    sys.exit(1 if out["files_with_hits"] else 0)


if __name__ == "__main__":
    main()
