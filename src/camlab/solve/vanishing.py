"""The focal from the pitch's own parallel lines.

A third instrument, sharing no machinery with the other two.

camlab has two focal estimates and they disagree. The paint fit says ~4315 px; the image→image maps
say ~2100–2500 px and their answer walks with the baseline, which means that model is
mis-specified. Two instruments disagreeing is a puzzle. This is a third, and it is built out of
neither: no pitch scale, no camera position, no feature matching, no ICP — only the fact that a
football pitch carries two families of lines that are **parallel to each other and perpendicular
between the families**.

**The identity.** Parallel world lines meet at a vanishing point. For two vanishing points of
perpendicular world directions,

    v₁ᵀ ω v₂ = 0,        ω = K⁻ᵀ K⁻¹

and with square pixels, no skew and a known principal point that collapses to one equation in one
unknown:

    f² = −[(u₁ − cx)(u₂ − cx) + (v₁ − cy)(v₂ − cy)]

The focal is the square root of minus the dot product of the two vanishing points, measured from
the principal point. Nothing else enters — not where the camera stands, not how big the pitch is.

**Where it is weak, said up front.** The right-hand side must be positive; if the two vanishing
points fall on the same side of the principal point in that inner product, no real focal makes
those directions perpendicular, and the honest output is a refusal. And a long lens pushes the
vanishing points far outside the frame, where a degree of segment noise moves them a long way — so
the uncertainty is reported alongside the answer, not implied by its precision.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VanishingFocal:
    """A focal recovered from two vanishing points, with what it rests on.

    Attributes:
        focal_px: The estimate, or NaN when the geometry admits none.
        v1, v2: The two vanishing points, homogeneous, normalised so the last element is 1 where
            finite. A direction parallel to the image plane gives a point at infinity.
        n1, n2: How many segments supported each.
        reason: Empty when the estimate stands; otherwise why it does not.
    """

    focal_px: float
    v1: np.ndarray
    v2: np.ndarray
    n1: int
    n2: int
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(np.isfinite(self.focal_px)) and not self.reason


def focal_from_vanishing_points(v1, v2, cx: float, cy: float) -> VanishingFocal:
    """`f² = −[(u₁−cx)(u₂−cx) + (v₁−cy)(v₂−cy)]`, with the cases where it has no answer.

    Both points are taken as inhomogeneous `(u, v)`. A vanishing point at infinity — a world
    direction exactly parallel to the image plane — carries no focal information in this relation
    and is refused rather than approximated: pushing it to a large finite value would return a
    number whose precision is invented.
    """
    v1 = np.asarray(v1, dtype=float).ravel()
    v2 = np.asarray(v2, dtype=float).ravel()
    for v in (v1, v2):
        if v.size == 3:
            if abs(v[2]) < 1e-9:
                return VanishingFocal(float("nan"), v1, v2, 0, 0,
                                      "a vanishing point is at infinity: no focal information")
    p1 = (v1[:2] / v1[2]) if v1.size == 3 else v1[:2]
    p2 = (v2[:2] / v2[2]) if v2.size == 3 else v2[:2]

    dot = float((p1[0] - cx) * (p2[0] - cx) + (p1[1] - cy) * (p2[1] - cy))
    if dot >= 0:
        # Not a numerical accident: it says these two directions cannot be perpendicular under ANY
        # focal with this principal point. Either the grouping is wrong or the principal point is.
        return VanishingFocal(float("nan"), p1, p2, 0, 0,
                              "no real focal: the vanishing points give a dot product of "
                              f"{dot:+.0f}")
    return VanishingFocal(float(np.sqrt(-dot)), p1, p2, 0, 0)


def intersect(l1: np.ndarray, l2: np.ndarray) -> np.ndarray:
    """Homogeneous intersection of two image lines."""
    return np.cross(np.asarray(l1, dtype=float), np.asarray(l2, dtype=float))


def line_through(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Homogeneous line through two image points."""
    return np.cross(np.array([p[0], p[1], 1.0]), np.array([q[0], q[1], 1.0]))


def _consistency(seg: np.ndarray, vp: np.ndarray) -> float:
    """Angle, in radians, between a segment and the ray from its midpoint to a vanishing point.

    Scored as an angle rather than as a distance from the vanishing point, because the vanishing
    point of a long lens sits thousands of pixels outside the frame: a distance threshold there is
    meaningless, while the angle is exactly the quantity the eye and the geometry both care about.
    """
    mid = np.array([(seg[0] + seg[2]) / 2.0, (seg[1] + seg[3]) / 2.0])
    d = np.array([seg[2] - seg[0], seg[3] - seg[1]], dtype=float)
    n = np.linalg.norm(d)
    if n < 1e-9:
        return np.pi
    d /= n
    if abs(vp[2]) < 1e-9:                    # vanishing point at infinity: compare directions
        r = vp[:2] / (np.linalg.norm(vp[:2]) + 1e-12)
    else:
        r = vp[:2] / vp[2] - mid
        m = np.linalg.norm(r)
        if m < 1e-9:
            return np.pi
        r = r / m
    return float(np.arccos(np.clip(abs(float(d @ r)), 0.0, 1.0)))


def find_vanishing_point(segments: np.ndarray, *, tol_deg: float = 1.5,
                         iters: int = 2000, rng_seed: int = 0):
    """RANSAC one vanishing point out of a set of segments. Returns `(vp, inlier mask)`.

    Every pair of segments proposes a vanishing point — their intersection — and the proposal is
    scored by how many *other* segments point at it. Weighted by length, because a 200 px segment
    on the halfway line is far better evidence than a 12 px fragment of a scuffed goal area.
    """
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    n = len(segments)
    if n < 3:
        return None, np.zeros(n, dtype=bool)

    lines = np.stack([line_through(s[:2], s[2:]) for s in segments])
    # Normalise on (a, b) so a line is `n·x = c` with |n| = 1. Without this the cross product's
    # magnitude depends on how long the segments happened to be, and no fixed conditioning
    # threshold can mean anything.
    lines /= np.linalg.norm(lines[:, :2], axis=1, keepdims=True) + 1e-12
    lengths = np.hypot(segments[:, 2] - segments[:, 0], segments[:, 3] - segments[:, 1])
    tol = np.radians(tol_deg)
    rng = np.random.default_rng(rng_seed)

    best_score, best_vp, best_mask = -1.0, None, np.zeros(n, dtype=bool)
    for _ in range(iters):
        i, j = rng.choice(n, size=2, replace=False)
        # Do NOT reject near-parallel pairs. For a long lens the vanishing point is far away and
        # the lines that define it are ALMOST PARALLEL by construction — rejecting those rejects
        # the signal. A 2-degree guard here dropped the inlier count from 17 segments to 2.
        # Only exactly-coincident lines are degenerate, and `intersect` returns ~0 for those,
        # which the norm check below catches. A vanishing point with a vanishing third component
        # is a point at infinity: a legitimate answer that `_consistency` already handles.
        vp = intersect(lines[i], lines[j])
        nrm = np.linalg.norm(vp)
        if nrm < 1e-9:
            continue
        vp = vp / nrm
        ang = np.array([_consistency(s, vp) for s in segments])
        mask = ang < tol
        score = float(lengths[mask].sum())
        if score > best_score:
            best_score, best_vp, best_mask = score, vp, mask
    return best_vp, best_mask


def two_perpendicular_families(segments: np.ndarray, *, tol_deg: float = 1.5,
                               min_segments: int = 3, rng_seed: int = 0):
    """The two dominant vanishing points. Returns `(vp1, mask1, vp2, mask2)`.

    The second is found among the segments the first did not claim, which is what makes them
    different families rather than the same one twice — the failure mode when a frame shows one
    direction far more strongly than the other.
    """
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    vp1, m1 = find_vanishing_point(segments, tol_deg=tol_deg, rng_seed=rng_seed)
    if vp1 is None or m1.sum() < min_segments:
        return None, m1, None, np.zeros(len(segments), dtype=bool)
    rest = np.flatnonzero(~m1)
    if rest.size < min_segments:
        return vp1, m1, None, np.zeros(len(segments), dtype=bool)
    vp2, m2r = find_vanishing_point(segments[rest], tol_deg=tol_deg, rng_seed=rng_seed + 1)
    m2 = np.zeros(len(segments), dtype=bool)
    if vp2 is not None:
        m2[rest[m2r]] = True
    return vp1, m1, vp2, m2


def focal_from_segments(segments: np.ndarray, cx: float, cy: float, *,
                        tol_deg: float = 1.5, min_segments: int = 3,
                        rng_seed: int = 0) -> VanishingFocal:
    """Group segments into two perpendicular families, read the focal off their vanishing points."""
    vp1, m1, vp2, m2 = two_perpendicular_families(
        segments, tol_deg=tol_deg, min_segments=min_segments, rng_seed=rng_seed)
    if vp1 is None or vp2 is None:
        return VanishingFocal(float("nan"), np.zeros(3), np.zeros(3),
                              int(m1.sum()), int(m2.sum()),
                              "could not find two families of parallel segments")
    out = focal_from_vanishing_points(vp1, vp2, cx, cy)
    return VanishingFocal(out.focal_px, out.v1, out.v2, int(m1.sum()), int(m2.sum()), out.reason)
