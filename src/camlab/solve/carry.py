"""Move a camera to the next frame using the pixels alone, so the search starts where it should.

The measured failure this exists to fix: `refit_frame` is a local search, and from the per-frame
solve's own seed it stops well short of a camera that exists and is stable. A human hand-aligned
frame 28 to 3.6 px; started there the refit stays; started from the solve it halts at 16.5 px.
Seeding each frame with the *previous frame's* camera is worth about three frames — 5.5, 8.8,
14.7 px on 29–31 — and then loses the track, because the operator is panning and zooming and a
copied camera has not moved at all. See `findings/the-search-fails-not-the-model.md`.

So move it first, then refine. The mover is `measure/pixel_motion.py`'s image→image homography,
which knows nothing about the pitch, the markings or the focal — it is SIFT features and MAGSAC on
raw pixels. That independence is the point: a seed derived from the same lines the objective scores
would inherit their mistakes.

**The identity.** A camera turning and zooming about a fixed centre maps frame *i* to frame *j* by

    H(i→j) = K_j Rⱼ Rᵢᵀ K_i⁻¹

whatever the scene is — depth cancels because nothing translated. Rearranged,

    Rⱼ Rᵢᵀ = K_j⁻¹ H K_i

and the left side is a rotation, which is what pins the unknown `f_j`. Writing `A = H K_i` with
rows `a₁, a₂, a₃`, the rows of `K_j⁻¹ A` are `(a₁ − cx·a₃)/f_j`, `(a₂ − cy·a₃)/f_j`, `a₃`. All
three must have equal norm, so

    f_j = |a₁ − cx·a₃| / |a₃|   and   f_j = |a₂ − cy·a₃| / |a₃|

twice over, from the two image axes independently. They are averaged, and how far apart they were
is returned as `focal_disagreement` — a wide split means the pure-rotation assumption did not hold
for that pair, which is exactly when the seed should not be trusted.

**What it assumes, and when that breaks.** A fixed centre. A person in a seat shifting their weight
translates a few centimetres, which at 70 m is nothing; standing up is not. The homography's own
`median_px` and the focal disagreement together say when to stop believing it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from camlab.core.angles import matrix_from_rodrigues, rodrigues_from_matrix

#: Beyond this the two image axes disagree about the focal by more than a pure rotation can
#: explain, and the carried camera is a guess rather than a measurement. Reported, not enforced —
#: the caller decides whether to fall back, because "no seed" is sometimes worse than a rough one.
FOCAL_DISAGREEMENT_WARN = 0.10


@dataclass(frozen=True)
class Carried:
    """A camera moved to another frame by the pixels.

    Attributes:
        focal_px: The focal the homography implies for the destination frame.
        rotation: Rodrigues world→camera rotation there.
        position: Unchanged. This is a rotation-and-zoom model; if the camera translated, that
            shows up as a bad fit downstream rather than being silently absorbed here.
        focal_disagreement: `|f_x − f_y| / f`, from the two image axes solved independently. Near
            zero means the pair really was a rotation about a fixed centre.
        orthonormality_px: How far `K_j⁻¹ H K_i` was from a rotation before being projected onto
            one, as the largest singular-value departure from 1. A second, independent smell test.
    """

    focal_px: float
    rotation: np.ndarray
    position: np.ndarray
    focal_disagreement: float
    orthonormality_px: float


def _k(focal: float, cx: float, cy: float) -> np.ndarray:
    return np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]])


def carry(focal: float, rvec, position, h: np.ndarray, cx: float, cy: float) -> Carried | None:
    """Take a camera through an image→image homography to the frame that homography lands in.

    `h` maps the SOURCE frame's pixels to the destination's — `PairMotion.h` with `i` the frame
    the camera belongs to. Returns None when the algebra degenerates (a homography that is not a
    rotation-and-zoom at all), rather than a plausible camera with no warning attached.
    """
    rot = matrix_from_rodrigues(np.asarray(rvec, dtype=float))
    a = np.asarray(h, dtype=float) @ _k(float(focal), cx, cy)

    n3 = float(np.linalg.norm(a[2]))
    if n3 < 1e-12:
        return None
    fx = float(np.linalg.norm(a[0] - cx * a[2])) / n3
    fy = float(np.linalg.norm(a[1] - cy * a[2])) / n3
    if not (np.isfinite(fx) and np.isfinite(fy)) or min(fx, fy) < 1e-6:
        return None
    f_new = 0.5 * (fx + fy)
    disagreement = abs(fx - fy) / f_new

    m = np.linalg.inv(_k(f_new, cx, cy)) @ a
    u, s, vt = np.linalg.svd(m)
    if s[2] < 1e-12:
        return None
    # Nearest rotation to `m` in the Frobenius sense, with the reflection ruled out: an SVD of a
    # noisy near-rotation can hand back a determinant of −1, and a mirrored camera reprojects
    # plausibly enough to survive a residual check while being physically impossible.
    d = np.diag([1.0, 1.0, float(np.sign(np.linalg.det(u @ vt)))])
    m_rot = u @ d @ vt

    return Carried(
        focal_px=f_new,
        rotation=rodrigues_from_matrix(m_rot @ rot),
        position=np.asarray(position, dtype=float).copy(),
        focal_disagreement=float(disagreement),
        orthonormality_px=float(np.max(np.abs(s / s.mean() - 1.0))),
    )
