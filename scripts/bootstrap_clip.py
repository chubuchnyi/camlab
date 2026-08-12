"""A first camera for a clip that has none, chosen by how well it survives being carried.

`solve/bootstrap.py` generates candidates well — family-consistent, order-preserving line
correspondences, four at a time, four thousand plausible cameras in twelve seconds. Choosing among
them on ONE frame does not work: the best by paint came back 113 m from the truth with the focal
pinned at its lower bound, because a wrong camera that sees half the pitch satisfies the paint
about as well as a right one that sees all of it.

**A wrong camera is wrong differently on the next frame.** Carry each candidate through the
measured image→image homography to two frames further on, refit it there, and score all three. The
right camera holds; a wrong one falls apart, because the homography moves it as the real camera
moved and the pitch it then predicts is not the pitch that is there.

That filter costs almost nothing — both halves already exist — and it is the strongest signal
available that a single frame cannot give.

**The 180° ambiguity is not solved here and cannot be.** A football pitch is symmetric under a
half-turn about the centre spot, so `(x, y, z) → (−x, −y, z)` with yaw + 180° scores *bit for bit*
identically. Both are returned; the caller or a human picks. See `findings/bootstrap-progress.md`.

Run:  .venv/bin/python scripts/bootstrap_clip.py <clip> [--frame 0] [--top 40]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402

from camlab.camera_file import write_camera  # noqa: E402
from camlab.core.angles import (  # noqa: E402
    angles_from_rotation,
    matrix_from_rodrigues,
    rodrigues_from_matrix,
    rotation_from_angles,
)
from camlab.measure.ellipse import arc_paint_distance  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import centreline_pixels, paint_masks  # noqa: E402
from camlab.measure.pixel_motion import measure_pairs  # noqa: E402
from camlab.measure.residual import frame_residual, world_to_image  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.bootstrap import hypotheses  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402

#: Arc samples below which the arc test has no evidence and must abstain. Overridable, because
#: every measured estimator here ships one.
MIN_ARC_SAMPLES = 8


def plausible(h) -> bool:
    """A football camera: off the pitch, above head height, not at a focal bound."""
    d = float(np.linalg.norm(h.position[:2]))
    return (900.0 < h.focal_px < 12000.0) and (5.0 < h.position[2] < 45.0) and (35.0 < d < 140.0)


def half_turn(focal, rvec, pos):
    """The other camera that fits the same markings exactly. Not an alternative — a twin."""
    yaw, elev, roll = angles_from_rotation(matrix_from_rodrigues(np.asarray(rvec, float)))
    return (focal,
            rodrigues_from_matrix(rotation_from_angles(yaw + 180.0, elev, roll)),
            np.array([-pos[0], -pos[1], pos[2]]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--gaps", default="5,11", help="frames ahead to carry each candidate to")
    ap.add_argument("--top", type=int, default=40, help="candidates taken past the single frame")
    ap.add_argument("--min-samples", type=int, default=100,
                    help="loose absolute coverage floor; NOT relative to the best candidate")
    ap.add_argument("--no-arcs", dest="require_arcs", action="store_false",
                    help="do not require the curved markings to land on paint")
    ap.add_argument("--min-arc-samples", type=int, default=8,
                    help="below this many arc samples the arc test abstains rather than rejects")
    ap.add_argument("--max-arc-px", type=float, default=6.0,
                    help="how far the projected centre circle and penalty arc may sit from the "
                         "nearest paint. The true camera on fan frame 8 sits at 1.5 px")
    ap.add_argument("--max-missing", type=float, default=0.05,
                    help="reject a camera predicting markings on turf with no paint under them, "
                         "beyond this fraction. The true camera on fan frame 8 sits at 0.3%%")
    ap.add_argument("--max-hypotheses", type=int, default=60_000)
    ap.add_argument("--out", default="camera_boot.json")
    args = ap.parse_args()
    global MIN_ARC_SAMPLES
    MIN_ARC_SAMPLES = int(args.min_arc_samples)

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    cx, cy = info.principal_point
    a = args.frame
    gaps = [int(g) for g in args.gaps.split(",") if g.strip()]
    probes = [a] + [a + g for g in gaps if a + g < info.n_frames]
    if len(probes) < 2:
        raise SystemExit(f"{args.clip} has {info.n_frames} frames — not enough to carry into")

    from scipy.spatial import cKDTree

    seg, tree = {}, {}
    for i in probes:
        d, s = paint_masks(cv2.imread(str(info.frame_path(i))))
        seg[i] = detect_segments(d, s, method="hough")
        tree[i] = cKDTree(centreline_pixels(d))
    print(f"== {args.clip}: anchor {a}, carrying candidates to {probes[1:]}")
    print(f"   segments per probe frame: {[len(seg[i]) for i in probes]}")

    pairs = measure_pairs({i: info.frame_path(i) for i in probes}, gaps=gaps)
    h_of = {(p.i, p.j): p.h for p in pairs}
    missing = [g for g in gaps if (a, a + g) not in h_of]
    if missing:
        print(f"   !! no measured homography for gaps {missing} — those probes are dropped")
    probes = [a] + [a + g for g in gaps if (a, a + g) in h_of]

    def paint(i, f, rv, c):
        """`(pooled median distance, samples, fraction of markings with no paint under them)`.

        The POOLED median, not `worst_line_px`. That distinction decides everything here. Worst
        line is the right number for judging a camera that is already close — it is what catches
        one marking sitting on its neighbour's paint. For telling a right camera from a wrong one
        it is nearly useless, because a wrong camera can have one bad marking and so can a good
        one. The pooled median separates them by a factor of seven to nine:

            fan frame 8   truth       median  1.7 px, 0.3 % with no paint under them
                          a candidate median 16.3 px, 6.8 %
                          another     median 12.2 px, 2.5 %

        `n_unmatched` is the second half and it is the direct statement of the failure: the camera
        predicted a marking there and the photograph has no paint there.
        """
        r = frame_residual(info.frame_path(i), f, rv, c, frame=i, cx=cx, cy=cy)
        return r.median_px, r.n, r.n_unmatched / max(r.n, 1)

    def arcs(i, f, rv, c):
        """The curved markings, which the straight ones cannot substitute for.

        A pitch is exactly symmetric under a half-turn and its focal trades against its distance,
        so many cameras fit the LINES. Far fewer also put the centre circle and the penalty arc
        where paint actually is — and a camera that puts them off-frame entirely has not scored
        badly, it has disqualified itself.
        """
        h = world_to_image(f, rv, c, info.width, info.height, cx=cx, cy=cy)
        return arc_paint_distance(h, tree[i], info.width, info.height)

    cands = []
    arc_seen: dict[str, int] = {}
    for h in hypotheses(seg[a], info.width, info.height, cx, cy,
                        max_hypotheses=args.max_hypotheses):
        if not plausible(h):
            continue
        rv = rodrigues_from_matrix(h.rotation)
        r = refit_frame_lm(seg[a], h.focal_px, rv, h.position, info.width, info.height, cx, cy)
        w, n, miss = paint(a, r.focal_px, r.rotation, r.position)
        ad, an = arcs(a, r.focal_px, r.rotation, r.position)
        if not (np.isfinite(w) and miss <= args.max_missing):
            continue
        # The arc test STAYS STRICT, and that was measured rather than assumed.
        #
        # It has a real defect: put the solved camera through it and `fan` 40 and 80 are thrown out,
        # because the operator has zoomed until no arc is in the picture and `arc_n = 0` reads as a
        # failure rather than as no evidence. Letting it abstain there — the rule
        # `MIN_SUPPORTING_MARKINGS` applies to markings — was tried on 2026-08-12 over six anchors
        # and made things WORSE, so it is not the fix:
        #
        #   fan 0   1.0 px / 3.11 m  ->  1.2 px / 3.26 m       diluted
        #   fan 40  no answer        ->  no answer             (dies at the miss gate, not here)
        #   fan 80  no answer        ->  an answer 198.9 m out, focal +36 %, reported at 9.9 px
        #   g14604660  no answer     ->  an answer at focal 910, pinned to the 900 px floor
        #
        # Two confident wrong answers where there had been none. "No camera" is a usable result and
        # a wrong one that reports 9.9 px is not — R-6 the other way round. What the gate rejects
        # off-frame is largely cameras pointing at the wrong world, and that work is load-bearing.
        arc_says = ("on paint" if (an >= MIN_ARC_SAMPLES and ad <= args.max_arc_px)
                    else "off paint" if an >= MIN_ARC_SAMPLES else "no arc in frame")
        arc_seen[arc_says] = arc_seen.get(arc_says, 0) + 1
        if args.require_arcs and arc_says != "on paint":
            continue
        cands.append((w + (0.0 if not np.isfinite(ad) else ad), n,
                      r.focal_px, r.rotation, r.position))
    # Said out loud either way: "the arcs were not usable here" and "the arcs agreed" are different
    # amounts of evidence behind the same result, and the reader cannot tell them apart afterwards.
    if arc_seen:
        print("   arcs: " + ", ".join(f"{v} {k}" for k, v in sorted(arc_seen.items())))
        if arc_seen.get("no arc in frame", 0) and not arc_seen.get("on paint", 0):
            print("   NO ARC IS IN THIS FRAME — the centre circle and both penalty arcs are out of "
                  "the picture, so the strongest check on a half-turn twin is unavailable here.")
    if not cands:
        raise SystemExit("no plausible camera at all on the anchor frame")
    # Only a loose ABSOLUTE floor. Coverage was briefly used relative to the best candidate and
    # that is backwards: a very wide camera far away projects the whole pitch small and scores 961
    # samples where the true camera scores 307, so "70 % of the best" threw the right answer out.
    # More coverage is not more correct, and the filter that actually works is below — a wrong
    # camera does not survive being carried.
    kept = [c for c in cands if c[1] >= args.min_samples]
    kept.sort(key=lambda c: c[0])
    print(f"   {len(cands)} cameras fit the anchor, {len(kept)} with at least "
          f"{args.min_samples} samples. Carrying the top {args.top}.")

    # The carry test goes FIRST and on everything, because ranking by the single frame is exactly
    # what was shown not to work: on fan the truth is in the pool — a hypothesis 4.8 m away with
    # the focal 11 % off — and it does not reach the top sixty by single-frame paint. So carry
    # every candidate with no refit (closed form, and the paint masks are already built), keep what
    # survives, and spend the expensive refit only on those.
    rough = []
    for w0, n0, f0, rv0, p0 in kept:
        ws, ns = [w0], [n0]
        for i in probes[1:]:
            moved = carry(f0, rv0, p0, h_of[(a, i)], cx, cy)
            if moved is None:
                ws.append(float("inf"))
                continue
            w, n, miss = paint(i, moved.focal_px, moved.rotation, moved.position)
            ws.append(w if (np.isfinite(w) and miss <= args.max_missing) else float("inf"))
            ns.append(n)
        rough.append((max(ws), f0, rv0, p0))
    rough.sort(key=lambda r: r[0])
    print(f"   carried all {len(kept)} with no refit; best worst-probe {rough[0][0]:.1f} px. "
          f"Refining the top {args.top}.")

    scored = []
    for _rw, f0, rv0, p0 in rough[:args.top]:
        ws, ns, cam = [], [], None
        for i in probes:
            if i == a:
                f_, rv_, p_ = f0, rv0, p0
            else:
                moved = carry(f0, rv0, p0, h_of[(a, i)], cx, cy)
                if moved is None:
                    ws.append(float("inf"))
                    continue
                f_, rv_, p_ = moved.focal_px, moved.rotation, moved.position
            r = refit_frame_lm(seg[i], f_, rv_, p_, info.width, info.height, cx, cy)
            w, n, miss = paint(i, r.focal_px, r.rotation, r.position)
            ws.append(w if (np.isfinite(w) and miss <= args.max_missing) else float("inf"))
            ns.append(n)
            if i == a:
                cam = (r.focal_px, r.rotation, r.position)
        if cam is None:
            continue
        # The WORST of the probe frames, not the mean. A camera that is right on one frame and
        # hopeless two frames later is not a seed, and a mean lets the good frame hide that.
        scored.append((max(ws), float(np.median(ws)), min(ns) if ns else 0,
                       cam[0], cam[1], cam[2], ws))
    scored.sort(key=lambda s: s[0])

    print(f"\n   {'worst probe':>12} {'median':>8} {'min samples':>12}  focal   position"
          "     (all errors are POOLED medians)")
    for s in scored[:6]:
        print(f"   {s[0]:12.1f} {s[1]:8.1f} {s[2]:12d}  {s[3]:6.0f}  {np.round(s[5], 1)}")

    worst, med, nmin, focal, rvec, pos, ws = scored[0]
    if not np.isfinite(worst):
        raise SystemExit("nothing survived being carried — no seed found")

    n = info.n_frames
    for tag, (f, rv, p) in (("", (focal, rvec, pos)),
                            ("_flip", half_turn(focal, rvec, pos))):
        out = args.out.replace(".json", f"{tag}.json")
        write_camera(
            info.dir / out, model="line_correspondence_bootstrap", clip_id=info.clip_id,
            width=info.width, height=info.height, frames=np.arange(n),
            focal_px=np.full(n, float(f)), position=np.tile(p, (n, 1)),
            rotation=np.tile(rv, (n, 1)), cx=cx, cy=cy, degenerate=[False] * n,
            bootstrap_frame=a, probe_frames=probes, probe_errors=[float(x) for x in ws],
            half_turn=bool(tag),
            notes=("One camera, repeated on every frame, to be used as a SEED — feed it to "
                   "solve_carry.py, which will follow the operator from here. The pitch is "
                   "symmetric under a half-turn about the centre spot, so the `_flip` file fits "
                   "the markings exactly as well and nothing in them can choose between the two."),
        )
    print(f"\n== wrote {args.out} and its half-turn twin in {time.time() - t0:.0f}s")
    print(f"   worst probe {worst:.1f} px over frames {probes}, min coverage {nmin} samples")
    print(f"   focal {focal:.0f}, position {np.round(pos, 2)}")
    print("   the twin fits identically — the markings cannot say which half of the pitch this is")


if __name__ == "__main__":
    main()
