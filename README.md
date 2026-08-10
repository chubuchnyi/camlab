# camlab

**One question: where was the camera, where was it pointed, and what was the focal, on each frame.**

A clip goes in. A camera comes out — visible in 3D, editable by hand, and checkable by eye against
the video: project the pitch model through it and the lines must land on the paint.

Everything else — poses, physics, rendering, the generative tail — stays in `pitch3d`.

## Why this exists

`pitch3d` solves each frame's calibration as a free 8-DOF homography with nothing tying the frames
to one camera. On a tripod clip that is tolerable. On a phone clip from the stands the pitch plane
slides **0.899 m per frame** under every player, which reads as a storm of footballers and makes the
scene unjudgeable by eye.

Measured 2026-08-10 (`pitch3d/docs/findings/m1-handheld-centre-2026-08-10.md`): fixing the camera
**position** for the whole clip costs 0.90–1.23× against those free homographies while placing
37–64 % *more* of the pitch in frame. Fixing the **focal** as well costs 1.5–2.1×, because the clip
zooms 1.66×. So: one position, one shared intrinsic, a per-frame focal curve, a per-frame rotation.

Full spec: `pitch3d/docs/camlab-spec.md`.

## Status

| | | |
|---|---|---|
| M-1 | is a fixed camera position defensible for handheld? | **done** — yes |
| **M0** | **repo, container, port, UI shows the pitch** | **in progress** |
| M1 | clip in → today's free homography → camera, frustum, trajectory, frame plane, camera view | |
| M1.5 | take PnLCalib's camera directly instead of collapsing it to a homography | |
| M2 | the PTZ model: one position, per-frame rotation, smooth focal | the point of the repo |
| M3 | hand controls, `camera_manual.json`, live reprojection error | |
| M4 | skeletons, ball, per-layer and per-player hiding | |

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/uvicorn camlab.server.app:app --port 8000     # -> http://localhost:8000
```

```bash
docker build -f docker/Dockerfile -t camlab:m0 .
docker run --rm -p 8000:8000 -v "$PWD/runs:/runs" camlab:m0
```

## Two rules it keeps

**No CDN.** three.js is vendored under `src/camlab/server/static/vendor/` with checksums, and a
test fails if any served file reaches the network. The target box runs behind a link that resets
every ~250 MB and is reached only over ssh; a page that fetches its renderer at load time is a page
that does not open.

**The browser never posts a matrix.** It posts a gesture or a few scalars; the server derives the
transform. A raw 3×3 from a client can express things that are not a camera, and then "one camera"
stops being a guarantee.

## Relationship to pitch3d

This is a **copy** of `pitch3d/src/pitch3d/core/`, not a dependency — the camera contract itself has
to change here (`CameraTrack` holds one intrinsic for a whole clip, so a zoom is not representable).
Each copied file carries a header saying where it came from. Do not hand-sync them back.

The transfer format in both directions is `calib/<clip>.npz` — `focal, centre, rvecs, frames,
world_to_image`. `tests/test_golden_real_camera.py` pins the copy against the same real measurement
`pitch3d` pins: focal 4169.32 px, one optical centre for 60 frames at (−2.29, −70.13, 17.22) m.
