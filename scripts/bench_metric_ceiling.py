"""How much of the real error the headline numbers cannot represent.

A human put a ruler on the overlay and read distances larger than `worst line` on every frame he
tried. That is not a disagreement about a hard case — it is structural, and this measures the size
of it.

`residual.worst_line_px` is `max over markings of (that marking's MEDIAN sample distance)`, where a
sample only counts if paint was found within `match_px = 40`. Three separate cuts, all of which
remove large errors and only large errors:

    1. no scored distance can exceed match_px, ever — 40 px is a ceiling, not a bound
    2. samples with no paint within it are dropped from the distance array entirely
    3. a marking is summarised by its MEDIAN, so a line half-right and half-wrong reads small

Run:  .venv/bin/python scripts/bench_metric_ceiling.py [clip] [camera.json]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.measure.paint import centreline_pixels, paint_masks  # noqa: E402
from camlab.measure.residual import (  # noqa: E402
    _marking_owner,
    _marking_samples,
    frame_residual,
    world_to_image,
)
from camlab.runs import ClipInfo  # noqa: E402


def per_line_stats(frame_path: Path, focal, rvec, centre, cx, cy, match_px: float) -> dict:
    """`{marking: (median, max, n)}` at a given match radius.

    The repo's own functions throughout — only the aggregation differs, since the aggregation is
    what is under suspicion.
    """
    import cv2
    from scipy.spatial import cKDTree

    bgr = cv2.imread(str(frame_path))
    height, width = bgr.shape[:2]
    _dist, surface = paint_masks(bgr)
    spine = centreline_pixels(_dist)
    if not len(spine):
        return {}
    tree = cKDTree(spine)

    xy1 = _marking_samples()
    owner = _marking_owner()
    h = world_to_image(focal, rvec, centre, width, height, cx=cx, cy=cy)
    q = xy1 @ h.T
    w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
    uv = q[:, :2] / w[:, None]

    inside = ((uv[:, 0] > 1) & (uv[:, 0] < width - 2)
              & (uv[:, 1] > 1) & (uv[:, 1] < height - 2))
    idx = np.flatnonzero(inside)
    if not len(idx):
        return {}
    sub = uv[idx]
    on = surface[np.rint(sub[:, 1]).astype(int), np.rint(sub[:, 0]).astype(int)] > 0
    idx, sub = idx[on], sub[on]
    if not len(idx):
        return {}

    d, _ = tree.query(sub, distance_upper_bound=match_px)
    hit = np.isfinite(d)
    d, own = d[hit], owner[idx[hit]]
    out = {}
    for k in np.unique(own):
        dk = d[own == k]
        if dk.size >= 8:
            out[int(k)] = (float(np.median(dk)), float(dk.max()), int(dk.size))
    return out


def main() -> None:
    import json

    clip_id = sys.argv[1] if len(sys.argv) > 1 else "fan"
    which = sys.argv[2] if len(sys.argv) > 2 else "camera_auto.json"
    info = ClipInfo.load(clip_id)
    cam = json.loads((info.dir / which).read_text())
    # Each camera's OWN principal point, not the clip's true optical axis. Four of the five solves
    # in runs/fan were fitted at the image centre and only `camera_axis` at the real axis 638 px
    # away; scoring them all at the real one measures a camera nobody solved. The first run of this
    # probe did exactly that and ranked `camera_axis` worst on its own K.
    cx = float(cam.get("cx", info.principal_point[0]))
    cy = float(cam.get("cy", info.principal_point[1]))

    stride = int(sys.argv[3]) if len(sys.argv) > 3 else max(1, len(cam["frames"]) // 12)
    frames = list(range(0, len(cam["frames"]), stride))
    print(f"{clip_id} / {which}   principal point ({cx:.0f}, {cy:.0f})\n")
    # Column 2 was the contrast that proved the ceiling; since the fix it is a CONTROL — it is
    # computed independently here, and it agreeing with column 1 is what says the fix landed.
    print("        reported   |  independent, @400  |  worst SAMPLE      |  samples with no")
    print("frame   worst line |  worst line         |  on that marking   |  paint within 40px")
    print("-" * 78)

    rows = []
    for n in frames:
        f, rv, c = cam["focal_px"][n], cam["rotation"][n], cam["position"][n]
        r = frame_residual(info.frame_path(n), f, rv, c, frame=n, cx=cx, cy=cy)
        wide = per_line_stats(info.frame_path(n), f, rv, c, cx, cy, match_px=400.0)
        if not wide:
            continue
        w_med = max(v[0] for v in wide.values())
        w_max = max(v[1] for v in wide.values())
        # `n_unmatched` is a SUBSET of `n` now that far samples are charged rather than dropped.
        # Adding the two together was right under the old contract and double-counts under this one.
        frac = r.n_unmatched / max(r.n, 1)
        rows.append((r.worst_line_px, w_med, w_max, frac))
        print(f"{n:5d}   {r.worst_line_px:8.1f}   |{w_med:14.1f}      |{w_max:13.1f}      "
              f"|{frac:12.0%}")

    a = np.array(rows, float)
    print("-" * 78)
    print(f"median  {np.nanmedian(a[:, 0]):8.1f}   |{np.nanmedian(a[:, 1]):14.1f}      "
          f"|{np.nanmedian(a[:, 2]):13.1f}      |{np.nanmedian(a[:, 3]):12.0%}")
    print(f"\nunderstatement, reported vs uncapped worst line: "
          f"{np.nanmedian(a[:, 1]) / np.nanmedian(a[:, 0]):.1f}x")
    print(f"understatement, reported vs worst sample:         "
          f"{np.nanmedian(a[:, 2]) / np.nanmedian(a[:, 0]):.1f}x")


if __name__ == "__main__":
    main()
