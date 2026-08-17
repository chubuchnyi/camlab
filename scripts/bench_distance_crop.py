"""Cropping the distance transform to the paint's own bounding box: refuted, with the numbers.

`cv2.distanceTransform` is ~11 ms of the 32.4 ms paint stage — a third of it, and the largest
single primitive left in a causal frame. It runs over the whole frame although nothing outside the
playing surface is ever read: the residual walks the normal from samples it has already restricted
to the surface, `detect_segments` masks to it, and `centreline_pixels` takes the transform's zeros,
which are the spine and are inside it by construction. Cropping to the spine's bounding box with a
margin larger than the residual's 40 px search limit is provably the same answer wherever anyone
looks.

**And it is not worth having.** The bounding box is 55–100 % of the frame, because a football
camera points at a football pitch and the pitch fills the picture:

    clip                spine bbox   distT full   distT cropped
    broadcast              65.5 %      9.68 ms       6.87 ms     1.41x
    g11710897              54.8        9.40          5.65        1.66x
    CRO_MOR_194948         87.8        9.61          9.32        1.03x
    ENG_FRA_232015         88.9        9.52          9.63        0.99x   a wash
    fan                   100.0        3.02          3.24        0.93x   SLOWER
    stadium_a             100.0        2.73          2.86        0.95x   SLOWER

Three clips of six gain nothing or lose, because the fill and the copy back cost more than the
pixels saved. This is the sparse-trick rule one more time: **whether a restriction wins is a
property of the data, not of the technique**, and the data here says the pitch fills the frame.

It would also cost the strongest check this work has. `check_paint_equivalence.py` compares the
distance map bit for bit against the shipped implementation; a cropped map is exact only INSIDE the
crop and must differ outside it, so shipping this would mean weakening that comparison to "exact
where we believe it is read" — which is the claim under test. A conditional 1.4x on a third of the
clips is not worth trading a total check for a circular one.

Kept as a measurement rather than an option. It is worth re-running on footage this repo does not
have: a camera zoomed into one corner, or a wide overhead where the pitch is a small part of the
frame, would move the bounding box and could move the answer.

    python scripts/bench_distance_crop.py broadcast fan g11710897 CRO_MOR_194948
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"

#: How far past the paint the cropped transform would have to stay exact. It must exceed
#: `frame_residual`'s `match_px` default of 40, which is how far `_across_on_normal` walks from a
#: sample that is itself already restricted to the playing surface.
MARGIN_PX = 48


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    from camlab.measure.paint import RIDGE_CONTRAST, RIDGE_MIN_V, ridge_map, thin

    load = os.getloadavg()
    print(f"load {load[0]:.2f} {load[1]:.2f}   margin {MARGIN_PX} px")
    if load[0] > 1.0:
        print("  *** the machine is busy; the times are upper bounds ***")
    print(f"{'clip':<24}{'spine bbox':>12}{'distT full':>12}{'cropped':>10}{'':>8}{'same?':>8}")

    for clip in args.clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        if not frames:
            continue
        step = max(1, len(frames) // args.frames)
        frac, full, crop, agree = [], [], [], True
        for path in frames[::step][:args.frames]:
            bgr = cv2.imread(str(path))
            h, w = bgr.shape[:2]
            ridge, val, surface = ridge_map(bgr)
            spine = thin((ridge >= RIDGE_CONTRAST) & (val >= RIDGE_MIN_V) & (surface > 0))
            ys, xs = np.nonzero(spine)
            if not len(ys):
                continue
            y0, y1 = max(0, ys.min() - MARGIN_PX), min(h, ys.max() + 1 + MARGIN_PX)
            x0, x1 = max(0, xs.min() - MARGIN_PX), min(w, xs.max() + 1 + MARGIN_PX)
            frac.append((y1 - y0) * (x1 - x0) / (h * w))

            inv = (~spine).astype(np.uint8)
            best = 1e9
            ref = None
            for _ in range(args.repeat):
                t = time.perf_counter()
                ref = cv2.distanceTransform(inv, cv2.DIST_L2, 5)
                best = min(best, time.perf_counter() - t)
            full.append(best * 1e3)

            sub = np.ascontiguousarray(inv[y0:y1, x0:x1])
            best, got = 1e9, None
            for _ in range(args.repeat):
                t = time.perf_counter()
                d = cv2.distanceTransform(sub, cv2.DIST_L2, 5)
                got = np.full(spine.shape, float(np.hypot(h, w)), np.float32)
                got[y0:y1, x0:x1] = d
                best = min(best, time.perf_counter() - t)
            crop.append(best * 1e3)
            # Exact where anyone reads it — inside the crop — and deliberately not outside, which
            # is the whole reason this cannot ship without weakening the equivalence check.
            agree &= np.array_equal(ref[y0:y1, x0:x1], got[y0:y1, x0:x1])
            agree &= np.array_equal(np.argwhere(ref == 0), np.argwhere(got == 0))

        if frac:
            f, c = float(np.mean(full)), float(np.mean(crop))
            flag = "" if f / c > 1.10 else ("  a wash" if f / c > 0.98 else "  SLOWER")
            print(f"{clip:<24}{np.mean(frac):>11.1%}{f:>12.2f}{c:>10.2f}{f / c:>7.2f}x"
                  f"{'yes' if agree else 'NO':>8}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
