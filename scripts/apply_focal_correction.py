"""Scale a solved camera's focal by a constant and let it re-fit the paint, focal held.

`the-degeneracy-measured-against-truth-2026-08-17.md` found camlab's focal short by a median 2.1 %
and the position error tracking it at r = -0.97, and drew the obvious conclusion: correct the focal
by one constant and 61 % of the position error goes away. This applies that correction so the
conclusion can be measured instead of argued.

**The correction can only be a post-processing step, and that is not a detail.** The chain has no
focal knob because it does not want one — every stage fits the focal to the paint, so a corrected
focal handed to the front of the chain is simply un-corrected by it. What shipping the correction
would actually mean is: solve as now, multiply the focal, then let rotation and position re-converge
on the paint with the new focal held fixed. That is what this does.

The refit is `refit_frame_lm`'s, to the line — same residual, same soft-L1, same `diff_step`, same
`_accept` guard — with one difference: the free parameters are rotation and position, and the focal
is not among them. Anything else would measure a different optimiser rather than a different focal.

    PYTHONPATH=src:. python scripts/apply_focal_correction.py ARG_CRO_220954 --scale 1.0216
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from camlab.camera_file import write_camera  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.residual import frame_evidence_cached  # noqa: E402
from camlab.parallel import map_items  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.refit import (  # noqa: E402
    LM_RESIDUALS,
    MIN_MATCHED,
    MISS_PX,
    STEP,
    _accept,
    endpoint_residuals,
    line_errors,
)

#: Per-worker cache of `(ClipInfo, camera)`, keyed by `(clip, src)`. `map_items` starts workers with
#: SPAWN, not fork, so a dict filled in `main` reaches them empty — the job has to travel inside the
#: item and be rebuilt on the far side. That cost me one run to learn.
_CACHE: dict = {}


def _job(clip: str, src: str):
    key = (clip, src)
    if key not in _CACHE:
        info = ClipInfo.load(clip)
        _CACHE[key] = (info, json.loads((info.dir / src).read_text()))
    return _CACHE[key]


def refit_fixed_focal(segments, focal, rvec, centre, width, height, cx, cy, frame: int = 0):
    """`refit_frame_lm` with the focal frozen: six free parameters, not seven.

    `refit_frame_lm` already has a `free_position=False` mode that optimises `p[:4]` — focal and
    rotation — so the machinery for a parameter subset exists; it just does not offer this subset.
    Rather than add a third mode to a shipped function for one experiment, the six-parameter version
    lives here, sharing every constant with it so the two cannot drift apart.
    """
    from scipy.optimize import least_squares

    p0 = np.concatenate([[float(focal)], np.asarray(rvec, float), np.asarray(centre, float)])

    def unpack(q):
        p = p0.copy()
        p[1:7] += q * STEP[1:7]  # index 0 is the focal, and it is not offered to the optimiser
        return p

    def r(q):
        p = unpack(q)
        if p[6] < 0.5:
            return np.full(LM_RESIDUALS, float(MISS_PX) * 10)
        errs = line_errors(segments, p[0], p[1:4], p[4:7], width, height, cx=cx, cy=cy)
        if sum(1 for e in errs if e.matched) < MIN_MATCHED:
            return np.full(LM_RESIDUALS, float(MISS_PX) * 10)
        v = endpoint_residuals(errs)
        pad = np.full(LM_RESIDUALS, float(MISS_PX))
        pad[:min(len(v), LM_RESIDUALS)] = v[:LM_RESIDUALS]
        return pad

    res = least_squares(r, np.zeros(6), loss="soft_l1", f_scale=8.0, diff_step=1e-2, max_nfev=1500)
    return _accept(segments, p0, unpack(res.x), width, height, cx, cy, frame)


def one_frame(item):
    """Correct and re-fit one frame. Returns `(i, focal, rvec, centre)`."""
    clip, src, scale, i = item
    info, cam = _job(clip, src)
    focal = float(cam["focal_px"][i]) * scale
    rvec = list(cam["rotation"][i])
    centre = list(cam["position"][i])

    d, s = frame_evidence_cached(info.frame_path(i))[:2]
    segments = detect_segments(d, s, method="hough")
    out = refit_fixed_focal(segments, focal, rvec, centre, cam["width"], cam["height"],
                            cam["cx"], cam["cy"], frame=i)
    # `_accept` hands back the starting camera when the refit did not improve, which is the
    # behaviour the chain already relies on; either way the focal is the corrected one.
    return i, float(out.focal_px), list(out.rotation), list(out.position)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--scale", type=float, required=True,
                    help="multiply the focal by this; 1.0216 is the working half's median deficit")
    ap.add_argument("--from", dest="src", default="camera_polished.json")
    ap.add_argument("--out", default="camera_focal_corrected.json")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    cam = json.loads((info.dir / args.src).read_text())
    n = len(cam["position"])
    items = [(args.clip, args.src, args.scale, i) for i in range(n)]
    got = map_items(one_frame, items, workers=args.workers)
    got.sort(key=lambda t: t[0])

    write_camera(info.dir / args.out, model=cam.get("model", "pinhole"), clip_id=args.clip,
                 width=cam["width"], height=cam["height"], cx=cam["cx"], cy=cam["cy"],
                 frames=list(cam["frames"]),
                 focal_px=[g[1] for g in got],
                 rotation=[g[2] for g in got],
                 position=[g[3] for g in got],
                 notes=(f"focal scaled by {args.scale:.4f} from {args.src}, then rotation and "
                        f"position re-fitted to the paint with the focal held fixed"))
    print(f"  {args.clip:<20} {n} frames, focal x{args.scale:.4f} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
