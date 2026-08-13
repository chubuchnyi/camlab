"""Find the frames the solve lost and re-seed each from its nearest good neighbour, until a round
changes nothing.

A chain seeds every frame from the previous one whether or not that one converged, so one bad frame
poisons its successors — which is why the anchor-free solve reaches 2.4 px median and still leaves
about fifty frames of a hundred and twenty above 20 px.

This is what a human did by hand: they fixed 51, 66-77, 86 and 87, every one a frame whose
NEIGHBOURS were already good, and every fix landed at 1.6-3.5 px. Nothing in that needed a person.
A lost frame announces itself in two ways that cost nothing to check:

    its paint error is high, or
    its scored-sample count has collapsed — frames 76, 77 and 86 had 25, 25 and 69 against a
    normal ~160, which is a camera pointing somewhere with almost no pitch in it

The neighbour's camera is then carried across the gap by the same image→image homography the chain
uses, measured directly for that jump rather than composed frame by frame, and refit. It is kept
only if the PAINT agrees better — the metric the optimiser does not see.

Run:  .venv/bin/python scripts/solve_selfheal.py [clip] [--from camera_nohand.json]
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

from camlab.camera_file import degenerate_from, write_camera  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.pixel_motion import measure_pairs  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--from", dest="src", default="camera_nohand.json")
    ap.add_argument("--out", default="camera_healed.json")
    ap.add_argument("--bad-px", type=float, default=20.0)
    ap.add_argument("--bad-spot-px", type=float, default=40.0,
                    help="a frame is also lost if its worst SPOT exceeds this, however good its "
                         "worst LINE looks. A human spotted frame 92 by eye at 11.4 px of worst "
                         "line and 69.6 px of worst spot: the marking sits on its paint in the "
                         "middle and is 70 px out at the end, pivoted, which a mid-overlap offset "
                         "cannot see")
    ap.add_argument("--min-coverage", type=float, default=0.5,
                    help="a frame scoring under this fraction of the clip's median sample count "
                         "is lost regardless of what its error reads")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--hold-position", action="store_true",
                    help="keep every camera centre where it is. Required when healing a solve that "
                         "already shares ONE centre, or the repair quietly un-fixes the thing that "
                         "made the trajectory renderable")
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    src = json.loads((info.dir / args.src).read_text())
    cx, cy = float(src["cx"]), float(src["cy"])
    n = len(src["frames"])

    focal = np.array(src["focal_px"], float)
    rot = np.array(src["rotation"], float)
    pos = np.array(src["position"], float)
    healed = np.zeros(n, int)
    chose: dict[int, str] = {}

    seg_cache: dict[int, np.ndarray] = {}

    def segs(i):
        if i not in seg_cache:
            d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
            seg_cache[i] = detect_segments(d, s, method="hough")
        return seg_cache[i]

    def score(i, f=None, rv=None, c=None):
        r = frame_residual(info.frame_path(i), focal[i] if f is None else f,
                           rot[i] if rv is None else rv, pos[i] if c is None else c,
                           frame=i, cx=cx, cy=cy)
        spot = max((v[2] for v in r.per_line.values() if v[1] >= 8), default=float("nan"))
        return r.worst_line_px, r.n, float(spot)

    w = np.empty(n)
    ns = np.empty(n, int)
    sp = np.empty(n)
    for i in range(n):
        w[i], ns[i], sp[i] = score(i)
    w0, sp0 = w.copy(), sp.copy()

    def bad_set():
        floor = args.min_coverage * float(np.median(ns))
        # Three ways to be lost, and the third was added because a human found a frame the first
        # two called fine.
        return {i for i in range(n)
                if not (w[i] < args.bad_px)
                or not (sp[i] < args.bad_spot_px)
                or ns[i] < floor}

    print(f"== {args.clip}: {n} frames from {args.src}")
    print(f"   start: median {np.nanmedian(w):.2f} px, {int(np.nansum(w < args.bad_px))} under "
          f"{args.bad_px:.0f} px, worst-spot median {np.nanmedian(sp):.1f} px, "
          f"coverage median {int(np.median(ns))} samples")

    for rnd in range(1, args.rounds + 1):
        bad = sorted(bad_set())
        good = [i for i in range(n) if i not in bad]
        if not bad:
            print(f"   round {rnd}: nothing left to fix")
            break
        if not good:
            print(f"   round {rnd}: every frame is bad — nothing to re-seed FROM. Stopping.")
            break

        fixed = 0
        for i in bad:
            # BOTH directions, then keep whichever the paint prefers. Taking simply the nearest
            # good frame left frames 69-78 and 91-98 unfixed through four rounds: they are long
            # contiguous blocks, so the one neighbour on offer was far away and whichever side it
            # happened to be on was the only side tried. A human looking at the same file picked
            # exactly those blocks out and said to try the right, then the left, and compare.
            # Every candidate that costs anything, then let the PAINT choose. A human fixed all
            # thirteen frames this could not, by plain-copying a neighbour with no carry and no
            # refit — 3.8 px where carry-then-refit had left 64.0, and 9.8 where it had left 131.8.
            #
            # Which is to say the carry is a HYPOTHESIS, not a correction. It assumes the measured
            # homography is trustworthy across the gap; when it is not, moving the camera by it is
            # worse than not moving at all. And the refit is a second hypothesis on top: from a
            # seed in the wrong basin it converges confidently to the wrong answer. Neither is
            # reliable enough to apply unconditionally, and both are cheap enough to just try.
            cands = []
            left = max((g for g in good if g < i), default=None)
            right = min((g for g in good if g > i), default=None)

            def offer(f_, rv_, c_, tag, gap, _i=i, _out=cands):
                nw, nn, nsp = score(_i, f_, rv_, c_)
                if np.isfinite(nw):
                    _out.append((nsp if np.isfinite(nsp) else nw, nw, nn, nsp, gap, tag,
                                 (f_, rv_, c_)))

            for j, side in ((right, "right"), (left, "left")):
                if j is None:
                    continue
                gap = abs(i - j)
                # 1. the neighbour's camera, copied verbatim
                offer(focal[j], rot[j], pos[j], f"copy {side}", gap)
                # 2. the same, refined here
                r = refit_frame_lm(segs(i), focal[j], rot[j], pos[j], info.width, info.height,
                                   cx, cy, free_position=not args.hold_position)
                offer(r.focal_px, r.rotation, r.position, f"copy+fit {side}", gap)
                # 3. carried across the gap by the measured homography
                pairs = measure_pairs({min(i, j): info.frame_path(min(i, j)),
                                       max(i, j): info.frame_path(max(i, j))}, gaps=(gap,))
                if not pairs:
                    continue
                h = pairs[0].h if j < i else np.linalg.inv(pairs[0].h)
                moved = carry(focal[j], rot[j], pos[j], h, cx, cy)
                if moved is None:
                    continue
                offer(moved.focal_px, moved.rotation, moved.position, f"carry {side}", gap)
                # 4. carried, then refined
                r = refit_frame_lm(segs(i), moved.focal_px, moved.rotation, moved.position,
                                   info.width, info.height, cx, cy,
                                   free_position=not args.hold_position)
                offer(r.focal_px, r.rotation, r.position, f"carry+fit {side}", gap)

            if not cands:
                continue
            _key, nw, nn, nsp, gap, tag, cam = min(cands, key=lambda c: c[0])
            # The PAINT decides, not the objective the refit just minimised. A camera that talked
            # its own objective down while drifting off the paint is the failure mode this whole
            # repo keeps rediscovering.
            better = (not np.isfinite(w[i]) or nw < w[i]) or (np.isfinite(nsp) and nsp < sp[i])
            # Coverage is judged against the CLIP's normal, not against this frame's current count.
            # Judging it against the current count blocked the right answer on every frame that
            # mattered: a badly aimed camera can score MORE samples than a correct one — frame 69
            # had 290 while the fix that took it from 64.0 px to 3.8 px had 161, because the wrong
            # camera still lands markings on the turf, just not where the paint is. Demanding 90 %
            # of 290 rejected 161 and left the frame broken.
            if better and nw <= max(w[i], args.bad_px) and nn >= 0.7 * float(np.median(ns)):
                focal[i], rot[i], pos[i] = cam
                w[i], ns[i], sp[i] = nw, nn, nsp
                healed[i] = gap
                chose[i] = tag
                fixed += 1

        print(f"   round {rnd}: {len(bad)} bad, fixed {fixed}, "
              f"median now {np.nanmedian(w):.2f} px, {int(np.nansum(w < args.bad_px))} under "
              f"{args.bad_px:.0f} px")
        if fixed == 0:
            print("   a round changed nothing — stopping rather than spinning")
            break

    out = write_camera(
        info.dir / args.out, model=f"{src['model']}+selfheal", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(src["frames"], int),
        focal_px=focal, position=pos, rotation=rot, cx=cx, cy=cy,
        # Derived from what is being written, not carried over from the source: a frame this
        # stage just repaired must stop being flagged as one the solver could not use.
        degenerate=degenerate_from(focal),
        healed_from=args.src, healed_gap=healed.tolist(),
        healed_by={str(k): v for k, v in chose.items()},
        notes=("Frames the solve lost, re-seeded from their nearest surviving neighbour through a "
               "directly measured image-to-image homography. `healed_gap` is how far each frame "
               "had to reach for a good one — 0 means it was never in trouble."),
    )
    from camlab.measure.verdict import judge

    v = judge(args.clip, {"cx": cx, "cy": cy, "focal_px": focal.tolist(),
                          "rotation": rot.tolist(), "position": pos.tolist()})
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(w0):6.2f} px  ->  {np.nanmedian(w):6.2f} px")
    print(f"   frames under {args.bad_px:.0f} px  {int(np.nansum(w0 < args.bad_px)):6d}     ->  "
          f"{int(np.nansum(w < args.bad_px)):6d}   of {n}")
    print(f"   worst spot, median  {np.nanmedian(sp0):6.2f} px  ->  {np.nanmedian(sp):6.2f} px")
    print(f"   frames re-seeded    {int((healed > 0).sum())}, reaching up to "
          f"{int(healed.max())} frames away")
    if chose:
        from collections import Counter
        tally = Counter(v.split()[0] for v in chose.values())
        print("   what won:           " + ", ".join(f"{k} {v}" for k, v in tally.most_common()))
    # LAST, because `solve/pipeline.py` summarises a stage by its FINAL line of output and
    # the viewer shows that. "40 of 40 frames under 20 px" as that line is how a clip
    # scoring TWO markings reads as solved — g11710897 printed exactly that today, and
    # its real verdict is "NO VERDICT, 2 markings/frame, 63 samples".
    print(f"   {v.line()}")


if __name__ == "__main__":
    main()
