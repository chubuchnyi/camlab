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
    """
    frames = np.asarray(frames, dtype=int)
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
        "notes": notes,
    }
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
