// The 3D pitch and the camera on it, as a mountable component.
//
// Two renderers, one scene:
//
//   A — the orbit view. The pitch, the solved camera as a body and a frustum, its trajectory, and
//       the video frame hanging inside the frustum where the camera would see it.
//   B — the camera's own view, drawn straight over the video frame. **This is the verdict.** When
//       the drawn lines lie on the painted ones, the camera is right; when they do not, the size
//       and direction of the miss says which way it is wrong. No metric substitutes for it.
//
// World convention, matching core/units.py and never silently converted: **Z-up, right-handed,
// metres, origin on the centre spot**. three.js is Y-up by default, so `camera.up` is set. Getting
// this wrong is invisible on a symmetric pitch and obvious the moment a goalpost is drawn — which
// is how the handedness bug in pitch3d survived until #118.
//
// The other convention that has to be right, and the one place a sign error would look almost
// plausible: our solve is **OpenCV** — `X_c = R X_w + t`, camera looking down +Z, image y running
// DOWN. three.js looks down −Z with +Y up. See `applySolvedCamera`.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";

const TURF = 0x2f5d33;
const PAINT = 0xffffff;
const UPRIGHT = 0x67e8f9;
const CAM_OK = 0xffd24a;
const CAM_BAD = 0xff3ea5;          // a frame the solver could not use: marked, never hidden (R-6)

//: A frame is drawn as unusable when THIS camera file still shows it so — no focal, or a focal
//: sitting on a search bound. Not from the `degenerate` list, which four stages used to copy
//: through from their source: `fan` 115-118 carry focals of 300/20000 in `camera_auto.json` and
//: 4729/4727/4726/4716 in `camera_smooth.json`, repaired four stages earlier and still painted in
//: the "could not use this" pink. `buildStrip` had already stopped trusting it; the camera body,
//: the frustum and the trajectory had not. Matches `camera_file.FOCAL_BOUNDS`.
const FOCAL_BOUNDS = [300, 20000];
const unusable = (cam, i) => {
  const f = cam.focal_px[i];
  return !(f > 0) || f <= FOCAL_BOUNDS[0] + 1e-6 || f >= FOCAL_BOUNDS[1] - 1e-6;
};
const CAM_DRAG = 0x63c7ff;         // the pose currently in a hand, so a preview cannot be mistaken
                                   // for the solve it has not replaced yet
const TRAIL = 0xffa640;

const VIEW_DIR = [0, -0.86, 0.51];
const FIT_MARGIN = 1.12;

//: OpenCV camera space -> three.js camera space. Flip Y (image y runs down) and Z (we look down
//: +Z, three.js looks down -Z). Two flips, so det = +1: a change of basis, not a mirror. A mirror
//: here would silently make every recovered camera left-handed and the error would look like a
//: small misalignment rather than a wrong convention.
const CV_TO_GL = new THREE.Matrix4().makeBasis(
  new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, -1, 0), new THREE.Vector3(0, 0, -1),
);

export function createPitchView(cfg) {
  const { mount, mountB } = cfg;
  const onCamera = cfg.onCamera || (() => {});

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  // View A's backdrop belongs to the RENDERER, not to the scene. `scene.background` is a property
  // of the scene, so it is painted by every renderer that draws it — including window B's, whose
  // whole job is to be transparent over the photograph. That one line turned B into a solid
  // rectangle of nothing, and it looked like a failed image load rather than what it was.
  renderer.setClearColor(0x14161a, 1);
  mount.appendChild(renderer.domElement);

  // Window B's canvas is transparent and sits ON TOP of an <img> of the frame, rather than
  // texturing the frame into its scene. Same picture, and it keeps the comparison honest: nothing
  // in the 3D pipeline can resample, tint or letterbox the evidence on its way to the eye.
  let rendererB = null;
  if (mountB) {
    rendererB = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    rendererB.setPixelRatio(Math.min(devicePixelRatio, 2));
    rendererB.setClearColor(0x000000, 0);
    mountB.appendChild(rendererB.domElement);
  }

  const scene = new THREE.Scene();   // no `background`: see setClearColor above

  const view = new THREE.PerspectiveCamera(45, 1, 0.1, 4000);
  view.up.set(0, 0, 1);
  const orbit = new OrbitControls(view, renderer.domElement);

  // Dragging the camera in the world, rather than typing three numbers at it. The gizmo is
  // attached to a PROXY rather than to the camera body, because `drawCamera` clears and rebuilds
  // that body on every frame — a gizmo attached to it would be detached from a deleted object one
  // scrub later, and three.js does not complain about that, it just stops working.
  //
  // The proxy carries the position only. Aim stays on the numbers: a rotation gizmo would let a
  // hand produce something that is not a rotation, and "this is one camera" would stop being a
  // guarantee (the same reason the browser never posts a matrix — see server/app.py).
  const dragProxy = new THREE.Object3D();
  const gizmo = new TransformControls(view, renderer.domElement);
  gizmo.setMode("translate");
  gizmo.setSpace("world");
  gizmo.enabled = false;
  gizmo.attach(dragProxy);
  scene.add(dragProxy);
  // three r170: TransformControls is a Controls, not an Object3D. Adding it to the scene is
  // silently a no-op — nothing draws and nothing errors — and `getHelper()` is what goes in.
  const gizmoHelper = gizmo.getHelper();
  gizmoHelper.visible = false;
  scene.add(gizmoHelper);
  let dragging = false;
  let shownIndex = 0;
  // The distance the frame plane was sized at when the hand took hold, held for the whole gesture.
  // It is derived from where the optical axis meets the grass, so recomputing it mid-drag rescales
  // the plane on every mouse move and then snaps it back on release — the picture appears to zoom
  // while being aimed, which is the one thing it must not do when it is the thing being aimed AT.
  // Frozen, the plane travels with the camera as one rigid body.
  let dragPlaneD = null;
  // Aiming a 70 m shot is a tenth-of-a-degree job: at a 3000 px focal, 0.1 deg is about 5 px on
  // the overlay, which is what the eye is being asked to judge. Stock speed moves whole degrees in
  // a short drag and overshoots every time. Alt goes finer again, matching the keyboard's alt.
  const ROTATE_SPEED = 0.25, ROTATE_FINE = 0.05;
  gizmo.rotationSpeed = ROTATE_SPEED;
  addEventListener("keydown", (e) => { if (e.key === "Alt") gizmo.rotationSpeed = ROTATE_FINE; });
  addEventListener("keyup", (e) => { if (e.key === "Alt") gizmo.rotationSpeed = ROTATE_SPEED; });

  gizmo.addEventListener("dragging-changed", (e) => {
    // Orbit and drag both claim the pointer. Without this the camera slides while the whole view
    // spins around it, which is unusable and looks like a bug in the gizmo.
    orbit.enabled = !e.value;
    dragging = e.value;
    if (e.value) {
      // Taken BEFORE the first move, and from the solve rather than the proxy, so it is the size
      // the plane is already being seen at.
      dragPlaneD = planeDistanceFor(shownIndex);
      return;
    }
    // Back to the solve's own colour, its own plane distance and the server's own overlay.
    dragPlaneD = null;
    drawCamera(shownIndex);
    drawFramePlane(shownIndex);
    if (cfg.onDragEnd) cfg.onDragEnd(proxyState());
  });

  // Live, on every pointer move, not on release. A drag that only shows its result when the mouse
  // comes up is aim-and-check-and-undo, and a tenth of a degree cannot be aimed that way. Both
  // halves are redrawn from the SAME proxy the release will commit, so the preview cannot promise
  // something the write does not deliver.
  gizmo.addEventListener("objectChange", () => {
    if (!dragging) return;
    drawCamera(shownIndex, dragProxy);
    drawFramePlane(shownIndex, dragProxy);
    // And window B, which is the half that decides anything. It renders the scene THROUGH
    // `solved`, so aiming `solved` at the proxy makes the markings on the video follow the hand —
    // no second projection to write and none to disagree with. `show()` calls
    // `applySolvedCamera`, which puts it back the moment the frame changes.
    // Composed, not assigned. `applySolvedCamera` sets `matrixAutoUpdate = false` because it
    // writes the matrix itself, so copying position and quaternion onto `solved` changes nothing
    // that renders — the preview would sit perfectly still and look like a dead event handler.
    solved.matrix.compose(dragProxy.position, dragProxy.quaternion, solved.scale);
    solved.matrix.decompose(solved.position, solved.quaternion, solved.scale);
    solved.updateMatrixWorld(true);
    if (cfg.onDragMove) cfg.onDragMove(proxyState());
  });

  /** The proxy as the SEVEN numbers the server speaks, never as a matrix.
   *
   * Angles derived exactly as the server does, which for roll is not the obvious thing: `right.z`
   * gives the roll only when the camera is already level — the one case that tests nothing — so it
   * is read in the LEVEL BASIS built from the forward direction. Getting that wrong shows up as a
   * roll that is right at the horizon and drifts as the camera tilts, which reads like a solver
   * problem rather than a conversion one.
   */
  function proxyState() {
    const fwd = new THREE.Vector3(0, 0, -1).applyQuaternion(dragProxy.quaternion).normalize();
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(dragProxy.quaternion).normalize();
    const yaw = (Math.atan2(fwd.y, fwd.x) * 180) / Math.PI;
    const elev = (Math.asin(Math.max(-1, Math.min(1, fwd.z))) * 180) / Math.PI;
    const down = new THREE.Vector3(0, 0, -1);
    let roll = 0;
    const r0 = new THREE.Vector3().crossVectors(down, fwd);
    if (r0.lengthSq() > 1e-12) {
      r0.normalize();
      const d0 = new THREE.Vector3().crossVectors(fwd, r0).normalize();
      roll = (Math.atan2(right.dot(d0), right.dot(r0)) * 180) / Math.PI;
    }
    return {
      position: [dragProxy.position.x, dragProxy.position.y, dragProxy.position.z],
      yaw, elev, roll,
    };
  }
  orbit.target.set(0, 0, 0);
  orbit.maxPolarAngle = Math.PI * 0.495;   // never orbit under the pitch: from below the markings
  orbit.screenSpacePanning = false;        // mirror and read as a plausible different camera

  // The solved camera, as a real three.js camera. Window B renders through it; view A draws it.
  const solved = new THREE.PerspectiveCamera(45, 1, 0.05, 4000);

  scene.add(new THREE.AmbientLight(0xffffff, 1.6));

  const groups = {};
  for (const k of ["turf", "markings", "goals", "camera", "trajectory", "frameplane"]) {
    groups[k] = new THREE.Group();
    scene.add(groups[k]);
  }

  let clip = null;
  let cam = null;
  let turfMesh = null;      // the double-click raycast target; see onDoubleClick
  //: null = auto: put the frame plane where the optical axis actually meets the pitch. A fixed
  //: default cannot be right — the camera is 78-87 m from what it is looking at on this clip, so
  //: the 40 m this used to hardcode hung the plane 10.7 m ABOVE the grass and made it look like a
  //: camera error. A number here is a manual override (the project's auto -> manual rule).
  let planeOverride = null;
  let frameTex = null;
  let fitPoints = [];

  // ---------------------------------------------------------------------------- primitives ----

  function polyline(pts, colour) {
    const geo = new THREE.BufferGeometry();
    const a = new Float32Array(pts.length * 3);
    pts.forEach((p, i) => {
      a[3 * i] = p[0];
      a[3 * i + 1] = p[1];
      a[3 * i + 2] = p.length > 2 ? p[2] : 0;
    });
    geo.setAttribute("position", new THREE.BufferAttribute(a, 3));
    return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: colour }));
  }

  function clear(group) {
    for (const o of [...group.children]) {
      group.remove(o);
      o.geometry?.dispose();
      o.material?.dispose?.();
    }
  }

  // -------------------------------------------------------------------------- the camera ------

  /** Point `solved` at frame `i`'s recovered pose. Returns false if that frame has no camera. */
  function applySolvedCamera(i) {
    if (!cam) return false;
    const f = cam.focal_px[i];
    if (!(f > 0)) return false;

    const [px, py, pz] = cam.position[i];
    const rv = cam.rotation[i];

    const angle = Math.hypot(rv[0], rv[1], rv[2]);
    const rot = new THREE.Matrix4();
    if (angle > 1e-12) {
      rot.makeRotationAxis(new THREE.Vector3(rv[0] / angle, rv[1] / angle, rv[2] / angle), angle);
    }
    // `rot` is world->camera. The camera's orientation in the world is its transpose, and CV->GL
    // is applied on the CAMERA side (right multiply) because it re-bases the camera's own axes,
    // not the world's.
    const camToWorld = rot.clone().transpose().multiply(CV_TO_GL);
    solved.matrixAutoUpdate = false;
    solved.matrix.copy(camToWorld).setPosition(px, py, pz);
    solved.matrix.decompose(solved.position, solved.quaternion, solved.scale);
    solved.updateMatrixWorld(true);

    // Exact, because the solve puts the principal point at the image centre — and says so in
    // camera_auto.json rather than leaving it to be assumed here.
    solved.fov = (2 * Math.atan(clip.height / (2 * f)) * 180) / Math.PI;
    solved.aspect = clip.width / clip.height;
    solved.updateProjectionMatrix();
    return true;
  }

  /** Half-extents of the image plane at distance `d`, in world metres. */
  function frustumHalf(i, d) {
    const f = cam.focal_px[i];
    return [(d * clip.width) / (2 * f), (d * clip.height) / (2 * f)];
  }

  /** Where the optical axis crosses the pitch plane Z=0, as a distance along the axis.
   *
   * NaN when the axis never gets there — pointing up, or level. That is not a rounding case: a
   * degenerate frame does exactly this. Fan frame 116 puts the intersection at -0.7 m, i.e.
   * BEHIND the camera, alongside a 47.7 deg roll and a focal pinned at the search bound.
   *
   * `pose` defaults to the solved camera. Passing the drag proxy is what lets the frustum and the
   * frame plane follow a hand instead of jumping to their new place on release.
   */
  function groundDistance(i, pose) {
    if (!pose && !applySolvedCamera(i)) return NaN;
    const at = pose || solved;
    const fwd = new THREE.Vector3();
    at.getWorldDirection(fwd);
    if (Math.abs(fwd.z) < 1e-6) return NaN;
    const t = -at.position.z / fwd.z;
    return t > 0 ? t : NaN;
  }

  /** The distance actually used: the manual override, else the ground intersection, else a
   *  fallback so a degenerate frame still draws something rather than vanishing. */
  function planeDistanceFor(i, pose) {
    if (dragPlaneD != null) return dragPlaneD;
    if (planeOverride != null) return planeOverride;
    const g = groundDistance(i, pose);
    return Number.isFinite(g) ? Math.min(Math.max(g, 2), 400) : 40;
  }

  function drawCamera(i, pose) {
    clear(groups.camera);
    if (!pose && !applySolvedCamera(i)) return;
    if (pose && !(cam?.focal_px[i] > 0)) return;
    const at = pose || solved;

    // A hand-held pose is drawn in its own colour. Without that the preview is indistinguishable
    // from the solve and there is no way to see, mid-drag, that anything is being changed.
    const colour = pose ? CAM_DRAG : (unusable(cam, i) ? CAM_BAD : CAM_OK);
    const c = at.position.clone();

    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.9, 0.9, 0.9),
      new THREE.MeshBasicMaterial({ color: colour, wireframe: true }),
    );
    body.position.copy(c);
    groups.camera.add(body);

    // The frustum out to the frame plane, so the plane visibly IS what the camera sees.
    const d = planeDistanceFor(i, pose);
    const [hw, hh] = frustumHalf(i, d);
    const corners = [[-hw, -hh], [hw, -hh], [hw, hh], [-hw, hh]]
      .map(([x, y]) => at.localToWorld(new THREE.Vector3(x, y, -d)));
    for (const k of corners) groups.camera.add(polyline([c.toArray(), k.toArray()], colour));
    groups.camera.add(polyline([...corners, corners[0]].map((v) => v.toArray()), colour));

    // The optical axis, past the plane: a frustum alone leaves the eye guessing which way is up
    // inside it, and where the camera POINTS is the thing being judged.
    const far = at.localToWorld(new THREE.Vector3(0, 0, -d * 1.4));
    groups.camera.add(polyline([c.toArray(), far.toArray()], colour));
  }

  function drawTrajectory() {
    clear(groups.trajectory);
    if (!cam) return;
    const pts = [];
    for (let i = 0; i < cam.frames.length; i++) {
      if (cam.focal_px[i] > 0) pts.push(cam.position[i]);
    }
    if (pts.length > 1) groups.trajectory.add(polyline(pts, TRAIL));
    // A dot per frame as well as the path. The path alone hides how the frames are DISTRIBUTED
    // along it, and clustering is the whole question: 100 frames in one place plus 20 flung across
    // the stands draws the same line as 120 spread evenly.
    for (let i = 0; i < cam.frames.length; i++) {
      if (!(cam.focal_px[i] > 0)) continue;
      const m = new THREE.Mesh(
        new THREE.SphereGeometry(0.35, 6, 6),
        new THREE.MeshBasicMaterial({ color: unusable(cam, i) ? CAM_BAD : TRAIL }),
      );
      m.position.set(...cam.position[i]);
      groups.trajectory.add(m);
    }
  }

  function drawFramePlane(i, pose) {
    clear(groups.frameplane);
    if (!cam || !frameTex || !(cam.focal_px[i] > 0)) return;
    const at = pose || solved;
    const d = planeDistanceFor(i, pose);
    const [hw, hh] = frustumHalf(i, d);
    const plane = new THREE.Mesh(
      new THREE.PlaneGeometry(2 * hw, 2 * hh),
      new THREE.MeshBasicMaterial({ map: frameTex, side: THREE.DoubleSide, toneMapped: false }),
    );
    // Sized to fill the frustum at exactly `d`, so from the camera's own position it covers the
    // view pixel for pixel and anything drawn between the two lands on the video where it belongs.
    // That is the point of putting it in 3D at all: it makes a DEPTH error visible from the orbit
    // view, which a flat 2D overlay cannot show.
    plane.position.copy(at.localToWorld(new THREE.Vector3(0, 0, -d)));
    plane.quaternion.copy(at.quaternion);
    groups.frameplane.add(plane);
  }

  // ------------------------------------------------------------------------------ plumbing ----

  function resize() {
    const w = mount.clientWidth || 1;
    const h = mount.clientHeight || 1;
    renderer.setSize(w, h);
    view.aspect = w / h;
    view.updateProjectionMatrix();
    if (rendererB && mountB) {
      rendererB.setSize(mountB.clientWidth || 1, mountB.clientHeight || 1);
    }
  }
  new ResizeObserver(resize).observe(mount);
  if (mountB) new ResizeObserver(resize).observe(mountB);

  // ------------------------------------------------------------------------------ navigation --
  //
  // Orbit and zoom alone are not enough to judge where a camera stands: the question is what the
  // stand looks like from a few metres away, and orbiting that means orbiting THERE, not around a
  // centre spot 75 m off.

  //: Metres per second at the base rate. Scaled by the distance to the pivot, so the same key
  //: feels the same whether the whole pitch is in view or one camera body is.
  const FLY_BASE = 0.55;
  const held = new Set();

  // Bound to the viewport, not to `window`. On window, typing a focal into a panel field would
  // fly the view — the "a" in a number box is not a movement command.
  mount.tabIndex = 0;
  mount.addEventListener("pointerdown", () => mount.focus());
  mount.addEventListener("keydown", (e) => {
    const k = e.key.toLowerCase();
    if ("wasdqe".includes(k)) { held.add(k); e.preventDefault(); }
    if (k === "f") frameAll();
  });
  mount.addEventListener("keyup", (e) => held.delete(e.key.toLowerCase()));
  mount.addEventListener("blur", () => held.clear());   // else a key held while alt-tabbing sticks

  /** One fly step. `keys` is any iterable of w/a/s/d/q/e/shift; `dt` is seconds.
   *
   * Split out from the key handler and exported, because the render loop it is normally driven
   * from is `requestAnimationFrame` — which a browser freezes in a background tab. That makes
   * "does WASD work?" unanswerable from outside without either a foreground window or this seam,
   * and "I could not observe it move" is not the same finding as "it does not move".
   *
   * Returns the distance actually travelled, in metres, so a caller can assert on it.
   */
  function fly(keys, dt) {
    const k = keys instanceof Set ? keys : new Set(keys);
    if (!k.size || !(dt > 0)) return 0;
    const fwd = new THREE.Vector3().subVectors(orbit.target, view.position);
    const dist = fwd.length();
    fwd.normalize();
    const right = new THREE.Vector3().crossVectors(fwd, view.up).normalize();
    // Speed scales with how far away the pivot is, so the same key feels the same whether the
    // whole pitch is in view or a single camera body is.
    const step = FLY_BASE * dt * Math.max(dist * 0.35, 1.5) * (k.has("shift") ? 3.3 : 1);

    const move = new THREE.Vector3();
    if (k.has("w")) move.add(fwd);
    if (k.has("s")) move.sub(fwd);
    if (k.has("d")) move.add(right);
    if (k.has("a")) move.sub(right);
    if (k.has("e")) move.add(view.up);
    if (k.has("q")) move.sub(view.up);
    if (!move.lengthSq()) return 0;
    move.normalize().multiplyScalar(step);
    // Move the pivot WITH the eye. Moving only the eye turns W into a zoom, and the next orbit
    // then spins around a point left behind somewhere in the stands.
    view.position.add(move);
    orbit.target.add(move);
    orbit.update();
    return move.length();
  }

  function flyStep(dt) { return fly(held, dt); }

  addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if (e.key === "Shift") held.add("shift");
    if (e.key === "f" || e.key === "F") frameAll();
  });
  addEventListener("keyup", (e) => { if (e.key === "Shift") held.delete("shift"); });

  const ray = new THREE.Raycaster();
  renderer.domElement.addEventListener("dblclick", (e) => {
    if (!turfMesh) return;
    const r = renderer.domElement.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(
      ((e.clientX - r.left) / r.width) * 2 - 1,
      -((e.clientY - r.top) / r.height) * 2 + 1,
    ), view);
    // Against the TURF only, and against the turf even when its layer is switched off — the pivot
    // must land on the ground plane. Raycasting the whole scene would happily pivot on a frustum
    // line or a trajectory dot, which puts the orbit centre inside the object being inspected.
    const was = groups.turf.visible;
    groups.turf.visible = true;
    const hit = ray.intersectObject(turfMesh, false)[0];
    groups.turf.visible = was;
    if (!hit) return;
    // Keep the angle and the distance; move only what is being looked at.
    const offset = new THREE.Vector3().subVectors(view.position, orbit.target);
    orbit.target.copy(hit.point);
    view.position.copy(hit.point).add(offset);
    orbit.update();
  });

  // Declared before the render loop on purpose: `flyStep` hoists, its `const held` does
  // not, so a loop that starts first dies on the temporal dead zone at frame one.
  let lastTick = 0;
  (function tick(now) {
    requestAnimationFrame(tick);
    // Real seconds, not frames: a 144 Hz screen must not fly twice as fast as a 60 Hz one.
    const dt = lastTick ? Math.min((now - lastTick) / 1000, 0.1) : 0;
    lastTick = now;
    flyStep(dt);
    orbit.update();
    renderer.render(scene, view);
    if (rendererB && cam) {
      // Hidden for B, and each for its own reason:
      //   camera     — a frustum drawn from inside itself is noise;
      //   frameplane — it would occlude the very pitch it exists to be compared against;
      //   turf       — the synthetic grass would cover the photograph that IS the evidence;
      //   trajectory — this one is not obvious and cost a paint: the camera sits INSIDE the cloud
      //                of its own recovered positions, so the trail renders across the whole near
      //                plane and fills window B with solid orange. The trail is a view-A object.
      const hidden = ["camera", "frameplane", "turf", "trajectory"];
      const was = hidden.map((k) => groups[k].visible);
      for (const k of hidden) groups[k].visible = false;
      rendererB.render(scene, solved);
      hidden.forEach((k, i) => { groups[k].visible = was[i]; });
    }
  })(0);


  // Fit to the PROJECTED corners, not to a bounding sphere. A pitch is a flat rectangle seen
  // obliquely: the sphere containing it projects far larger than it does, so fitting the sphere
  // leaves the pitch small and floating in the upper half of the window.
  function frameAll() {
    if (!fitPoints.length) return;
    const v = new THREE.Vector3();
    let d = 200;
    let target = new THREE.Vector3(0, 0, 0);
    for (let pass = 0; pass < 4; pass++) {
      view.position.set(VIEW_DIR[0] * d, VIEW_DIR[1] * d, VIEW_DIR[2] * d).add(target);
      view.lookAt(target);
      view.updateMatrixWorld();
      view.updateProjectionMatrix();
      let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
      for (const p of fitPoints) {
        v.set(p[0], p[1], p[2]).project(view);
        x0 = Math.min(x0, v.x); x1 = Math.max(x1, v.x);
        y0 = Math.min(y0, v.y); y1 = Math.max(y1, v.y);
      }
      const dx = (x0 + x1) / 2, dy = (y0 + y1) / 2;
      const right = new THREE.Vector3().setFromMatrixColumn(view.matrixWorld, 0);
      const up = new THREE.Vector3().setFromMatrixColumn(view.matrixWorld, 1);
      const scale = Math.tan((view.fov * Math.PI) / 360) * d;
      target = target.clone()
        .add(right.multiplyScalar(dx * scale * view.aspect))
        .add(up.multiplyScalar(dy * scale));
      d *= Math.max((x1 - x0) / 2, (y1 - y0) / 2) * FIT_MARGIN;
    }
    orbit.target.copy(target);
    orbit.update();
  }

  async function initPitch() {
    const r = await fetch("/api/pitch");
    if (!r.ok) throw new Error(`/api/pitch -> ${r.status}`);
    const d = await r.json();
    const { length, width } = d.dimensions;

    const turf = new THREE.Mesh(
      new THREE.PlaneGeometry(length, width),
      new THREE.MeshLambertMaterial({ color: TURF }),
    );
    turf.position.z = -0.01;     // below the paint, so z-fighting never eats a line
    groups.turf.add(turf);
    turfMesh = turf;

    for (const poly of d.markings) {
      if (poly.length === 1) {
        const dot = new THREE.Mesh(new THREE.CircleGeometry(0.15, 16),
          new THREE.MeshBasicMaterial({ color: PAINT }));
        dot.position.set(poly[0][0], poly[0][1], 0.004);
        groups.markings.add(dot);
      } else {
        groups.markings.add(polyline(poly, PAINT));
      }
    }
    for (const poly of d.uprights) groups.goals.add(polyline(poly, UPRIGHT));

    const hz = Math.max(...d.uprights.flat().map((p) => p[2]));
    fitPoints = [];
    for (const sx of [-length / 2, length / 2]) {
      for (const sy of [-width / 2, width / 2]) {
        for (const sz of [0, hz]) fitPoints.push([sx, sy, sz]);
      }
    }
    resize();
    frameAll();
    return d;
  }

  /** Load a run: its clip record and its solve. */
  // No default name here either: an empty `which` lets the server pick one the clip actually has.
  async function loadRun(clipId, which = "") {
    const [runs, camResp] = await Promise.all([
      fetch("/api/runs").then((r) => r.json()),
      fetch(`/api/run/${clipId}/camera?which=${which}`),
    ]);
    clip = runs.find((r) => r.clip_id === clipId);
    if (!clip) throw new Error(`no run ${clipId}`);
    if (!camResp.ok) throw new Error(`/api/run/${clipId}/camera -> ${camResp.status}`);
    cam = await camResp.json();
    if (cam.width !== clip.width || cam.height !== clip.height) {
      // A refusal, not a warning. A camera solved in a different image space than the frames on
      // disk produces an overlay that is confidently and subtly wrong, which is worse than none —
      // it is the exact shape of the crop-space defect this repo was carved out to stop repeating.
      throw new Error(
        `solve is ${cam.width}x${cam.height} but the frames are ${clip.width}x${clip.height}`);
    }
    drawTrajectory();
    return cam;
  }

  const loader = new THREE.TextureLoader();

  /** Show frame `i`: repoint the solved camera, redraw its frustum, retexture the frame plane. */
  async function show(i) {
    shownIndex = i;
    if (!cam) return null;
    const url = `/api/run/${clip.clip_id}/frame/${i}`;
    await new Promise((res) => {
      loader.load(url, (t) => {
        t.colorSpace = THREE.SRGBColorSpace;
        frameTex?.dispose();
        frameTex = t;
        res();
      }, undefined, () => res());
    });
    drawCamera(i);
    drawFramePlane(i);
    // Follow the camera unless a hand is on the gizmo, in which case the hand wins until it lets go.
    // The proxy carries the camera's own frame, position and orientation both, so the rotate
    // gizmo turns about the axes a human sees rather than about the world's.
    if (!dragging) {
      dragProxy.position.copy(solved.position);
      dragProxy.quaternion.copy(solved.quaternion);
    }
    const live = cam.focal_px[i] > 0;
    // The camera has SEVEN independent degrees of freedom — position (3), orientation (3), focal
    // (1) — and the panel used to show five numbers, of which one was derived. The three angles
    // were solved and stored all along and simply never displayed.
    let yaw = NaN, elev = NaN, roll = NaN;
    if (live) {
      const fwd = new THREE.Vector3();
      solved.getWorldDirection(fwd);
      const right = new THREE.Vector3().setFromMatrixColumn(solved.matrixWorld, 0);
      // Readable angles, not an Euler triple: an XYZ decomposition in a Z-up world produces
      // numbers nobody can check against a photograph.
      //   yaw  — bearing from +X, counter-clockwise seen from above
      //   elev — of the optical axis; negative is looking down
      //   roll — tilt of the horizon; 0 is level, and a handheld phone stays within a few degrees.
      //          Frame 116's 47.7 deg is the tell that its solve is nonsense.
      yaw = (Math.atan2(fwd.y, fwd.x) * 180) / Math.PI;
      elev = (Math.asin(Math.max(-1, Math.min(1, fwd.z))) * 180) / Math.PI;
      roll = (Math.asin(Math.max(-1, Math.min(1, right.z))) * 180) / Math.PI;
    }
    const f = cam.focal_px[i];
    const info = {
      frame: i,
      live,
      // Derived, like the colour above. The file's own `degenerate` list is inherited from
      // whatever seeded the chain and outlives the repairs made since — see `unusable`.
      degenerate: unusable(cam, i),
      focal_px: f,
      // Derived from the focal and the image size, not free — shown because a human reads angles,
      // not pixels, and both axes matter on a 16:9 crop.
      fov_x_deg: live ? (2 * Math.atan(clip.width / (2 * f)) * 180) / Math.PI : NaN,
      fov_y_deg: live ? (2 * Math.atan(clip.height / (2 * f)) * 180) / Math.PI : NaN,
      yaw_deg: yaw, elevation_deg: elev, roll_deg: roll,
      position: cam.position[i],
      ground_distance_m: groundDistance(i),
      plane_distance_m: planeDistanceFor(i),
      plane_auto: planeOverride == null,
      frame_url: url,
    };
    onCamera(info);
    return info;
  }

  function setLayer(name, on) { if (groups[name]) groups[name].visible = !!on; }

  /** `d = null` returns to auto. Anything else is a manual override that sticks across frames. */
  function setPlaneDistance(d, i) {
    planeOverride = d == null ? null : Math.max(2, d);
    if (cam) { drawCamera(i); drawFramePlane(i); }
    return planeDistanceFor(i);
  }

  /** Turn the drag gizmo on or off. Off by default: a gizmo sitting in the view is a thing to
      catch with the mouse while orbiting, and most of the time the camera is not being moved. */
  function setDragMode(on, mode) {
    gizmo.enabled = !!on;
    gizmoHelper.visible = !!on;
    if (mode) gizmo.setMode(mode);
    if (on) {
      dragProxy.position.copy(solved.position);
      dragProxy.quaternion.copy(solved.quaternion);
    }
  }

  return {
    initPitch, loadRun, show, setLayer, setPlaneDistance, groundDistance, frameAll, fly, resize,
    setDragMode,
    resetView: frameAll,
    get clip() { return clip; },
    get cam() { return cam; },
    scene, view, solved, groups,
  };
}
