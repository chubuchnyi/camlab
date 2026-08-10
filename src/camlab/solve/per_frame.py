"""What camera does each frame think it is?

The pipeline this repo exists to fix solves every frame as an independent 8-DOF homography. That
family is provably not one camera — `plane_camera.camera_from_calibration` refuses it, correctly —
but each frame taken **alone** does decompose: a plane homography plus a focal gives a rotation and
a position, and the focal itself comes from Zhang's constraint on that one frame.

So this asks each frame separately, and the answer is the defect made visible. On a tripod clip the
120 recovered positions land on top of each other. On the handheld clip they scatter across the
stands — and that scatter is exactly the ground swim the eye reads as a storm of footballers,
drawn as what it actually is.

This is the **control side** of the A/B. M2 replaces it with one position, a per-frame rotation and
a smooth focal curve, and the two are drawn in the same viewer.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from camlab.core.plane_camera import FOCAL_BOUNDS, _decompose, _k_inv, _orthonormality

#: Below this, relative to the clip's own median, a homography has collapsed toward a line.
#: **Relative on purpose.** An absolute threshold cannot work — the scale of |det| depends on the
#: image size and the world units — and pitch3d's absolute `_SINGULAR_DET = 1e-12` misses the real
#: cases by six orders of magnitude: fan clip frames 115 and 117 sit at 1.0e-6 and 5.3e-8 against a
#: clip median of 3.4e-3, carry ordinary confidence (0.475, 0.394), and flip the measured world
#: handedness. See `landmines.md`.
DEGENERATE_DET_RATIO = 1e-3


@dataclass(frozen=True)
class PerFrameCameras:
    """One camera per frame, each recovered from that frame's homography alone.

    Attributes:
        frames: Source frame indices, shape (T,).
        focal_px: Per-frame focal, shape (T,). Free — this is what a zoom looks like when nothing
            is asked to be constant.
        position: Camera centre in world metres, shape (T, 3). `C = -Rᵀt`.
        rotation: World→camera rotation as Rodrigues vectors, shape (T, 3).
        zhang_residual: How far each frame's `K⁻¹H` columns are from a real rotation's, shape (T,).
            Zero means that frame *is* a pinhole at that focal; it says nothing about whether it is
            the same pinhole as its neighbours.
        degenerate: Frames whose homography is rank-poor, shape (T,). Recovered anyway and marked
            rather than dropped — R-6, mark never hide — but do not fit through them.
    """

    frames: np.ndarray
    focal_px: np.ndarray
    position: np.ndarray
    rotation: np.ndarray
    zhang_residual: np.ndarray
    degenerate: np.ndarray

    def __len__(self) -> int:
        return int(self.frames.shape[0])


def _rodrigues_inv(rot: np.ndarray) -> np.ndarray:
    theta = float(np.arccos(np.clip((np.trace(rot) - 1.0) / 2.0, -1.0, 1.0)))
    if theta < 1e-9:
        return np.zeros(3)
    v = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    return v * (theta / (2.0 * np.sin(theta)))


def focal_from_one_homography(h_w2i: np.ndarray, width: int, height: int,
                              n_grid: int = 160, cx: float | None = None,
                              cy: float | None = None) -> tuple[float, float]:
    """The focal that best makes ONE homography come from a real rotation. Returns (focal, cost).

    Coarse log grid then a golden-section refine. The residual is smooth in `f` but not convex over
    three octaves, so a local search from a fixed start settles in the wrong basin — the same
    reason `plane_camera._measure_focal` does this over the whole clip.

    A single plane cannot always pin the focal well: the residual's minimum is shallow when the
    frame sees little of the pitch. `zhang_residual` is returned so a shallow, untrustworthy answer
    is visible rather than implied.
    """
    cx = width / 2.0 if cx is None else float(cx)
    cy = height / 2.0 if cy is None else float(cy)

    def cost(f: float) -> float:
        return _orthonormality(h_w2i, _k_inv(f, cx, cy))

    grid = np.geomspace(*FOCAL_BOUNDS, n_grid)
    best = int(np.argmin([cost(float(f)) for f in grid]))
    a = float(grid[max(best - 1, 0)])
    b = float(grid[min(best + 1, len(grid) - 1)])

    phi = (np.sqrt(5.0) - 1.0) / 2.0
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = cost(c), cost(d)
    for _ in range(48):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = cost(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = cost(d)
    f = float((a + b) / 2.0)
    return f, cost(f)


def per_frame_cameras(h_i2w: np.ndarray, frames: np.ndarray, width: int, height: int,
                      cx: float | None = None, cy: float | None = None) -> PerFrameCameras:
    """Decompose each image→world homography into its own camera.

    Args:
        h_i2w: (T, 3, 3) image→world plane homographies, the way `FieldCalibration` stores them.
        frames: (T,) source frame indices.
        width, height: The image space `h_i2w` lives in. Get this wrong and every number below is
            wrong in a way that still looks plausible — see `runs.py`.
    """
    h_i2w = np.asarray(h_i2w, dtype=float)
    frames = np.asarray(frames, dtype=int)
    cx = width / 2.0 if cx is None else float(cx)
    cy = height / 2.0 if cy is None else float(cy)
    t = len(h_i2w)

    det = np.abs(np.linalg.det(h_i2w))
    finite = np.isfinite(h_i2w).all(axis=(1, 2))
    med = float(np.median(det[finite])) if finite.any() else 0.0
    degenerate = (~finite) | (det < DEGENERATE_DET_RATIO * med)

    focal = np.zeros(t)
    position = np.zeros((t, 3))
    rotation = np.zeros((t, 3))
    zhang = np.full(t, np.inf)

    for i in range(t):
        if not finite[i] or det[i] <= 0.0:
            continue
        h_w2i = np.linalg.inv(h_i2w[i])
        f, cost = focal_from_one_homography(h_w2i, width, height, cx=cx, cy=cy)
        rot, tr = _decompose(h_w2i, _k_inv(f, cx, cy))
        focal[i] = f
        rotation[i] = _rodrigues_inv(rot)
        position[i] = -rot.T @ tr        # world-space optical centre
        zhang[i] = cost

    return PerFrameCameras(
        frames=frames, focal_px=focal, position=position, rotation=rotation,
        zhang_residual=zhang, degenerate=degenerate,
    )
