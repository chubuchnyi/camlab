"""A first camera from one frame, with no seed and no human — by trying correspondences, not poses.

Everything downstream of a starting camera works: carry, self-heal, one shared centre, and 120 of
120 frames under 20 px on the fan clip. Both clips that reached that point were handed their first
camera by pitch3d, and seven of nine sample clips have no such file. This is the missing step.

**Why the obvious thing fails.** Sampling cameras at random — position around the pitch, aim at a
random point on it, focal over a wide range — and keeping the best by the line objective does not
work, and not for want of trying: on fan frame 8, 4000, 20 000 and 60 000 samples all return the
*identical* wrong camera, 17.3 px on 22 scored samples against a truth of 2.1 px on 307. The search
converges, to the wrong place, because `refit.objective` charges `MISS_PX` per unmatched marking
and a camera that frames almost no pitch has almost nothing to miss. Pointing at a corner and
fitting four lines beats framing the pitch and fitting twelve.

**So search the correspondences instead.** The pitch is known geometry, and two facts collapse the
combinatorics without assuming anything about the camera:

    the markings form exactly two world-parallel families, and each family meets at its own
    vanishing point in the image — so the detected lines can be split into two groups before any
    camera exists;

    and parallel markings appear in the image in the SAME ORDER as in the world, always, so once
    two detected lines and two model markings are chosen the assignment between them is fixed up to
    which end is which.

Four line correspondences — two from each family — determine a homography. Lines map by
`l_world ∝ Hᵀ l_image`, so each correspondence gives two linear equations in the nine entries of H,
and four give eight: an SVD away from an answer. The focal follows from requiring that homography
to come from a real rotation, which `focal_from_one_homography` already does.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from camlab.core.plane_camera import _decompose, _k_inv
from camlab.measure.line_error import straight_markings, world_family
from camlab.solve.per_frame import focal_from_one_homography

#: A vanishing point is "shared" when every line of the family passes this close to it, measured in
#: the image. Generous, because a family's vanishing point can sit far outside the frame where a
#: degree of line-angle error is a long way in pixels.
VP_TOL_PX = 60.0

#: Below this fraction of the pitch model landing inside the picture, a camera is not a candidate
#: however well it fits: it is looking at a corner. This is the guard the random search lacked.
MIN_IN_FRAME = 0.12


@dataclass(frozen=True)
class Hypothesis:
    """One candidate camera and the correspondence that produced it."""

    focal_px: float
    rotation: np.ndarray
    position: np.ndarray
    in_frame: float
    pairs: tuple


def _line(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Homogeneous line through two points, normalised so `|n| = 1`."""
    line = np.cross(np.append(p, 1.0), np.append(q, 1.0))
    n = np.linalg.norm(line[:2])
    return line / n if n > 1e-12 else line


def split_families(segments: np.ndarray, tol_px: float = VP_TOL_PX) -> tuple[list[int], list[int]]:
    """Split detected segments into the two world-parallel families, using the image alone.

    Consensus on a vanishing point, not clustering on angle. Angle fails by construction:
    perspective spreads one family's image directions across more than the threshold that would
    have to separate them — measured at 22.1° to 32.5° for three members of a single family on one
    real frame, against an 8° tolerance. Their vanishing point is shared exactly.
    """
    n = len(segments)
    if n < 4:
        return list(range(n)), []
    pts = [(np.array(s[:2], float), np.array(s[2:], float)) for s in segments]
    lines = [_line(a, b) for a, b in pts]

    best: tuple[int, list[int]] = (0, [])
    for i, j in combinations(range(n), 2):
        v = np.cross(lines[i], lines[j])
        if abs(v[2]) < 1e-9:                      # parallel in the image: vanishing point at
            v = np.array([v[0], v[1], 0.0])       # infinity, which is legitimate
        else:
            v = v / v[2]
        members = []
        for k, line in enumerate(lines):
            # Distance from the vanishing point to the line, in pixels when v is finite.
            d = abs(float(line @ v)) / (1.0 if abs(v[2]) < 1e-9 else 1.0)
            if d < tol_px:
                members.append(k)
        if len(members) > len(best[1]):
            best = (0, members)
    a = best[1]
    b = [k for k in range(n) if k not in a]
    return (a, b) if len(a) >= len(b) else (b, a)


def _homography_from_lines(img_lines: list[np.ndarray], world_lines: list[np.ndarray]):
    """World→image homography from ≥4 line correspondences, or None if degenerate.

    Lines are contravariant: `l_world ∝ Hᵀ l_image`. Writing `m = Hᵀ l_image` as a linear map on
    the nine entries of H, `l_world × m = 0` gives two independent rows per correspondence.
    """
    rows = []
    for li, lw in zip(img_lines, world_lines, strict=True):
        m = np.zeros((3, 9))
        for i in range(3):
            for j in range(3):
                m[j, 3 * i + j] = li[i]
        cross = np.array([[0.0, -lw[2], lw[1]], [lw[2], 0.0, -lw[0]], [-lw[1], lw[0], 0.0]])
        rows.append(cross @ m)
    a = np.vstack(rows)
    if a.shape[0] < 8:
        return None
    _u, s, vt = np.linalg.svd(a)
    if s[-2] < 1e-12:
        return None
    h = vt[-1].reshape(3, 3)
    return None if abs(np.linalg.det(h)) < 1e-12 else h


def _in_frame_share(h_w2i: np.ndarray, samples: np.ndarray, width: int, height: int) -> float:
    q = samples @ h_w2i.T
    w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
    uv = q[:, :2] / w[:, None]
    ok = (q[:, 2] > 0) & (uv[:, 0] > 0) & (uv[:, 0] < width) & (uv[:, 1] > 0) & (uv[:, 1] < height)
    return float(ok.mean())


def hypotheses(segments: np.ndarray, width: int, height: int, cx: float, cy: float,
               *, max_hypotheses: int = 400_000, rng=None):
    """Every family-consistent, order-preserving 2+2 assignment that yields a plausible camera.

    Yields `Hypothesis`. The caller scores them — this deliberately does not, so the scoring rule
    stays where it can be changed and measured.
    """
    from camlab.measure.residual import _marking_samples

    segments = np.asarray(segments, float).reshape(-1, 4)
    if len(segments) < 4:
        return
    fam_img = split_families(segments)
    if len(fam_img[0]) < 2 or len(fam_img[1]) < 2:
        return

    img_lines = [_line(np.array(s[:2]), np.array(s[2:])) for s in segments]
    model = {}
    for k, world in straight_markings():
        model.setdefault(world_family(world), []).append(
            (k, _line(world[0], world[1]), (world[0] + world[1]) / 2.0))
    if 0 not in model or 1 not in model:
        return
    # Order both sides along the family's own normal, so "order-preserving" is well defined.
    for f in model:
        u = model[f][0][1][:2]
        nrm = np.array([-u[1], u[0]])
        model[f].sort(key=lambda e, nrm=nrm: float(e[2] @ nrm))
    img_sorted = []
    for ids in fam_img:
        u = img_lines[ids[0]][:2]
        nrm = np.array([-u[1], u[0]])
        img_sorted.append(sorted(ids, key=lambda i, nrm=nrm: float(
            ((segments[i][:2] + segments[i][2:]) / 2) @ nrm)))

    samples = _marking_samples()
    count = 0
    # Which image family is which world family is unknown, so both ways round.
    for swap in (False, True):
        ia, ib = (img_sorted[1], img_sorted[0]) if swap else (img_sorted[0], img_sorted[1])
        ma, mb = model[0], model[1]
        for (p, q) in combinations(ia, 2):
            for (r, s) in combinations(ib, 2):
                for (x, y) in combinations(range(len(ma)), 2):
                    for (z, w) in combinations(range(len(mb)), 2):
                        # Image order may run with the world order or against it, per family.
                        for flip_a in (False, True):
                            for flip_b in (False, True):
                                aa = (ma[y], ma[x]) if flip_a else (ma[x], ma[y])
                                bb = (mb[w], mb[z]) if flip_b else (mb[z], mb[w])
                                h = _homography_from_lines(
                                    [img_lines[p], img_lines[q], img_lines[r], img_lines[s]],
                                    [aa[0][1], aa[1][1], bb[0][1], bb[1][1]])
                                count += 1
                                if count > max_hypotheses:
                                    return
                                if h is None:
                                    continue
                                share = _in_frame_share(h, samples, width, height)
                                if share < MIN_IN_FRAME:
                                    continue
                                focal, _cost = focal_from_one_homography(
                                    h, width, height, n_grid=40, cx=cx, cy=cy)
                                if not (300.0 < focal < 20000.0):
                                    continue
                                rot, t = _decompose(h, _k_inv(focal, cx, cy))
                                centre = -rot.T @ t
                                if centre[2] < 2.0 or centre[2] > 80.0:
                                    continue
                                yield Hypothesis(float(focal), rot, centre, share,
                                                 ((p, aa[0][0]), (q, aa[1][0]),
                                                  (r, bb[0][0]), (s, bb[1][0])))
