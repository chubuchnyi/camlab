"""After the whole chain has run, go back over the frames it left worst and try the neighbours.

`solve_selfheal.py` already offers a neighbour's camera to a frame the solve lost — but it runs on
`camera_carry.json`, two stages before the end. Shared-centre moves every frame onto one optical
centre and the median filter moves every frame again, so a frame that was fine when self-heal
looked at it can be the worst one in the clip by the time the chain finishes. An operator scrubbing
`g14604660` found exactly that: some frames were poor, and copying a neighbour by hand improved them
a lot.

So this is the same idea applied where the damage actually is, plus one candidate self-heal does not
offer: the **interpolation** between the nearest good frame on each side. A camera that pans
smoothly is better described by what its neighbours were doing than by either of them alone.

Nothing is taken on faith. Every candidate is scored against the paint on that frame and kept only
if it beats what is already there **and** does not score on fewer markings — a camera can always
lower its error by pushing a marking out of the picture. Otherwise the frame is left exactly as the
chain left it.

    PYTHONPATH=src .venv/bin/python scripts/polish_camera.py <clip> \
        --from camera_smooth.json --out camera_polished.json
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
from scipy.spatial.transform import Rotation, Slerp  # noqa: E402

from camlab.camera_file import degenerate_from, write_camera  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402

#: A frame is worth trying only if it is this much worse than the clip's own median. Relative,
#: because 6 px is bad on a clip that sits at 1.6 and ordinary on one that sits at 5.8, and the
#: clips here span both.
OUTLIER_RATIO = 1.6

#: …and never below this, so a clip that is uniformly excellent is left alone instead of being
#: churned for a tenth of a pixel.
OUTLIER_FLOOR_PX = 2.0


def score(info, i, focal, rvec, pos, cx, cy) -> tuple[float, int]:
    """`(worst marking's own median distance to the paint, markings scored)` for one frame."""
    r = frame_residual(info.frame_path(i), focal, rvec, pos, frame=i, cx=cx, cy=cy)
    return float(r.worst_line_px), int(r.n_markings)


def interpolate(rot_a, rot_b, f_a, f_b, p_a, p_b, t: float):
    """A camera `t` of the way from a to b. Rotations by slerp, not by averaging Rodrigues vectors.

    Averaging rvecs is wrong in general — they are an axis times an angle, and the mean of two of
    them is not the rotation halfway between. It looks right for small differences, which is
    exactly how it would ship and then be wrong on the one frame where the camera swings.
    """
    key = Slerp([0.0, 1.0], Rotation.from_rotvec([np.asarray(rot_a, float),
                                                  np.asarray(rot_b, float)]))
    return (key([t])[0].as_rotvec(),
            float(f_a + (f_b - f_a) * t),
            np.asarray(p_a, float) + (np.asarray(p_b, float) - np.asarray(p_a, float)) * t)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--from", dest="src", default="camera_smooth.json")
    ap.add_argument("--out", default="camera_polished.json")
    ap.add_argument("--outlier-ratio", type=float, default=OUTLIER_RATIO)
    ap.add_argument("--floor-px", type=float, default=OUTLIER_FLOOR_PX)
    ap.add_argument("--no-refit", dest="refit", action="store_false",
                    help="offer the neighbours as they are, without a Levenberg-Marquardt polish")
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    cam = json.loads((info.dir / args.src).read_text())
    cx, cy = float(cam["cx"]), float(cam["cy"])
    n = len(cam["frames"])
    focal = np.array(cam["focal_px"], float)
    rot = np.array(cam["rotation"], float)
    pos = np.array(cam["position"], float)

    print(f"== {args.clip} / {args.src}: {n} frames")
    w = np.full(n, np.nan)
    mk = np.zeros(n, int)
    for i in range(n):
        if focal[i] > 0:
            w[i], mk[i] = score(info, i, focal[i], rot[i], pos[i], cx, cy)
    w0 = w.copy()

    med = float(np.nanmedian(w))
    cut = max(med * args.outlier_ratio, args.floor_px)
    targets = [i for i in range(n) if not (w[i] < cut)]
    print(f"   median worst line {med:.2f} px; trying the {len(targets)} frames above {cut:.2f} px")
    if not targets:
        print("   nothing stands out — the chain left this clip even")

    segs: dict[int, np.ndarray] = {}

    def lines(i):
        if i not in segs:
            d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
            segs[i] = detect_segments(d, s, method="hough")
        return segs[i]

    won: dict[str, int] = {}
    for i in targets:
        # Neighbours worth borrowing from: the nearest frame each side that the paint likes better
        # than this one. Not simply i-1 and i+1 — on a run of bad frames those are bad too.
        left = next((j for j in range(i - 1, -1, -1) if focal[j] > 0 and w[j] < w[i]), None)
        right = next((j for j in range(i + 1, n) if focal[j] > 0 and w[j] < w[i]), None)

        cand: list[tuple[str, float, np.ndarray, np.ndarray]] = []
        for j, tag in ((left, "copy left"), (right, "copy right")):
            if j is not None:
                cand.append((tag, focal[j], rot[j], pos[j]))
        if left is not None and right is not None:
            t = (i - left) / (right - left)
            rv, f, p = interpolate(rot[left], rot[right], focal[left], focal[right],
                                   pos[left], pos[right], t)
            cand.append(("interpolate", f, rv, p))

        best = (w[i], mk[i], "kept", focal[i], rot[i], pos[i])
        for tag, f, rv, p in cand:
            trials = [(tag, f, rv, p)]
            if args.refit and len(lines(i)) >= 4:
                r = refit_frame_lm(lines(i), f, rv, p, info.width, info.height, cx, cy, frame=i)
                trials.append((tag + "+fit", r.focal_px, r.rotation, r.position))
            for name, f2, rv2, p2 in trials:
                s, m = score(info, i, f2, rv2, p2, cx, cy)
                # Strictly better AND not on fewer markings. Without the second half a camera can
                # win by pushing a marking out of frame, which is measuring less, not fitting more.
                if np.isfinite(s) and s < best[0] and m >= best[1]:
                    best = (s, m, name, f2, rv2, p2)

        if best[2] != "kept":
            w[i], mk[i], focal[i], rot[i], pos[i] = best[0], best[1], best[3], best[4], best[5]
            won[best[2]] = won.get(best[2], 0) + 1
            print(f"   frame {i:4d}: {w0[i]:7.2f} -> {w[i]:6.2f} px  ({best[2]})")
        else:
            print(f"   frame {i:4d}: {w0[i]:7.2f} px  nothing beat it — left as the chain left it")

    out = info.dir / args.out
    write_camera(out, clip_id=args.clip, model=f"{cam.get('model', args.src)}+polish",
                 frames=np.array(cam["frames"]), focal_px=focal, rotation=rot, position=pos,
                 width=info.width, height=info.height, cx=cx, cy=cy,
                 degenerate=degenerate_from(focal),
                 notes={"polished_from": args.src, "frames_changed": int((w != w0).sum()),
                        "what_won": won})

    from camlab.measure.verdict import judge

    v = judge(args.clip, {"cx": cx, "cy": cy, "focal_px": focal.tolist(),
                          "rotation": rot.tolist(), "position": pos.tolist()})
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(w0):6.2f} px  ->  {np.nanmedian(w):6.2f} px")
    print(f"   worst frame         {np.nanmax(w0):6.2f} px  ->  {np.nanmax(w):6.2f} px")
    print(f"   frames changed      {int((w != w0).sum())} of {n}"
          + (f"   ({', '.join(f'{k} {v_}' for k, v_ in sorted(won.items()))})" if won else ""))
    print(f"   {v.line()}")


if __name__ == "__main__":
    main()
