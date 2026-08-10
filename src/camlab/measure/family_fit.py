"""Which detected lines are markings — decided by spacing, which is the only thing that can.

Local appearance cannot do it: a mowing-stripe boundary is a bright narrow ridge with turf on both
sides, which is the definition paint detection uses, and measurement showed colour and ridge
contrast both failing to separate them
(`findings/local-appearance-cannot-find-markings.md`). Nor can a vanishing point: stripes are mown
along the pitch, so they join a real family and point at the same place.

What they cannot fake is **where they sit**. A pitch's parallel markings are at known world
positions — the touchline, the goal-area line, the penalty-area line — and a stripe falls between
them at a position no marking occupies.

**The invariant that makes this checkable without a camera.** Cut a family of parallel world lines
with any transversal and the map from world position to image position along it is a
one-dimensional projective map, `t → (a·t + b) / (c·t + d)`. Three correspondences determine it;
the fourth and beyond *test* it. So a set of detected lines either admits an assignment to model
markings under some such map, or it does not — and no camera is needed to ask, which is what makes
this an independent check rather than another way of assuming the answer.

A stripe has no model position to be assigned to. Forced into one it breaks the fit, and dropping
it restores it. That is the whole discriminator.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class FamilyFit:
    """One parallel family, and which of its detected lines are markings.

    Attributes:
        assignment: `{detected index: model index}` for the lines that fit.
        rejected: Detected indices that fit no model position — stripes, nets, shadows.
        residual_px: Worst disagreement, in image px along the transversal, over the assignment.
        n_used: How many correspondences the fit rests on. Three is the minimum and carries no
            test at all — a projective map through three points is exact by construction, so a
            three-point "fit" proves only that three points exist.
    """

    assignment: dict
    rejected: list
    residual_px: float
    n_used: int

    @property
    def tested(self) -> bool:
        """Whether the fit was actually constrained. Below four points it was not."""
        return self.n_used >= 4


def projective_1d(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares 1-D projective map `t → (a t + b)/(c t + d)`, as `[a, b, c, d]`.

    Solved as a homogeneous system, so it degrades gracefully rather than blowing up when the
    correspondences are nearly affine — which they are whenever the family is far from the horizon.
    """
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    # (a t + b) - u (c t + d) = 0
    a = np.column_stack([src, np.ones_like(src), -dst * src, -dst])
    _u, _s, vt = np.linalg.svd(a)
    return vt[-1]


def apply_1d(p: np.ndarray, t: np.ndarray) -> np.ndarray:
    a, b, c, d = p
    den = c * np.asarray(t, float) + d
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    return (a * np.asarray(t, float) + b) / den


def fit_family(detected_t: np.ndarray, model_t: np.ndarray, *,
               tol_px: float = 12.0, min_used: int = 4) -> FamilyFit:
    """Assign detected line positions to model marking positions under a 1-D projective map.

    Args:
        detected_t: Image positions of the detected lines along a transversal, any consistent unit.
        model_t: World positions of the family's markings, in metres.
        tol_px: How far a line may sit from where the fitted map puts it and still count.
        min_used: Fewest correspondences worth trusting. Three determine the map exactly and test
            nothing, so the default is four.

    Searches assignments in descending size and keeps the first that fits, which is the largest
    consistent explanation of the evidence rather than the cheapest.
    """
    detected_t = np.asarray(detected_t, float)
    model_t = np.asarray(model_t, float)
    n_det, n_mod = len(detected_t), len(model_t)
    if n_det < min_used or n_mod < min_used:
        return FamilyFit({}, list(range(n_det)), float("nan"), 0)

    # Detected lines keep their order along the transversal, and so do the model positions: a
    # projective map of the real line is monotone wherever it does not cross its pole, and a family
    # of pitch markings never straddles the horizon in a usable frame. So only ORDER-PRESERVING
    # assignments are candidates, which collapses the search from n! to a choice of subsets.
    det_order = np.argsort(detected_t)
    mod_order = np.argsort(model_t)
    dt = detected_t[det_order]
    mt = model_t[mod_order]

    best: FamilyFit | None = None
    for size in range(min(n_det, n_mod), min_used - 1, -1):
        for di in combinations(range(n_det), size):
            for mi in combinations(range(n_mod), size):
                p = projective_1d(mt[list(mi)], dt[list(di)])
                pred = apply_1d(p, mt[list(mi)])
                err = float(np.abs(pred - dt[list(di)]).max())
                if err <= tol_px and (best is None or err < best.residual_px):
                    best = FamilyFit(
                        {int(det_order[a]): int(mod_order[b]) for a, b in zip(di, mi, strict=True)},
                        [int(det_order[i]) for i in range(n_det) if i not in di],
                        err, size,
                    )
            if best is not None:
                break
        if best is not None:
            break
    if best is None:
        return FamilyFit({}, list(range(n_det)), float("nan"), 0)
    return best
