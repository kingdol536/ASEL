"""실행 기록 manifest (docs/07-EXPERIMENTAL-DESIGN.md §11)."""

from __future__ import annotations

import platform
import subprocess
import sys
from importlib import metadata
from pathlib import Path


def _git(*args: str, cwd: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def code_revision(repo: Path) -> dict:
    commit = _git("rev-parse", "HEAD", cwd=repo)
    status = _git("status", "--porcelain", "--untracked-files=no", cwd=repo)
    return {"commit": commit, "dirty": bool(status) if status is not None else None}


def _version(pkg: str) -> str | None:
    try:
        return metadata.version(pkg)
    except metadata.PackageNotFoundError:
        return None


def environment_info() -> dict:
    return {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": {p: _version(p) for p in ("asel", "pydantic", "pyyaml")},
    }
