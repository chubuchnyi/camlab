"""One camera position for the whole clip, found by sliding along the line the solve strung itself
out on. Writes a camera that can actually be rendered from.

A human looked at the 3D view and said the camera moves along a visible line. It does, and that
line is the diagnosis: 99 % of the position variance in the anchor-free solve lies along a single
direction, 108 m of it, and that direction sits 13-25 degrees off the line of sight to the pitch
centre. Move back and zoom in and the image barely changes — the focal/distance degeneracy on a
plane, made visible. It is why every frame's overlay could be nearly exact while the trajectory
jumped 10 m between neighbours and was useless for a render.

The fix follows from the picture. The camera is ONE point, so:

    1. fit the line the positions lie on (first principal direction),
    2. slide along it, refitting every frame's focal and rotation with the centre HELD,
    3. keep the point where the paint error is lowest.

That is a one-dimensional search and the curve has a real minimum — on the fan clip, 1.9 px at the
optimum against 4.3 px three metres either side, so the position is pinned to about a metre. The
degeneracy is not flat; it only looked flat because nobody had searched along it.

Run:  .venv/bin/python scripts/solve_shared_centre.py [clip] [--from camera_lm.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402

from camlab.camera_file import write_camera  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402


def fit_line(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """`(centroid, unit direction, fraction of variance along it)`."""
    m = positions.mean(axis=0)
    _u, s, vt = np.linalg.svd(positions - m, full_matrices=False)
    return m, vt[0], float(s[0] ** 2 / (s ** 2).sum())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--from", dest="src", default="camera_lm.json")
    ap.add_argument("--out", default="camera_fixed.json")
    ap.add_argument("--span", type=float, default=6.0, help="metres either way along the line")
    ap.add_argument("--step", type=float, default=0.75)
    ap.add_argument("--probe", type=int, default=6, help="score every Nth frame while searching")
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    src = json.loads((info.dir / args.src).read_text())
    cx, cy = float(src["cx"]), float(src["cy"])
    n = len(src["frames"])
    pos = np.asarray(src["position"], float)

    centroid, direction, share = fit_line(pos)
    off = pos - centroid
    scatter = np.linalg.norm(off - np.outer(off @ direction, direction), axis=1)
    print(f"== {args.clip}: {n} frames from {args.src}")
    print(f"   the positions lie on a line: {share:.1%} of their variance along "
          f"{np.round(direction, 3)}, spread {float(np.ptp(off @ direction)):.1f} m, "
          f"scatter about it {np.median(scatter):.2f} m")

    seg_cache: dict[int, np.ndarray] = {}

    def segs(i):
        if i not in seg_cache:
            d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
            seg_cache[i] = detect_segments(d, s, method="hough")
        return seg_cache[i]

    def solve_at(centre, frames):
        out = {}
        for i in frames:
            r = refit_frame_lm(segs(i), src["focal_px"][i], np.asarray(src["rotation"][i], float),
                               centre, info.width, info.height, cx, cy, free_position=False)
            out[i] = (r.focal_px, r.rotation, r.position)
        return out

    def score(sol):
        w = [frame_residual(info.frame_path(i), f, rv, c, frame=i, cx=cx, cy=cy).worst_line_px
             for i, (f, rv, c) in sol.items()]
        return float(np.nanmedian(w)), int(np.nansum(np.asarray(w) < 20.0)), len(w)

    probe = list(range(0, n, args.probe))
    print(f"\n   sliding along it, scoring {len(probe)} frames at each stop:")
    print(f'   {"t (m)":>7} {"median":>8} {"under 20":>10}')
    best = None
    for t in np.arange(-args.span, args.span + 1e-9, args.step):
        med, u20, tot = score(solve_at(centroid + t * direction, probe))
        print(f"   {t:7.2f} {med:8.2f} {u20:7d}/{tot}")
        if best is None or med < best[0]:
            best = (med, float(t))
    med, t_best = best
    centre = centroid + t_best * direction
    print(f"\n   best at t = {t_best:+.2f} m -> {np.round(centre, 2)}, {med:.2f} px on the probe")

    sol = solve_at(centre, range(n))
    focal = np.array([sol[i][0] for i in range(n)])
    rot = np.array([sol[i][1] for i in range(n)])
    posn = np.tile(centre, (n, 1))

    b = np.array([frame_residual(info.frame_path(i), src["focal_px"][i], src["rotation"][i],
                                 src["position"][i], frame=i, cx=cx, cy=cy).worst_line_px
                  for i in range(n)])
    a = np.array([frame_residual(info.frame_path(i), focal[i], rot[i], centre,
                                 frame=i, cx=cx, cy=cy).worst_line_px for i in range(n)])

    out = write_camera(
        info.dir / args.out, model=f"{src['model']}+shared_centre", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(src["frames"], int),
        focal_px=focal, position=posn, rotation=rot, cx=cx, cy=cy,
        degenerate=src.get("degenerate", [False] * n),
        shared_centre=centre.tolist(), fitted_from=args.src,
        line_direction=direction.tolist(), line_variance_share=share,
        notes=("ONE optical centre for the whole clip, per-frame focal and rotation. The centre "
               "was found by sliding along the line the free-position solve strung itself out on "
               "— the focal/distance degeneracy — and keeping the point where the paint agrees "
               "best. Unlike its parent this trajectory is renderable: the camera does not move."),
    )
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(b):6.2f} px  ->  {np.nanmedian(a):6.2f} px")
    print(f"   frames under 20 px  {int(np.nansum(b < 20)):6d}     ->  {int(np.nansum(a < 20)):6d}"
          f"   of {n}")
    print(f"   camera movement     {np.linalg.norm(np.diff(pos, axis=0), axis=1).max():6.2f} m"
          f"  ->  0.00 m between frames")


if __name__ == "__main__":
    main()
