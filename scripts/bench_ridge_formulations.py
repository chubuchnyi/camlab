"""Four ways to compute the same ridge map, and whether they agree.

`ridge_map`'s docstring says the honest ceiling on it is about 2x, on the grounds that a top-hat
asks one question and this asks a directional one twelve times with a turf condition on each. That
argues about the number of QUESTIONS. It does not argue about the algebra, and the algebra factors:

    ridge = max over (d, dir) of  [ val - max(v_+, v_-) ]        with -1000 where turf fails
          = val - min over (d, dir) of max(v_+, v_-)             with 255 substituted for non-turf

because a non-turf neighbour standing in as 255 makes that combination's `max` the largest possible,
so the `min` discards it — exactly what the -1000 fill did, without a mask, a temporary or a
scatter. And the whole inner loop then lives in the range 0..255, so it runs in **uint8** rather
than int16: half the bytes moved on a workload the repo itself measured to be memory-bound.

The two are not bit-identical on the raw array — where no combination passes the turf test the old
code writes -1000 and this writes `val - 255`, which is in [-255, 0]. Every consumer thresholds at
a strictly positive value (`RIDGE_CONTRAST` is 16, `AUTO_COARSE` starts at 12, the fine step floors
at 6, and the adaptive path clips to 0 first), so the two agree on every question anyone asks. This
script checks that rather than asserting it.

    python scripts/bench_ridge_formulations.py broadcast fan g11710897
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
DIRS = ((1, 0), (0, 1), (1, 1), (1, -1))


def shipped(val_i16, turf, scales):
    """Exactly what `ridge_map` does today, from `val`/`turf` already computed."""
    pad = max(scales)
    height, width = val_i16.shape
    vpad = np.full((height + 2 * pad, width + 2 * pad), 255, np.int16)
    vpad[pad:pad + height, pad:pad + width] = val_i16
    tpad = np.zeros((height + 2 * pad, width + 2 * pad), bool)
    tpad[pad:pad + height, pad:pad + width] = turf
    ridge = np.full(val_i16.shape, -1000, np.int16)
    hi = np.empty(val_i16.shape, np.int16)
    side = np.empty(val_i16.shape, np.int16)
    both = np.empty(val_i16.shape, bool)
    for d in scales:
        for dy, dx in DIRS:
            def win(a, sy, sx, d=d, dy=dy, dx=dx):
                return a[pad + sy * d * dy:pad + sy * d * dy + height,
                         pad + sx * d * dx:pad + sx * d * dx + width]
            np.maximum(win(vpad, 1, 1), win(vpad, -1, -1), out=hi)
            np.subtract(val_i16, hi, out=side)
            np.logical_and(win(tpad, 1, 1), win(tpad, -1, -1), out=both)
            side[~both] = -1000
            np.maximum(ridge, side, out=ridge)
    return ridge


def factored_i16(val_i16, turf, scales):
    """The factorisation, still in int16 — isolates the algebra from the dtype."""
    pad = max(scales)
    height, width = val_i16.shape
    vpad = np.full((height + 2 * pad, width + 2 * pad), 255, np.int16)
    inner = vpad[pad:pad + height, pad:pad + width]
    np.copyto(inner, val_i16, where=turf)          # non-turf stays 255
    acc = np.full(val_i16.shape, 255, np.int16)
    hi = np.empty(val_i16.shape, np.int16)
    for d in scales:
        for dy, dx in DIRS:
            def win(a, sy, sx, d=d, dy=dy, dx=dx):
                return a[pad + sy * d * dy:pad + sy * d * dy + height,
                         pad + sx * d * dx:pad + sx * d * dx + width]
            np.maximum(win(vpad, 1, 1), win(vpad, -1, -1), out=hi)
            np.minimum(acc, hi, out=acc)
    return np.subtract(val_i16, acc, dtype=np.int16)


def factored_u8(val_u8, turf, scales):
    """The factorisation in uint8 — half the bytes of everything above."""
    pad = max(scales)
    height, width = val_u8.shape
    vpad = np.full((height + 2 * pad, width + 2 * pad), 255, np.uint8)
    inner = vpad[pad:pad + height, pad:pad + width]
    np.copyto(inner, val_u8, where=turf)
    acc = np.full(val_u8.shape, 255, np.uint8)
    hi = np.empty(val_u8.shape, np.uint8)
    for d in scales:
        for dy, dx in DIRS:
            def win(a, sy, sx, d=d, dy=dy, dx=dx):
                return a[pad + sy * d * dy:pad + sy * d * dy + height,
                         pad + sx * d * dx:pad + sx * d * dx + width]
            np.maximum(win(vpad, 1, 1), win(vpad, -1, -1), out=hi)
            np.minimum(acc, hi, out=acc)
    return val_u8.astype(np.int16) - acc.astype(np.int16)


def factored_cv2(val_u8, turf_u8, scales):
    """The same, with OpenCV's elementwise kernels — SIMD and threaded across rows."""
    pad = max(scales)
    height, width = val_u8.shape
    vpad = np.full((height + 2 * pad, width + 2 * pad), 255, np.uint8)
    # 255 wherever the pixel is not turf: max(val, ~turf) is val on turf and 255 off it.
    cv2.max(val_u8, cv2.bitwise_not(turf_u8), dst=vpad[pad:pad + height, pad:pad + width])
    acc = np.full(val_u8.shape, 255, np.uint8)
    hi = np.empty(val_u8.shape, np.uint8)
    for d in scales:
        for dy, dx in DIRS:
            def win(a, sy, sx, d=d, dy=dy, dx=dx):
                return a[pad + sy * d * dy:pad + sy * d * dy + height,
                         pad + sx * d * dx:pad + sx * d * dx + width]
            cv2.max(win(vpad, 1, 1), win(vpad, -1, -1), dst=hi)
            cv2.min(acc, hi, dst=acc)
    return cv2.subtract(val_u8, acc, dtype=cv2.CV_16S)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--scales", default=None, help="comma list; default the shipped (2,4,7)")
    args = ap.parse_args()

    scales = tuple(int(x) for x in args.scales.split(",")) if args.scales else P.RIDGE_SCALES
    print(f"opencv threads {cv2.getNumThreads()}   scales {scales}")

    for clip in args.clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        step = max(1, len(frames) // args.frames)
        imgs = [cv2.imread(str(p)) for p in frames[::step][:args.frames]]
        h, w = imgs[0].shape[:2]

        prepared = []
        for bgr in imgs:
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
            turf = P._turf(hsv)
            val_u8 = np.ascontiguousarray(hsv[..., 2])
            prepared.append((val_u8, val_u8.astype(np.int16), turf,
                             (turf.astype(np.uint8) * 255)))

        variants = {
            "shipped int16":  lambda p: shipped(p[1], p[2], scales),
            "factored int16": lambda p: factored_i16(p[1], p[2], scales),
            "factored uint8": lambda p: factored_u8(p[0], p[2], scales),
            "factored cv2":   lambda p: factored_cv2(p[0], p[3], scales),
        }

        best = dict.fromkeys(variants, 1e9)
        for _ in range(args.repeat):
            for p in prepared:
                for name, fn in variants.items():         # interleaved
                    t = time.perf_counter()
                    fn(p)
                    best[name] = min(best[name], time.perf_counter() - t)

        # agreement: on every threshold anyone downstream uses
        ref = shipped(prepared[0][1], prepared[0][2], scales)
        thresholds = (6, 12, P.RIDGE_CONTRAST, 24, 36, 48, 60, 75, 90, 110, 116)
        print(f"\n{clip}  {w}x{h}")
        base = best["shipped int16"]
        for name, fn in variants.items():
            got = fn(prepared[0])
            same = all(np.array_equal(got >= t, ref >= t) for t in thresholds)
            clipped = np.array_equal(np.clip(got, 0, 255), np.clip(ref, 0, 255))
            exact = np.array_equal(got, ref)
            print(f"  {name:<16}{best[name] * 1e3:>8.2f} ms  {base / best[name]:>5.2f}x   "
                  f"thresholds {'agree' if same else 'DIFFER'}  "
                  f"clip0-255 {'agree' if clipped else 'DIFFER'}  "
                  f"raw {'identical' if exact else 'differs (expected)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
