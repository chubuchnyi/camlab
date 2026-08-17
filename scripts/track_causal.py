"""A CAUSAL tracker: one frame at a time, no future, and what it costs in accuracy.

The chain is five stages and four of them are not causal — shared centre searches a line over the
whole clip, smoothing is a median filter along it, polish offers a frame its neighbours' cameras.
A live stream can run none of them. What it can run is this loop:

    seed the anchor frame -> for every frame after it:
        measure the motion from the frame before          (SIFT, or optical flow)
        carry the previous camera through that homography
        refit against this frame's own paint

which is `solve_carry` with one anchor, one direction, and nothing downstream.

**This exists to answer two questions with numbers, and neither is "how many seconds".**

1. *How far does a causal tracker drift?* The chain's `across` is the number this repo defends;
   a causal tracker has no self-heal to rescue a lost frame and no smoothing to hide a wobble, so
   it will be worse, and the question is by how much and where it breaks.
2. *Does optical flow track as well as SIFT inside the same loop?* `flow_pairs` agrees with
   `measure_pairs` to a median of 0.018–0.360 px on a single pair — but `carry` ACCUMULATES, and
   the worst pair measured disagrees by 2–7.8 px. A median that good and a tail that bad is exactly
   the shape where per-pair agreement says nothing and only the accumulation does.

Running the SAME loop with both motion sources is the point: it separates the detector from the
tracker, so a difference is the detector's and nothing else's.

    python scripts/track_causal.py broadcast --motion flow --scale 0.5
    python scripts/track_causal.py broadcast --motion sift --scale 1.0
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from camlab.measure.lines import detect_segments, merge_collinear  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.pixel_motion import flow_pairs, measure_pairs  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--motion", choices=("flow", "sift", "none"), default="flow",
                    help="`none` carries nothing and lets the refit start from the previous "
                         "frame's camera — the control that says what the motion is worth")
    ap.add_argument("--scale", type=float, default=1.0, help="resolution the PAINT runs at")
    ap.add_argument("--motion-scale", type=float, default=1.0,
                    help="resolution the FLOW runs at; its homography is scaled back either way")
    ap.add_argument("--reference", default="camera_polished.json",
                    help="the shipped chain's answer, used to seed the anchor and to compare")
    ap.add_argument("--anchor", type=int, default=0)
    ap.add_argument("--frames", type=int, default=0, help="0 = the whole clip")
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    ref = json.loads((info.dir / args.reference).read_text())
    cx, cy = ref.get("cx"), ref.get("cy")
    n = args.frames or len(ref["focal_px"])
    order = [i for i in range(args.anchor, n)]
    if len(order) < 2:
        raise SystemExit("need at least two frames after the anchor")

    load = os.getloadavg()
    print(f"{args.clip}  {info.width}x{info.height}  {len(order)} frames from {args.anchor}  "
          f"motion={args.motion}  paint scale={args.scale}  load {load[0]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; the times are upper bounds ***")

    # The motion for the whole clip up front. A live tracker would compute each pair as its frame
    # arrives; batching it here changes the cost per frame not at all — both detectors cache their
    # per-frame work — and keeps this script about accuracy.
    paths = {i: info.frame_path(i) for i in order}
    t0 = time.perf_counter()
    if args.motion == "none":
        pairs = []
    elif args.motion == "flow":
        pairs = flow_pairs(paths, gaps=(1,), scale=args.motion_scale)
    else:
        pairs = measure_pairs(paths, gaps=(1,))
    motion_s = time.perf_counter() - t0
    h_of = {(p.i, p.j): p.h for p in pairs}
    print(f"   motion: {len(pairs)}/{len(order) - 1} consecutive pairs in {motion_s:.1f} s "
          f"({motion_s * 1e3 / max(1, len(order) - 1):.1f} ms a frame)")

    def segs(i):
        import cv2
        bgr = cv2.imread(str(info.frame_path(i)))
        if args.scale < 1.0:
            bgr = cv2.resize(bgr, None, fx=args.scale, fy=args.scale,
                             interpolation=cv2.INTER_AREA)
        d, s = paint_masks(bgr)
        got = merge_collinear(detect_segments(d, s))
        return got / args.scale if len(got) else got

    def score(i, f, rv, c):
        r = frame_residual(info.frame_path(i), f, rv, c, frame=i, cx=cx, cy=cy)
        return r.worst_across_px, len(r.per_line)

    a = args.anchor
    focal = float(ref["focal_px"][a])
    rot = np.asarray(ref["rotation"][a], float)
    pos = np.asarray(ref["position"][a], float)

    rows, lost, per_frame_s = [], 0, []
    for i in order[1:]:
        t = time.perf_counter()
        h = h_of.get((i - 1, i))
        if h is None:
            lost += 1
        else:
            moved = carry(focal, rot, pos, h, cx, cy)
            if moved is None:
                lost += 1
            else:
                focal, rot, pos = moved.focal_px, moved.rotation, moved.position
        seg = segs(i)
        if len(seg):
            r = refit_frame_lm(seg, focal, rot, pos, info.width, info.height, cx, cy,
                               frame=i, free_position=False)
            focal, rot, pos = r.focal_px, r.rotation, r.position
        per_frame_s.append(time.perf_counter() - t)

        got, marks = score(i, focal, rot, pos)
        want, _ = score(i, float(ref["focal_px"][i]), np.asarray(ref["rotation"][i], float),
                        np.asarray(ref["position"][i], float))
        rows.append((i, got, want, marks))

    ok = [r for r in rows if np.isfinite(r[1]) and np.isfinite(r[2])]
    if not ok:
        print("   no frame scored on both — nothing to compare")
        return 1
    mine = np.array([r[1] for r in ok])
    theirs = np.array([r[2] for r in ok])
    print(f"   scored {len(ok)}/{len(rows)} frames, {lost} with no usable motion")
    print(f"   {'':>22}{'median':>9}{'p90':>9}{'worst':>9}{'under 20 px':>13}")
    for name, v in (("causal tracker", mine), (f"the chain ({args.reference})", theirs)):
        print(f"   {name:>22}{np.median(v):>9.2f}{np.percentile(v, 90):>9.2f}{v.max():>9.2f}"
              f"{int((v < 20).sum()):>9d}/{len(v)}")
    drift = mine - theirs
    print(f"   {'tracker minus chain':>22}{np.median(drift):>9.2f}{np.percentile(drift, 90):>9.2f}"
          f"{drift.max():>9.2f}")
    print(f"   per frame: {np.median(per_frame_s) * 1e3:.1f} ms paint+refit, "
          f"{motion_s * 1e3 / max(1, len(order) - 1):.1f} ms motion, "
          f"**{np.median(per_frame_s) * 1e3 + motion_s * 1e3 / max(1, len(order) - 1):.1f} ms "
          f"total** against a 40 ms budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
