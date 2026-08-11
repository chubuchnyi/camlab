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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from camlab import __version__
from camlab.camera_file import read_camera
from camlab.core.angles import (
    angles_from_rotation,
    matrix_from_rodrigues,
    rodrigues_from_matrix,
    rotation_from_angles,
)
from camlab.core.pitch import pitch_polylines, pitch_upright_polylines
from camlab.core.units import FieldDimensions
from camlab.measure.line_error import line_errors, summarise
from camlab.measure.lines import detect_segments
from camlab.measure.paint import paint_masks
from camlab.measure.residual import frame_residual
from camlab.runs import ClipInfo, list_runs, runs_root

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


def _camera_files(info) -> list[str]:
    return sorted(p.name for p in info.dir.glob("camera_*.json") if "manual" not in p.name)


def _load_camera(info, which: str) -> dict:
    """A solve plus any hand edits laid over it.

    `camera_manual.json` is a separate file and is never merged into the solve on disk. What the
    algorithm said and what a human corrected stay separable, or in a week nobody can say where a
    number came from (spec §4.2, ADR-0002).
    """
    path = info.dir / which
    if not path.exists():
        raise HTTPException(404, f"{info.clip_id} has no {which}")
    cam = read_camera(path)
    manual = info.dir / "camera_manual.json"
    if manual.exists():
        import json
        edits = json.loads(manual.read_text()).get(which, {})
        cam["manual_frames"] = sorted(int(k) for k in edits)
        for k, v in edits.items():
            i = int(k)
            cam["focal_px"][i] = v["focal_px"]
            cam["rotation"][i] = v["rotation"]
            cam["position"][i] = v["position"]
    else:
        cam["manual_frames"] = []
    return cam


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


#: An upload is a video, not an archive and not a script. Nothing here executes what arrives — it
#: is handed to ffmpeg through `ingest`, which decodes frames or fails.
_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
#: 2 GB. Large enough for a phone clip at 4K, small enough that a mistake does not fill the volume.
_MAX_UPLOAD_BYTES = 2 << 30


# Module-level singletons rather than calls in the signature: FastAPI wants the call, ruff's B008
# forbids it in a default, and this is the form both accept.
_F_VIDEO = File(...)
_F_CLIP = Form("")
_F_FRAMES = Form(60)
_F_FIRST = Form(0)


@app.post("/api/upload")
async def upload(video: UploadFile = _F_VIDEO, clip_id: str = _F_CLIP,
                 frames: int = _F_FRAMES, first: int = _F_FIRST) -> dict:
    """Take a video from the browser, decode it into a run, and make it selectable.

    The point is to be able to try a clip nobody has tuned anything for. Every number in this repo
    was measured on two clips that arrived with a camera already fitted by another project, and a
    method that only works on the clips it was built against is not a method.

    Decoding is synchronous. Sixty frames takes a few seconds and a progress channel would be more
    moving parts than the wait is worth; the browser shows a spinner and waits.
    """
    from camlab.io.ingest import ingest

    name = Path(video.filename or "clip").name
    if Path(name).suffix.lower() not in _VIDEO_SUFFIXES:
        raise HTTPException(400, f"{name}: expected one of {sorted(_VIDEO_SUFFIXES)}")
    cid = "".join(c if (c.isalnum() or c in "-_") else "_"
                  for c in (clip_id.strip() or Path(name).stem))[:40]
    if not cid:
        raise HTTPException(400, "give the clip a name")
    if cid in set(list_runs()):
        raise HTTPException(409, f"{cid} already exists — pick another name")
    if not (1 <= frames <= 600):
        raise HTTPException(400, "frames must be between 1 and 600")

    uploads = runs_root() / "_uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    dest = uploads / f"{cid}{Path(name).suffix.lower()}"
    size = 0
    with dest.open("wb") as fh:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "over 2 GB")
            fh.write(chunk)
    try:
        info = ingest(dest, cid, first=first, n_frames=frames, crop=None)
    except Exception as exc:                      # noqa: BLE001 - report, do not leave a half-run
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"could not decode {name}: {exc}") from exc
    return {"clip_id": info.clip_id, "width": info.width, "height": info.height,
            "fps": info.fps, "n_frames": info.n_frames, "bytes": size}


@app.get("/api/run/{clip_id}/camera")
def camera(clip_id: str, which: str = "camera_auto.json") -> dict:
    """The solve, as written. The viewer draws exactly this — no smoothing, no interpolation.

    A frame the solver could not use comes back marked, not removed: `focal_px == 0` and
    `degenerate == true`. Dropping it would make a broken clip look like a shorter good one, which
    is the failure mode R-6 exists to prevent, applied to the camera instead of to a player.
    """
    info = ClipInfo.load(clip_id)
    blob = _load_camera(info, which)
    blob["fps"] = info.fps
    blob["first_frame"] = info.first_frame
    blob["available"] = _camera_files(info)
    blob["which"] = which
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


def _num(v: float) -> float | None:
    """`None` for NaN. JSON has no NaN, and `json.dumps` emits a bare `NaN` that `JSON.parse`
    rejects — so a frame the metric could not score used to break the whole panel rather than
    show a dash."""
    return None if v != v else round(float(v), 2)


@app.get("/api/run/{clip_id}/residual/{n}")
def residual(clip_id: str, n: int, which: str = "camera_auto.json") -> dict:
    """How far this frame's camera puts the pitch from where the pitch is actually painted.

    The number behind window B. `n_scored` is not decoration: only markings that land on the
    playing surface are scored, so a camera that has run away projects almost everything somewhere
    unscoreable and posts a flattering median on the survivors. Read the two together, always.
    """
    info = ClipInfo.load(clip_id)
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside 0..{len(cam['frames']) - 1}")

    key = (clip_id, n, which,
           cam["focal_px"][n], tuple(cam["position"][n]), tuple(cam["rotation"][n]))
    if key not in _RESIDUAL_CACHE:
        # `cx, cy` from the CAMERA, exactly as the overlay route does. Omitting them defaulted to
        # the image centre, so on this cropped clip the number was computed with an optical axis
        # 638 px away from the one the overlay was drawn with — the picture and its score were two
        # different cameras, and no ruler laid on the picture could ever agree with the number.
        r = frame_residual(info.frame_path(n), cam["focal_px"][n], cam["rotation"][n],
                           cam["position"][n], frame=n, cx=cam["cx"], cy=cam["cy"])
        _RESIDUAL_CACHE[key] = {
            "frame": r.frame,
            # worst_line_px first, because it is the verdict. A pooled median cannot show a camera
            # sitting on one family of lines while the family parallel to it is metres off, and
            # that is the failure a human spotted in the overlay while the median read 7 px.
            "worst_line_px": _num(r.worst_line_px),
            # The worst single sample on a solidly-scored marking — what the ruler finds, because a
            # human measures a line where it is furthest out, not at the middle where its median is.
            "worst_place_px": _num(max((v[2] for v in r.per_line.values() if v[1] >= 8),
                                       default=float("nan"))),
            "median_px": _num(r.median_px),
            "p90_px": _num(r.p90_px),
            "max_px": _num(r.max_px),
            "per_line": {str(k): [round(v[0], 2), v[1], round(v[2], 2)]
                         for k, v in r.per_line.items()},
            "n_scored": r.n,
            "n_projected": r.n_projected,
            "n_unmatched": r.n_unmatched,
            "coverage": round(r.coverage, 4),
        }
    return _RESIDUAL_CACHE[key]


_LINES_CACHE: dict[tuple, dict] = {}


@app.get("/api/run/{clip_id}/paint/{n}.png")
def paint_png(clip_id: str, n: int) -> Response:
    """The paint mask itself, as a transparent PNG — what the line finder was actually given.

    Worth being able to see on its own. A frame with no detected line and a frame with no paint
    look identical in an overlay of segments, and they mean opposite things: one is a finder
    problem, the other is that there is nothing there.
    """
    import cv2

    info = ClipInfo.load(clip_id)
    path = info.frame_path(n)
    if not path.exists():
        raise HTTPException(404, f"{clip_id} frame {n} not decoded")
    bgr = cv2.imread(str(path))
    dist, surface = paint_masks(bgr)
    on = (dist == 0) & (surface > 0)
    rgba = np.zeros((*on.shape, 4), np.uint8)
    rgba[on] = (60, 190, 255, 255)          # BGRA: amber, opaque only on the paint
    ok, buf = cv2.imencode(".png", rgba)
    if not ok:
        raise HTTPException(500, "png encode failed")
    return Response(bytes(buf), media_type="image/png")


@app.get("/api/run/{clip_id}/lines/{n}")
def lines(clip_id: str, n: int, method: str = "hough",
          which: str = "camera_auto.json") -> dict:
    """Line-to-line error for one frame, in IMAGE coordinates, ready to draw and to measure.

    Everything here is in the pixels of the frame on disk, so the viewer can put it straight into
    an SVG over the photograph and a ruler dropped on `p1`..`p2` reads `offset_px` exactly. That is
    the property the previous metric lacked: a number nobody could check against the screen.
    """
    import cv2

    info = ClipInfo.load(clip_id)
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside 0..{len(cam['frames']) - 1}")
    if not (cam["focal_px"][n] > 0):
        return {"frame": n, "lines": [], "segments": [], "summary": None,
                "note": "no camera for this frame"}

    if method not in ("hough", "lsd"):
        raise HTTPException(400, "method must be hough or lsd")
    key = (clip_id, n, method, which,
           cam["focal_px"][n], tuple(cam["position"][n]), tuple(cam["rotation"][n]))
    if key in _LINES_CACHE:
        return _LINES_CACHE[key]

    bgr = cv2.imread(str(info.frame_path(n)))
    if bgr is None:
        raise HTTPException(404, f"{clip_id} frame {n} not decoded")
    dist, surface = paint_masks(bgr)
    segs = detect_segments(dist, surface, method=method)
    # The principal point the camera was SOLVED under, from the camera file — not the clip's true
    # optical axis. A camera is only valid with its own K; swapping one in makes a different camera
    # and every offset below would be measuring that instead.
    errs = line_errors(segs, cam["focal_px"][n], cam["rotation"][n], cam["position"][n],
                       info.width, info.height, cx=cam["cx"], cy=cam["cy"])
    out = {
        "frame": n,
        "method": method,
        "width": info.width, "height": info.height,
        "segments": [[round(v, 1) for v in s] for s in segs.tolist()],
        "lines": [
            {
                "marking": e.marking,
                "model": [[round(v, 1) for v in p] for p in e.model_uv.tolist()],
                "found": None if e.found_uv is None
                         else [[round(v, 1) for v in p] for p in e.found_uv.tolist()],
                "offset_px": None if not e.matched else round(e.offset_px, 1),
                "angle_deg": None if not e.matched else round(e.angle_deg, 2),
                "overlap_px": round(e.overlap_px, 1),
                "p1": None if e.p1_uv is None else [round(v, 1) for v in e.p1_uv.tolist()],
                "p2": None if e.p2_uv is None else [round(v, 1) for v in e.p2_uv.tolist()],
            }
            for e in errs
        ],
        "summary": {k: (None if isinstance(v, float) and v != v else v)
                    for k, v in summarise(errs).items()},
    }
    _LINES_CACHE[key] = out
    return out


@app.get("/api/run/{clip_id}/manual/{n}")
def manual_get(clip_id: str, n: int, which: str = "camera_auto.json") -> dict:
    """This frame's camera as READABLE ANGLES, ready to be typed into."""
    info = ClipInfo.load(clip_id)
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside the clip")
    yaw, elev, roll = angles_from_rotation(matrix_from_rodrigues(np.asarray(cam["rotation"][n])))
    x, y, z = cam["position"][n]
    return {"frame": n, "which": which, "focal_px": cam["focal_px"][n],
            "x": x, "y": y, "z": z, "yaw": yaw, "elev": elev, "roll": roll,
            "edited": n in cam.get("manual_frames", [])}


@app.post("/api/run/{clip_id}/manual/{n}")
def manual_set(clip_id: str, n: int, body: dict) -> dict:
    """Apply a hand edit. The client sends SCALARS; the camera is derived here.

    Never a matrix from the browser: a client-side 3x3 can express things that are not a rotation,
    and then "this is one camera" stops being a guarantee and becomes a hope. Seven numbers a human
    can read off the panel go in, and `rotation_from_angles` — round-trip tested — turns them back.

    Writes `camera_manual.json`, keyed by which solve it overlays. The solve on disk is untouched:
    what the algorithm said and what a human corrected have to stay separable.
    """
    import json

    info = ClipInfo.load(clip_id)
    which = str(body.get("which", "camera_auto.json"))
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside the clip")

    rot = rotation_from_angles(float(body["yaw"]), float(body["elev"]), float(body["roll"]))
    rvec = rodrigues_from_matrix(rot)
    pos = [float(body["x"]), float(body["y"]), float(body["z"])]
    focal = float(body["focal_px"])
    if not (100.0 < focal < 40000.0):
        raise HTTPException(400, f"focal {focal} is not a lens on a {info.width} px wide image")

    path = info.dir / "camera_manual.json"
    blob = json.loads(path.read_text()) if path.exists() else {}
    edits = blob.setdefault(which, {})
    scope = body.get("scope", "frame")
    targets = [n] if scope == "frame" else list(range(len(cam["frames"])))

    # A clip-scoped write replaces the position on EVERY frame, including ones a human aligned by
    # eye. It did that silently once and destroyed a frame that had been tuned to 3.6 px — the
    # rotation survived, but a rotation aimed from a different point is a worse camera than the
    # solve it replaced (that frame went 3.6 -> 41.1 px, against 32.2 for the untouched solve).
    # So: back the file up before touching it, and report how many hand positions were displaced
    # so the caller can ask first.
    displaced = 0
    if scope != "frame":
        for i in targets:
            prev = edits.get(str(i))
            if i != n and prev is not None and list(prev["position"]) != pos:
                displaced += 1
        if path.exists():
            (info.dir / "camera_manual.bak.json").write_text(path.read_text())

    for i in targets:
        # "clip" scope moves only the POSITION: orientation and focal are per-frame by definition,
        # and copying one frame's aim to the whole clip would be a different camera, not an edit.
        prev = edits.get(str(i))
        if i == n or prev is None:
            base_r = rvec.tolist() if i == n else list(cam["rotation"][i])
            base_f = focal if i == n else cam["focal_px"][i]
        else:
            base_r, base_f = prev["rotation"], prev["focal_px"]
        edits[str(i)] = {"focal_px": base_f, "rotation": list(base_r), "position": pos}
    path.write_text(json.dumps(blob, indent=1))
    return {"ok": True, "edited_frames": len(edits), "scope": scope,
            "displaced_hand_positions": displaced,
            "backup": "camera_manual.bak.json" if scope != "frame" else None}


@app.delete("/api/run/{clip_id}/manual/{n}")
def manual_clear(clip_id: str, n: int, which: str = "camera_auto.json",
                 scope: str = "frame") -> dict:
    """Drop hand edits — this frame's, or all of them. The solve underneath is never touched."""
    import json

    info = ClipInfo.load(clip_id)
    path = info.dir / "camera_manual.json"
    if not path.exists():
        return {"ok": True, "edited_frames": 0}
    blob = json.loads(path.read_text())
    edits = blob.get(which, {})
    if scope == "frame":
        edits.pop(str(n), None)
    else:
        edits = {}
    blob[which] = edits
    path.write_text(json.dumps(blob, indent=1))
    return {"ok": True, "edited_frames": len(edits)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
