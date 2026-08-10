"""Refit a camera against the line metric — the objective the original solve never saw.

Everything in this repo was fitted by ICP against *nearest paint within 40 px*, a measurement later
shown not to measure camera error: blind to a line sliding along itself, happy to let one marking
score against another's paint, and with the shipped camera not even at its minimum
(`findings/the-metric-does-not-measure-camera-error.md`).

So this optimises what is actually being judged: **the signed perpendicular offset of each pitch
marking from the detected line it corresponds to**, the number drawn in the viewer and checkable
with the ruler.

**The miss penalty is inside the objective, not bolted on.** That distinction is the whole
difficulty. A camera can lower its worst offset by pushing a marking out of frame or out of
correspondence, and a penalty added after the optimiser has chosen is a penalty the optimiser never
saw. Measured with a flat 40 px added afterwards: matched markings fell from 7 to 4 while the
number "improved". Here a miss costs `MISS_PX` inside the term being minimised, so trading a line
away has to pay for itself.

**What it does not do is move the camera far.** It is a local refit from the existing solve, which
is the honest scope: half a metre and a few per cent of focal was enough to drop the error three-
to fivefold, so the answer was never far away — the old objective simply did not point at it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from camlab.measure.line_error import line_errors

#: What one unmatched marking costs, in the same pixels as the offsets. Set at the scale of a
#: clearly-bad offset rather than a catastrophic one: a marking genuinely off the frame should not
#: dominate the objective, but losing one to save 20 px on another must not pay.
MISS_PX = 60.0

#: Below this many correspondences there is nothing to fit. Three points fix a homography exactly,
#: so a "fit" through three of them tests nothing at all.
MIN_MATCHED = 4

#: Parameter steps for the simplex, in the units each parameter lives in. Without this the focal
#: (~3000) and a rotation component (~0.5) share a step size and the optimiser cannot see the one
#: it is not scaled for — the same trap `x_scale="jac"` exists to avoid in least_squares.
STEP = np.array([150.0, 0.01, 0.01, 0.01, 0.8, 0.8, 0.8])


@dataclass(frozen=True)
class Refit:
    """One frame refitted. `before`/`after` are worst-offset px; `n_*` are matched counts."""

    frame: int
    focal_px: float
    rotation: np.ndarray
    position: np.ndarray
    before: float
    after: float
    n_before: int
    n_after: int
    moved_m: float
    d_focal: float

    @property
    def improved(self) -> bool:
        """Better AND not by measuring less. The second half is the one that needs saying."""
        return self.after < self.before and self.n_after >= self.n_before


def objective(segments, focal, rvec, centre, width, height, cx, cy) -> float:
    """Worst matched offset, plus `MISS_PX` for every marking with no correspondence.

    Worst rather than median, because a camera that fits three lines and misplaces a fourth is
    wrong, and a median lets the three outvote the fourth — which is exactly the failure a human
    caught by eye while the median read 7 px.
    """
    if not (300.0 < focal < 20000.0) or centre[2] < 0.5:
        return 1e6
    errs = line_errors(segments, focal, rvec, centre, width, height, cx=cx, cy=cy)
    matched = [e for e in errs if e.matched]
    if len(matched) < MIN_MATCHED:
        return 1e6
    worst = max(abs(e.offset_px) for e in matched)
    return worst + MISS_PX * (len(errs) - len(matched))


def refit_frame(segments, focal, rvec, centre, width, height, cx, cy,
                frame: int = 0, maxiter: int = 1200) -> Refit:
    """Local refit of `(focal, rotation, position)` for one frame. Nelder-Mead, no gradients.

    Derivative-free on purpose: the objective steps whenever a correspondence appears or vanishes,
    so it is piecewise-continuous and a gradient method would either smooth over those steps or
    stall on them.
    """
    p0 = np.concatenate([[float(focal)], np.asarray(rvec, float), np.asarray(centre, float)])

    def f(q):
        p = p0 + q * STEP
        return objective(segments, p[0], p[1:4], p[4:7], width, height, cx, cy)

    before = f(np.zeros(7))
    res = minimize(f, np.zeros(7), method="Nelder-Mead",
                   options={"maxiter": maxiter, "xatol": 1e-3, "fatol": 1e-2})
    p1 = p0 + res.x * STEP

    def stats(p):
        errs = line_errors(segments, p[0], p[1:4], p[4:7], width, height, cx=cx, cy=cy)
        m = [e for e in errs if e.matched]
        return (max((abs(e.offset_px) for e in m), default=float("nan")), len(m))

    w0, n0 = stats(p0)
    w1, n1 = stats(p1)
    # Refuse a "better" answer that is worse on the thing the objective was protecting.
    if not np.isfinite(w1) or n1 < MIN_MATCHED or float(res.fun) >= before:
        p1, w1, n1 = p0, w0, n0
    return Refit(frame, float(p1[0]), p1[1:4].copy(), p1[4:7].copy(),
                 float(w0), float(w1), int(n0), int(n1),
                 float(np.linalg.norm(p1[4:7] - p0[4:7])), float(p1[0] - p0[0]))
