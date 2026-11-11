"""이식성 측정 스크립트 (#32): 현재 커밋에서 공개 이름·공통 언어 항목을 읽을 수 있다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("pm", ROOT / "experiments" / "configs" / "portability_metrics.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_reads_public_names_and_vocabulary_at_head():
    m = _load()
    names = m.public_names("HEAD")
    assert "model.Task.predecessors" in names and "actions.ActionKind.START_TASK=start_task" in names
    items = m.vocabulary_items("HEAD")
    assert "CONCEPTS:'Task'" in items


def test_identical_commits_measure_zero():
    m = _load()
    r = m.measure("HEAD", "HEAD")
    assert r["core_diff_lines"] == r["public_interface_changes"] == r["new_concepts"] == 0
    assert r["config_only_ratio"] is None
