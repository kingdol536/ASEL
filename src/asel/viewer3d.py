"""3D 재생 화면 (티켓 #58, 결정 0007 재검토). 장면 데이터(scene3d) + 내장 Three.js → HTML 한 파일.

- 인터넷 없이 열린다: Three.js(0.170.0, MIT)를 HTML 안에 그대로 넣는다 (`static/three/SOURCE.md`).
- 읽기 전용: 공개 로그로 만든 장면 데이터만 넣는다. 화면은 시간에 따라 그 데이터를 보여줄 뿐,
  위치·천장 충돌을 계산하지 않는다 (충돌은 scene3d 가 엔진 함수 roles_over_ceiling 으로 낸 결과).
- 물리 엔진 없음, 정적 배치. 역할에 필요 높이가 정의되지 않았으면 2.0 m 상자로 그린다 (표시용).
"""

from __future__ import annotations

import hashlib
import html
from pathlib import Path

from asel.scene3d import dumps, scene_for_run

THREE_DIR = Path(__file__).resolve().parent / "static" / "three"
THREE_FILE = THREE_DIR / "three.module.min.js"
THREE_SHA256 = "08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7"  # three@0.170.0, SOURCE.md


def three_source() -> str:
    data = THREE_FILE.read_bytes()
    if hashlib.sha256(data).hexdigest() != THREE_SHA256:
        raise RuntimeError(f"{THREE_FILE} does not match the recorded SHA-256 (see SOURCE.md)")
    src = data.decode("utf-8")
    if "</script" in src.lower():  # HTML 안에 넣을 때 script 태그가 끊기지 않아야 한다
        raise RuntimeError("three.module.min.js contains '</script'")
    return src


def render_html(scene: dict) -> str:
    data = dumps(scene).replace("</", "<\\/")  # JSON 의 "\/" 는 "/" 와 같다 → script 태그 안전
    title = html.escape(f"ASEL 3D 재생 — {scene.get('run_id', '')}")
    license_text = html.escape((THREE_DIR / "LICENSE").read_text(encoding="utf-8"))
    return (_TEMPLATE.replace("__TITLE__", title).replace("__SCENE_JSON__", data)
            .replace("__THREE_LICENSE__", license_text).replace("__THREE_SRC__", three_source()))


def render_run(run_dir: str | Path, layout_path: str | Path | None = None, out: str | Path | None = None) -> Path:
    scene = scene_for_run(run_dir, layout_path)
    out = Path(out) if out else Path(run_dir) / "view3d.html"
    out.write_text(render_html(scene), encoding="utf-8", newline="\n")
    return out


_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#f4f5f7; --panel:#ffffff; --ink:#1f2933; --muted:#5f6b7a; --line:#d8dde3; --bad:#c62828; --accent:#2f6fdf; }
  * { box-sizing:border-box; }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--ink);
    font:14px/1.45 system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif; }
  #app { display:grid; grid-template-columns: 1fr 320px; grid-template-rows: 1fr auto; height:100vh; }
  #view { position:relative; overflow:hidden; min-height:300px; }
  #view canvas { display:block; }
  #labels { position:absolute; inset:0; pointer-events:none; }
  .label { position:absolute; transform:translate(-50%,-100%); background:rgba(255,255,255,.88); border:1px solid var(--line);
    border-radius:6px; padding:2px 6px; font-size:12px; white-space:nowrap; }
  .label .bad { color:var(--bad); font-weight:600; }
  .label.clash { border-color:var(--bad); box-shadow:0 0 0 2px rgba(198,40,40,.25); z-index:2; }
  #side { grid-row:1 / span 2; grid-column:2; background:var(--panel); border-left:1px solid var(--line); padding:14px 16px; overflow:auto; }
  #side h1 { font-size:16px; margin:0 0 4px; }
  #side h2 { font-size:13px; margin:16px 0 6px; color:var(--muted); text-transform:none; }
  #side .run { color:var(--muted); font-size:12px; word-break:break-all; }
  #side ul { margin:0; padding-left:18px; }
  #side li { margin:3px 0; }
  #side button.jump { border:0; background:none; color:var(--accent); cursor:pointer; padding:0; font:inherit; text-align:left; }
  .sw { display:inline-block; width:12px; height:12px; border-radius:3px; vertical-align:-1px; margin-right:6px; }
  #banner { position:absolute; left:12px; top:12px; max-width:min(560px, calc(100% - 24px)); background:#fff; border:2px solid var(--bad);
    color:var(--bad); border-radius:8px; padding:8px 10px; font-weight:600; display:none; }
  #bar { grid-column:1; display:flex; gap:10px; align-items:center; padding:8px 12px; background:var(--panel); border-top:1px solid var(--line); }
  #bar button, #bar select { font:inherit; padding:4px 10px; border:1px solid var(--line); border-radius:6px; background:#fff; cursor:pointer; }
  #track { position:relative; flex:1; }
  #time { width:100%; }
  .tick { position:absolute; top:-6px; width:2px; height:8px; background:var(--bad); }
  .tick.rej { background:#7c3aed; }
  #tlabel { min-width:120px; text-align:right; font-variant-numeric:tabular-nums; }
  #err { position:absolute; inset:0; display:none; align-items:center; justify-content:center; padding:24px; color:var(--bad); text-align:center; }
  .note { color:var(--muted); font-size:12px; }
  details { margin-top:12px; } summary { cursor:pointer; color:var(--muted); font-size:12px; }
  pre.lic { white-space:pre-wrap; font-size:11px; color:var(--muted); }
  @media (max-width: 760px) {
    #app { grid-template-columns: 1fr; grid-template-rows: 60vh auto auto; }
    #side { grid-row:3; grid-column:1; border-left:0; border-top:1px solid var(--line); }
    #bar { grid-row:2; }
  }
</style>
</head>
<body>
<div id="app">
  <div id="view"><div id="labels"></div><div id="banner"></div><div id="err"></div></div>
  <div id="bar">
    <button id="play" type="button" aria-label="재생">▶ 재생</button>
    <div id="track"><input id="time" type="range" min="0" step="0.5" value="0" aria-label="모의 시각"><div id="ticks"></div></div>
    <span id="tlabel">0 s</span>
    <select id="speed" aria-label="재생 속도"><option value="30">30×</option><option value="120" selected>120×</option><option value="600">600×</option></select>
  </div>
  <aside id="side">
    <h1>3D 재생</h1>
    <div class="run" id="runid"></div>
    <p class="note" id="layoutnote"></p>
    <h2>색</h2>
    <ul id="legend"></ul>
    <h2>천장 충돌</h2>
    <ul id="clashes"></ul>
    <h2>엔진이 거절한 전환</h2>
    <ul id="rejected"></ul>
    <h2>천장에 막힌 전환 옵션</h2>
    <ul id="blocked"></ul>
    <h2>조작</h2>
    <p class="note">드래그: 회전 · 휠: 확대/축소 · 오른쪽 드래그(또는 Shift+드래그): 이동 · 목록의 시각을 누르면 그 순간으로 이동</p>
    <h2>한계</h2>
    <p class="note">물리 엔진 없음 · 정적 배치 · 이동체 없음. 그래픽은 엔진 판정(셀별 천장 높이 vs 역할의 필요 높이)을
      보여주는 시각화일 뿐이다. 필요 높이가 정의되지 않은 역할은 2.0 m 상자로 그린다(표시용). 모든 수치는 가상 값이다.</p>
    <details><summary>Three.js 라이선스 (MIT, 0.170.0)</summary><pre class="lic">__THREE_LICENSE__</pre></details>
  </aside>
</div>
<script type="application/json" id="scene-data">__SCENE_JSON__</script>
<script type="text/plain" id="three-src">__THREE_SRC__</script>
<script type="module">
const T0 = performance.now();
const $ = id => document.getElementById(id);
function fail(msg) { const e = $("err"); e.textContent = msg; e.style.display = "flex"; }
let THREE;
try {
  const url = URL.createObjectURL(new Blob([$("three-src").textContent], { type: "text/javascript" }));
  THREE = await import(url);
} catch (e) { fail("3D 라이브러리를 불러오지 못했다: " + e); throw e; }
const S = JSON.parse($("scene-data").textContent);

const STATE_KO = { idle: "대기", busy: "작업 중", draining: "비우는 중", changeover: "셋업 중", outage: "고장" };
const COLORS = { idle: 0x9aa3ad, busy: 0x2f6fdf, draining: 0xd9a52b, changeover: 0xe07b2b, outage: 0x6b1d2a, clash: 0xd62828 };
const DEFAULT_H = 2.0;
const hex = n => "#" + n.toString(16).padStart(6, "0");
const el = (tag, cls, text) => { const x = document.createElement(tag); if (cls) x.className = cls; if (text != null) x.textContent = text; return x; };
const fmt = t => t.toFixed(0) + " s";
const roleHeight = caps => {
  const hs = caps.map(c => (S.capability_space[c] || {}).height_m).filter(h => h != null);
  return hs.length ? Math.max(...hs) : DEFAULT_H;
};

// ---- 렌더러·카메라
const view = $("view");
let renderer;
try { renderer = new THREE.WebGLRenderer({ antialias: true }); }
catch (e) { fail("이 브라우저에서 WebGL 을 쓸 수 없다: " + e); throw e; }
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
view.prepend(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf4f5f7);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.7));
const sun = new THREE.DirectionalLight(0xffffff, 1.3); sun.position.set(-12, 30, 18); scene.add(sun);

// ---- 바닥 (배치 범위)
let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
for (const c of S.cells) {
  const p = c.space;
  minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x + p.width);
  minZ = Math.min(minZ, p.y); maxZ = Math.max(maxZ, p.y + p.depth);
}
const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2, span = Math.max(maxX - minX, maxZ - minZ, 1);
const size = Math.ceil(span * 1.4);
const floor = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshLambertMaterial({ color: 0xe9ebef }));
floor.rotation.x = -Math.PI / 2; floor.position.set(cx, 0, cz); scene.add(floor);
const grid = new THREE.GridHelper(size, size, 0xc9ced6, 0xdde1e6); grid.position.set(cx, 0.002, cz); scene.add(grid);

// ---- 셀: 바닥판(상태), 장비 상자(역할의 필요 높이), 천장판, 라벨
const labels = $("labels");
const cells = S.cells.map(c => {
  const p = c.space, w = p.width, d = p.depth, x = p.x + w / 2, z = p.y + d / 2;
  const low = c.blocked_options.length > 0 || S.clashes.some(k => k.cell === c.id);
  const slab = new THREE.Mesh(new THREE.BoxGeometry(w, 0.08, d), new THREE.MeshLambertMaterial({ color: 0xc5ccd4 }));
  slab.position.set(x, 0.04, z); scene.add(slab);
  const body = new THREE.Mesh(new THREE.BoxGeometry(w * 0.6, 1, d * 0.6),
    new THREE.MeshLambertMaterial({ color: COLORS.idle, transparent: true, opacity: 0.93 }));
  scene.add(body);
  const ceil = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshLambertMaterial({
    color: low ? 0xf2c14e : 0xb8c4d6, transparent: true, opacity: low ? 0.5 : 0.12, side: THREE.DoubleSide, depthWrite: false }));
  ceil.rotation.x = -Math.PI / 2; ceil.position.set(x, p.ceiling_m, z); scene.add(ceil);
  const frame = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, p.ceiling_m, d)),
    new THREE.LineBasicMaterial({ color: low ? 0xb7860b : 0xaab2bd, transparent: true, opacity: low ? 0.95 : 0.35 }));
  frame.position.set(x, p.ceiling_m / 2, z); scene.add(frame);
  const label = el("div", "label"); labels.appendChild(label);
  return { c, x, z, slab, body, label, labelY: 2, low };
});

// ---- 공정 연결 (바닥의 선 + 화살촉)
const byId = Object.fromEntries(cells.map(o => [o.c.id, o]));
for (const r of S.relations) {
  const a = byId[r.source], b = byId[r.target];
  if (!a || !b) continue;
  const from = new THREE.Vector3(a.x, 0.12, a.z), to = new THREE.Vector3(b.x, 0.12, b.z);
  scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, to]), new THREE.LineBasicMaterial({ color: 0x7b8794 })));
  const dir = to.clone().sub(from); const len = dir.length(); dir.normalize();
  const tip = new THREE.Mesh(new THREE.ConeGeometry(0.25, 0.6, 12), new THREE.MeshLambertMaterial({ color: 0x7b8794 }));
  tip.position.copy(from.clone().add(dir.clone().multiplyScalar(len * 0.62)));
  tip.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir); scene.add(tip);
}

// ---- 시간에 따른 상태 (장면 데이터만 읽는다)
function roleAt(c, t) { let r = c.roles[0][1]; for (const [t0, caps] of c.roles) if (t0 <= t) r = caps; return r; }
function stateAt(c, t) {
  for (const [s, e] of c.outages) if (s <= t && t < e) return "outage";
  for (const [k, s, e] of c.reconf) if (s <= t && t < e) return k;
  for (const [s, e] of c.busy) if (s <= t && t < e) return "busy";
  return "idle";
}
function clashAt(c, t, caps) { return S.clashes.find(k => k.cell === c.id && k.t <= t && k.roles.every(r => caps.includes(r))); }

const banner = $("banner");
function update(t) {
  const active = [];
  for (const o of cells) {
    const caps = roleAt(o.c, t), st = stateAt(o.c, t), k = clashAt(o.c, t, caps), h = roleHeight(caps);
    o.body.scale.y = h; o.body.position.set(o.x, 0.08 + h / 2, o.z);
    o.body.material.color.setHex(k ? COLORS.clash : COLORS[st]);
    o.slab.material.color.setHex(st === "idle" ? 0xc5ccd4 : COLORS[st]);
    o.labelY = 0.08 + Math.max(h, o.c.space.ceiling_m * (o.low ? 1 : 0)) + 0.5;
    const parts = [el("b", null, o.c.id), el("br"), document.createTextNode(caps.join("/") + " · " + STATE_KO[st])];
    if (k) { parts.push(el("br"), el("span", "bad", `천장 충돌: 필요 ${k.need_m} m > 천장 ${k.ceiling_m} m`)); active.push(k); }
    o.label.replaceChildren(...parts);
    o.label.classList.toggle("clash", !!k);
  }
  banner.style.display = active.length ? "block" : "none";
  banner.textContent = active.map(k => `${k.cell}: ${k.roles.join("/")} 역할에 ${k.need_m} m 가 필요하지만 천장은 ${k.ceiling_m} m — `
    + (S.layout === "run" ? "엔진이 막았어야 할 상태" : "2D 실행에서는 가능했지만 이 3D 배치에서는 불가능한 전환")).join(" / ");
  $("tlabel").textContent = fmt(t) + " / " + fmt(S.end_time);
}

// ---- 측면 정보
$("runid").textContent = S.run_id;
$("layoutnote").textContent = S.layout === "run"
  ? "배치: 이 실행 자체의 3D 배치 (엔진이 천장 높이를 검사하며 실행함)."
  : `배치: 2D 실행을 3D 배치 시나리오 '${S.layout}' 위에 겹쳐 봄. 빨간 장비는 2D 에서 일어났지만 이 배치의 천장 때문에 불가능한 전환이다.`;
for (const [k, label] of [["idle", "대기"], ["busy", "작업 중"], ["draining", "비우는 중 (전환 요청 뒤)"], ["changeover", "셋업 중"], ["outage", "고장"], ["clash", "천장 충돌"]]) {
  const li = el("li"); const sw = el("span", "sw"); sw.style.background = hex(COLORS[k]); li.append(sw, label); $("legend").append(li);
}
{ const li = el("li"); const sw = el("span", "sw"); sw.style.background = "#f2c14e"; li.append(sw, "낮은 천장 (막힌 옵션이 있는 셀)"); $("legend").append(li); }
const slider = $("time"); slider.max = String(S.end_time);
function jumpItem(t, text) { const li = el("li"); const b = el("button", "jump", fmt(t)); b.type = "button"; b.onclick = () => setT(t + 0.5); li.append(b, " " + text); return li; }
if (!S.clashes.length) $("clashes").append(el("li", "note", "없음"));
for (const k of S.clashes) $("clashes").append(jumpItem(k.t, `${k.cell} → ${k.roles.join("/")} (필요 ${k.need_m} m > 천장 ${k.ceiling_m} m)`));
if (!S.rejected_switches.length) $("rejected").append(el("li", "note", "없음"));
for (const r of S.rejected_switches) $("rejected").append(jumpItem(r.t, `${r.cell} → ${(r.capabilities || []).join("/")} (${(r.reasons || []).join("; ")})`));
const blocked = cells.filter(o => o.c.blocked_options.length);
if (!blocked.length) $("blocked").append(el("li", "note", "없음"));
for (const o of blocked) $("blocked").append(el("li", null, `${o.c.id}: ${o.c.blocked_options.map(x => x.join("/")).join(", ")} (천장 ${o.c.space.ceiling_m} m)`));
for (const [list, cls] of [[S.clashes, "tick"], [S.rejected_switches, "tick rej"]]) for (const k of list) {
  const d = el("div", cls); d.style.left = (100 * k.t / S.end_time) + "%"; $("ticks").append(d);
}

// ---- 카메라 조작 (궤도·확대·이동)
const orbit = { theta: -2.1, phi: 0.9, r: span * 1.8, tx: cx, ty: 1.0, tz: cz };
function applyCam() {
  const sp = Math.sin(orbit.phi);
  camera.position.set(orbit.tx + orbit.r * sp * Math.cos(orbit.theta), orbit.ty + orbit.r * Math.cos(orbit.phi), orbit.tz + orbit.r * sp * Math.sin(orbit.theta));
  camera.lookAt(orbit.tx, orbit.ty, orbit.tz);
}
let drag = null;
renderer.domElement.addEventListener("contextmenu", e => e.preventDefault());
renderer.domElement.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey }; renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener("pointerup", () => { drag = null; });
renderer.domElement.addEventListener("pointermove", e => {
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y; drag.x = e.clientX; drag.y = e.clientY;
  if (drag.pan) {
    // 바닥 위 카메라 기준 벡터: 앞 f = (-cosθ, 0, -sinθ), 오른쪽 r = (sinθ, 0, -cosθ). 바닥을 잡아 끄는 느낌으로 이동
    const k = orbit.r * 0.0015, s = Math.sin(orbit.theta), c = Math.cos(orbit.theta);
    orbit.tx += (-dx * s - dy * c) * k;
    orbit.tz += (dx * c - dy * s) * k;
  } else {
    orbit.theta += dx * 0.006; orbit.phi = Math.min(1.45, Math.max(0.12, orbit.phi - dy * 0.006));
  }
  applyCam();
});
renderer.domElement.addEventListener("wheel", e => { e.preventDefault(); orbit.r = Math.min(span * 5, Math.max(3, orbit.r * Math.exp(e.deltaY * 0.001))); applyCam(); }, { passive: false });
function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(view);
resize(); applyCam();

// ---- 재생
let t = 0, shown = -1, playing = false, last = performance.now();
// first_render_ms: 페이지 열기 시작 → 첫 화면, module_ms: 스크립트 시작(라이브러리 읽기 포함) → 첫 화면
const perf = { frames: 0, render_ms: [], first_render_ms: null, module_ms: null };
function setT(v) { t = Math.max(0, Math.min(S.end_time, v)); slider.value = String(t); }
slider.addEventListener("input", () => { t = Number(slider.value); playing = false; $("play").textContent = "▶ 재생"; });
$("play").addEventListener("click", () => {
  if (t >= S.end_time) setT(0);
  playing = !playing; $("play").textContent = playing ? "❚❚ 멈춤" : "▶ 재생";
});
const v3 = new THREE.Vector3();
function placeLabels() {
  const w = view.clientWidth, h = view.clientHeight;
  for (const o of cells) {
    v3.set(o.x, o.labelY, o.z).project(camera);
    const vis = v3.z < 1 && v3.z > -1;
    o.label.style.display = vis ? "block" : "none";
    if (vis) { o.label.style.left = ((v3.x + 1) / 2 * w) + "px"; o.label.style.top = ((1 - v3.y) / 2 * h) + "px"; }
  }
}
function frame(now) {
  const dt = (now - last) / 1000; last = now;
  if (playing) {
    setT(t + dt * Number($("speed").value));
    if (t >= S.end_time) { playing = false; $("play").textContent = "▶ 재생"; }
  }
  if (t !== shown) { update(t); shown = t; }
  placeLabels();
  const r0 = performance.now(); renderer.render(scene, camera); const r1 = performance.now();
  perf.frames++; perf.render_ms.push(r1 - r0); if (perf.render_ms.length > 600) perf.render_ms.shift();
  requestAnimationFrame(frame);
}
// 첫 화면은 화면 갱신 주기를 기다리지 않고 바로 그린다 (창이 백그라운드여도 내용이 준비된다)
update(t); shown = t; placeLabels(); renderer.render(scene, camera);
perf.first_render_ms = performance.now(); perf.module_ms = perf.first_render_ms - T0;
window.__asel3d = {
  perf, setT, play: on => { playing = !!on; },
  renderMsAvg: () => perf.render_ms.reduce((a, b) => a + b, 0) / Math.max(perf.render_ms.length, 1),
  stateAt: (id, time) => { const o = byId[id]; return { role: roleAt(o.c, time), state: stateAt(o.c, time), clash: !!clashAt(o.c, time, roleAt(o.c, time)) }; },
  // 측정용: 카메라를 조금씩 돌리며 n 장을 그리고, GPU 작업이 끝날 때까지 기다린 시간(gl.finish 포함)을 잰다
  bench: (n = 120) => {
    const gl = renderer.getContext(), xs = [], th = orbit.theta;
    for (let i = 0; i < n; i++) {
      orbit.theta = th + i * 0.01; applyCam(); update(S.end_time * i / n);
      const a = performance.now(); renderer.render(scene, camera); gl.finish(); xs.push(performance.now() - a);
    }
    orbit.theta = th; applyCam(); shown = -1;
    xs.sort((p, q) => p - q);
    return { n, avg_ms: xs.reduce((p, q) => p + q, 0) / n, p95_ms: xs[Math.floor(n * 0.95)], max_ms: xs[n - 1] };
  },
};
requestAnimationFrame(frame);
</script>
</body>
</html>
"""
