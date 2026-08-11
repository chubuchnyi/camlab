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


def endpoint_residuals(errs) -> np.ndarray:
    """Both ENDS of every matched marking, against the line it matched. Pixels.

    `objective` above collapses a frame to one number: the worst marking's offset, taken at the
    middle of its overlap. Two things are thrown away there and both matter.

    Measured at the middle, a marking pivoted about that middle reports **zero** and scores perfect
    while both its ends are far out. That is the gap between `worst line` and `worst spot` in the
    viewer, and it is why the angle was worth drawing. A marking of visible length `L`, shifted by
    `d` and rotated by `theta`, misses its own ends by `d ± (L/2)·tan(theta)` — which puts the
    offset and the angle in one unit with no invented weight between them.

    And it is a VECTOR, so `least_squares` sees every marking and a Jacobian instead of a simplex
    feeling around one scalar. Against eight hand-aligned frames that is the whole difference: this
    same residual under Nelder-Mead lands at 29.3 px median, under Levenberg-Marquardt at 2.0.
    """
    out = []
    for e in errs:
        if not e.matched:
            continue
        half = 0.5 * float(np.linalg.norm(e.model_uv[1] - e.model_uv[0]))
        swing = half * float(np.tan(np.radians(e.angle_deg)))
        out.append(abs(e.offset_px + swing))
        out.append(abs(e.offset_px - swing))
    return np.asarray(out, dtype=float)


#: Residual vector length for the least-squares refit. `least_squares` needs a fixed size and the
#: number of matched markings changes as the camera moves, so short frames are padded with the same
#: `MISS_PX` the scalar objective charges, which keeps the two comparable.
LM_RESIDUALS = 64


def refit_frame_lm(segments, focal, rvec, centre, width, height, cx, cy,
                   frame: int = 0, free_position: bool = True) -> Refit:
    """Levenberg-Marquardt on `endpoint_residuals`, soft-L1. The one that converges.

    `refit_frame` argued that a gradient method would stall on the steps the objective takes when a
    correspondence appears or vanishes. Measured against eight hand-aligned frames, that argument
    is wrong: a finite-difference Jacobian at `diff_step=1e-2` steps clean over them, and soft-L1
    stops one bad correspondence steering the fit.

        seed 34.7 px | human 5.1 | shipped objective 13.8 | this 2.0     (median of eight)

    It diverges on one of those eight, which is why `_accept` is not optional.
    """
    from scipy.optimize import least_squares

    p0 = np.concatenate([[float(focal)], np.asarray(rvec, float), np.asarray(centre, float)])
    n_free = 7 if free_position else 4

    def unpack(q):
        p = p0.copy()
        p[:n_free] += q * STEP[:n_free]
        return p

    def r(q):
        p = unpack(q)
        if not (300.0 < p[0] < 20000.0) or p[6] < 0.5:
            return np.full(LM_RESIDUALS, float(MISS_PX) * 10)
        errs = line_errors(segments, p[0], p[1:4], p[4:7], width, height, cx=cx, cy=cy)
        if sum(1 for e in errs if e.matched) < MIN_MATCHED:
            return np.full(LM_RESIDUALS, float(MISS_PX) * 10)
        v = endpoint_residuals(errs)
        pad = np.full(LM_RESIDUALS, float(MISS_PX))
        pad[:min(len(v), LM_RESIDUALS)] = v[:LM_RESIDUALS]
        return pad

    res = least_squares(r, np.zeros(n_free), loss="soft_l1", f_scale=8.0,
                        diff_step=1e-2, max_nfev=1500)
    return _accept(segments, p0, unpack(res.x), width, height, cx, cy, frame)


def _accept(segments, p0, p1, width, height, cx, cy, frame):
    """Take the new camera only if it is better AND has not lost correspondences.

    The second half is the one that needs saying: a camera can lower its worst offset by pushing a
    marking out of frame, and then it is measuring less rather than fitting better.
    """
    def stats(p):
        errs = line_errors(segments, p[0], p[1:4], p[4:7], width, height, cx=cx, cy=cy)
        m = [e for e in errs if e.matched]
        return (max((abs(e.offset_px) for e in m), default=float("nan")), len(m))

    w0, n0 = stats(p0)
    w1, n1 = stats(p1)
    if not np.isfinite(w1) or n1 < MIN_MATCHED or n1 < n0 or not (w1 < w0):
        p1, w1, n1 = p0, w0, n0
    return Refit(frame, float(p1[0]), p1[1:4].copy(), p1[4:7].copy(),
                 float(w0), float(w1), int(n0), int(n1),
                 float(np.linalg.norm(p1[4:7] - p0[4:7])), float(p1[0] - p0[0]))


def refit_frame(segments, focal, rvec, centre, width, height, cx, cy,
                frame: int = 0, maxiter: int = 1200, free_position: bool = True) -> Refit:
    """Local refit of `(focal, rotation, position)` for one frame. Nelder-Mead, no gradients.

    Kept because every measurement in the findings so far was taken with it. For new work use
    `refit_frame_lm`, which reaches 2.0 px where this reaches 13.8 on the same eight frames.
    """
    p0 = np.concatenate([[float(focal)], np.asarray(rvec, float), np.asarray(centre, float)])
    # With the position frozen this is the inner step of a PTZ refit: the centre is shared across
    # the clip, so it cannot be a per-frame free parameter while it is being fitted globally.
    n_free = 7 if free_position else 4

    def f(q):
        p = p0.copy()
        p[:n_free] += q * STEP[:n_free]
        return objective(segments, p[0], p[1:4], p[4:7], width, height, cx, cy)

    before = f(np.zeros(n_free))
    res = minimize(f, np.zeros(n_free), method="Nelder-Mead",
                   options={"maxiter": maxiter, "xatol": 1e-3, "fatol": 1e-2})
    p1 = p0.copy()
    p1[:n_free] += res.x * STEP[:n_free]

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


def refit_ptz(per_frame, evidence, width: int, height: int, cx: float, cy: float, *,
              anchors=None, rounds: int = 3, maxiter_inner: int = 400):
    """Fit ONE shared optical centre against the line metric, by block coordinate descent.

    Alternating, because the two blocks have very different shapes. Hold the centre and each
    frame's `(focal, rotation)` is an independent four-parameter problem; hold the rotations and
    the centre is three parameters shared by everything. Optimising all `3 + 4F` at once would put
    a simplex in thirty-five dimensions, where it does badly and where the three parameters that
    matter get lost among the thirty-two that do not.

    `per_frame` is `{frame: (focal, rvec, position)}` — the starting camera, normally the
    line-refitted per-frame solve, whose median position is the seed for the shared one.

    Returns `(centre, {frame: (focal, rvec)}, worst_offsets)`.
    """
    frames = sorted(evidence)
    if anchors is None:
        anchors = frames if len(frames) <= 16 else [
            frames[i] for i in np.unique(np.linspace(0, len(frames) - 1, 16).round().astype(int))
        ]
    centre = np.median(np.stack([per_frame[f][2] for f in frames]), axis=0)
    centre[2] = max(centre[2], 0.5)
    state = {f: (float(per_frame[f][0]), np.asarray(per_frame[f][1], float).copy())
             for f in frames}

    def score_at(c, subset):
        tot = 0.0
        for f in subset:
            fo, rv = state[f]
            tot += objective(evidence[f], fo, rv, c, width, height, cx, cy)
        return tot / max(len(subset), 1)

    for _ in range(rounds):
        # --- block 1: every frame's own focal and rotation, centre held -----------------------
        for f in frames:
            fo, rv = state[f]
            r = refit_frame(evidence[f], fo, rv, centre, width, height, cx, cy,
                            frame=f, maxiter=maxiter_inner, free_position=False)
            if r.after < r.before and r.n_after >= r.n_before:
                state[f] = (r.focal_px, r.rotation)
        # --- block 2: the shared centre, rotations held ----------------------------------------
        step = np.array([1.5, 1.5, 1.0])
        # Bound the loop variables explicitly: a closure over `centre` would see whatever it holds
        # when the optimiser calls back, not what it held when the lambda was written.
        res = minimize(lambda q, c0=centre, st=step: score_at(c0 + q * st, anchors), np.zeros(3),
                       method="Nelder-Mead",
                       options={"maxiter": 300, "xatol": 1e-3, "fatol": 1e-2})
        cand = centre + res.x * step
        if cand[2] > 0.5 and score_at(cand, anchors) < score_at(centre, anchors):
            centre = cand

    worst = {}
    for f in frames:
        fo, rv = state[f]
        errs = line_errors(evidence[f], fo, rv, centre, width, height, cx=cx, cy=cy)
        m = [e for e in errs if e.matched]
        worst[f] = max((abs(e.offset_px) for e in m), default=float("nan"))
    return centre, state, worst
