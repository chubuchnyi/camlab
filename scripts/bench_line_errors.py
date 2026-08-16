"""`line_errors` on its own, timed without a profiler attached — and why that distinction matters.

cProfile said `compare_line` was 259 331 calls and **9.8 s** of a 40.3 s `shared centre` stage, and
that number is most of a profiler. `cProfile` adds roughly a microsecond of bookkeeping to every
call it sees, so a function called a quarter of a million times a stage is charged a second or two
that does not exist outside the profiler, and its callees (`_overlap`, `_unit`, `np.linalg.norm` at
a million calls) are charged the same way. A profile ranks functions by call count as much as by
cost, and the ranking is only trustworthy for functions with a similar call count.

The way to tell is to time the thing itself, with a wall clock, twice. That is what this does.

    python scripts/bench_line_errors.py broadcast fan --repeat 200
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--repeat", type=int, default=200)
    args = ap.parse_args()

    import cv2

    from camlab.measure.line_error import line_errors
    from camlab.measure.lines import detect_segments, merge_collinear
    from camlab.measure.paint import paint_masks

    load = os.getloadavg()
    print(f"load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; treat every row as an upper bound ***")

    for clip in args.clips:
        cam_path = RUNS / clip / "camera_polished.json"
        if not cam_path.exists():
            print(f"{clip}: no camera_polished.json, skipped")
            continue
        cam = json.loads(cam_path.read_text())
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        bgr = cv2.imread(str(frames[0]))
        dist, surface = paint_masks(bgr)
        segs = merge_collinear(detect_segments(dist, surface))
        h, w = bgr.shape[:2]
        kw = dict(segments=segs, rvec=cam["rotation"][0], centre=cam["position"][0],
                  width=w, height=h, cx=cam.get("cx"), cy=cam.get("cy"))

        best = 1e9
        got = None
        for k in range(args.repeat):
            # nudge the focal so no cache anywhere can be keyed on the camera
            call = dict(kw, focal=float(cam["focal_px"][0]) * (1.0 + 1e-7 * k))
            t = time.perf_counter()
            got = line_errors(**call)
            best = min(best, time.perf_counter() - t)

        print(f"  {clip:<20} {len(segs):>3} segments, {len(got):>2} matched markings   "
              f"{best * 1e3:>7.3f} ms a call   "
              f"({best * 1e3 * 105:.0f} ms per LM refit of one frame)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
