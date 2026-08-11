"""Find the frames the solve lost and re-seed each from its nearest good neighbour, until a round
changes nothing.

A chain seeds every frame from the previous one whether or not that one converged, so one bad frame
poisons its successors — which is why the anchor-free solve reaches 2.4 px median and still leaves
about fifty frames of a hundred and twenty above 20 px.

This is what a human did by hand: they fixed 51, 66-77, 86 and 87, every one a frame whose
NEIGHBOURS were already good, and every fix landed at 1.6-3.5 px. Nothing in that needed a person.
A lost frame announces itself in two ways that cost nothing to check:

    its paint error is high, or
    its scored-sample count has collapsed — frames 76, 77 and 86 had 25, 25 and 69 against a
    normal ~160, which is a camera pointing somewhere with almost no pitch in it

The neighbour's camera is then carried across the gap by the same image→image homography the chain
uses, measured directly for that jump rather than composed frame by frame, and refit. It is kept
only if the PAINT agrees better — the metric the optimiser does not see.

Run:  .venv/bin/python scripts/solve_selfheal.py [clip] [--from camera_nohand.json]
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
from camlab.measure.pixel_motion import measure_pairs  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--from", dest="src", default="camera_nohand.json")
    ap.add_argument("--out", default="camera_healed.json")
    ap.add_argument("--bad-px", type=float, default=20.0)
    ap.add_argument("--min-coverage", type=float, default=0.5,
                    help="a frame scoring under this fraction of the clip's median sample count "
                         "is lost regardless of what its error reads")
    ap.add_argument("--rounds", type=int, default=6)
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    src = json.loads((info.dir / args.src).read_text())
    cx, cy = float(src["cx"]), float(src["cy"])
    n = len(src["frames"])

    focal = np.array(src["focal_px"], float)
    rot = np.array(src["rotation"], float)
    pos = np.array(src["position"], float)
    healed = np.zeros(n, int)

    seg_cache: dict[int, np.ndarray] = {}

    def segs(i):
        if i not in seg_cache:
            d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
            seg_cache[i] = detect_segments(d, s, method="hough")
        return seg_cache[i]

    def score(i, f=None, rv=None, c=None):
        r = frame_residual(info.frame_path(i), focal[i] if f is None else f,
                           rot[i] if rv is None else rv, pos[i] if c is None else c,
                           frame=i, cx=cx, cy=cy)
        return r.worst_line_px, r.n

    w = np.empty(n)
    ns = np.empty(n, int)
    for i in range(n):
        w[i], ns[i] = score(i)
    w0 = w.copy()

    def bad_set():
        floor = args.min_coverage * float(np.median(ns))
        return {i for i in range(n)
                if not (w[i] < args.bad_px) or ns[i] < floor}

    print(f"== {args.clip}: {n} frames from {args.src}")
    print(f"   start: median {np.nanmedian(w):.2f} px, {int(np.nansum(w < args.bad_px))} under "
          f"{args.bad_px:.0f} px, median coverage {int(np.median(ns))} samples")

    for rnd in range(1, args.rounds + 1):
        bad = sorted(bad_set())
        good = [i for i in range(n) if i not in bad]
        if not bad:
            print(f"   round {rnd}: nothing left to fix")
            break
        if not good:
            print(f"   round {rnd}: every frame is bad — nothing to re-seed FROM. Stopping.")
            break

        fixed = 0
        for i in bad:
            # Nearest good frame. Ties go to the earlier one, which is arbitrary and harmless.
            j = min(good, key=lambda g: (abs(g - i), g))
            gap = abs(i - j)
            # One pair, measured for exactly this jump. Composing `gap` consecutive homographies
            # would accumulate the very error being repaired.
            pairs = measure_pairs({min(i, j): info.frame_path(min(i, j)),
                                   max(i, j): info.frame_path(max(i, j))}, gaps=(gap,))
            if not pairs:
                continue
            h = pairs[0].h if j < i else np.linalg.inv(pairs[0].h)
            moved = carry(focal[j], rot[j], pos[j], h, cx, cy)
            if moved is None:
                continue
            r = refit_frame_lm(segs(i), moved.focal_px, moved.rotation, moved.position,
                               info.width, info.height, cx, cy)
            nw, nn = score(i, r.focal_px, r.rotation, r.position)
            # The PAINT decides, not the objective the refit just minimised. A camera that talked
            # its own objective down while drifting off the paint is the failure mode this whole
            # repo keeps rediscovering.
            if np.isfinite(nw) and (not np.isfinite(w[i]) or nw < w[i]) and nn >= 0.9 * ns[i]:
                focal[i], rot[i], pos[i] = r.focal_px, r.rotation, r.position
                w[i], ns[i] = nw, nn
                healed[i] = gap
                fixed += 1

        print(f"   round {rnd}: {len(bad)} bad, fixed {fixed}, "
              f"median now {np.nanmedian(w):.2f} px, {int(np.nansum(w < args.bad_px))} under "
              f"{args.bad_px:.0f} px")
        if fixed == 0:
            print("   a round changed nothing — stopping rather than spinning")
            break

    out = write_camera(
        info.dir / args.out, model=f"{src['model']}+selfheal", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(src["frames"], int),
        focal_px=focal, position=pos, rotation=rot, cx=cx, cy=cy,
        degenerate=src.get("degenerate", [False] * n),
        healed_from=args.src, healed_gap=healed.tolist(),
        notes=("Frames the solve lost, re-seeded from their nearest surviving neighbour through a "
               "directly measured image-to-image homography. `healed_gap` is how far each frame "
               "had to reach for a good one — 0 means it was never in trouble."),
    )
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(w0):6.2f} px  ->  {np.nanmedian(w):6.2f} px")
    print(f"   frames under {args.bad_px:.0f} px  {int(np.nansum(w0 < args.bad_px)):6d}     ->  "
          f"{int(np.nansum(w < args.bad_px)):6d}   of {n}")
    print(f"   frames re-seeded    {int((healed > 0).sum())}, reaching up to "
          f"{int(healed.max())} frames away")


if __name__ == "__main__":
    main()
