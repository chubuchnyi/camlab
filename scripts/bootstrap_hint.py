#!/usr/bin/env python3
"""What camlab can say about a clip's camera **without solving it** — a hint, not an answer.

AVATAR already finds the first camera and the expensive part there is the search. This narrows it.
Nothing here needs a camera, a seed, or the pitch model's correspondences; everything is measured
from the pixels and from the detected lines, so it is available on a clip that has never been
touched.

Three things, and each is reported with what it is worth rather than as a number to trust:

**Focal, twice, independently.**

- *vanishing points* — two perpendicular families of markings on one frame fix the focal, with no
  camera and no naming: it does not matter WHICH lines they are, only that the two families are
  perpendicular on the pitch, which on a football field they always are.
- *a long-baseline homography* — the closed form under rotation about a fixed centre. Needs a few
  degrees of turn, so the pair must be **seconds apart**: measured 96.9 % out between neighbours
  and 10.8 % out at four seconds (`findings/the-focal-from-pixels-needs-seconds-not-frames`).

They share no inputs and no assumptions. Where they agree, the agreement is the confidence — and
where they do not, that is worth knowing before a search is run against either.

**Does the camera turn, or does it travel?** `rotation_only_residual_px` is calibrated at about
**1 px per metre** of camera translation at these viewing distances. A camera on a mount and a
phone in a hand are different search problems, and this separates them without any model.

**Where the playing surface stops**, as a fraction of frame height. Not a camera height, but it
does separate a shot with sky in it from a crop that is all grass.

    PYTHONPATH=src python scripts/bootstrap_hint.py g11710897
    PYTHONPATH=src python scripts/bootstrap_hint.py --all --json out/hints.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.pixel_motion import (  # noqa: E402
    focals_from_homography,
    measure_pairs,
    rotation_only_residual_px,
)
from camlab.measure.residual import frame_evidence_cached  # noqa: E402
from camlab.runs import ClipInfo, runs_root  # noqa: E402
from camlab.solve.vanishing import focal_from_segments  # noqa: E402

#: Seconds between the two frames of a long-baseline pair. Below ~2 s the turn is under a degree
#: and the closed form is noise; the measured curve is 96.9 % out at 0.03 s, 29 % at 2 s, 10.8 % at
#: 4 s. Four is the target and two is the floor, because a short clip may not offer four.
WANT_SECONDS = (4.0, 3.0, 2.0)

#: Two independent estimates this close are treated as agreeing. Wide on purpose: the honest error
#: on the homography side alone is 11-29 %, so anything tighter would be claiming a precision
#: neither estimator has.
AGREE_FRAC = 0.30

#: Horizontal field of view a football camera can plausibly have. The gate is in DEGREES because
#: that is the unit the number means something in: the vanishing-point construction returned 97 px
#: on a 1080-wide frame for `g11710897` and 305 for `g14604660` — 200 and 120 degrees across. No
#: camera films football on either, and both were 94-95 % out.
#:
#: Why it fails there and not elsewhere: seen from pitch level the pitch is edge-on, so the two
#: marking families are nearly parallel in the image and their vanishing points collapse together.
#: The construction is ill-conditioned exactly where this branch's clips live. Measured against the
#: solved cameras, with this gate applied:
#:
#:     NET_ARG_225042   0.1 %      broadcast     25.1 %
#:     14604731         4.6 %      g11710897     rejected (was 95.0 % out)
#:     CRO_MOR_194948   5.7 %      g14604660     rejected (was 94.1 %)
#:     fan              6.3 %
#:
#: R-6 as the rest of the repo applies it: abstain where the geometry cannot answer, rather than
#: report a number that looks like one.
FOV_DEG_RANGE = (4.0, 100.0)


def _fov_deg(focal_px: float, width: int) -> float:
    return float(np.degrees(2.0 * np.arctan(width / (2.0 * focal_px))))


def _surface_top(info, frames) -> float | None:
    """Where the playing surface starts, as a fraction of frame height. `None` if never found."""
    tops = []
    for f in frames:
        got = frame_evidence_cached(info.frame_path(f))
        rows = np.where(np.asarray(got[1]).any(axis=1))[0]
        if len(rows):
            tops.append(rows.min() / info.height)
    return float(np.median(tops)) if tops else None


def _focal_from_lines(info, frames) -> tuple[float | None, int]:
    """Median focal from two perpendicular vanishing points, and how many frames answered."""
    got = []
    for f in frames:
        ev = frame_evidence_cached(info.frame_path(f))
        segs = detect_segments(ev[0], ev[1])
        if len(segs) < 4:
            continue
        r = focal_from_segments(segs, info.width / 2.0, info.height / 2.0)
        if r is None or not getattr(r, "focal_px", None) or not r.focal_px > 0:
            continue
        lo, hi = FOV_DEG_RANGE
        if not (lo <= _fov_deg(float(r.focal_px), info.width) <= hi):
            continue
        got.append(float(r.focal_px))
    return (float(np.median(got)) if got else None), len(got)


def _focal_from_motion(info, frames) -> tuple[float | None, int, float | None, float | None]:
    """`(median focal, pairs that answered, seconds used, median turn residual in px)`."""
    for want in WANT_SECONDS:
        gap = int(round(want * info.fps))
        if gap < 1 or gap >= info.n_frames:
            continue
        picks = [f for f in frames if f + gap < info.n_frames]
        if not picks:
            continue
        pairs = measure_pairs({f: info.frame_path(f)
                               for f in sorted(set(picks) | {f + gap for f in picks})},
                              gaps=(gap,))
        cx, cy = info.width / 2.0, info.height / 2.0
        focals, moved = [], []
        for p in pairs:
            f0, _f1 = focals_from_homography(p.h, cx, cy)
            if f0 and 200.0 < f0 < 30000.0:
                focals.append(f0)
            px, _fi, _fj = rotation_only_residual_px(p, cx, cy, info.width, info.height)
            if np.isfinite(px):
                moved.append(px)
        if focals:
            return (float(np.median(focals)), len(focals), want,
                    float(np.median(moved)) if moved else None)
    return None, 0, None, None


def hint(clip_id: str, n_frames: int = 8) -> dict:
    info = ClipInfo.load(clip_id)
    step = max(1, info.n_frames // n_frames)
    frames = list(range(0, info.n_frames, step))[:n_frames]

    f_lines, n_lines = _focal_from_lines(info, frames)
    f_motion, n_motion, secs, moved_px = _focal_from_motion(info, frames)

    agree = None
    focal = None
    if f_lines and f_motion:
        agree = abs(f_lines - f_motion) / max(f_lines, f_motion) <= AGREE_FRAC
        focal = float(np.sqrt(f_lines * f_motion)) if agree else None
    elif f_lines or f_motion:
        focal = f_lines or f_motion

    return {
        "clip_id": clip_id,
        "width": info.width, "height": info.height, "fps": info.fps,
        "focal_px": focal,
        "focal_confidence": ("two independent methods agree" if agree
                             else "one method only" if focal
                             else "no estimate"),
        "focal_from_vanishing_points": f_lines, "frames_that_answered": n_lines,
        "focal_from_motion": f_motion, "pairs_that_answered": n_motion,
        "baseline_seconds": secs,
        # ~1 px per metre of camera translation at these viewing distances. Small says a mount,
        # large says a hand — a different search, before any of it is run.
        "rotation_only_residual_px": moved_px,
        "camera": (None if moved_px is None else
                   "turns about a point" if moved_px < 2.0 else
                   "travels — a rotation cannot explain it"),
        "surface_top_frac": _surface_top(info, frames),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("clip", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    clips = ([d.name for d in sorted(runs_root().iterdir())
              if (d / "clip.json").exists()] if args.all else [args.clip])
    if not clips or clips == [None]:
        ap.error("give a clip, or --all")

    out = []
    for c in clips:
        try:
            out.append(hint(c))
        except Exception as exc:                              # noqa: BLE001
            out.append({"clip_id": c, "error": str(exc)[:120]})

    print(f"{'clip':32} {'focal':>8} {'lines':>8} {'motion':>8}  {'moves':>6}  confidence")
    for h in out:
        if "error" in h:
            print(f"{h['clip_id']:32} {h['error']}")
            continue
        n = lambda v: f"{v:8.0f}" if v else "       -"   # noqa: E731
        r = h["rotation_only_residual_px"]
        mv = f"{r:6.2f}" if r else "     -"
        print(f"{h['clip_id']:32} {n(h['focal_px'])} {n(h['focal_from_vanishing_points'])} "
              f"{n(h['focal_from_motion'])}  {mv}  {h['focal_confidence']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=1))
        print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
