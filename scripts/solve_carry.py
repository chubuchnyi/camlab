"""Solve a whole clip by carrying the camera frame to frame, and write `camera_carry.json`.

The measured method (`findings/carrying-the-camera-works.md`): anchor once, then for each frame
take the previous camera through the image→image homography and refine it locally. The mover knows
nothing about the pitch, so a bad line does not steer it.

Anchor with `--anchor N`; if `calib/<clip>-hand-aligned-*.json` has that frame it is used, which is
the manual-override half of the design. Otherwise the solve's own camera for that frame is refitted
and used, which needs no human at all — measured at 22.7 px median against `camera_auto`'s 38.5.

**The chain drifts**, and this writes that into the file rather than hiding it: every frame carries
a `carry_drift` counter — how many frames since the anchor — and frames the metric cannot score are
left visible rather than dropped.

Run:  .venv/bin/python scripts/solve_carry.py [clip] [--anchor N] [--out camera_carry.json]
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
from camlab.solve.refit import refit_frame, refit_frame_lm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--anchor", default="0",
                    help="comma-separated frame numbers; each frame is carried from its nearest")
    ap.add_argument("--seed", default="camera_auto.json")
    ap.add_argument("--out", default="camera_carry.json")
    ap.add_argument("--no-hand", action="store_true",
                    help="ignore calib/ and refit every anchor from the solve — the honest test "
                         "of whether this works with no human in the loop at all")
    ap.add_argument("--nelder-mead", action="store_true",
                    help="use the old scalar objective. Off by default: measured against eight "
                         "hand-aligned frames it reaches 13.8 px where the least-squares refit "
                         "reaches 2.0")
    ap.add_argument("--free-position", action="store_true",
                    help="let the refit move the camera centre too. Off by default: the carry's "
                         "own derivation assumes a fixed centre, and freeing it is what drifted")
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    seed = json.loads((info.dir / args.seed).read_text())
    cx, cy = float(seed["cx"]), float(seed["cy"])
    n = len(seed["frames"])

    hand_path = next((Path(__file__).resolve().parent.parent / "calib")
                     .glob(f"{args.clip}-hand-aligned-*.json"), None)
    hand = json.loads(hand_path.read_text()).get(args.seed, {}) if hand_path else {}
    if args.no_hand:
        hand = {}
    anchors = sorted({int(a) for a in str(args.anchor).split(",") if a.strip() != ""})
    if not anchors or anchors[0] < 0 or anchors[-1] >= n:
        raise SystemExit(f"anchors {anchors} must all be within 0..{n - 1}")
    by_hand = [a for a in anchors if str(a) in hand]

    print(f"== {args.clip}: {n} frames, anchors {anchors} "
          f"({len(by_hand)} hand-aligned: {by_hand}), K = ({cx:.0f}, {cy:.0f})")

    pairs = measure_pairs({f: info.frame_path(f) for f in range(n)}, gaps=(1,))
    h_of = {(p.i, p.j): p for p in pairs}
    print(f"   {len(pairs)}/{n - 1} consecutive pairs, median reprojection "
          f"{np.median([p.median_px for p in pairs]):.2f} px")

    fit = refit_frame if args.nelder_mead else refit_frame_lm
    print("   refit: " + ("Nelder-Mead on the scalar objective" if args.nelder_mead
                          else "Levenberg-Marquardt on the endpoint residuals"))

    def segs(i):
        d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
        return detect_segments(d, s, method="hough")

    focal = np.array(seed["focal_px"], float).copy()
    rot = np.array(seed["rotation"], float).copy()
    pos = np.array(seed["position"], float).copy()
    drift = np.zeros(n, int)

    # Each frame belongs to its NEAREST anchor, and no chain runs past the midpoint to the next
    # one. Drift is what breaks this method — one anchor held ~60 frames on the fan clip and then
    # collapsed — so the longest chain any frame sits on is what decides its quality, and halving
    # it by adding an anchor halves the accumulation. `carry_drift` records that distance per frame
    # so a reader can distrust the far ones without re-deriving which they are.
    for a in anchors:
        if str(a) in hand:
            e = hand[str(a)]
            focal[a], rot[a], pos[a] = e["focal_px"], np.asarray(e["rotation"], float), \
                np.asarray(e["position"], float)
        else:
            r = fit(segs(a), focal[a], rot[a], pos[a], info.width, info.height, cx, cy)
            focal[a], rot[a], pos[a] = r.focal_px, r.rotation, r.position
        drift[a] = 0

    bounds = []
    for idx, a in enumerate(anchors):
        lo = 0 if idx == 0 else (anchors[idx - 1] + a) // 2 + 1
        hi = n - 1 if idx == len(anchors) - 1 else (a + anchors[idx + 1]) // 2
        bounds.append((lo, hi))

    # Outward in both directions, so an anchor need not be frame 0. A backward step uses the same
    # pair inverted: H(j->i) is H(i->j)^-1 for a homography, exactly.
    for a, (lo, hi) in zip(anchors, bounds, strict=True):
        for direction, stop in ((1, hi), (-1, lo)):
            i = a
            while 0 <= i + direction < n and (i + direction) * direction <= stop * direction:
                j = i + direction
                f0, rv0, c0 = focal[i], rot[i], pos[i]
                p = h_of.get((min(i, j), max(i, j)))
                if p is not None:
                    m = np.linalg.inv(p.h) if direction < 0 else p.h
                    moved = carry(f0, rv0, c0, m, cx, cy)
                    if moved is not None:
                        f0, rv0, c0 = moved.focal_px, moved.rotation, moved.position
                # Position HELD. `carry` is derived from `H = K_j Rj Ri^T K_i^-1`, which is only
                # true for a camera turning about a fixed centre — and the measurement says that
                # holds here, the two image axes agreeing on the focal to 0.001. Letting the refit
                # move the centre anyway contradicts the model that produced the seed, and it is
                # where the drift came from: the carried solve wandered 2.9 / 4.7 / 2.1 m per axis
                # with a single-frame step of 11.5 m, which a person in a seat does not do at
                # 30 fps.
                r = fit(segs(j), f0, rv0, c0, info.width, info.height, cx, cy,
                        free_position=args.free_position)
                focal[j], rot[j], pos[j] = r.focal_px, r.rotation, r.position
                drift[j] = abs(j - a)
                i = j
        print(f"      anchor {a}: frames {lo}..{hi} done", flush=True)

    before, after = [], []
    for i in range(n):
        before.append(frame_residual(info.frame_path(i), seed["focal_px"][i], seed["rotation"][i],
                                     seed["position"][i], frame=i, cx=cx, cy=cy).worst_line_px)
        after.append(frame_residual(info.frame_path(i), focal[i], rot[i], pos[i],
                                    frame=i, cx=cx, cy=cy).worst_line_px)
    b, a = np.array(before), np.array(after)

    out = write_camera(
        info.dir / args.out, model=f"{seed['model']}+pixel_carry", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(seed["frames"], int),
        focal_px=focal, position=pos, rotation=rot, cx=cx, cy=cy,
        degenerate=seed.get("degenerate", [False] * n),
        carried_from=args.seed, anchor_frames=anchors,
        anchors_hand_aligned=by_hand,
        carry_drift=drift.tolist(),
        notes=("Each frame's camera is the previous frame's taken through the measured image-to-"
               "image homography, then refit locally. The chain ACCUMULATES: `carry_drift` is the "
               "distance in frames from the anchor, and a large one is a reason to distrust that "
               "frame rather than a decoration."),
    )
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(b):7.1f} px  ->  {np.nanmedian(a):7.1f} px")
    print(f"   frames under 20 px  {int(np.nansum(b < 20)):7d}     ->  {int(np.nansum(a < 20)):7d}"
          f"   of {n}")
    print(f"   frames the metric cannot score at all: {int(np.isnan(b).sum())} -> "
          f"{int(np.isnan(a).sum())}")


if __name__ == "__main__":
    main()
