// The 3D pitch, as a mountable component.
//
// M0 draws the one thing this project knows exactly: the markings. Everything that arrives later —
// the camera and its frustum, the trajectory, the video frame as a textured plane, the skeletons —
// hangs off the same `groups` map and the same `setLayer` switch, so adding a layer is adding a
// group, not rewiring the view.
//
// World convention, matching core/units.py and never to be silently converted: **Z-up,
// right-handed, metres, origin on the centre spot**. three.js defaults to Y-up, so `camera.up` is
// set explicitly. Getting this wrong is invisible on a symmetric pitch and obvious the moment a
// goalpost is drawn — which is exactly how the handedness bug in pitch3d survived (#118).

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const TURF = 0x2f5d33;
const PAINT = 0xffffff;
const UPRIGHT = 0x67e8f9;
//: Direction only. The DISTANCE is computed from the pitch and the viewport in `frameAll()` —
//: a hardcoded distance is right at exactly one window size, and wrong at every other.
const VIEW_DIR = [0, -0.86, 0.51];
const FIT_MARGIN = 1.12;

export function createPitchView(cfg) {
  const { mount } = cfg;
  const onStatus = cfg.onStatus || (() => {});
  const onError = cfg.onError || (() => {});

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  mount.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x14161a);

  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
  camera.up.set(0, 0, 1);                          // Z-up world, see the header

  const orbit = new OrbitControls(camera, renderer.domElement);
  orbit.target.set(0, 0, 0);
  // Stop the orbit going under the pitch: from below, the markings are mirrored and read as a
  // plausible different camera, which is a good way to spend an hour chasing nothing.
  orbit.maxPolarAngle = Math.PI * 0.495;
  orbit.screenSpacePanning = false;
  orbit.update();

  scene.add(new THREE.AmbientLight(0xffffff, 1.6));

  const groups = {
    turf: new THREE.Group(),
    markings: new THREE.Group(),
    goals: new THREE.Group(),
  };
  for (const g of Object.values(groups)) scene.add(g);

  function polyline(pts, colour, z) {
    const geo = new THREE.BufferGeometry();
    const a = new Float32Array(pts.length * 3);
    pts.forEach((p, i) => {
      a[3 * i] = p[0];
      a[3 * i + 1] = p[1];
      a[3 * i + 2] = p.length > 2 ? p[2] : z;
    });
    geo.setAttribute("position", new THREE.BufferAttribute(a, 3));
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: colour }));
  }

  //: The eight corners of what should fit on screen, world metres. Set once the pitch is known.
  let fitPoints = [];

  function resize() {
    const w = mount.clientWidth || 1;
    const h = mount.clientHeight || 1;
    renderer.setSize(w, h);   // updateStyle on: the canvas is absolute, see style.css
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  // Fit to the PROJECTED corners, not to a bounding sphere. A pitch is a flat rectangle seen
  // obliquely: the sphere that contains it projects far larger than it does, and fitting the
  // sphere leaves the pitch small and floating in the upper half of the window. Iterating on the
  // real projection is a few lines and correct at any aspect ratio.
  function frameAll() {
    if (!fitPoints.length) return;
    const v = new THREE.Vector3();
    let d = 200;
    let target = new THREE.Vector3(0, 0, 0);
    for (let pass = 0; pass < 4; pass++) {
      camera.position.set(VIEW_DIR[0] * d, VIEW_DIR[1] * d, VIEW_DIR[2] * d).add(target);
      camera.lookAt(target);
      camera.updateMatrixWorld();
      camera.updateProjectionMatrix();
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const p of fitPoints) {
        v.set(p[0], p[1], p[2]).project(camera);
        x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x);
        y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
      }
      // Re-centre by nudging the orbit target along the camera's own screen axes, then rescale
      // the distance by how far the widest axis overshoots the unit NDC box.
      const dx = (x0 + x1) / 2, dy = (y0 + y1) / 2;
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
      const scale = Math.tan((camera.fov * Math.PI) / 360) * d;
      target = target.clone()
        .add(right.multiplyScalar(dx * scale * camera.aspect))
        .add(up.multiplyScalar(dy * scale));
      d *= Math.max((x1 - x0) / 2, (y1 - y0) / 2) * FIT_MARGIN;
    }
    orbit.target.copy(target);
    orbit.update();
  }
  new ResizeObserver(resize).observe(mount);

  (function tick() {
    requestAnimationFrame(tick);
    orbit.update();
    renderer.render(scene, camera);
  })();

  addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.key === "f" || e.key === "F") frameAll();
  });

  function resetView() { frameAll(); }

  async function init() {
    onStatus("fetching pitch…");
    const r = await fetch("/api/pitch");
    if (!r.ok) throw new Error(`/api/pitch -> ${r.status}`);
    const d = await r.json();

    const { length, width } = d.dimensions;
    // Slightly below zero so the paint at z=0 is never z-fought by the grass it sits on.
    const turf = new THREE.Mesh(
      new THREE.PlaneGeometry(length, width),
      new THREE.MeshLambertMaterial({ color: TURF }),
    );
    turf.position.z = -0.01;
    groups.turf.add(turf);

    let dots = 0;
    for (const poly of d.markings) {
      if (poly.length === 1) {
        // The centre spot and the two penalty spots come back as one point each. They are paint
        // like any other marking; a line with one vertex draws nothing.
        const dot = new THREE.Mesh(
          new THREE.CircleGeometry(0.15, 16),
          new THREE.MeshBasicMaterial({ color: PAINT }),
        );
        dot.position.set(poly[0][0], poly[0][1], 0.004);
        groups.markings.add(dot);
        dots++;
      } else {
        groups.markings.add(polyline(poly, PAINT, 0.004));
      }
    }
    for (const poly of d.uprights) groups.goals.add(polyline(poly, UPRIGHT, 0));

    const hx = length / 2, hy = width / 2;
    const hz = Math.max(...d.uprights.flat().map((p) => p[2]));
    fitPoints = [];
    for (const sx of [-hx, hx]) for (const sy of [-hy, hy]) for (const sz of [0, hz]) {
      fitPoints.push([sx, sy, sz]);
    }
    resize();
    frameAll();
    onStatus(`pitch ${length} x ${width} m · ${d.markings.length} marking polylines ` +
             `(${dots} spots) · ${d.uprights.length} uprights`);
    onError("");
    return {
      length, width,
      markings: d.markings.length,
      uprights: d.uprights.length,
    };
  }

  function setLayer(name, on) {
    if (groups[name]) groups[name].visible = !!on;
  }

  return { init, setLayer, resetView, frameAll, resize, scene, camera, groups };
}
