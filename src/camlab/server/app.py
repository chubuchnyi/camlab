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

import threading
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


#: Which camera to open a clip on when the caller does not say. In order of how much has been done
#: to it, best last-solved first. `camera_auto.json` is at the END rather than hardcoded as the
#: default, which it used to be: `broadcast` has never had one — its cameras are `known`, `carry`,
#: `healed`, `fixed`, `smooth` — so selecting that clip 404'd and the viewer showed nothing.
#: `camera_polished.json` leads, and it is read off `solve.pipeline` rather than spelled here: the
#: chain gained a fifth stage on 2026-08-13 and this list did not, so the viewer opened
#: `camera_smooth.json` — one stage BEHIND the result — and every number an operator read off it was
#: the previous stage's. `landmines.md` already records this exact shape twice.
def _preference() -> tuple[str, ...]:
    from camlab.solve.pipeline import FINAL_CAMERA

    rest = ("camera_smooth.json", "camera_fixed.json", "camera_healed.json",
            "camera_carry.json", "camera_auto.json", "camera_known.json", "camera_start.json")
    return (FINAL_CAMERA, *(n for n in rest if n != FINAL_CAMERA))


_CAMERA_PREFERENCE = _preference()


def _default_camera(info) -> str:
    have = _camera_files(info)
    if not have:
        raise HTTPException(404, f"{info.clip_id} has no camera at all")
    for name in _CAMERA_PREFERENCE:
        if name in have:
            return name
    return have[0]


def _write_manual(path, blob) -> None:
    """Write `camera_manual.json` atomically, under a lock.

    It holds the operator's own alignment — the thing that cannot be recomputed — and it was
    written with a plain `write_text` from four routes plus a background solve thread. One copy on
    disk was found corrupt: `runs/g15449383/camera_manual.json` held a complete JSON object
    followed by a stray `}`, which is two writers interleaving. The data was recoverable that time.

    Temp file in the same directory, then `os.replace`, which is atomic on POSIX: a reader sees
    either the old file or the new one and never a half of each. The lock is because these routes
    read-modify-write, and two of them racing lose one edit even with atomic writes.
    """
    import json
    import os
    import tempfile

    with _MANUAL_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".camera_manual.", suffix=".json")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(blob, fh, indent=1)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


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
            # ANY camera, not `camera_auto.json` specifically. broadcast has four — known, carry,
            # healed, fixed — and none of them is named auto, so it reported itself unsolved and
            # the page refused to open the better-solved of the two clips in the repo.
            "solved": bool(_camera_files(info)),
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
    # A default camera, immediately. Without one the clip lands in the list unopenable and the
    # edit fields have nothing to show, so "upload a video" stopped one step short of being useful.
    # It is a labelled guess and nothing here pretends otherwise.
    write_start_camera(info)
    return {"clip_id": info.clip_id, "width": info.width, "height": info.height,
            "fps": info.fps, "n_frames": info.n_frames, "bytes": size}


@app.get("/api/run/{clip_id}/camera")
def camera(clip_id: str, which: str = "") -> dict:
    """The solve, as written. The viewer draws exactly this — no smoothing, no interpolation.

    A frame the solver could not use comes back marked, not removed: `focal_px == 0` and
    `degenerate == true`. Dropping it would make a broken clip look like a shorter good one, which
    is the failure mode R-6 exists to prevent, applied to the camera instead of to a player.
    """
    info = ClipInfo.load(clip_id)
    which = which or _default_camera(info)
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
def residual(clip_id: str, n: int, which: str = "") -> dict:
    """How far this frame's camera puts the pitch from where the pitch is actually painted.

    The number behind window B. `n_scored` is not decoration: only markings that land on the
    playing surface are scored, so a camera that has run away projects almost everything somewhere
    unscoreable and posts a flattering median on the survivors. Read the two together, always.
    """
    info = ClipInfo.load(clip_id)
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
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
          which: str = "") -> dict:
    """Line-to-line error for one frame, in IMAGE coordinates, ready to draw and to measure.

    Everything here is in the pixels of the frame on disk, so the viewer can put it straight into
    an SVG over the photograph and a ruler dropped on `p1`..`p2` reads `offset_px` exactly. That is
    the property the previous metric lacked: a number nobody could check against the screen.
    """
    import cv2

    info = ClipInfo.load(clip_id)
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
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
def manual_get(clip_id: str, n: int, which: str = "") -> dict:
    """This frame's camera as READABLE ANGLES, ready to be typed into."""
    info = ClipInfo.load(clip_id)
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside the clip")
    yaw, elev, roll = angles_from_rotation(matrix_from_rodrigues(np.asarray(cam["rotation"][n])))
    x, y, z = cam["position"][n]
    return {"frame": n, "which": which, "focal_px": cam["focal_px"][n],
            "x": x, "y": y, "z": z, "yaw": yaw, "elev": elev, "roll": roll,
            "edited": n in cam.get("manual_frames", [])}


def write_start_camera(info) -> Path:
    """A labelled default camera, so a freshly ingested clip is openable and editable.

    Stands on the near touchline, looking at the centre spot, focal from a 22° horizontal field of
    view — which is roughly what match footage is shot on. Nothing in it is measured from the clip
    and the file says `is_default: true`.
    """
    from camlab.camera_file import write_camera

    cx, cy = info.principal_point
    pos = np.array([0.0, -75.0, 20.0])
    f = np.asarray([0.0, 0.0, 0.0]) - pos
    f = f / np.linalg.norm(f)
    rvec = rodrigues_from_matrix(rotation_from_angles(
        float(np.degrees(np.arctan2(f[1], f[0]))), float(np.degrees(np.arcsin(f[2]))), 0.0))
    focal = (info.width / 2.0) / np.tan(np.radians(22.0) / 2.0)
    n = info.n_frames
    return write_camera(
        info.dir / "camera_start.json", model="hand_start_default", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.arange(n),
        focal_px=np.full(n, focal), position=np.tile(pos, (n, 1)),
        rotation=np.tile(rvec, (n, 1)), cx=cx, cy=cy, degenerate=[False] * n,
        is_default=True, assumed_fov_deg=22.0,
        notes=("A DEFAULT, not a solve. Drag it onto the paint on one frame, then run the solve — "
               "the chain follows the operator from there."),
    )


#: Guards the read-modify-write of `camera_manual.json`. See `_write_manual`.
_MANUAL_LOCK = threading.Lock()

#: One solve at a time per clip, and its progress. In memory: a solve that a restart interrupts has
#: not half-written anything, since each stage writes its own camera file only on success.
_SOLVES: dict[str, dict] = {}


@app.post("/api/run/{clip_id}/solve")
def solve(clip_id: str, anchor: int = 0, seed: str = "camera_start.json") -> dict:
    """Run the whole chain in the background: carry, self-heal, shared centre, smooth.

    Not synchronous. Sixty frames takes a few minutes and an HTTP request that long is a request
    that dies to some proxy or laptop lid. Poll `GET .../solve` for progress.

    `anchor` should be a frame the human has aligned by eye, if there is one: measured at about
    sixty frames' worth of anchor, and the difference between 2.11 px and 7.75 px on the fan clip.
    """
    import threading

    from camlab.solve.pipeline import run as run_pipeline

    ClipInfo.load(clip_id)                                   # 404s if the clip is unknown
    cur = _SOLVES.get(clip_id)
    if cur and cur.get("state") == "running":
        raise HTTPException(409, f"{clip_id} is already solving: {cur.get('stage')}")

    st: dict = {"state": "running", "stage": "starting", "step": 0, "of": 4,
                "anchor": anchor, "seed": seed, "stages": {}}
    _SOLVES[clip_id] = st

    def progress(i, n, label, what):
        st.update(step=i, of=n, stage=f"{label} — {what}")

    def work():
        try:
            res = run_pipeline(clip_id, anchor=anchor, seed=seed, on_progress=progress)
            st.update(state="done" if res["ok"] else "failed", stages=res["stages"],
                      camera=res.get("camera"))
        except Exception as exc:                              # noqa: BLE001 - surface, never hide
            st.update(state="failed", stage=f"crashed: {exc}")

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "clip_id": clip_id, "anchor": anchor, "seed": seed}


@app.get("/api/run/{clip_id}/solve")
def solve_status(clip_id: str) -> dict:
    """How the background solve is going, or that none has run."""
    return _SOLVES.get(clip_id) or {"state": "idle"}


@app.post("/api/run/{clip_id}/flip")
def flip(clip_id: str, which: str = "") -> dict:
    """Turn the whole clip's camera through 180° about the centre spot.

    A pitch is **exactly** symmetric under that half-turn, so the rotated camera scores bit for bit
    the same — measured at 2.1 px on 307 samples either way on fan, 4.5 px on 300 on broadcast.
    Nothing in the markings can choose, and no solver ever will: the information is not there. It
    takes something off the pitch — the stands, the scoreboard, which way the teams attack — or one
    click from someone looking at the picture.

    Applied to every frame at once, because the answer cannot differ between frames of one clip.
    Written as ordinary hand edits, so `reset every edit` undoes it like anything else.
    """
    import json

    info = ClipInfo.load(clip_id)
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
    cam = _load_camera(info, which)
    path = info.dir / "camera_manual.json"
    blob = json.loads(path.read_text()) if path.exists() else {}
    edits = blob.setdefault(which, {})
    for i in range(len(cam["frames"])):
        rvec = np.asarray(cam["rotation"][i])
        yaw, elev, roll = angles_from_rotation(matrix_from_rodrigues(rvec))
        rot = rotation_from_angles(yaw + 180.0, elev, roll)
        x, y, z = cam["position"][i]
        edits[str(i)] = {"focal_px": cam["focal_px"][i],
                         "rotation": rodrigues_from_matrix(rot).tolist(),
                         "position": [-x, -y, z]}
    _write_manual(path, blob)
    return {"ok": True, "flipped_frames": len(cam["frames"]), "which": which}


@app.post("/api/run/{clip_id}/refine/{n}")
def refine(clip_id: str, n: int, body: dict) -> dict:
    """Take the camera the human has roughly aimed at this frame and let the solver finish it.

    The division of labour the viewer was missing. A human is good at the thing the solver is bad
    at — knowing which painted line is which — and bad at the thing the solver is good at, which is
    the last two pixels. Measured over eight hand-aligned frames: a rough seed sits at 34.7 px, a
    careful human at 5.1, and `refit_frame_lm` from that seed at **2.0**.

    It refuses rather than damages. `refit._accept` takes the new camera only if the worst offset
    fell AND no correspondence was lost — a camera can always lower its error by pushing a marking
    out of frame — so a hand alignment that is already better than the fit survives untouched, and
    the reply says so.

    Writes through `camera_manual.json` exactly as a typed number does. What the algorithm said and
    what the human corrected stay separable even when the correction came from the algorithm.
    """
    import json

    import cv2

    from camlab.solve.refit import refit_frame_lm

    info = ClipInfo.load(clip_id)
    which = str(body.get("which", "") or "")
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
    cam = _load_camera(info, which)
    if not (0 <= n < len(cam["frames"])):
        raise HTTPException(404, f"frame {n} outside the clip")
    if not (cam["focal_px"][n] > 0):
        raise HTTPException(400, f"frame {n} has no camera to refine — aim one first")

    bgr = cv2.imread(str(info.frame_path(n)))
    if bgr is None:
        raise HTTPException(404, f"{clip_id} frame {n} not decoded")
    dist, surface = paint_masks(bgr)
    segs = detect_segments(dist, surface, method=str(body.get("method", "hough")))
    if len(segs) < 4:
        raise HTTPException(
            400, f"only {len(segs)} lines found on frame {n}; four is the floor for a fit")

    cx, cy = float(cam["cx"]), float(cam["cy"])
    before = frame_residual(info.frame_path(n), cam["focal_px"][n], cam["rotation"][n],
                            cam["position"][n], frame=n, cx=cx, cy=cy)
    r = refit_frame_lm(segs, cam["focal_px"][n], cam["rotation"][n], cam["position"][n],
                       info.width, info.height, cx, cy, frame=n)
    after = frame_residual(info.frame_path(n), r.focal_px, r.rotation, r.position,
                           frame=n, cx=cx, cy=cy)

    # AND it has to be better against the PAINT, which is the judge. `refit._accept` compares the
    # solver's own worst matched offset, and that is not the same number: on `g14604660` frame 30
    # a fit lowered its own objective while taking the worst marking from 1.37 px to 1.85 against
    # the paint, and the button wrote it. An operator pressing "auto-fit" on a frame that is
    # already good must not end up with a worse one.
    worse = (np.isfinite(after.worst_line_px) and np.isfinite(before.worst_line_px)
             and after.worst_line_px > before.worst_line_px)
    d_pos = float(np.linalg.norm(np.asarray(r.position) - np.asarray(cam["position"][n])))
    d_rot = float(np.linalg.norm(np.asarray(r.rotation) - np.asarray(cam["rotation"][n])))
    # Thresholds a human could see, not float noise. At machine epsilon a converged fit still
    # reports "moved" on every press, so the button never says "this is already as good as these
    # lines allow" — which is the one answer that tells an operator to stop pressing it.
    # 1 mm, 1e-5 rad (0.0006 deg) and half a pixel of focal are all far below what the overlay
    # shows at 70 m.
    moved = (not worse
             and (abs(r.focal_px - cam["focal_px"][n]) > 0.5 or d_pos > 1e-3 or d_rot > 1e-5))
    if moved:
        path = info.dir / "camera_manual.json"
        blob = json.loads(path.read_text()) if path.exists() else {}
        blob.setdefault(which, {})[str(n)] = {
            "focal_px": float(r.focal_px),
            "rotation": [float(v) for v in np.asarray(r.rotation).ravel()],
            "position": [float(v) for v in np.asarray(r.position).ravel()],
        }
        _write_manual(path, blob)

    yaw, elev, roll = angles_from_rotation(matrix_from_rodrigues(np.asarray(r.rotation, float)))
    # "Nothing to fit to" and "already the best fit" are the same `moved: false` and completely
    # different things to tell an operator. With fewer than MIN_MATCHED correspondences the
    # residual is a constant, the optimiser has no gradient at all, and it returns the seed — the
    # aim has to come closer by hand before the solver can do anything with it. Measured: a rough
    # aim on fan frame 0 that scores 16.94 px matched ZERO of the 7 detected lines.
    from camlab.solve.refit import MIN_MATCHED

    return {
        "frame": n, "which": which, "moved": moved,
        # Distinguished from "converged" so the viewer can say which happened: a fit that the paint
        # rejects is a different message from one that had nothing left to give.
        "refused_worse": bool(worse),
        "matched": int(r.n_before) >= MIN_MATCHED,
        "min_matched": int(MIN_MATCHED),
        "lines": int(len(segs)),
        # Both the solver's own number (worst matched offset, which is what it minimises) and the
        # paint's (which is what the panel shows), because they are different questions and the
        # register says to report the one that judges, not only the one that was optimised.
        "offset_before": None if not np.isfinite(r.before) else round(float(r.before), 2),
        "offset_after": None if not np.isfinite(r.after) else round(float(r.after), 2),
        "matched_before": int(r.n_before), "matched_after": int(r.n_after),
        "worst_line_before": None if not np.isfinite(before.worst_line_px)
                             else round(float(before.worst_line_px), 2),
        "worst_line_after": None if not np.isfinite(after.worst_line_px)
                            else round(float(after.worst_line_px), 2),
        "moved_m": round(float(r.moved_m), 3), "d_focal": round(float(r.d_focal), 1),
        "focal_px": float(r.focal_px), "x": float(r.position[0]), "y": float(r.position[1]),
        "z": float(r.position[2]), "yaw": float(yaw), "elev": float(elev), "roll": float(roll),
    }


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
    which = str(body.get("which", "") or "")
    # Resolved HERE and not inside the loader: every one of these routes goes on to use
    # `which` as the key into `camera_manual.json`, so resolving it out of sight would
    # leave the key empty and lose the operator's edits without a word. Same shape as the
    # seed-snapshot defect of 2026-08-14.
    which = which or _default_camera(info)
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
    _write_manual(path, blob)
    return {"ok": True, "edited_frames": len(edits), "scope": scope,
            "displaced_hand_positions": displaced,
            "backup": "camera_manual.bak.json" if scope != "frame" else None}


@app.delete("/api/run/{clip_id}/manual/{n}")
def manual_clear(clip_id: str, n: int, which: str = "",
                 scope: str = "frame") -> dict:
    """Drop hand edits — this frame's, or all of them. The solve underneath is never touched."""
    import json

    info = ClipInfo.load(clip_id)
    which = which or _default_camera(info)
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
    _write_manual(path, blob)
    return {"ok": True, "edited_frames": len(edits)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
