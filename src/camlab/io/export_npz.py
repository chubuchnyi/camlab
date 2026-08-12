"""The camera, written out. One shape, always — the zoom is not optional and neither is anything
else here.

pitch3d's existing transfer file holds `focal` as a **scalar**: one intrinsic for a whole clip.
Measured, what collapsing to that costs:

| clip | zoom | per-frame focal | one focal | frames under 20 px |
|---|---|---|---|---|
| `fan` | **1.59×** | **1.69 px** | 4.88 px | 30/30 → 25/30 |
| `broadcast` | 1.03× | 2.75 px | 4.71 px | 15/15 → 12/15 |
| `g15449383` | 1.01× | 2.92 px | 2.96 px | 10/10 → 10/10 |

Sixty-five per cent of the accuracy on the clip that zooms.

The first version of this file tried to keep both contracts: write `focal_px` always, and the old
scalar `focal` too when the focal happened to be constant, so an old reader would raise `KeyError`
on a zoom rather than silently collapse it. That was the right instinct against a silent loss and
the wrong shape — a key that is sometimes present is a branch every reader has to know about, and
this project has spent enough sessions on "why does that file have a field this one does not".

**pitch3d can be changed, so it is changed.** One schema, every key present on every camera, no
conditional compatibility. What a reader needs to know is in `schema` and `SCHEMA_2_KEYS`.

`world_to_image` is recomputed from `(focal, rvec, centre, cx, cy)` rather than copied, so the file
cannot carry a homography that disagrees with the parameters beside it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

#: Bumped from 1, which held `focal` as a scalar and had no principal point. Nothing reads 1 any
#: more; a reader that finds it should say so rather than guess.
SCHEMA = 2

#: Every key, on every camera, always. A reader can rely on all of them existing.
SCHEMA_2_KEYS = (
    "schema",           # int, 2
    "clip_id", "model",
    "width", "height", "cx", "cy",
    "frames",           # (N,) int
    "focal_px",         # (N,) float — per frame, always, whether or not it varies
    "rvecs",            # (N, 3) Rodrigues, world -> camera
    "position",         # (N, 3) the optical centre, per frame
    "world_to_image",   # (N, 3, 3) on the pitch plane Z=0
    "zoom_ratio",       # max focal / min focal, so "does this clip zoom" needs no arithmetic
    "centre_spread_m",  # how far the position wanders; 0.0 means one shared centre
)


def export_npz(camera: dict, path: Path, *, clip_id: str | None = None) -> dict:
    """Write `camera` — a parsed camlab camera file — to `path`. Returns a summary of what went in.

    Refuses a non-positive focal for the same reason `write_camera` does: that is not a camera, and
    a transfer file is the last place to let one through.
    """
    from camlab.measure.residual import world_to_image

    frames = np.asarray(camera["frames"], dtype=int)
    focal = np.asarray(camera["focal_px"], dtype=float)
    rvecs = np.asarray(camera["rotation"], dtype=float)
    pos = np.asarray(camera["position"], dtype=float)
    width, height = int(camera["width"]), int(camera["height"])
    cx = float(camera.get("cx", width / 2.0))
    cy = float(camera.get("cy", height / 2.0))

    if not (focal > 0).all():
        raise ValueError(
            f"{path.name}: {int((focal <= 0).sum())} frame(s) have a non-positive focal. "
            "That is not a camera, and a transfer file is the last place to let one through."
        )
    n = len(frames)
    for name, arr, shape in (("focal_px", focal, (n,)), ("rvecs", rvecs, (n, 3)),
                             ("position", pos, (n, 3))):
        if arr.shape != shape:
            raise ValueError(f"{path.name}: {name} is {arr.shape}, expected {shape}")

    w2i = np.stack([world_to_image(focal[i], rvecs[i], pos[i], width, height, cx=cx, cy=cy)
                    for i in range(n)])

    out = {
        "schema": np.array(SCHEMA),
        "clip_id": np.array(clip_id or camera.get("clip_id", "")),
        "model": np.array(camera.get("model", "")),
        "width": np.array(width),
        "height": np.array(height),
        "cx": np.array(cx),
        "cy": np.array(cy),
        "frames": frames,
        "focal_px": focal,
        "rvecs": rvecs,
        "position": pos,
        "world_to_image": w2i,
        "zoom_ratio": np.array(float(focal.max() / focal.min())),
        "centre_spread_m": np.array(
            float(np.linalg.norm(pos - pos.mean(axis=0), axis=1).max())),
    }
    assert set(out) == set(SCHEMA_2_KEYS), "every schema-2 key, on every camera, always"
    np.savez(path, **out)
    return {
        "path": str(path), "frames": n,
        "zoom_ratio": round(float(out["zoom_ratio"]), 4),
        "centre_spread_m": round(float(out["centre_spread_m"]), 3),
        "focal_px": (round(float(focal.min()), 1), round(float(focal.max()), 1)),
    }


def read_npz(path: Path) -> dict:
    """Read one back, refusing anything that is not schema 2 rather than guessing at it."""
    blob = np.load(path, allow_pickle=False)
    schema = int(blob["schema"]) if "schema" in blob.files else 1
    if schema != SCHEMA:
        raise ValueError(
            f"{path.name} is schema {schema}, this reads {SCHEMA}. Schema 1 held `focal` as a "
            "single scalar for a whole clip, which cannot represent a zoom — on the fan clip that "
            "is a 1.59x range and costs 65% of the accuracy. Re-export it."
        )
    missing = [k for k in SCHEMA_2_KEYS if k not in blob.files]
    if missing:
        raise ValueError(f"{path.name}: schema 2 but missing {missing}")
    return {k: blob[k] for k in SCHEMA_2_KEYS}


#: Exactly the five keys pitch3d's reader takes, and exactly those: its golden test asserts
#: `set(blob.files) == {"focal", "centre", "rvecs", "frames", "world_to_image"}`, so an extra key
#: fails it. `focal` is a scalar and `centre` is one point for the whole clip.
SCHEMA_1_KEYS = ("focal", "centre", "rvecs", "frames", "world_to_image")


def export_npz_legacy(camera: dict, path: Path) -> dict:
    """The schema-1 shape, for reading by pitch3d as it stands today.

    Written because "pitch3d is being changed rather than accommodated" was a decision nobody has
    carried out yet, so schema 2 is unreadable downstream and the only test against the actual goal
    — does a novel view look right — has never been run.

    **It loses the zoom, and how much that costs depends entirely on the clip.** Collapsing to the
    median focal, measured:

    | clip | zoom | per-frame focal | one focal | frames under 20 px |
    |---|---|---|---|---|
    | `fan` | 1.59× | 1.65 px | **4.56 px** | 12/12 → 10/12 |
    | `broadcast` | 1.03× | 2.29 px | 4.16 px | 6/6 → 5/6 |
    | `CRO_MOR_194948` | 1.07× | 4.04 px | **4.69 px** | 12/12 → 12/12 |

    So this is honest on `CRO_MOR_194948` and dishonest on `fan`. The summary returned says which,
    and a caller that quotes the per-frame number while shipping this file is misreporting by 3x.

    The centre costs nothing: `solve_shared_centre` already collapses the camera to one point and
    the paint prefers it — measured spread 0.000 m on all three clips.
    """
    import numpy as np

    frames = np.asarray(camera["frames"], dtype=int)
    focal = np.asarray(camera["focal_px"], dtype=float)
    rvecs = np.asarray(camera["rotation"], dtype=float)
    pos = np.asarray(camera["position"], dtype=float)
    width, height = int(camera["width"]), int(camera["height"])
    cx = float(camera.get("cx", width / 2.0))
    cy = float(camera.get("cy", height / 2.0))

    live = focal > 0
    if not live.any():
        raise ValueError(f"{path.name}: no frame has a focal; that is not a camera")
    one_focal = float(np.median(focal[live]))
    one_centre = np.median(pos[live], axis=0)
    spread = float(np.linalg.norm(pos[live] - one_centre, axis=1).max())

    from camlab.measure.residual import world_to_image

    # Rebuilt from the COLLAPSED focal and centre, not copied from the per-frame solve: a
    # `world_to_image` that disagrees with the `focal` beside it is the shape of defect this file
    # already exists to avoid.
    w2i = np.stack([world_to_image(one_focal, rvecs[i], one_centre, width, height, cx=cx, cy=cy)
                    for i in range(len(frames))])

    out = {"focal": np.array(one_focal), "centre": one_centre, "rvecs": rvecs,
           "frames": frames, "world_to_image": w2i}
    assert set(out) == set(SCHEMA_1_KEYS), "pitch3d asserts this key set exactly"
    np.savez(path, **out)
    return {"path": str(path), "frames": int(len(frames)), "focal": round(one_focal, 1),
            "zoom_ratio": round(float(focal[live].max() / focal[live].min()), 4),
            "centre_spread_m": round(spread, 3)}
