"""Read the homographies out of a pitch3d `scene.json`.

M1 shows *today's* camera — the free per-frame homography — so the honest source is the one the
pipeline already produced, not a re-solve. Wiring PnLCalib in here would take a GPU, two 265 MB
weight files and an out-of-tree checkout, and would answer a question M1 is not asking.

This reads only the calibration block, by path, without importing pitch3d. The tagged-JSON
encoding (`{"__type__": ..., "fields": ...}` / `{"__ndarray__": {...}}`) is stable and the
alternative — depending on the package camlab deliberately forked — would defeat the point.

**The image space is not in the file.** `FieldCalibration` has no width/height, and the pipeline
applies `--crop auto` at decode while leaving the uncropped size on the clip record. So the caller
supplies it, and `camlab.runs.ClipInfo` is where it comes from: the frames on disk are already in
that space. Guessing it from the source filename gives a plausible wrong answer — that is a
recorded landmine, not a hypothetical.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np


def _nd(node) -> np.ndarray:
    """Decode one `{"__ndarray__": {...}}` node."""
    if isinstance(node, dict) and "__ndarray__" in node:
        a = node["__ndarray__"]
        return np.asarray(a["data"], dtype=a.get("dtype", "float64")).reshape(a["shape"])
    return np.asarray(node)


def read_calibration(scene_json: Path) -> dict:
    """Return `{homographies (T,3,3) image→world, frames (T,), confidence (T,)}`."""
    blob = json.loads(Path(scene_json).read_text())
    try:
        cal = blob["fields"]["field"]["fields"]["calibration"]["fields"]
    except (KeyError, TypeError) as e:  # noqa: B904
        raise ValueError(f"{scene_json}: no field.calibration block") from e

    h = _nd(cal["homographies"]).astype(float)
    frames = _nd(cal["frames"]).astype(int)
    conf = _nd(cal["confidence"]).astype(float) if "confidence" in cal else np.ones(len(h))
    if h.ndim != 3 or h.shape[1:] != (3, 3):
        raise ValueError(f"{scene_json}: homographies are {h.shape}, expected (T, 3, 3)")
    return {"homographies": h, "frames": frames, "confidence": conf}


def world_handedness(h_i2w: np.ndarray, width: int, height: int) -> np.ndarray:
    """Per frame: +1 if the homography maps to our right-handed world, -1 if mirrored.

    PnLCalib's keypoint table is a top-down template with Y running *down* it. Read those axes as
    ours and call the third "up" and the labelling is left-handed, so a homography that maps the
    lawn perfectly still decomposes to a camera looking upward from under the grass (#118). The
    pitch is symmetric about Y=0, so no marking metric can ever catch it — only something with
    height can, which is why the goalposts are the instrument.

    Measured per frame rather than assumed from a label, so a calibration solved before that fix
    still reads correctly. Returns a per-frame array because on a real clip they disagree: fan
    frames 115 and 117 read mirrored while 118 others do not, and those two turn out to be
    rank-poor rather than differently framed.
    """
    out = np.zeros(len(h_i2w))
    corners = np.array([[0.0, 0.0, 1.0], [width, 0.0, 1.0], [0.0, height, 1.0]])
    for i, h in enumerate(h_i2w):
        if not np.isfinite(h).all():
            continue
        p = corners @ h.T
        w = np.where(np.abs(p[:, 2]) > 1e-12, p[:, 2], 1e-12)
        xy = p[:, :2] / w[:, None]
        # Signed area of the image's own (0,0)-(w,0)-(0,h) triangle after mapping to the world.
        # Image y runs down and world y runs up, so an unmirrored map flips the winding: negative
        # cross product is the RIGHT-handed case here.
        u, v = xy[1] - xy[0], xy[2] - xy[0]
        cross = float(u[0] * v[1] - u[1] * v[0])   # 2D cross; numpy 2 removed the 2-vector form
        out[i] = -np.sign(cross)
    return out
