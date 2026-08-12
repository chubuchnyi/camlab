"""`camera_auto.json` — the solve on disk, and the one format the viewer reads.

Deliberately flat and model-tagged rather than a serialised `CameraTrack`. `CameraTrack` carries
**one** `CameraIntrinsics` for a whole clip, so a zoom is not representable in it at all — which is
half the reason camlab is a separate repo (spec §1.5, §3.4). Here the focal is per frame, and a
model that shares it says so by writing the same number down T times.

`position` is the camera CENTRE in world metres, not the `t` of `X_c = R X_w + t`. Those differ by
`C = -Rᵀt` and confusing them puts the camera under the pitch — the shape of #118. The centre is
what a human reads off a viewer and types into a box, so it is what gets stored.

Hand edits never land here. They go to `camera_manual.json` and are laid over this at read time
(M3), so "what the algorithm said" and "what I corrected" never merge into one unattributable
number.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

#: Bumped when the meaning of a field changes, never for an addition.
SCHEMA = 1

#: The same bounds `core/plane_camera.py` fits within. Imported rather than re-declared would be
#: better, and would be a circular import: `plane_camera` writes cameras.
FOCAL_BOUNDS = (300.0, 20000.0)


def _clip_principal_point(clip_id: str):
    """The clip's own optical axis, or None when the clip is not on disk (tests, fixtures).

    Deliberately best-effort: this is a note written into the file, not a gate. A camera solved
    under a principal point that is not the clip's is a legitimate thing to want — `camera_axis`
    and `camera_auto` differ by exactly that and both are kept — and refusing it here would make
    the comparison that measured the 0.88 m impossible to run.
    """
    try:
        from camlab.runs import ClipInfo

        return ClipInfo.load(clip_id).principal_point
    except Exception:                          # noqa: BLE001 - a missing clip is not an error here
        return None


def write_camera(
    path: Path,
    *,
    model: str,
    clip_id: str,
    width: int,
    height: int,
    frames: np.ndarray,
    focal_px: np.ndarray,
    position: np.ndarray,
    rotation: np.ndarray,
    cx: float | None = None,
    cy: float | None = None,
    notes: str = "",
    **extra,
) -> Path:
    """Write a solve. `rotation` is Rodrigues, world→camera; `position` is the world centre.

    `cx, cy` default to the image centre, which is right only for an uncropped clip. **A camera is
    valid only with the K it was solved under**, so this is recorded here rather than reconstructed
    by a reader: swapping in a different principal point later does not adjust the camera, it makes
    a different one. Every evaluation reads these back.

    **Three things are checked here that used to be checked nowhere.** A review from pitch3d found
    all three by reading the files this function had written:

    * A focal of **zero** is not a degenerate camera, it is not a camera. `runs/fan/camera_ptz.json`
      carries fourteen of them. The crash that caused downstream was fixed months later in
      `frame_residual`; the thing that wrote it was not touched. Now it raises.
    * A focal **pinned at a `FOCAL_BOUNDS` end** is a finding, not a setting — this project's own
      rule. Four fan cameras have nine frames each at 20000 and three at 300, the same twelve
      frames in all of them, so it is inherited from the per-frame decomposition. Counted into
      `focal_at_bound` rather than left for someone to notice.
    * A `(cx, cy)` that **disagrees with the clip's own optical axis** is recorded as
      `principal_point_offset_px`. The fan clip is cropped, its axis is 638 px from the image
      centre, and every shipped camera used the image centre anyway — not because a default was
      wrong but because each stage copies `cx, cy` from its input and nothing ever compared them.
      Measured, that costs 0.88 m of camera position on a 70 m shot; small, and worth writing in
      the file rather than rediscovering.
    """
    frames = np.asarray(frames, dtype=int)
    f = np.asarray(focal_px, dtype=float)
    if f.size and not np.all(np.isfinite(f)):
        raise ValueError(f"{path.name}: focal contains NaN or inf")
    bad = np.flatnonzero(f <= 0.0)
    if bad.size:
        raise ValueError(
            f"{path.name}: {bad.size} frame(s) have a focal of {f[bad[0]]:g} — first is frame "
            f"{int(frames[bad[0]]) if bad[0] < len(frames) else bad[0]}. That is not a camera. "
            "Mark the frame degenerate and leave the focal out, or fix the solve."
        )
    at_bound = int(((f <= FOCAL_BOUNDS[0] + 1e-6) | (f >= FOCAL_BOUNDS[1] - 1e-6)).sum())
    payload = {
        "schema": SCHEMA,
        "model": model,
        "clip_id": clip_id,
        # The image space every pixel quantity here is in. Stored beside the numbers rather than
        # inferred at read time, because inferring it is exactly what goes wrong (see runs.py).
        "width": int(width),
        "height": int(height),
        "cx": width / 2.0 if cx is None else float(cx),
        "cy": height / 2.0 if cy is None else float(cy),
        "frames": frames.tolist(),
        "focal_px": np.asarray(focal_px, dtype=float).round(4).tolist(),
        "position": np.asarray(position, dtype=float).round(5).tolist(),
        "rotation": np.asarray(rotation, dtype=float).round(7).tolist(),
        # A bound that the data reaches is a bound that hides the tail. Counted, always, even when
        # it is zero — an absent field reads as "not checked" and a zero reads as "checked, clean".
        "focal_at_bound": at_bound,
        "notes": notes,
    }
    axis = _clip_principal_point(clip_id)
    if axis is not None:
        off = float(np.hypot(payload["cx"] - axis[0], payload["cy"] - axis[1]))
        payload["principal_point_offset_px"] = round(off, 2)
    for k, v in extra.items():
        payload[k] = v.tolist() if isinstance(v, np.ndarray) else v
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def read_camera(path: Path) -> dict:
    blob = json.loads(Path(path).read_text())
    if blob.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {blob.get('schema')}, expected {SCHEMA}")
    return blob


def summarise(blob: dict) -> str:
    """One line for a log or a HUD: how much the camera moves and how much the focal does."""
    pos = np.asarray(blob["position"], dtype=float)
    f = np.asarray(blob["focal_px"], dtype=float)
    live = f > 0
    spread = float(np.linalg.norm(pos[live] - np.median(pos[live], axis=0), axis=1).max()) \
        if live.any() else float("nan")
    ok_zoom = live.any() and f[live].min() > 0
    zoom = float(f[live].max() / f[live].min()) if ok_zoom else float("nan")
    return (f"{blob['model']}: {int(live.sum())}/{len(f)} frames · "
            f"centre spread {spread:.2f} m · focal {f[live].min():.0f}-{f[live].max():.0f} px "
            f"(x{zoom:.2f})")
