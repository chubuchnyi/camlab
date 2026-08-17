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


from camlab.camera_file import degenerate_from, write_camera  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.pixel_motion import measure_pairs  # noqa: E402
from camlab.measure.residual import frame_evidence_cached, frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.hand import hand_candidates  # noqa: E402
from camlab.solve.refit import refit_frame, refit_frame_lm  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--anchor", default="0",
                    help="comma-separated frame numbers; each frame is carried from its nearest")
    ap.add_argument("--seed", default="camera_auto.json")
    ap.add_argument("--hand-key", default=None,
                    help="which camera the operator's edits are keyed to, when that is not the "
                         "seed's own name. The pipeline snapshots a seed it is about to overwrite "
                         "to camera_seed_used.json, and the edits stay keyed to the original.")
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
    ap.add_argument("--no-carry", action="store_true",
                    help="measure no motion at all and let every frame refit from its neighbour's "
                         "camera. THE CONTROL, not a mode to solve in: a causal tracker measured "
                         "the homography to be worth nothing on seven clips, and this asks the "
                         "same question of the shipped chain instead of a script resembling it")
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    seed = json.loads((info.dir / args.seed).read_text())
    cx, cy = float(seed["cx"]), float(seed["cy"])
    n = len(seed["frames"])

    def paint_worst(i, focal, rvec, centre) -> tuple[int, float]:
        """`(markings scored, the worst one's own median distance to the paint)` on frame `i`.

        **Both, and the count first.** `worst_line_px` is a max over the markings a frame scores, so
        a camera holding three of them and one holding seven are not being measured by the same
        statistic and cannot be ranked against each other by that number. Comparing them anyway is
        how the operator's own anchor on `g11710897` — 22.51 px on **7 markings** — lost to the
        seed's untouched pose at 16.61 px on **3**, and the whole clip stayed unsolvable because the
        chain then ran from a camera whose focal was 32 % out and which had pushed four markings off
        the picture.

        This repo already names the rule as `MIN_SUPPORTING_MARKINGS`, and the anchor chooser I
        wrote this morning broke it.
        """
        r = frame_residual(info.frame_path(i), focal, rvec, centre, frame=i, cx=cx, cy=cy)
        return int(r.n_markings), float(r.worst_line_px)

    # BOTH stores offer candidates and the PAINT picks. Ranking by store is what broke this the
    # first time it was fixed: preferring the run's own file put `fan --anchor 0` on a 31.55 px
    # anchor where `calib/` holds 5.30, and frame 51 on 102.01 px against 2.17. Where an anchor was
    # recorded says nothing about whether it is a good one, and the frames are right here.
    #
    # Clip-scoped position writes are dropped before the choice — 117 of `fan`'s 120 manual entries
    # are the "position applies to the whole clip" tick-box, not an aim. See `solve/hand.py`.
    # Keyed to whatever the operator aimed AGAINST, which is not always the file being read. The
    # pipeline copies a seed it is about to overwrite to `camera_seed_used.json` and reads the copy;
    # the edits stay keyed to the original, and looking them up under the copy's name finds none.
    # That combination silently refitted every anchor from the seed's own pose on `g11710897` —
    # anchor list correct, anchors themselves gone.
    candidates = hand_candidates(
        info.dir, args.hand_key or args.seed, seed_camera=seed,
        calib_dir=Path(__file__).resolve().parent.parent / "calib", clip_id=args.clip)
    if args.no_hand:
        candidates = {}
    anchors = sorted({int(a) for a in str(args.anchor).split(",") if a.strip() != ""})
    if not anchors or anchors[0] < 0 or anchors[-1] >= n:
        raise SystemExit(f"anchors {anchors} must all be within 0..{n - 1}")

    print(f"== {args.clip}: {n} frames, anchors {anchors}, K = ({cx:.0f}, {cy:.0f})")

    hand: dict[str, dict] = {}
    for a in anchors:
        offers = candidates.get(str(a), [])
        if not offers:
            continue
        # The seed's own pose is a candidate too, and it wins when every hand aim is worse than it.
        scored = [(paint_worst(a, seed["focal_px"][a], seed["rotation"][a], seed["position"][a]),
                   "the solve itself", None)]
        scored += [(paint_worst(a, e["focal_px"], e["rotation"], e["position"]), src, e)
                   for src, e in offers]
        # Most markings first, then the lowest error among those. A camera that sees more of the
        # pitch is being asked a harder question, and winning the easier one is not winning.
        scored.sort(key=lambda r: (-r[0][0], np.isnan(r[0][1]), r[0][1]))
        best, src, entry = scored[0]
        for (mk, w), s_, _e in scored:
            print(f"   anchor {a}: {w:8.2f} px on {mk:2d} markings  {s_}")
        if entry is not None:
            hand[str(a)] = entry
        print(f"   anchor {a}: using {src} at {best[1]:.2f} px on {best[0]} markings")

    by_hand = [a for a in anchors if str(a) in hand]
    # Said out loud, because "the anchor you aimed was ignored" is invisible in the result: the
    # chain still reports 120 of 120 frames and a plausible focal range.
    if not by_hand:
        print("   NO HAND ANCHOR IS BEING USED — every anchor is refitted from the seed's "
              "own pose. If you aimed one in the viewer, the paint preferred the solve to it.")

    if args.no_carry:
        pairs, h_of = [], {}
        print("   --no-carry: no motion measured, every frame refits from its neighbour's camera")
    else:
        pairs = measure_pairs({f: info.frame_path(f) for f in range(n)}, gaps=(1,))
        h_of = {(p.i, p.j): p for p in pairs}
        print(f"   {len(pairs)}/{n - 1} consecutive pairs, median reprojection "
              f"{np.median([p.median_px for p in pairs]):.2f} px")

    fit = refit_frame if args.nelder_mead else refit_frame_lm
    print("   refit: " + ("Nelder-Mead on the scalar objective" if args.nelder_mead
                          else "Levenberg-Marquardt on the endpoint residuals"))

    # Through the evidence cache, not around it. This called `paint_masks` directly, so the paint
    # it detected was invisible to `frame_residual`, which then detected the same pixels again for
    # the same frame — 120 `paint_masks` on a 60-frame clip where 60 is the information content.
    def segs(i):
        d, s = frame_evidence_cached(info.frame_path(i))[:2]
        return detect_segments(d, s, method="hough")

    # A frame's before/after pair, taken the moment that frame is FINAL. It used to be a separate
    # sweep over the whole clip after the carry finished, and `EVIDENCE_CACHE` holds four frames,
    # so by then every frame's paint had been evicted and was detected a second time. Every frame
    # is assigned exactly once — anchors in the loop below, the rest in the carry loop, and the
    # `bounds` are disjoint — so taking the pair at that moment is the same number, one paint
    # earlier.
    before_of: dict[int, float] = {}
    after_of: dict[int, float] = {}

    def sweep(k: int) -> None:
        before_of[k] = frame_residual(info.frame_path(k), seed["focal_px"][k],
                                      seed["rotation"][k], seed["position"][k],
                                      frame=k, cx=cx, cy=cy).worst_line_px
        after_of[k] = frame_residual(info.frame_path(k), focal[k], rot[k], pos[k],
                                     frame=k, cx=cx, cy=cy).worst_line_px

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
            # `free_position` too. It was missing here while the per-frame refit below had it, so
            # the one frame the whole chain hangs off was fitted with its position nailed down.
            # Measured on `CRO_MOR_194948` frame 0: 7.06 px locked against 3.67 px free.
            r = fit(segs(a), focal[a], rot[a], pos[a], info.width, info.height, cx, cy,
                    free_position=args.free_position)
            focal[a], rot[a], pos[a] = r.focal_px, r.rotation, r.position
        drift[a] = 0
        sweep(a)

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
                sweep(j)
                i = j
        print(f"      anchor {a}: frames {lo}..{hi} done", flush=True)

    # Anything an anchor's range did not reach — there should be none, and if the bounds ever stop
    # covering the clip this catches it instead of a KeyError three lines down.
    for k in range(n):
        if k not in before_of:
            sweep(k)
    b = np.array([before_of[k] for k in range(n)])
    a = np.array([after_of[k] for k in range(n)])

    out = write_camera(
        info.dir / args.out, model=f"{seed['model']}+pixel_carry", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(seed["frames"], int),
        focal_px=focal, position=pos, rotation=rot, cx=cx, cy=cy,
        # Derived from what is being written, not carried over from the seed.
        degenerate=degenerate_from(focal),
        carried_from=args.seed, anchor_frames=anchors,
        anchors_hand_aligned=by_hand,
        carry_drift=drift.tolist(),
        notes=("Each frame's camera is the previous frame's taken through the measured image-to-"
               "image homography, then refit locally. The chain ACCUMULATES: `carry_drift` is the "
               "distance in frames from the anchor, and a large one is a reason to distrust that "
               "frame rather than a decoration."),
    )
    from camlab.measure.verdict import judge

    v = judge(args.clip, {"cx": cx, "cy": cy, "focal_px": focal.tolist(),
                          "rotation": rot.tolist(), "position": pos.tolist()})
    print(f"\n== wrote {out} in {time.time() - t0:.0f}s")
    print(f"   worst line, median  {np.nanmedian(b):7.1f} px  ->  {np.nanmedian(a):7.1f} px")
    print(f"   frames under 20 px  {int(np.nansum(b < 20)):7d}     ->  {int(np.nansum(a < 20)):7d}"
          f"   of {n}")
    print(f"   frames the metric cannot score at all: {int(np.isnan(b).sum())} -> "
          f"{int(np.isnan(a).sum())}")
    # LAST, because `solve/pipeline.py` summarises a stage by its FINAL line of output and
    # the viewer shows that. "40 of 40 frames under 20 px" as that line is how a clip
    # scoring TWO markings reads as solved — g11710897 printed exactly that today, and
    # its real verdict is "NO VERDICT, 2 markings/frame, 63 samples".
    print(f"   {v.line()}")


if __name__ == "__main__":
    main()
