"""Deciding the playing surface at reduced resolution: 4x faster, and it must not ship.

`_surface` closes the turf mask with a 45x45 and then a 61x61 rectangular element, and its output
is a filled REGION whose only question is "is this pixel on the pitch". That question has no
sub-pixel meaning, so asking it on a quarter-scale image with quarter-scale elements looked like a
free 4x on a stage worth 5 ms of a 30 ms frame.

It is not free, and this script is the measurement that says so. The reduced answer disagrees with
the full one on **8.3 % of the pixels of `CRO_MOR_194948`** — and disagrees MORE at half scale than
at quarter, which is the signature of a different connected component winning `CC_STAT_AREA`, not
of a blurred boundary. A surface mask decides which detected segments are on the pitch at all, so a
component flip is not a rounding error, it is a different set of markings.

The other three clips move 0.1–1.5 %, which is exactly why one clip is not a measurement here:
three of four would have shipped it.

Kept as a refutation with its numbers, not as an option. If the surface ever needs to be cheaper,
the thing to try is a smaller element at full resolution, which cannot re-rank components.

    python scripts/bench_surface_resolution.py broadcast fan g11710897 CRO_MOR_194948
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camlab.measure import paint as P  # noqa: E402

RUNS = Path(__file__).resolve().parents[1] / "runs"


def surface_reduced(turf_u8: np.ndarray, scale: int = 4) -> np.ndarray:
    """`_surface` decided at 1/`scale` resolution and put back, elements scaled to match."""
    h, w = turf_u8.shape
    small = cv2.resize(turf_u8, (max(1, w // scale), max(1, h // scale)),
                       interpolation=cv2.INTER_AREA)
    k1 = max(3, (45 // scale) | 1)
    k2 = max(3, (61 // scale) | 1)
    filled = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((k1, k1), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(filled, 8)
    if count < 2:
        out = filled
    else:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        out = cv2.morphologyEx((labels == biggest).astype(np.uint8), cv2.MORPH_CLOSE,
                               np.ones((k2, k2), np.uint8))
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_NEAREST)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    for clip in args.clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        if not frames:
            print(f"{clip}: no frames")
            continue
        step = max(1, len(frames) // args.frames)
        turfs = [np.asarray(P._turf(cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2HSV)))
                 for p in frames[::step][:args.frames]]
        h, w = turfs[0].shape

        best = {"full": 1e9, "1/2": 1e9, "1/4": 1e9}
        cases = (("full", P._surface), ("1/2", lambda a: surface_reduced(a, 2)),
                 ("1/4", lambda a: surface_reduced(a, 4)))
        for _ in range(args.repeat):
            for turf in turfs:
                for name, fn in cases:
                    st = time.perf_counter()
                    fn(turf)
                    best[name] = min(best[name], time.perf_counter() - st)

        dis = {"1/2": 0.0, "1/4": 0.0}
        for turf in turfs:
            ref = np.asarray(P._surface(turf)) > 0
            for name, factor in (("1/2", 2), ("1/4", 4)):
                got = surface_reduced(turf, factor) > 0
                dis[name] = max(dis[name], float(np.mean(ref != got)))

        print(f"\n{clip}  {w}x{h}")
        print(f"  full   {best['full'] * 1e3:>6.2f} ms")
        for name in ("1/2", "1/4"):
            print(f"  {name}    {best[name] * 1e3:>6.2f} ms  {best['full'] / best[name]:>5.2f}x   "
                  f"disagrees on {100 * dis[name]:.3f} % of pixels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
