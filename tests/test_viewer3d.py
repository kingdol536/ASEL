"""3D 재생 화면 (#58): 내장 Three.js 로 인터넷 없이 열리고, 공개 로그로 만든 장면 데이터만 담는다."""

from __future__ import annotations

import hashlib
import json
import re

import pytest

from asel.cli import main
from asel.io.scenario import load_scenario
from asel.runner import run_scenario, write_run
from asel.scene3d import scene_for_run
from asel.viewer3d import THREE_DIR, THREE_SHA256, render_html, three_source
from conftest import ROOT

B2P = ROOT / "scenarios" / "assembly-line-b.yaml"
B3P = ROOT / "scenarios" / "assembly-line-b-3d.yaml"
XHTML_NS = "http://www.w3.org/1999/xhtml"  # Three.js 안의 이름공간 문자열 (네트워크 요청 아님)


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    out = tmp_path_factory.mktemp("runs")
    b2 = write_run(run_scenario(load_scenario(B2P), seed=0, structure_policy="p1"), out)
    b3 = write_run(run_scenario(load_scenario(B3P), seed=0, structure_policy="p1"), out)
    return b2, b3


def _script(html_text: str, script_id: str) -> str:
    m = re.search(rf'<script type="[^"]+" id="{script_id}">(.*?)</script>', html_text, re.S)
    assert m, script_id
    return m.group(1)


def test_vendored_three_matches_recorded_checksum():
    src = three_source()  # 체크섬이 다르면 예외
    assert hashlib.sha256(src.encode("utf-8")).hexdigest() == THREE_SHA256
    assert THREE_SHA256 in (THREE_DIR / "SOURCE.md").read_text(encoding="utf-8")
    assert "MIT" in (THREE_DIR / "LICENSE").read_text(encoding="utf-8")


def test_html_embeds_scene_and_library_unchanged(runs):
    scene = scene_for_run(runs[0], B3P)
    page = render_html(scene)
    assert json.loads(_script(page, "scene-data")) == scene  # 장면 데이터 그대로
    embedded = _script(page, "three-src")
    assert hashlib.sha256(embedded.encode("utf-8")).hexdigest() == THREE_SHA256  # 라이브러리 바이트 그대로
    assert "Three.js Authors" in page  # 라이선스 고지


def test_html_makes_no_external_requests(runs):
    page = render_html(scene_for_run(runs[1]))
    assert not re.search(r"<script[^>]*\bsrc=", page) and "<link" not in page and "@import" not in page
    assert "fetch(" not in page.replace(_script(page, "three-src"), "")
    urls = set(re.findall(r"https?://[^\s\"'<>)]+", page))
    assert urls <= {XHTML_NS}, urls


@pytest.mark.parametrize("evil", ["</script><script>alert(1)</script>", "<!--<script>", "a<b"])
def test_scene_text_cannot_break_out_of_script_tag(runs, evil):
    scene = scene_for_run(runs[1])
    scene["cells"][0]["id"] = evil  # 데이터에 태그·주석 문자열이 있어도
    page = render_html(scene)
    data = _script(page, "scene-data")
    assert "<" not in data  # 데이터 블록에는 '<' 가 없다 → HTML 해석 상태가 바뀌지 않는다
    assert json.loads(data)["cells"][0]["id"] == evil  # 값은 그대로
    assert page.count("</script>") == 3  # 장면·라이브러리·앱 스크립트의 닫는 태그뿐


def test_cli_view3d(runs, tmp_path, capsys):
    out = tmp_path / "v.html"
    assert main(["view3d", str(runs[0]), "--layout", str(B3P), "--out", str(out)]) == 0
    scene = json.loads(_script(out.read_text(encoding="utf-8"), "scene-data"))
    assert scene["clashes"] and scene["layout"] == "assembly-line-b-3d"
    assert main(["view3d", str(runs[0])]) == 2  # 2D 실행은 배치 시나리오가 필요하다
    assert "no 3D space" in capsys.readouterr().err
