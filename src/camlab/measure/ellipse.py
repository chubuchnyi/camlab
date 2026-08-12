"""The centre circle, found in the image as the ellipse it projects to.

Every other marking on a pitch is a straight line, and straight lines carry less information than
they look like they do. Measured this session: the pitch is *exactly* symmetric under a half-turn,
so two cameras fit its markings bit for bit identically; and on a plane the focal trades against
the distance, so a whole family along the line of sight fits to within a pixel. The line-based
bootstrap lands 21–54 m from the true camera with the focal three times off, and is not wrong to —
those cameras really do fit.

**A circle is different, because its projection has a shape.** A circle of known radius on the
pitch plane projects to an ellipse whose eccentricity and orientation depend on where the camera is
and what its focal is — not merely its size. Slide the camera along the touchline and the ellipse
tilts; widen the lens and it changes proportion. Those are exactly the two errors the line-based
seed makes, and the ellipse is the one thing on the pitch that reports them.

It is also correspondence-free. A line has to be matched to *which* marking it is before it says
anything; there is only one centre circle.

**What this does not fix.** The half-turn symmetry, because the centre circle is symmetric too. Two
cameras will still fit. That ambiguity needs something off the pitch and is recorded in
`findings/bootstrap-progress.md`.

**And the detector below does not work, while `arc_paint_distance` does.** Recorded rather than
deleted, because the failure is informative. `detect_ellipse` fits a conic to painted pixels that
are not on a detected straight line, and on both real clips it returns something with 200–600
inliers at under 2 px RMS that is not the arc: axis ratios of 69:1 and 970:1 on the first run, and
axes four times too large after an eccentricity bound was added. Whatever is left after the lines
are removed is still mostly line-like, and the largest consistent conic through it is a shallow
curve through noise. A connected-component version — the one that did find the arc when measuring
lens distortion — finds no curved run at all here, because the arc's paint arrives in fragments too
short to fit.

The arc is nevertheless *present*: projecting the model arcs through a known camera puts every one
of their 35 points in frame with paint a median of 1.5 px away. So it was never a detection problem
to solve — a camera hypothesis already says where the arc should be, and asking whether paint is
there is both cheaper and decisive:

    truth        1.5 px, 35 arc points in frame
    candidate    7.9 px, 17
    candidate    5.7 px, 12
    candidate     ---- , 0     — the arcs are off-frame entirely, which is a disqualification
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Painted pixels within this of a detected straight segment are that segment's, not the circle's.
#: The halfway line runs through the circle, so without this the fit is pulled onto a chord.
LINE_EXCLUSION_PX = 6.0

#: A conic is decided by five points; RANSAC samples that many. Generous iteration count because
#: the non-line paint is a minority of a noisy mask and the inlier rate can be low.
RANSAC_ITERS = 3000

#: How close a pixel must sit to the fitted conic, in the algebraic distance normalised by the
#: conic's own gradient — which is a first-order approximation of the geometric distance in pixels.
INLIER_PX = 3.0

#: Longest axis over shortest. Without this the fit finds the straightest thing available: on the
#: first run it returned 1524/22 and 217020/224 — ratios of 69:1 and 970:1, which are not ellipses
#: seen at an angle but lines with a conic drawn through them. A real centre circle at the
#: obliquest angle these clips ever show it comes back at about 4.5:1.
MAX_AXIS_RATIO = 12.0


@dataclass(frozen=True)
class Ellipse:
    """A fitted ellipse in image pixels.

    Attributes:
        centre: `(u, v)` of the ellipse centre — NOT the projection of the circle's centre. Those
            differ under perspective, and confusing them is a metre-scale error on the pitch.
        axes: semi-major and semi-minor, pixels.
        angle_deg: orientation of the major axis, from the +u axis.
        conic: the `(3, 3)` symmetric matrix, normalised. This is the useful form: a circle
            `C_world` maps to `C_image = H⁻ᵀ C_world H⁻¹`, so a camera can be checked against it
            without ever converting to axes and back.
        inliers: painted pixels supporting it.
        rms_px: their RMS distance from the curve.
    """

    centre: tuple[float, float]
    axes: tuple[float, float]
    angle_deg: float
    conic: np.ndarray
    inliers: int
    rms_px: float


def _fit_conic(pts: np.ndarray) -> np.ndarray | None:
    """Least-squares conic through >=5 points. Returns the symmetric 3x3, or None."""
    x, y = pts[:, 0], pts[:, 1]
    a = np.column_stack([x * x, x * y, y * y, x, y, np.ones_like(x)])
    try:
        _u, s, vt = np.linalg.svd(a)
    except np.linalg.LinAlgError:
        return None
    if s[-1] > 1e-6 * s[0] and len(pts) > 5:
        pass                                   # a poor fit is caught by the inlier test, not here
    a_, b_, c_, d_, e_, f_ = vt[-1]
    return np.array([[a_, b_ / 2, d_ / 2], [b_ / 2, c_, e_ / 2], [d_ / 2, e_ / 2, f_]])


def conic_to_ellipse(conic: np.ndarray) -> tuple[tuple[float, float], tuple[float, float], float]:
    """`(centre, (semi-major, semi-minor), angle°)`, or raise if the conic is not an ellipse."""
    m = conic[:2, :2]
    if np.linalg.det(m) <= 0:
        raise ValueError("not an ellipse")                     # hyperbola or degenerate
    centre = np.linalg.solve(m, -conic[:2, 2])
    # Value of the conic at its own centre, which scales the axes.
    k = float(centre @ m @ centre + 2 * conic[:2, 2] @ centre + conic[2, 2])
    if abs(k) < 1e-12:
        raise ValueError("degenerate conic")
    vals, vecs = np.linalg.eigh(m / -k)
    if np.any(vals <= 0):
        raise ValueError("not an ellipse")
    axes = 1.0 / np.sqrt(vals)
    order = np.argsort(-axes)
    axes, vecs = axes[order], vecs[:, order]
    angle = float(np.degrees(np.arctan2(vecs[1, 0], vecs[0, 0])))
    return (float(centre[0]), float(centre[1])), (float(axes[0]), float(axes[1])), angle


def _distance(conic: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Sampson distance: the algebraic residual divided by its own gradient. Pixels, to first order.

    The bare algebraic residual is not a distance — it scales with the conic's arbitrary
    normalisation and with how far the point is from the centre, so a fixed threshold on it accepts
    a wildly different band at each radius.
    """
    h = np.column_stack([pts, np.ones(len(pts))])
    num = np.einsum("ij,jk,ik->i", h, conic, h)
    grad = 2.0 * (h @ conic)[:, :2]
    return np.abs(num) / (np.linalg.norm(grad, axis=1) + 1e-12)


def detect_ellipse(spine: np.ndarray, segments: np.ndarray | None = None, *,
                   width: int | None = None, height: int | None = None,
                   rng=None, iters: int = RANSAC_ITERS,
                   inlier_px: float = INLIER_PX, min_inliers: int = 60) -> Ellipse | None:
    """The best ellipse through painted pixels that are not on a detected straight line.

    `spine` is `paint.centreline_pixels(dist)`. `segments` are the straight markings already found;
    their pixels are removed first, because the halfway line runs through the centre circle and a
    conic fit that keeps it lands on a chord.
    """
    rng = np.random.default_rng(0) if rng is None else rng
    pts = np.asarray(spine, float)
    if segments is not None and len(segments):
        seg = np.asarray(segments, float).reshape(-1, 4)
        keep = np.ones(len(pts), bool)
        for s in seg:
            a, b = s[:2], s[2:]
            d = b - a
            n = float(np.linalg.norm(d))
            if n < 1e-9:
                continue
            t = np.clip(((pts - a) @ d) / (n * n), 0.0, 1.0)
            foot = a + t[:, None] * d
            keep &= np.linalg.norm(pts - foot, axis=1) > LINE_EXCLUSION_PX
        pts = pts[keep]
    if len(pts) < max(min_inliers, 5):
        return None

    best = None
    for _ in range(iters):
        sample = pts[rng.choice(len(pts), 5, replace=False)]
        conic = _fit_conic(sample)
        if conic is None:
            continue
        try:
            centre, axes, _ang = conic_to_ellipse(conic)
        except ValueError:
            continue
        # An ellipse bigger than the frame, a few pixels across, or so eccentric it is really a
        # line, is not the centre circle.
        span = max(width or 4000, height or 4000)
        if not (8.0 < axes[1] and axes[0] < 3.0 * span):
            continue
        if axes[0] / max(axes[1], 1e-9) > MAX_AXIS_RATIO:
            continue
        d = _distance(conic, pts)
        n_in = int((d < inlier_px).sum())
        if best is None or n_in > best[0]:
            best = (n_in, conic)
    if best is None or best[0] < min_inliers:
        return None

    # Refit on every inlier, then once more on the inliers of that — a five-point sample fixes the
    # support, not the shape.
    conic = best[1]
    for _ in range(3):
        inl = pts[_distance(conic, pts) < inlier_px]
        if len(inl) < 5:
            break
        refit = _fit_conic(inl)
        if refit is None:
            break
        try:
            _c, ax, _a = conic_to_ellipse(refit)
        except ValueError:
            break
        if ax[0] / max(ax[1], 1e-9) > MAX_AXIS_RATIO:
            break                              # the refit slid onto a line; keep what we had
        conic = refit
    d = _distance(conic, pts)
    inl = d < inlier_px
    if int(inl.sum()) < min_inliers:
        return None
    try:
        centre, axes, angle = conic_to_ellipse(conic)
    except ValueError:
        return None
    if axes[0] / max(axes[1], 1e-9) > MAX_AXIS_RATIO:
        return None
    return Ellipse(centre, axes, angle, conic / np.linalg.norm(conic),
                   int(inl.sum()), float(np.sqrt(np.mean(d[inl] ** 2))))


def predict_conic(h_w2i: np.ndarray, radius: float,
                  centre_xy: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    """Where a world circle lands in the image, as a conic, given the world→image homography.

    `C_image = H⁻ᵀ C_world H⁻¹`. Returned normalised so two conics can be compared directly.
    """
    cx, cy = centre_xy
    c_world = np.array([[1.0, 0.0, -cx],
                        [0.0, 1.0, -cy],
                        [-cx, -cy, cx * cx + cy * cy - radius * radius]])
    hinv = np.linalg.inv(np.asarray(h_w2i, float))
    c = hinv.T @ c_world @ hinv
    return c / np.linalg.norm(c)


def conic_disagreement(a: np.ndarray, b: np.ndarray, pts: np.ndarray,
                       near_px: float = INLIER_PX) -> float:
    """RMS pixel distance from `a`'s curve to `b`'s, sampled where `a` actually runs.

    Comparing conic matrices entry by entry is meaningless — they are defined up to scale and sign,
    and two normalisations of the same curve can differ everywhere. Comparing where the curves
    actually run does not have that problem.

    **`a` used to be ignored entirely**: the body was `_distance(b, pts)`, which is how far the
    POINTS are from `b` and has nothing to do with `a`. It was caught by the number refusing to
    move — four completely different fitted ellipses on the same frame all "disagreed" with the
    same predicted arc by exactly 180.2 px, because none of them was ever consulted.

    `pts` is the pixel population to look in — a paint spine, usually. The points within `near_px`
    of `a` are where `a` runs; their distance to `b` is the answer. NaN when `a` runs nowhere near
    any of them, which is a real answer and not a zero.
    """
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    pts = np.asarray(pts, float)
    on_a = pts[np.abs(_distance(a, pts)) <= near_px]
    if len(on_a) < 5:
        return float("nan")
    return float(np.sqrt(np.mean(_distance(b, on_a) ** 2)))


#: Indices into `core.pitch.pitch_polylines()` of the markings that are NOT straight — the centre
#: circle and the penalty arc. Derived rather than hardcoded, because the pitch model is the one
#: thing here that is known exactly and it should stay the single source.
def arc_markings() -> list[np.ndarray]:
    """Every curved marking, as `(N, 2)` world points."""
    from camlab.core.pitch import pitch_polylines

    out = []
    for poly in pitch_polylines():
        xy = np.asarray(poly, float)[:, :2]
        if len(xy) < 3:
            continue
        d = xy[-1] - xy[0]
        n = float(np.linalg.norm(d))
        if n < 1e-9:
            continue
        perp = np.abs((xy - xy[0]) @ np.array([-d[1], d[0]]) / n)
        if perp.max() > 0.05:                  # the same 5 cm test `straight_markings` excludes on
            out.append(xy)
    return out


def arc_paint_distance(h_w2i: np.ndarray, paint_tree, width: int, height: int,
                       min_points: int = 8) -> tuple[float, int]:
    """`(median pixels from the projected arcs to the nearest paint, arc points in frame)`.

    The discriminator the straight markings cannot provide. A pitch is exactly symmetric under a
    half-turn and its focal trades against its distance, so many cameras fit the LINES; far fewer
    also put the curved markings where paint actually is. Measured on fan frame 8: the true camera
    lands its arcs 1.5 px from paint with all 35 points in frame, while line-fitted candidates land
    at 5.7 and 7.9 px with 12 and 17 points — and one puts the arcs off-frame entirely, which is
    not a bad score but a disqualification.

    `paint_tree` is a `scipy.spatial.cKDTree` over `paint.centreline_pixels(dist)`.
    """
    ds, n_seen = [], 0
    for xy in arc_markings():
        q = np.column_stack([xy, np.ones(len(xy))]) @ np.asarray(h_w2i, float).T
        w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
        uv = q[:, :2] / w[:, None]
        vis = ((q[:, 2] > 0) & (uv[:, 0] > 0) & (uv[:, 0] < width)
               & (uv[:, 1] > 0) & (uv[:, 1] < height))
        if int(vis.sum()) < min_points:
            continue
        d, _ = paint_tree.query(uv[vis])
        ds.append(d)
        n_seen += int(vis.sum())
    if not ds:
        return float("nan"), 0
    return float(np.median(np.concatenate(ds))), n_seen
