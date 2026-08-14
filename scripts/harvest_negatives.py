#!/usr/bin/env python3
"""Label every detected segment as a marking or not, so #14 has something to be measured against.

#14 — reject non-markings — has been parked twice for the same reason, and it is not a lack of
ideas. It is that **a discriminator cannot be evaluated on a clip that has nothing to discriminate**
(`straightness-is-not-the-discriminator-length-is.md`). The class counts on the clips that were on
disk when that was written:

    fan          208 markings    88 others
    broadcast    118              7
    g15449383      3             19

Both apparent reversals of the straightness finding rested on 7 and 3 observations. So the register
already knows the shape of the problem: nothing separates until there are enough of both classes,
and `broadcast`'s turf is too clean to supply negatives while `g15449383` sees too little pitch to
supply positives.

The pitch-level clips are the other case entirely. Shot from the touchline, a frame holds a hedge,
advertising boards, a tree line and mowing stripes — every one of them a straight bright ridge with
turf on both sides, which is exactly what `paint_masks` is looking for. They are the negatives this
task has never had.

**A label here is only as good as the camera that produced it.** A segment is called junk when no
model marking lands along it, so a wrong camera relabels every real marking as junk and the whole
set becomes noise pointing the wrong way. Frames are therefore harvested only where the residual
says the camera is actually supported — `MIN_SUPPORTING_MARKINGS` markings or better — and the
count of frames skipped for that reason is reported rather than quietly dropped.

    PYTHONPATH=src python scripts/harvest_negatives.py g11710897 --camera camera_polished.json
    PYTHONPATH=src python scripts/harvest_negatives.py --report out/negatives-*.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.camera_file import read_camera  # noqa: E402
from camlab.measure.line_error import (  # noqa: E402
    clip_to_image,
    line_errors,
    straight_markings,
)
from camlab.measure.lines import detect_segments, on_paint_fraction  # noqa: E402
from camlab.measure.residual import MIN_SUPPORTING_MARKINGS, frame_evidence_cached  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402


def _sag_px(seg: np.ndarray, spine: np.ndarray, tol_px: float = 2.5) -> float:
    """How far the paint under a segment bows away from the straight line through its ends.

    **Recorded, not used, because as written it cannot mean what it says.** Membership in the band
    is `|perp| <= tol_px` and the answer is `max |perp|` over that same band, so the value is
    capped at `tol_px` by construction. It duly separated the classes at 0.842 on `fan` — entirely
    an artefact of segments piling up against the cap, which a cut sweep exposed at once: every
    threshold from 2.5 upward keeps 100 % of both classes, and 2.0 keeps 40 % against 5 %.

    Widening the band does not fix it, it moves the cap. Straightness was measured properly under
    #17 and the answer there is that it does not discriminate and points the wrong way
    (`straightness-is-not-the-discriminator-length-is.md`); this column exists so that conclusion
    is not accidentally re-derived from a saturated number.
    """
    a, b = seg[:2], seg[2:]
    ab = b - a
    n = float(np.linalg.norm(ab))
    if n < 1e-6 or not len(spine):
        return float("nan")
    d = ab / n
    rel = spine - a
    t = rel @ d
    perp = rel @ np.array([-d[1], d[0]])
    near = (t >= 0) & (t <= n) & (np.abs(perp) <= tol_px)
    return float(np.abs(perp[near]).max()) if near.sum() >= 8 else float("nan")


def _nearest_marking_px(seg: np.ndarray, model_uv: list[np.ndarray]) -> float:
    """Distance from a segment's midpoint to the closest projected marking, matched or not.

    The check that has to come before any conclusion drawn from these labels. `_assign_in_order`
    gives each model marking **one** detected segment, so where a marking arrives broken in two the
    second piece is labelled junk — a real marking in the negative class, and one that looks exactly
    like a marking under every feature. A genuine negative is far from every marking; a labelling
    artefact sits on top of one.
    """
    if not model_uv:
        return float("inf")
    mid = np.array([(seg[0] + seg[2]) / 2.0, (seg[1] + seg[3]) / 2.0])
    best = np.inf
    for uv in model_uv:
        a, b = uv[0], uv[1]
        ab = b - a
        n2 = float(ab @ ab)
        t = 0.0 if n2 < 1e-9 else float(np.clip((mid - a) @ ab / n2, 0.0, 1.0))
        best = min(best, float(np.linalg.norm(mid - (a + t * ab))))
    return best


def _nearest_arc_px(seg: np.ndarray, arc_uv: np.ndarray) -> float:
    """Distance from a segment's midpoint to the nearest projected ARC point.

    Found by looking at the labelled render rather than at the numbers, which is the whole argument
    for looking. On `g14604660` frame 5 two segments sit exactly on the penalty D and are labelled
    junk, because `line_errors` only knows `straight_markings()` and an arc has no straight
    counterpart. They are paint, and a filter trained with them in the negative class learns to
    throw arcs away — on a pitch whose arcs are 9-25 % of every clip's line set.
    """
    if not len(arc_uv):
        return float("inf")
    mid = np.array([(seg[0] + seg[2]) / 2.0, (seg[1] + seg[3]) / 2.0])
    return float(np.min(np.linalg.norm(arc_uv - mid, axis=1)))


def _projected_arcs(cam, idx, info, cx, cy) -> np.ndarray:
    """Every curved marking's sample points, projected and kept where they land in the image."""
    from camlab.measure.ellipse import arc_markings
    from camlab.measure.residual import world_to_image

    h = world_to_image(float(cam["focal_px"][idx]), cam["rotation"][idx], cam["position"][idx],
                       info.width, info.height, cx=cx, cy=cy)
    out = []
    for world in arc_markings():
        q = np.column_stack([world, np.ones(len(world))]) @ h.T
        ok = np.abs(q[:, 2]) > 1e-9
        if not ok.any():
            continue
        uv = q[ok, :2] / q[ok, 2, None]
        uv = uv[np.isfinite(uv).all(axis=1)]
        inside = ((uv[:, 0] >= -50) & (uv[:, 0] < info.width + 50)
                  & (uv[:, 1] >= -50) & (uv[:, 1] < info.height + 50))
        if inside.any():
            out.append(uv[inside])
    return np.vstack(out) if out else np.zeros((0, 2))


def _projected_markings(cam, idx, info, cx, cy) -> list[np.ndarray]:
    """Every straight model marking that reaches the image, clipped to it."""
    from camlab.measure.residual import world_to_image

    h = world_to_image(float(cam["focal_px"][idx]), cam["rotation"][idx], cam["position"][idx],
                       info.width, info.height, cx=cx, cy=cy)
    out = []
    for _k, world in straight_markings():
        q = np.column_stack([world, np.ones(2)]) @ h.T
        if np.any(np.abs(q[:, 2]) < 1e-9):
            continue
        uv = q[:, :2] / q[:, 2, None]
        if not np.isfinite(uv).all():
            continue
        vis = clip_to_image(uv, info.width, info.height)
        if vis is not None and np.linalg.norm(vis[1] - vis[0]) >= 40.0:
            out.append(vis)
    return out


def harvest(clip_id: str, camera_name: str) -> dict:
    info = ClipInfo.load(clip_id)
    cam = read_camera(info.dir / camera_name)
    # The CAMERA's optical axis, not the clip's. They are not the same number and the difference is
    # not small: `fan` solved at (540, 304) and `ClipInfo.principal_point` derives (540, -334), 638
    # px apart, because the clip is a crop and that property answers "where is the axis in the
    # SOURCE frame". Passing the clip's value here scored 1 model marking and 0 matches on a frame
    # that has 8 and 7. `line_errors`' own docstring recommended the clip's value, which is how
    # this happened; it now says otherwise.
    cx = float(cam.get("cx", info.principal_point[0]))
    cy = float(cam.get("cy", info.principal_point[1]))
    rows: list[dict] = []
    skipped: list[int] = []
    used: list[int] = []

    for idx, frame in enumerate(cam["frames"]):
        frame = int(frame)
        path = info.frame_path(frame)
        if not path.exists():
            continue
        got = frame_evidence_cached(path)
        if got is None:
            continue
        dist, surface, spine = got[0], got[1], got[2]

        segs = detect_segments(dist, surface)
        if not len(segs):
            continue
        errs = line_errors(segs, float(cam["focal_px"][idx]), cam["rotation"][idx],
                           cam["position"][idx], info.width, info.height, cx=cx, cy=cy)
        hit = sum(1 for e in errs if e.found_uv is not None)
        if hit < MIN_SUPPORTING_MARKINGS:
            skipped.append(frame)
            continue
        used.append(frame)
        model_uv = _projected_markings(cam, idx, info, cx, cy)
        arc_uv = _projected_arcs(cam, idx, info, cx, cy)

        matched = {tuple(np.round(np.asarray(e.found_uv, float).ravel(), 4))
                   for e in errs if e.found_uv is not None}
        for s in segs:
            key = tuple(np.round(np.asarray([[s[0], s[1]], [s[2], s[3]]], float).ravel(), 4))
            v = np.array([(s[1] + s[3]) / 2.0])
            rows.append({
                "clip": clip_id, "frame": frame,
                "is_marking": key in matched,
                "length_px": float(np.hypot(s[2] - s[0], s[3] - s[1])),
                "on_paint": float(on_paint_fraction(s, dist)),
                "sag_px": _sag_px(np.asarray(s, float), spine),
                "row_frac": float(v[0] / info.height),
                "angle_deg": float(np.degrees(np.arctan2(s[3] - s[1], s[2] - s[0])) % 180.0),
                "nearest_marking_px": _nearest_marking_px(np.asarray(s, float), model_uv),
                "nearest_arc_px": _nearest_arc_px(np.asarray(s, float), arc_uv),
            })

    return {"clip": clip_id, "camera": camera_name, "rows": rows,
            "frames_used": used, "frames_skipped_unsupported": skipped,
            "min_supporting_markings": MIN_SUPPORTING_MARKINGS}


#: A segment labelled "not a marking" that sits this close to a projected marking is a labelling
#: artefact, not a negative: `_assign_in_order` gives each model marking ONE detected segment, so
#: where a marking arrives broken in two the second piece falls into the negative class looking
#: exactly like a marking. Measured on `fan`, the two classes are cleanly bimodal and this cut sits
#: in the empty middle - 66 of 394 negatives lie within 5 px, 67 within 20, and the rest have a
#: median gap of 54 px. Excluding them costs 17 % of the negatives and removes the only ones that
#: would teach a filter to reject real paint.
ARTEFACT_GAP_PX = 5.0

#: And a segment this close to a projected ARC is paint too. `line_errors` only knows the straight
#: markings, so every chord detected along the centre circle or a penalty D lands in the negative
#: class looking like junk. The share is wildly clip-dependent - 2.4 % of `fan`'s negatives, 3.6 %
#: of `broadcast`'s, and **35 % of `g14604660`'s** - so a filter validated without this cut learns,
#: on exactly the clips that matter, to throw away arcs. Same 5 px as above, for the same reason:
#: it is the width either class is resolved to.
ARC_GAP_PX = 5.0


def report(paths: list[Path], gap_px: float = ARTEFACT_GAP_PX,
           arc_px: float = ARC_GAP_PX) -> None:
    rows: list[dict] = []
    for p in paths:
        blob = json.loads(p.read_text())
        rows += blob["rows"]
        print(f"{blob['clip']:20} {len(blob['rows']):5d} segments   "
              f"{len(blob['frames_used'])} frames used, "
              f"{len(blob['frames_skipped_unsupported'])} skipped as unsupported")
    if not rows:
        print("no segments at all")
        return

    yes = [r for r in rows if r["is_marking"]]
    raw_no = [r for r in rows if not r["is_marking"]]
    near_line = [r for r in raw_no if r.get("nearest_marking_px", float("inf")) <= gap_px]
    rest = [r for r in raw_no if r.get("nearest_marking_px", float("inf")) > gap_px]
    on_arc = [r for r in rest if r.get("nearest_arc_px", float("inf")) <= arc_px]
    no = [r for r in rest if r.get("nearest_arc_px", float("inf")) > arc_px]
    print(f"\n{len(yes)} markings, {len(no)} non-markings")
    print(f"  dropped from the negative class: {len(near_line)} second pieces of a straight "
          f"marking, {len(on_arc)} chords lying on an arc - both are paint")
    if len(no) < 30:
        print("!! too few negatives to conclude anything - the register has been caught three "
              "times reading a reversal off single-digit counts")

    print(f"\n{'feature':12} {'markings med':>13} {'others med':>12} {'separation':>11}")
    for f in ("length_px", "on_paint", "row_frac"):
        a = np.array([r[f] for r in yes], float)
        b = np.array([r[f] for r in no], float)
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if not len(a) or not len(b):
            continue
        ma, mb = float(np.median(a)), float(np.median(b))
        # Rank-based, so it does not assume either class is normal and cannot be inflated by one
        # extreme segment: the share of (marking, non-marking) pairs the feature orders correctly.
        auc = float((a[:, None] > b[None, :]).mean() + 0.5 * (a[:, None] == b[None, :]).mean())
        print(f"{f:12} {ma:13.2f} {mb:12.2f} {max(auc, 1 - auc):11.3f}")
    print("\nseparation is AUC folded to [0.5, 1]: 0.5 is useless, 1.0 is perfect.")
    print("sag_px and nearest_marking_px are deliberately absent: the first is capped by its own\n"
          "band and the second is what the artefact cut is made on, so both would score high for\n"
          "reasons that say nothing about a segment.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("clip", nargs="?")
    ap.add_argument("--camera", default="camera_polished.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--report", nargs="*", type=Path)
    ap.add_argument("--gap-px", type=float, default=ARTEFACT_GAP_PX,
                    help="a negative closer than this to a marking is a labelling artefact")
    ap.add_argument("--arc-px", type=float, default=ARC_GAP_PX,
                    help="a negative closer than this to a projected arc is a chord of it")
    args = ap.parse_args()

    if args.report is not None:
        report(args.report, args.gap_px, args.arc_px)
        return
    if not args.clip:
        ap.error("give a clip, or --report with the files to summarise")

    got = harvest(args.clip, args.camera)
    out = Path(args.out or f"out/negatives-{args.clip}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(got, indent=1))
    n_yes = sum(1 for r in got["rows"] if r["is_marking"])
    print(f"{args.clip}: {len(got['rows'])} segments "
          f"({n_yes} markings, {len(got['rows']) - n_yes} others) "
          f"over {len(got['frames_used'])} frames, "
          f"{len(got['frames_skipped_unsupported'])} skipped as unsupported -> {out}")


if __name__ == "__main__":
    main()
