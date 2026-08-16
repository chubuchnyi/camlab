"""What one frame costs, primitive by primitive, against a real-time budget.

The 2026-08-13 note set the target: a 90-minute match at 25 fps is 135 000 frames, and real time
needs **40 ms a frame**. This is what a frame costs now, split so the question "can this be real
time" is answered by arithmetic instead of by opinion.

Two paths are timed, because they are different problems and only one of them could ever be causal:

* **the causal path** — decode, paint, segments, refit. Everything needed to place a camera on a
  frame given the frame before it. A live stream can only ever run this.
* **the frame-to-frame motion** — SIFT, match, MAGSAC. `solve_carry`'s input, and the single most
  expensive thing in the chain.

Reported per frame, at full resolution and at the reduced scales `residual.SEARCH_SCALE` documents,
so the trade the repo already measured for accuracy can be read against the clock.

The chain's other four stages are NOT here and cannot be: shared centre searches a line over the
whole clip, smoothing is a median filter along it, polish offers a frame its neighbours' cameras.
They need frames that have not happened yet.

    python scripts/bench_frame_budget.py broadcast fan --repeat 5
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

TARGET_MS = 40.0


def best(fn, repeat):
    got = 1e9
    out = None
    for _ in range(repeat):
        t = time.perf_counter()
        out = fn()
        got = min(got, time.perf_counter() - t)
    return got * 1e3, out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--scales", default="1.0,0.5,0.35")
    args = ap.parse_args()

    from camlab.measure.lines import detect_segments, merge_collinear
    from camlab.measure.paint import paint_masks
    from camlab.measure.pixel_motion import clear_descriptor_cache, measure_pairs
    from camlab.solve.refit import refit_frame_lm

    load = os.getloadavg()
    print(f"target {TARGET_MS:.0f} ms a frame (25 fps)   load {load[0]:.2f} {load[1]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; every row is an upper bound ***")

    for clip in args.clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        cam_path = RUNS / clip / "camera_polished.json"
        if len(frames) < 2 or not cam_path.exists():
            print(f"{clip}: not usable")
            continue
        cam = json.loads(cam_path.read_text())
        bgr = cv2.imread(str(frames[0]))
        h, w = bgr.shape[:2]
        print(f"\n{clip}  {w}x{h}")
        print(f"  {'scale':>6}{'decode':>9}{'paint':>9}{'segments':>10}{'refit':>9}"
              f"{'causal':>9}{'vs 40ms':>9}   {'SIFT pair':>10}")

        def row(s, bgr=bgr, frames=frames, cam=cam, w=w, h=h):
            img = bgr if s >= 1.0 else cv2.resize(bgr, None, fx=s, fy=s,
                                                  interpolation=cv2.INTER_AREA)
            t_dec, _ = best(lambda: cv2.imread(str(frames[0])), args.repeat)
            if s < 1.0:
                t_dec += best(lambda: cv2.resize(bgr, None, fx=s, fy=s,
                                                 interpolation=cv2.INTER_AREA), args.repeat)[0]
            t_paint, (dist, surface) = best(lambda: paint_masks(img), args.repeat)
            t_seg, segs = best(lambda: merge_collinear(detect_segments(dist, surface)),
                               args.repeat)
            hh, ww = img.shape[:2]
            cx = (cam.get("cx") or w / 2.0) * s
            cy = (cam.get("cy") or h / 2.0) * s
            t_fit, _ = best(lambda: refit_frame_lm(
                segs, float(cam["focal_px"][0]) * s, np.asarray(cam["rotation"][0], float),
                np.asarray(cam["position"][0], float), ww, hh, cx, cy,
                free_position=False), args.repeat)
            causal = t_dec + t_paint + t_seg + t_fit
            print(f"  {s:>6.2f}{t_dec:>9.1f}{t_paint:>9.1f}{t_seg:>10.1f}{t_fit:>9.1f}"
                  f"{causal:>9.1f}{causal / TARGET_MS:>8.1f}x", end="")
            if s >= 1.0:
                clear_descriptor_cache()
                t_sift, _ = best(lambda: (clear_descriptor_cache(),
                                          measure_pairs({0: frames[0], 1: frames[1]},
                                                        gaps=(1,)))[1], args.repeat)
                print(f"   {t_sift:>10.1f}")
            else:
                print()

        for scale in (float(x) for x in args.scales.split(",")):
            row(scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
