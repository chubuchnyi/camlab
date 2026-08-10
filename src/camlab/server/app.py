"""The camlab HTTP surface.

Deliberately small and deliberately offline. Two rules it keeps from `poseannot`, both of which
were learned the expensive way there:

* **No CDN.** three.js is vendored under `static/vendor/` with its checksums (spec §7.3). The
  target box runs the container behind a link that resets every ~250 MB and is reached only over
  ssh; a page that fetches its renderer at load time is a page that does not open.
* **The browser never posts a matrix.** When editing arrives (M3) the client sends a gesture or a
  few scalars and the server derives the transform. A raw 3x3 from the client can express things
  that are not a camera, and then "one camera" stops being a guarantee and becomes a hope.

Run:

    uvicorn camlab.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from camlab import __version__
from camlab.camera_file import read_camera
from camlab.core.pitch import pitch_polylines, pitch_upright_polylines
from camlab.core.units import FieldDimensions
from camlab.measure.residual import frame_residual
from camlab.runs import ClipInfo, list_runs

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="camlab", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/pitch")
def pitch() -> dict:
    """The pitch, in world metres: Z-up, right-handed, origin on the centre spot.

    Regenerated from the Laws-of-the-Game constants in `core/pitch.py`, not stored in any run —
    the markings are the one thing in this project that is known exactly, and a solved camera is
    judged by whether it lands them on the paint.

    `markings` are on the plane and come back as (x, y). `uprights` — the two goal frames and the
    four corner flagposts — are the only geometry with height, which makes them the instrument for
    checking the focal: a wrong focal puts the crossbar in the right place on the ground and the
    wrong place in the air.

    Single-point "polylines" (the centre spot and the two penalty spots) are kept as length-1
    lists rather than dropped; the viewer draws them as dots.
    """
    dims = FieldDimensions()
    return {
        "dimensions": {"length": dims.length, "width": dims.width},
        "markings": [np.asarray(p, dtype=float).round(4).tolist() for p in pitch_polylines()],
        "uprights": [
            np.asarray(p, dtype=float).round(4).tolist() for p in pitch_upright_polylines()
        ],
    }


@app.get("/api/runs")
def runs() -> list[dict]:
    """Every ingested clip, and whether it has been solved."""
    out = []
    for cid in list_runs():
        info = ClipInfo.load(cid)
        out.append({
            "clip_id": cid,
            "width": info.width, "height": info.height,
            "fps": info.fps, "n_frames": info.n_frames,
            "first_frame": info.first_frame, "crop": info.crop,
            "source": Path(info.source).name,
            "solved": (info.dir / "camera_auto.json").exists(),
        })
    return out


@app.get("/api/run/{clip_id}/camera")
def camera(clip_id: str) -> dict:
    """The solve, as written. The viewer draws exactly this — no smoothing, no interpolation.

    A frame the solver could not use comes back marked, not removed: `focal_px == 0` and
    `degenerate == true`. Dropping it would make a broken clip look like a shorter good one, which
    is the failure mode R-6 exists to prevent, applied to the camera instead of to a player.
    """
    info = ClipInfo.load(clip_id)
    path = info.dir / "camera_auto.json"
    if not path.exists():
        raise HTTPException(404, f"{clip_id} has no camera_auto.json — run `camlab solve` first")
    blob = read_camera(path)
    blob["fps"] = info.fps
    blob["first_frame"] = info.first_frame
    return blob


@app.get("/api/run/{clip_id}/frame/{n}")
def frame(clip_id: str, n: int) -> FileResponse:
    """One decoded frame, ALREADY CROPPED — the same pixels the homographies were fitted to.

    So a texture made from this and a projection made from `camera_auto.json` are in one space,
    and window B is a fair comparison rather than a coincidence.
    """
    info = ClipInfo.load(clip_id)
    p = info.frame_path(n)
    if not p.exists():
        raise HTTPException(404, f"{clip_id} frame {n} not decoded (have {info.n_frames})")
    return FileResponse(p, media_type="image/jpeg")


#: Masks cost ~0.4 s a frame and never change for a given (clip, frame, camera), so the scrubber
#: would otherwise re-measure the same thing every time it passed. Keyed by the camera too, so a
#: hand edit (M3) or a filtered track (#8) does not silently read a stale number.
_RESIDUAL_CACHE: dict[tuple, dict] = {}


@app.get("/api/run/{clip_id}/residual/{n}")
def residual(clip_id: str, n: int) -> dict:
    """How far this frame's camera puts the pitch from where the pitch is actually painted.

    The number behind window B. `n_scored` is not decoration: only markings that land on the
    playing surface are scored, so a camera that has run away projects almost everything somewhere
    unscoreable and posts a flattering median on the survivors. Read the two together, always.
    """
    info = ClipInfo.load(clip_id)
    path = info.dir / "camera_auto.json"
    if not path.exists():
        raise HTTPException(404, f"{clip_id} has no camera_auto.json")
    cam = read_camera(path)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside 0..{len(cam['frames']) - 1}")

    key = (clip_id, n, cam["focal_px"][n], tuple(cam["position"][n]), tuple(cam["rotation"][n]))
    if key not in _RESIDUAL_CACHE:
        r = frame_residual(info.frame_path(n), cam["focal_px"][n], cam["rotation"][n],
                           cam["position"][n], frame=n)
        _RESIDUAL_CACHE[key] = {
            "frame": r.frame,
            "median_px": None if r.n == 0 else round(r.median_px, 2),
            "p90_px": None if r.n == 0 else round(r.p90_px, 2),
            "n_scored": r.n,
            "n_projected": r.n_projected,
            "coverage": round(r.coverage, 4),
        }
    return _RESIDUAL_CACHE[key]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
