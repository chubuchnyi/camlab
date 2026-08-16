"""Where a refit's milliseconds are, and how much of its work is the same work.

`refit_frame_lm` is the biggest single item left in a causal frame — 13.5 ms on `broadcast`, 59 ms
on `g11710897` — and it is the only one that does NOT get cheaper with resolution, because it costs
per segment and per LM iteration rather than per pixel.

It is `least_squares` with a finite-difference Jacobian over 7 free parameters, so every iteration
costs one evaluation for the residual plus one per parameter for the Jacobian column. This counts
those evaluations, times each part of `line_errors`, and asks the question that decides what to do
about it: **across the 7 evaluations of one Jacobian block, does the CORRESPONDENCE change?**

That matters because `_assign_in_order` is a pure-Python dynamic program run on every evaluation,
and a derivative taken at a fixed correspondence — which is what an analytic Jacobian would be —
would compute it once per block instead of eight times. If the answer is "it never changes", that
is a large, exact-in-the-limit saving. If it changes often, the finite-difference Jacobian is
stepping over correspondence changes on purpose, which is what the docstring says it is for, and
freezing it would be changing the objective rather than speeding it up.

    python scripts/bench_refit.py broadcast fan g11710897 CRO_MOR_194948
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--frames", type=int, default=4)
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    from camlab.measure import line_error as LE
    from camlab.measure.lines import detect_segments, merge_collinear
    from camlab.measure.paint import paint_masks
    from camlab.solve import refit as RF

    load = os.getloadavg()
    print(f"load {load[0]:.2f} {load[1]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; the times are upper bounds ***")

    for clip in args.clips:
        cam_path = RUNS / clip / "camera_polished.json"
        if not cam_path.exists():
            print(f"{clip}: no camera")
            continue
        cam = json.loads(cam_path.read_text())
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        step = max(1, len(frames) // args.frames)
        picks = list(range(0, len(frames), step))[:args.frames]

        per_refit_ms, calls, segs_n, assign_frac = [], [], [], []
        same_block, total_block = 0, 0

        for i in picks:
            bgr = cv2.imread(str(frames[i]))
            h, w = bgr.shape[:2]
            dist, surface = paint_masks(bgr)
            segments = merge_collinear(detect_segments(dist, surface))
            segs_n.append(len(segments))
            kw = dict(width=w, height=h, cx=cam.get("cx"), cy=cam.get("cy"))
            f0 = float(cam["focal_px"][i])
            rv0 = np.asarray(cam["rotation"][i], float)
            c0 = np.asarray(cam["position"][i], float)

            # count `line_errors` calls, and record the matched correspondence of each
            seen: list[tuple] = []
            real = LE.line_errors

            def counting(*a, _seen=seen, _real=real, **k):
                out = _real(*a, **k)
                _seen.append(tuple(sorted((e.marking, tuple(np.round(e.found_uv.ravel(), 6)))
                                          for e in out if e.matched)))
                return out

            LE.line_errors = counting
            RF.line_errors = counting
            try:
                best = 1e9
                for _ in range(args.repeat):
                    seen.clear()
                    t = time.perf_counter()
                    RF.refit_frame_lm(segments, f0, rv0, c0, frame=i, free_position=True, **kw)
                    best = min(best, time.perf_counter() - t)
                per_refit_ms.append(best * 1e3)
                calls.append(len(seen))
                # the Jacobian blocks: after the first residual, evaluations come in runs of 7
                # (one per free parameter). Compare each block against its own base evaluation.
                k = 1
                while k + 7 <= len(seen):
                    base = seen[k - 1]
                    total_block += 1
                    if all(seen[k + j] == base for j in range(7)):
                        same_block += 1
                    k += 8
            finally:
                LE.line_errors = real
                RF.line_errors = real

            # the split inside one `line_errors`
            best_le = 1e9
            for _ in range(50):
                t = time.perf_counter()
                real(segments, f0, rv0, c0, **kw)
                best_le = min(best_le, time.perf_counter() - t)
            assign_frac.append(best_le)

        print(f"\n{clip}   {np.median(segs_n):.0f} segments a frame")
        print(f"  refit                 {np.median(per_refit_ms):>7.1f} ms")
        print(f"  line_errors calls     {np.median(calls):>7.0f} per refit")
        one = np.median(assign_frac) * 1e3
        n_c = np.median(calls)
        print(f"  one line_errors       {one:>7.3f} ms   x{n_c:.0f} = {one * n_c:.1f} ms, "
              f"{100 * one * n_c / np.median(per_refit_ms):.0f} % of the refit")
        if total_block:
            print(f"  Jacobian blocks where the correspondence never moves: "
                  f"{same_block}/{total_block}  ({100 * same_block / total_block:.0f} %)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
