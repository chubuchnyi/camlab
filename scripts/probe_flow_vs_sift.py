"""Can sparse optical flow replace SIFT for the frame-to-frame homography? — measured, not argued.

SIFT is 354 ms a pair on `broadcast`, nine times the whole 40 ms real-time budget for a single
frame, and it is the one thing in a causal frame that makes real time arithmetically impossible.
It is also, on gap-1 pairs, being asked a question it was not built for: SIFT is a **wide-baseline**
descriptor, and the repo's own measurement says consecutive frames at 30 fps turn by **0.06 deg**.
Lucas-Kanade is the small-motion instrument.

So this is the experiment. `goodFeaturesToTrack` + pyramidal LK + a forward-backward check + the
same `USAC_MAGSAC` that `measure_pairs` uses, against `measure_pairs` itself, on real gap-1 pairs.

**What is compared is not the matrices** — two homographies can differ in every entry and agree
everywhere it matters, and comparing entries is how you get a number nobody can interpret. A grid
of points is pushed through both and the disagreement is read in PIXELS, which is the unit the rest
of this repo argues in. A camera solved from a map that is 0.1 px from SIFT's is the same camera; a
map 5 px out is a different clip.

This does NOT propose swapping the detector. `solve_carry` is built on these homographies and every
camera in `runs/` descends from them, so a change here re-solves the repo. It answers one question:
whether the real-time wall is a property of the problem or of one library call.

    python scripts/probe_flow_vs_sift.py broadcast fan g11710897 --pairs 8
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

MIN_INLIERS = 40
RANSAC_PX = 3.0


def flow_homography(a_gray, b_gray, max_corners=2000, scale=1.0):
    """`(H, inliers, ms)` from pyramidal Lucas-Kanade, or `(None, 0, ms)`."""
    t = time.perf_counter()
    ga = a_gray if scale >= 1.0 else cv2.resize(a_gray, None, fx=scale, fy=scale,
                                                interpolation=cv2.INTER_AREA)
    gb = b_gray if scale >= 1.0 else cv2.resize(b_gray, None, fx=scale, fy=scale,
                                                interpolation=cv2.INTER_AREA)
    p0 = cv2.goodFeaturesToTrack(ga, maxCorners=max_corners, qualityLevel=0.01, minDistance=7)
    if p0 is None or len(p0) < MIN_INLIERS:
        return None, 0, (time.perf_counter() - t) * 1e3
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01)
    p1, st, _ = cv2.calcOpticalFlowPyrLK(ga, gb, p0, None, winSize=(21, 21), maxLevel=3,
                                         criteria=crit)
    # Forward-backward: track it home and keep only what lands where it started. This is what
    # replaces SIFT's ratio test — without it, a point on a repeating stand pattern drifts along
    # the pattern and the homography follows it.
    p0r, st2, _ = cv2.calcOpticalFlowPyrLK(gb, ga, p1, None, winSize=(21, 21), maxLevel=3,
                                           criteria=crit)
    good = (st.ravel() == 1) & (st2.ravel() == 1)
    good &= np.linalg.norm((p0r - p0).reshape(-1, 2), axis=1) < 1.0
    if int(good.sum()) < MIN_INLIERS:
        return None, 0, (time.perf_counter() - t) * 1e3
    src = (p0[good] / scale).astype(np.float32)
    dst = (p1[good] / scale).astype(np.float32)
    h, mask = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, RANSAC_PX,
                                 maxIters=5000, confidence=0.9999)
    ms = (time.perf_counter() - t) * 1e3
    if h is None or mask is None or int(mask.sum()) < MIN_INLIERS:
        return None, 0, ms
    return h, int(mask.sum()), ms


def disagreement(h1, h2, w, h_img, n=40):
    """Median and worst distance, in PIXELS, between where the two maps send a grid of points."""
    xs, ys = np.meshgrid(np.linspace(0, w - 1, n), np.linspace(0, h_img - 1, n))
    pts = np.column_stack([xs.ravel(), ys.ravel(), np.ones(xs.size)])

    def push(h):
        q = pts @ h.T
        z = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
        return q[:, :2] / z[:, None]

    d = np.linalg.norm(push(h1) - push(h2), axis=1)
    return float(np.median(d)), float(np.percentile(d, 95)), float(d.max())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--pairs", type=int, default=8)
    ap.add_argument("--scales", default="1.0,0.5")
    args = ap.parse_args()

    from camlab.measure.pixel_motion import clear_descriptor_cache, measure_pairs

    load = os.getloadavg()
    print(f"load {load[0]:.2f} {load[1]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; the times are upper bounds ***")

    for clip in args.clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        if len(frames) < 2:
            continue
        step = max(1, (len(frames) - 1) // args.pairs)
        pairs = [(i, i + 1) for i in range(0, len(frames) - 1, step)][:args.pairs]
        img0 = cv2.imread(str(frames[0]))
        h_img, w = img0.shape[:2]
        print(f"\n{clip}  {w}x{h_img}   {len(pairs)} consecutive pairs")

        sift_ms, sift_h, sift_in = [], {}, []
        for i, j in pairs:
            clear_descriptor_cache()
            t = time.perf_counter()
            got = measure_pairs({i: frames[i], j: frames[j]}, gaps=(1,))
            sift_ms.append((time.perf_counter() - t) * 1e3)
            if got:
                sift_h[(i, j)] = got[0].h
                sift_in.append(got[0].inliers)

        for s in (float(x) for x in args.scales.split(",")):
            rows, ms, inl = [], [], []
            for i, j in pairs:
                ga = cv2.imread(str(frames[i]), cv2.IMREAD_GRAYSCALE)
                gb = cv2.imread(str(frames[j]), cv2.IMREAD_GRAYSCALE)
                hf, n_in, t_ms = flow_homography(ga, gb, scale=s)
                ms.append(t_ms)
                if hf is None or (i, j) not in sift_h:
                    continue
                inl.append(n_in)
                rows.append(disagreement(sift_h[(i, j)], hf, w, h_img))
            if not rows:
                print(f"  flow @{s:.2f}   no usable pair")
                continue
            med = np.median([r[0] for r in rows])
            p95 = np.median([r[1] for r in rows])
            wor = max(r[2] for r in rows)
            print(f"  flow @{s:<5.2f} {np.median(ms):>7.1f} ms   {int(np.median(inl)):>5d} inliers"
                  f"   vs SIFT over the frame: median {med:>6.3f} px, p95 {p95:>6.3f}, "
                  f"worst {wor:>7.3f}")
        print(f"  SIFT       {np.median(sift_ms):>7.1f} ms   "
              f"{int(np.median(sift_in)) if sift_in else 0:>5d} inliers   "
              f"{len(sift_h)}/{len(pairs)} pairs produced a homography")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
