"""What stands between each clip and a solved camera. One row per clip, measured.

The chain works end to end on two clips and both were handed a starting camera by pitch3d. Every
other clip has none, so before anything is built the question is which stage each one actually
fails at — the paint, the line finder, the bootstrap, or nothing.

Four things per clip, cheapest first, and each is a different fix:

    paint      fraction of pixels the marking mask keeps. Far too many and the mask has given up
               and flagged the whole pitch — the known daylight failure, where turf and paint are
               the same brightness and the threshold has nothing to separate.
    lines      merged markings the finder returns per frame. Under about four and correspondence
               cannot start, whatever the camera.
    bootstrap  best of N random cameras handed to the least-squares refit, on one frame. This is
               the missing piece: `camlab solve` reads homographies out of a pitch3d scene.json and
               there is no such file for a new clip.
    coverage   samples that bootstrap scored. THE NUMBER TO READ FIRST. A camera that has run away
               projects almost everything off the surface and posts a flattering error on the
               handful that survive, so an error without its count says nothing at all.

Run:  .venv/bin/python scripts/survey_clips.py [--tries 4000]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402

from camlab.core.angles import rodrigues_from_matrix, rotation_from_angles  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo, list_runs  # noqa: E402
from camlab.solve.refit import objective, refit_frame_lm  # noqa: E402


def look_at(pos, target):
    f = np.asarray(target, float) - np.asarray(pos, float)
    f /= np.linalg.norm(f)
    return rodrigues_from_matrix(rotation_from_angles(
        float(np.degrees(np.arctan2(f[1], f[0]))), float(np.degrees(np.arcsin(f[2]))), 0.0))


def bootstrap(info, n, segs, tries, rng):
    """Best of `tries` random cameras, then one least-squares refit. No seed, no human."""
    cx, cy = info.principal_point
    best = None
    for _ in range(tries):
        side = rng.choice([-1, 1])
        pos = np.array([rng.uniform(-45, 45), side * rng.uniform(45, 110), rng.uniform(4, 40)])
        tgt = np.array([rng.uniform(-52, 52), rng.uniform(-34, 34), 0.0])
        f = rng.uniform(600, 12000)
        rv = look_at(pos, tgt)
        o = objective(segs, f, rv, pos, info.width, info.height, cx, cy)
        if best is None or o < best[0]:
            best = (o, f, rv, pos)
    _o, f, rv, pos = best
    r = refit_frame_lm(segs, f, rv, pos, info.width, info.height, cx, cy)
    res = frame_residual(info.frame_path(n), r.focal_px, r.rotation, r.position,
                         frame=n, cx=cx, cy=cy)
    spot = max((v[2] for v in res.per_line.values() if v[1] >= 8), default=float("nan"))
    return res.worst_line_px, float(spot), res.n, r.focal_px


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tries", type=int, default=4000)
    ap.add_argument("--frames", type=int, default=3)
    args = ap.parse_args()
    rng = np.random.default_rng(0)

    print(f"{'clip':28s} {'size':>11} {'paint%':>7} {'lines':>6} "
          f"{'boot line':>10} {'spot':>7} {'samples':>8}  verdict")
    print("-" * 100)
    for cid in sorted(list_runs()):
        info = ClipInfo.load(cid)
        probe = list(range(0, min(args.frames * 4, info.n_frames), 4))[:args.frames]
        paint_frac, nlines = [], []
        for i in probe:
            bgr = cv2.imread(str(info.frame_path(i)))
            dist, surface = paint_masks(bgr)
            # The mask itself, not the distance transform: `dist` is a ridge/distance map and
            # counting its non-zeros measures the frame, not the paint. That mistake was made
            # twice before this line was written.
            mask = (dist > 0) & (surface > 0) & (dist < dist.max())
            paint_frac.append(100.0 * float(mask.sum()) / mask.size)
            nlines.append(len(detect_segments(dist, surface, method="hough")))
        i = probe[len(probe) // 2]
        dist, surface = paint_masks(cv2.imread(str(info.frame_path(i))))
        segs = detect_segments(dist, surface, method="hough")
        if len(segs) < 4:
            line, spot, ns, _f = float("nan"), float("nan"), 0, 0
        else:
            line, spot, ns, _f = bootstrap(info, i, segs, args.tries, rng)

        med_lines = float(np.median(nlines))
        if med_lines < 4:
            verdict = "the line finder returns too little to correspond"
        elif not np.isfinite(line):
            verdict = "bootstrap found no camera at all"
        elif ns < 120:
            verdict = f"UNVERIFIED — {ns} samples is too few to believe the error"
        elif line < 20:
            verdict = "bootstrap plausible, needs an eye"
        else:
            verdict = "bootstrap did not converge"
        print(f"{cid[:27]:28s} {info.width}x{info.height:<5} {np.mean(paint_frac):6.1f}% "
              f"{med_lines:6.1f} {line:10.1f} {spot:7.1f} {ns:8d}  {verdict}")


if __name__ == "__main__":
    main()
