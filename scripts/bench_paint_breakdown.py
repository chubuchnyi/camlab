"""Where the paint stage's milliseconds actually are, split to the primitive.

The repo's performance day (`docs/findings/making-it-fast-2026-08-13.md`) profiled `paint_masks`
to two names — `ridge_map` 42 % and `thin` 34 % — and concluded the remaining cost was "~60
unavoidable passes over the frame plus two distance transforms". Neither `_turf` nor `_surface`
appears in that account at all, and `_surface` runs two rectangular closes at 45x45 and 61x61.
This splits the stage to every primitive so the claim can be checked rather than repeated.

**Every stage here calls the shipped function.** The first version of this script carried its own
copy of `ridge_map`'s loop, and so went on reporting the old cost of a function that had been
rewritten — the same failure mode as a stale run directory, in a measuring instrument. The ridge
loop is reported as `ridge_map` minus the three things it calls before the loop, which is
arithmetic on measurements of real code rather than a second copy of it.

Interleaved across repeats so background load lands on every stage equally, and reported as the
MINIMUM over repeats rather than the mean: the minimum is the closest thing to the machine's real
cost, and a mean measures whatever else the laptop was doing. The load average is printed because
a number taken on a busy machine is not comparable with one taken on a quiet one, and this repo
has no habit yet of recording that.

    python scripts/bench_paint_breakdown.py fan broadcast --frames 5 --repeat 5
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camlab.measure import paint as P  # noqa: E402

RUNS = Path(__file__).resolve().parents[1] / "runs"


def frame_paths(clip: str, n: int) -> list[Path]:
    frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
    if not frames:
        raise SystemExit(f"no frames for {clip}")
    step = max(1, len(frames) // n)
    return frames[::step][:n]


def stages(bgr: np.ndarray) -> dict[str, float]:
    """One frame through the shipped paint stage, timing each shipped function."""
    out: dict[str, float] = {}

    def timed(name, fn):
        t = time.perf_counter()
        got = fn()
        out[name] = time.perf_counter() - t
        return got

    hsv = timed("cvtColor", lambda: cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV))
    turf = timed("_turf", lambda: P._turf(hsv))
    timed("_surface", lambda: P._surface(turf))
    ridge, val, surface = timed("ridge_map", lambda: P.ridge_map(bgr))
    mask = timed("threshold",
                 lambda: (ridge >= P.RIDGE_CONTRAST) & (val >= P.RIDGE_MIN_V) & (surface > 0))
    spine = timed("thin", lambda: P.thin(mask))
    timed("distanceTransform",
          lambda: cv2.distanceTransform((~spine).astype(np.uint8), cv2.DIST_L2, 5))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--frames", type=int, default=5)
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--threads", type=int, default=None,
                    help="cv2.setNumThreads; default leaves OpenCV alone")
    args = ap.parse_args()

    if args.threads is not None:
        cv2.setNumThreads(args.threads)
    load = os.getloadavg()
    print(f"opencv threads: {cv2.getNumThreads()}   ridge scales: {P.RIDGE_SCALES}   "
          f"load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; these numbers are an upper bound, not a measurement ***")

    for clip in args.clips:
        paths = frame_paths(clip, args.frames)
        imgs = [cv2.imread(str(p)) for p in paths]
        h, w = imgs[0].shape[:2]
        mpx = h * w / 1e6

        best: dict[str, float] = {}
        whole = 1e9
        for _ in range(args.repeat):
            for img in imgs:
                for k, v in stages(img).items():
                    best[k] = min(best.get(k, 1e9), v)
                t = time.perf_counter()
                P.paint_masks(img)
                whole = min(whole, time.perf_counter() - t)

        # `ridge_map` does cvtColor, _turf and _surface before its loop; the loop is what is left.
        best["ridge loop"] = (best["ridge_map"] - best["cvtColor"]
                              - best["_turf"] - best["_surface"])
        del best["ridge_map"]

        total = sum(best.values())
        print(f"\n{clip}  {w}x{h} ({mpx:.2f} Mpx)  best-of-{args.repeat} over {len(imgs)} frames")
        print(f"{'stage':<20}{'ms':>9}{'%':>8}{'ms/Mpx':>10}")
        for k, v in sorted(best.items(), key=lambda kv: -kv[1]):
            print(f"{k:<20}{v * 1e3:>9.2f}{100 * v / total:>7.1f}%{v * 1e3 / mpx:>10.1f}")
        print(f"{'sum of the parts':<20}{total * 1e3:>9.2f}{100.0:>7.1f}%"
              f"{total * 1e3 / mpx:>10.1f}")
        print(f"{'paint_masks (whole)':<20}{whole * 1e3:>9.2f}{'':>7} {whole * 1e3 / mpx:>9.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
