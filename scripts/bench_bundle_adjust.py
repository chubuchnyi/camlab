#!/usr/bin/env python3
"""#35: refine every frame's rotation and focal at once, and judge it on the paint.

The chain fights carry drift **locally** — each frame is carried from its nearest anchor and
refitted alone, and the register's own finding is that one anchor holds about sixty frames before
it collapses. `cv2.detail.BundleAdjusterRay` attacks the same thing **globally**: it takes the
matched points between every pair and adjusts all rotations and focals together, under exactly the
model the carry stage already assumes and has measured — a camera turning about a fixed centre.

**It has no notion of position**, which is not a limitation here: the carry model says the centre
does not move, so the position is held at the solved camera's and only focal and rotation change.

Judged by `frame_residual` per frame, before and against after, because the class of thing that
goes wrong here is a refinement that improves its own objective and moves away from the paint.

    PYTHONPATH=src python scripts/bench_bundle_adjust.py fan --camera camera_smooth.json
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.camera_file import read_camera  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402

#: Long-baseline pairs as well as neighbours. The whole point of a global adjustment is that it can
#: use a constraint the chain cannot — frame 0 against frame 60 — and a pass over neighbours only
#: would give it nothing the carry does not already have.
GAPS = (1, 5, 20, 60)


def _features(info, frames, max_features: int = 2000):
    sift = cv2.SIFT_create(nfeatures=max_features)
    out = []
    for idx, f in enumerate(frames):
        img = cv2.imread(str(info.frame_path(f)), cv2.IMREAD_GRAYSCALE)
        kp, desc = sift.detectAndCompute(img, None)
        fe = cv2.detail.ImageFeatures()
        fe.img_idx = idx
        fe.img_size = (info.width, info.height)
        fe.keypoints = kp
        fe.descriptors = cv2.UMat(desc)
        out.append(fe)
    return out


def _match(feats, frames):
    """Every pair at the requested gaps, as OpenCV's own `MatchesInfo`.

    The adjuster wants the FULL square: `pairwise_matches[i * n + j]`, with an empty entry where
    there is no match. Handing it a ragged list silently misaddresses every pair.
    """
    n = len(feats)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    blank = []
    for i in range(n):
        for j in range(n):
            m = cv2.detail.MatchesInfo()
            m.src_img_idx, m.dst_img_idx = i, j
            blank.append(m)

    made = 0
    for i in range(n):
        for j in range(n):
            if j <= i or (frames[j] - frames[i]) not in GAPS:
                continue
            d0 = feats[i].descriptors.get()
            d1 = feats[j].descriptors.get()
            pairs = bf.knnMatch(d0, d1, k=2)
            good = [a for a, b in pairs if a.distance < 0.75 * b.distance]
            if len(good) < 30:
                continue
            p0 = np.float32([feats[i].getKeypoints()[g.queryIdx].pt for g in good])
            p1 = np.float32([feats[j].getKeypoints()[g.trainIdx].pt for g in good])
            h, mask = cv2.findHomography(p0, p1, cv2.USAC_MAGSAC, 3.0)
            if h is None or mask is None or int(mask.sum()) < 20:
                continue
            m = cv2.detail.MatchesInfo()
            m.src_img_idx, m.dst_img_idx = i, j
            m.matches = tuple(good)
            m.inliers_mask = tuple(int(x) for x in mask.ravel())
            m.num_inliers = int(mask.sum())
            m.H = h
            # The stitcher's own heuristic. Below `confThresh` (1.0) the adjuster drops the pair.
            m.confidence = m.num_inliers / (8.0 + 0.3 * len(good))
            blank[i * n + j] = m
            made += 1
    return blank, made


def _cameras(cam, frames):
    out = []
    for f in frames:
        c = cv2.detail.CameraParams()
        c.focal = float(cam["focal_px"][f])
        c.aspect = 1.0
        c.ppx, c.ppy = float(cam["cx"]), float(cam["cy"])
        c.R = cv2.Rodrigues(np.asarray(cam["rotation"][f], float))[0].astype(np.float32)
        c.t = np.zeros((3, 1), np.float32)
        out.append(c)
    return out


def _score(info, cam, frames, focals, rots) -> tuple[float, float]:
    """`(median worst-line, median across)` over the frames, through `frame_residual`."""
    line, across = [], []
    for k, f in enumerate(frames):
        r = frame_residual(info.frame_path(f), float(focals[k]), rots[k],
                           np.asarray(cam["position"][f], float), frame=f,
                           cx=float(cam["cx"]), cy=float(cam["cy"]))
        if np.isfinite(r.worst_line_px):
            line.append(r.worst_line_px)
            across.append(r.worst_across_px)
    return (float(np.median(line)) if line else float("nan"),
            float(np.median(across)) if across else float("nan"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("clip")
    ap.add_argument("--camera", default="camera_smooth.json")
    ap.add_argument("--step", type=int, default=1, help="use every Nth frame")
    ap.add_argument("--limit", type=int, default=40, help="at most this many frames")
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    cam = read_camera(info.dir / args.camera)
    frames = list(range(0, info.n_frames, args.step))[:args.limit]
    print(f"== {args.clip}: {len(frames)} frames, seeded from {args.camera}")

    t0 = time.time()
    feats = _features(info, frames)
    matches, made = _match(feats, frames)
    print(f"   {made} pairs matched over gaps {GAPS} in {time.time() - t0:.0f}s")
    if made < len(frames):
        print("   !! fewer pairs than frames — the graph is not connected, the adjuster will not "
              "have a constraint on every frame")

    cams = _cameras(cam, frames)
    before_f = [c.focal for c in cams]
    before_r = [cv2.Rodrigues(np.asarray(c.R, float))[0].ravel() for c in cams]

    adj = cv2.detail.BundleAdjusterRay()
    adj.setConfThresh(1.0)
    t0 = time.time()
    ok, cams = adj.apply(feats, matches, cams)
    print(f"   adjuster returned {ok} in {time.time() - t0:.0f}s")
    if not ok:
        print("   refused to adjust — nothing to compare")
        return

    after_f = [c.focal for c in cams]
    after_R = [np.asarray(c.R, float) for c in cams]

    # **Put the gauge back.** A ray bundle adjustment constrains only the RELATIVE rotations: a
    # panorama has no world frame, so the whole set is free to turn together and OpenCV's adjuster
    # duly turns it. First run here moved every frame by 110.52 deg with a spread of 0.6 deg — one
    # global rotation, not 30 independent errors — and every frame then scored `nan` because the
    # pitch had left the picture. Comparing that to the seed would have said "useless".
    #
    # Recovered by orthogonal Procrustes over the whole set rather than by pinning frame 0, so one
    # badly adjusted frame cannot define the gauge for the rest.
    before_R = [cv2.Rodrigues(np.asarray(b, float))[0] for b in before_r]
    m = sum(a.T @ b for a, b in zip(after_R, before_R, strict=True))
    u, _s, vt = np.linalg.svd(m)
    gauge = u @ vt
    if np.linalg.det(gauge) < 0:
        u[:, -1] *= -1
        gauge = u @ vt
    after_R = [a @ gauge for a in after_R]
    after_r = [cv2.Rodrigues(a)[0].ravel() for a in after_R]

    bl, ba = _score(info, cam, frames, before_f, before_r)
    al, aa = _score(info, cam, frames, after_f, after_r)
    turn = np.degrees([np.arccos(np.clip((np.trace(
        cv2.Rodrigues(b)[0] @ cv2.Rodrigues(a)[0].T) - 1) / 2, -1, 1))
        for b, a in zip(before_r, after_r, strict=True)])

    print(f"\n   {'':22} {'before':>10} {'after':>10}")
    print(f"   {'worst line, median':22} {bl:10.2f} {al:10.2f}")
    print(f"   {'across, median':22} {ba:10.2f} {aa:10.2f}")
    print(f"   {'focal, median':22} {np.median(before_f):10.0f} {np.median(after_f):10.0f}")
    print(f"\n   it moved each frame's rotation by {np.median(turn):.2f} deg "
          f"(max {turn.max():.2f})")
    print("   VERDICT:", "better on the paint" if al < bl else
          "NO BETTER on the paint — it improved its own objective and not the picture")


if __name__ == "__main__":
    main()
