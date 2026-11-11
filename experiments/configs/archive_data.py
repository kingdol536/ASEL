"""원자료 보관 (M6 #51). 실험 배치 폴더와 Claude 응답 캐시를 압축하고 SHA-256 을 남긴다.

    uv run python experiments/configs/archive_data.py dist/asel-data

만든 파일은 GitHub Release 자산으로 올린다 (저장소에는 체크섬 목록만 커밋).
- batches-<실험>.zip : experiments/batches/<실험> (실행별 사건 로그·manifest·평가)
- llm-cache.zip      : Claude 응답 캐시 (응답 텍스트·사용량만, 요청·키 없음). 풀어서 ASEL_LLM_DIR 로 지정하면
                       Claude 실행도 API 키 없이 replay 로 재현된다.
"""

from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

from asel.agents.claude_policy import default_llm_dir

ROOT = Path(__file__).resolve().parents[2]


def _zip(src: Path, dest: Path, arc_root: str) -> None:
    files = sorted(p for p in src.rglob("*") if p.is_file())
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, f"{arc_root}/{p.relative_to(src).as_posix()}")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for d in sorted((ROOT / "experiments" / "batches").iterdir()):
        if d.is_dir():
            dest = out / f"batches-{d.name}.zip"
            _zip(d, dest, f"experiments/batches/{d.name}")
            made.append(dest)
    cache = default_llm_dir() / "cache"
    if cache.is_dir():
        dest = out / "llm-cache.zip"
        _zip(cache, dest, "cache")
        made.append(dest)
    lines = [f"{_sha(p)}  {p.name}  {p.stat().st_size}" for p in made]
    (out / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
