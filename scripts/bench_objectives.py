"""Which objective actually converges? Judged against frames a human aligned by eye.

Until now this repo had nothing to converge *towards*. Eight frames of the fan clip are now
hand-aligned and land, remarkably evenly, at 4.8-5.5 px of paint error — so "did the search find
the right camera" is finally a question with an answer, and the objective can be compared instead
of argued about.

What the current objective feeds back (`refit.objective`):

    worst |offset| over matched markings  +  MISS_PX * (markings with no match)

One scalar, from about six lines. The ANGLE each marking reports is discarded entirely, and so is
every line but the worst. Minimised by Nelder-Mead, a derivative-free simplex, over 7 parameters.

The variants here, all scored the same way — refit from the solve's own seed, then measure the
result against the paint with `frame_residual`:

    worst      what ships: max |offset|, angle unused                       (L-infinity)
    sum        mean |offset|, angle unused                                  (L1)
    ends       mean over markings of the ENDPOINT displacement, which folds
               offset and angle into one number in the same unit as both:
               a marking of visible length L rotated by theta and shifted by
               d misses its own ends by |d| +/- L/2 * tan(theta)
    ends_lm    the same residual vector, but minimised by Levenberg-Marquardt
               with a soft-L1 loss instead of a simplex

Run:  .venv/bin/python scripts/bench_objectives.py [clip]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402
from scipy.optimize import least_squares, minimize  # noqa: E402

from camlab.measure.line_error import line_errors  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.refit import MIN_MATCHED, MISS_PX, STEP  # noqa: E402

BOUNDS_BAD = 1e6


def _errs(segs, p, w, h, cx, cy):
    if not (300.0 < p[0] < 20000.0) or p[6] < 0.5:
        return None
    return line_errors(segs, p[0], p[1:4], p[4:7], w, h, cx=cx, cy=cy)


def _endpoint_residuals(errs) -> np.ndarray:
    """How far each matched marking's own ENDS are from the line it matched, in pixels.

    The offset is measured at the middle of the overlap, so a marking pivoted about that middle
    reports zero and is perfect by the shipped objective while both its ends are far out. That is
    not hypothetical — it is what `worst spot` shows on the frames where `worst line` looks fine.
    Folding the angle in at the marking's own visible length puts both faults in one unit.
    """
    out = []
    for e in errs:
        if not e.matched:
            continue
        half = 0.5 * float(np.linalg.norm(e.model_uv[1] - e.model_uv[0]))
        swing = half * np.tan(np.radians(e.angle_deg))
        out.append(abs(e.offset_px + swing))
        out.append(abs(e.offset_px - swing))
    return np.array(out) if out else np.array([])


def make_objective(kind):
    def f(segs, p, w, h, cx, cy):
        errs = _errs(segs, p, w, h, cx, cy)
        if errs is None:
            return BOUNDS_BAD
        matched = [e for e in errs if e.matched]
        if len(matched) < MIN_MATCHED:
            return BOUNDS_BAD
        miss = MISS_PX * (len(errs) - len(matched))
        if kind == "worst":
            return max(abs(e.offset_px) for e in matched) + miss
        if kind == "sum":
            return float(np.mean([abs(e.offset_px) for e in matched])) + miss
        if kind == "ends":
            return float(np.mean(_endpoint_residuals(errs))) + miss
        raise ValueError(kind)
    return f


def refit_nm(segs, p0, w, h, cx, cy, kind, maxiter=1200):
    obj = make_objective(kind)

    def g(q):
        return obj(segs, p0 + q * STEP, w, h, cx, cy)

    res = minimize(g, np.zeros(7), method="Nelder-Mead",
                   options={"maxiter": maxiter, "xatol": 1e-3, "fatol": 1e-2})
    return p0 + res.x * STEP


def refit_lm(segs, p0, w, h, cx, cy, n_res=64):
    """Levenberg-Marquardt on the endpoint residual VECTOR, soft-L1 so one bad line cannot steer.

    A fixed-length vector is required — `least_squares` cannot take a residual that changes size
    when a correspondence appears or vanishes. Missing entries are charged `MISS_PX`, which is the
    same penalty the shipped objective applies and keeps the two comparable.
    """
    def r(q):
        errs = _errs(segs, p0 + q * STEP, w, h, cx, cy)
        if errs is None:
            return np.full(n_res, BOUNDS_BAD ** 0.5)
        matched = [e for e in errs if e.matched]
        if len(matched) < MIN_MATCHED:
            return np.full(n_res, BOUNDS_BAD ** 0.5)
        v = _endpoint_residuals(errs)
        pad = np.full(n_res, float(MISS_PX))
        pad[:min(len(v), n_res)] = v[:n_res]
        return pad

    res = least_squares(r, np.zeros(7), loss="soft_l1", f_scale=8.0,
                        diff_step=1e-2, max_nfev=1500)
    return p0 + res.x * STEP


def main() -> None:
    clip_id = sys.argv[1] if len(sys.argv) > 1 else "fan"
    info = ClipInfo.load(clip_id)
    seed = json.loads((info.dir / "camera_auto.json").read_text())
    cx, cy = float(seed["cx"]), float(seed["cy"])
    hand = json.loads(
        next((Path(__file__).resolve().parent.parent / "calib")
             .glob(f"{clip_id}-hand-aligned-*.json")).read_text()
    )["camera_auto.json"]
    # Frame 29's stored edit is worse than the solve and is excluded by measurement, not by taste.
    frames = [int(k) for k in sorted(hand, key=int) if int(k) in (0, 1, 2, 3, 4, 8, 9, 19)]

    def score(n, p):
        return frame_residual(info.frame_path(n), p[0], p[1:4], p[4:7],
                              frame=n, cx=cx, cy=cy).worst_line_px

    kinds = ["worst", "sum", "ends"]
    rows = {k: [] for k in [*kinds, "ends_lm", "seed", "human"]}
    print(f"{'frame':>5} {'seed':>7} {'human':>7} | "
          + " ".join(f"{k:>8}" for k in [*kinds, "ends_lm"]))
    for n in frames:
        d, s = paint_masks(cv2.imread(str(info.frame_path(n))))
        segs = detect_segments(d, s, method="hough")
        p0 = np.concatenate([[seed["focal_px"][n]], seed["rotation"][n], seed["position"][n]])
        e = hand[str(n)]
        ph = np.concatenate([[e["focal_px"]], e["rotation"], e["position"]])
        rows["seed"].append(score(n, p0))
        rows["human"].append(score(n, ph))
        got = {}
        for k in kinds:
            got[k] = score(n, refit_nm(segs, p0, info.width, info.height, cx, cy, k))
            rows[k].append(got[k])
        got["ends_lm"] = score(n, refit_lm(segs, p0, info.width, info.height, cx, cy))
        rows["ends_lm"].append(got["ends_lm"])
        print(f"{n:5d} {rows['seed'][-1]:7.1f} {rows['human'][-1]:7.1f} | "
              + " ".join(f"{got[k]:8.1f}" for k in [*kinds, "ends_lm"]))

    print()
    for k in ["seed", "human", *kinds, "ends_lm"]:
        a = np.array(rows[k], float)
        print(f"   {k:8s} median {np.nanmedian(a):6.1f} px   "
              f"within 2x of the human: {int(np.nansum(a < 2 * np.array(rows['human'])))}"
              f"/{len(a)}")


if __name__ == "__main__":
    main()
