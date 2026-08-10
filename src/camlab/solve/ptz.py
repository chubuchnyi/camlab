"""One camera, standing in one place, panning and tilting and zooming. The point of this repo.

The clip is currently 8 free parameters per frame with nothing tying the frames together, and the
consequence is measured: the recovered camera position wanders a median of 6.4 m and a worst of
82.3 m, which the eye reads as the whole pitch sliding under the players. This fits the model a
phone on a stand actually obeys instead:

| | |
|---|---|
| position | **one 3-vector for the whole clip** — a spectator does not walk |
| rotation | 3 per frame — they pan and tilt |
| focal | 1 per frame, smooth — they zoom, and this clip zooms 1.66x |
| principal point | assumed at the image centre, and that assumption is on the unverified list |

3 + 4N against 8N. But the parameter count is not the argument. **The camera cannot translate, so
the ground cannot slide** — the swim goes by construction rather than by smoothing afterwards, and
that distinction matters: smoothing would impose the very property being measured.

**Fitted to the paint, not to the homographies.** The homographies are 120 noisy fits *to* the
evidence; asking one camera to reproduce them is asking it to reproduce their noise. The evidence
is the painted lines in the frames, and `camlab.measure` is what reads them.

**Two stages, because the problem factorises.** The position is shared, so it only needs enough
frames to be pinned — and every frame that sees a different part of the pitch adds more than
another frame of the same view. Once the position is fixed, each frame's rotation and focal are
independent of every other frame's, so they solve one frame at a time in four parameters. That
turns a 483-parameter problem into a 100-parameter one plus N small ones, and it is why a fit over
120 frames takes seconds rather than minutes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares

from camlab.core.plane_camera import FOCAL_BOUNDS
from camlab.measure.paint import FrameEvidence
from camlab.measure.residual import _marking_samples, world_to_image
from camlab.solve.per_frame import PerFrameCameras

#: A marking sample matches the paint it is nearest to only if it is this close. Wide enough for a
#: seed that is several px out to find its own line, narrow enough that a marking cannot capture
#: its neighbour: the tightest pair on a pitch — the goal-area and goal lines, 5.5 m apart — is
#: still tens of px apart wherever both are visible.
MATCH_PX = 14.0

#: The camera is above the pitch. Not a regularisation term but a fact, and imposing it removes a
#: whole family of solutions that fit the plane perfectly while standing underneath it — the shape
#: of pitch3d's #118. The per-frame solve puts 8 of 116 fan frames below ground.
MIN_HEIGHT_M = 0.5


@dataclass(frozen=True)
class PTZFit:
    """One position, per-frame orientation and focal.

    Attributes:
        centre: The one optical centre, world metres.
        frames: Frame indices, shape (T,).
        focal_px: Per-frame focal, shape (T,). Zero where the frame could not be solved.
        rotation: Per-frame Rodrigues world→camera, shape (T, 3).
        fit_frames: Which frames the shared position was fitted over.
        centre_seed: Where the fit started, so the distance it travelled is readable.
        stage1_px: Median paint residual over `fit_frames` after the position was fixed.
    """

    centre: np.ndarray
    frames: np.ndarray
    focal_px: np.ndarray
    rotation: np.ndarray
    fit_frames: np.ndarray
    centre_seed: np.ndarray
    stage1_px: float

    def __len__(self) -> int:
        return int(self.frames.shape[0])


def _rodrigues(r: np.ndarray) -> np.ndarray:
    theta = float(np.linalg.norm(r))
    if theta < 1e-12:
        return np.eye(3)
    k = np.asarray(r, dtype=float) / theta
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * kx + (1 - np.cos(theta)) * (kx @ kx)


def _project(h: np.ndarray, xy1: np.ndarray) -> np.ndarray:
    q = xy1 @ h.T
    w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
    return q[:, :2] / w[:, None]


def _match(h: np.ndarray, ev: FrameEvidence, xy1: np.ndarray):
    """Correspondences between projected markings and painted pixels, ICP-style.

    A distance map is a scalar with a cap, so a sample 20 px out has no gradient at all. Its zero
    set is the paint's centreline, though, so a KD-tree turns every sample into a real 2D
    correspondence with a real Jacobian. Re-matched each round, so the fit can travel further than
    one match radius.
    """
    uv = _project(h, xy1)
    ok = ((uv[:, 0] > 1) & (uv[:, 0] < ev.width - 2)
          & (uv[:, 1] > 1) & (uv[:, 1] < ev.height - 2))
    idx = np.flatnonzero(ok)
    if not len(idx):
        return None
    sub = uv[idx]
    on = ev.surface[np.rint(sub[:, 1]).astype(int), np.rint(sub[:, 0]).astype(int)] > 0
    idx, sub = idx[on], sub[on]
    if not len(idx):
        return None
    d, nn = ev.tree.query(sub, distance_upper_bound=MATCH_PX)
    hit = np.isfinite(d)
    if not hit.any():
        return None
    return xy1[idx[hit]], ev.spine[nn[hit]]


def _fit_one_frame(ev, focal0, rvec0, centre, xy1, rounds=3):
    """Frame's own (focal, rotation) with the position held. Four parameters, its own paint."""
    p = np.concatenate([[focal0], rvec0])
    lo = np.array([FOCAL_BOUNDS[0], -np.inf, -np.inf, -np.inf])
    hi = np.array([FOCAL_BOUNDS[1], np.inf, np.inf, np.inf])
    for _ in range(rounds):
        m = _match(world_to_image(p[0], p[1:], centre, ev.width, ev.height), ev, xy1)
        if m is None:
            return p, 0
        src, dst = m

        def residuals(q, src=src, dst=dst):
            h = world_to_image(q[0], q[1:], centre, ev.width, ev.height)
            return (_project(h, src) - dst).ravel()

        p = least_squares(residuals, np.clip(p, lo, hi), bounds=(lo, hi), x_scale="jac",
                          loss="soft_l1", f_scale=3.0, max_nfev=120).x
    m = _match(world_to_image(p[0], p[1:], centre, ev.width, ev.height), ev, xy1)
    return p, (0 if m is None else len(m[0]))


def fit_ptz(
    seed: PerFrameCameras,
    evidence: dict[int, FrameEvidence],
    *,
    anchor_frames: np.ndarray | None = None,
    rounds: int = 4,
) -> PTZFit:
    """Fit one position for the clip, then each frame's orientation and focal against it.

    Args:
        seed: The per-frame decomposition, used only as a starting point. Its median position is
            where the shared centre starts; its per-frame focals and rotations start each frame.
        evidence: Paint per frame, keyed by frame index. Frames absent here cannot be fitted.
        anchor_frames: Which frames pin the shared position. Defaults to an even spread over the
            frames that have both evidence and a non-degenerate seed. More is not better past a
            point — what helps is frames that see *different* parts of the pitch.
    """
    xy1 = _marking_samples()
    usable = np.array([
        i for i, f in enumerate(seed.frames)
        if int(f) in evidence and seed.focal_px[i] > 0 and not seed.degenerate[i]
    ], dtype=int)
    if usable.size < 2:
        raise ValueError(f"only {usable.size} usable frame(s): nothing to tie a position to")

    if anchor_frames is None:
        n_anchor = int(min(24, max(6, usable.size // 4)))
        anchor = usable[np.unique(np.linspace(0, usable.size - 1, n_anchor).round().astype(int))]
    else:
        anchor = np.array([i for i in anchor_frames if i in usable], dtype=int)

    centre_seed = np.median(seed.position[usable], axis=0)
    centre_seed[2] = max(centre_seed[2], MIN_HEIGHT_M)

    # ---- stage 1: the shared position, with the anchors' own focals and rotations free --------
    n = len(anchor)
    p = np.concatenate([centre_seed,
                        np.column_stack([seed.focal_px[anchor], seed.rotation[anchor]]).ravel()])
    lo = np.concatenate([[-np.inf, -np.inf, MIN_HEIGHT_M],
                         np.tile([FOCAL_BOUNDS[0], -np.inf, -np.inf, -np.inf], n)])
    hi = np.concatenate([[np.inf, np.inf, np.inf],
                         np.tile([FOCAL_BOUNDS[1], np.inf, np.inf, np.inf], n)])

    for _ in range(rounds):
        pairs, owner = [], []
        for j, i in enumerate(anchor):
            ev = evidence[int(seed.frames[i])]
            h = world_to_image(p[3 + 4 * j], p[4 + 4 * j:7 + 4 * j], p[:3], ev.width, ev.height)
            m = _match(h, ev, xy1)
            if m is None:
                continue
            pairs.append(m)
            owner.append(np.full(len(m[0]), j))
        if not pairs:
            break
        src = np.concatenate([a for a, _ in pairs])
        dst = np.concatenate([b for _, b in pairs])
        own = np.concatenate(owner)

        def residuals(q, src=src, dst=dst, own=own):
            out = np.empty_like(dst)
            for j, i in enumerate(anchor):
                m = own == j
                if not m.any():
                    continue
                ev = evidence[int(seed.frames[i])]
                h = world_to_image(q[3 + 4 * j], q[4 + 4 * j:7 + 4 * j], q[:3],
                                   ev.width, ev.height)
                out[m] = _project(h, src[m])
            return (out - dst).ravel()

        # The centre touches every residual; each frame's block touches only its own. Declaring
        # that turns a dense 100-column numerical Jacobian into a handful of evaluations.
        spar = np.zeros((2 * len(own), len(p)), dtype=np.uint8)
        spar[:, :3] = 1
        for j in range(n):
            rows = np.flatnonzero(own == j)
            rows = np.concatenate([2 * rows, 2 * rows + 1])
            if rows.size:
                spar[np.ix_(rows, list(range(3 + 4 * j, 7 + 4 * j)))] = 1
        # x_scale="jac" is required, not tuning: a focal is ~4000 and a rotation component is ~1,
        # so on a common scale the optimiser cannot see the focal and hands back its seed.
        p = least_squares(residuals, np.clip(p, lo, hi), jac_sparsity=spar, bounds=(lo, hi),
                          x_scale="jac", loss="soft_l1", f_scale=3.0, max_nfev=300).x

    centre = p[:3].copy()

    # ---- stage 2: every frame's own orientation and focal, position held ----------------------
    t = len(seed.frames)
    focal = np.zeros(t)
    rot = np.zeros((t, 3))
    for i in range(t):
        ev = evidence.get(int(seed.frames[i]))
        if ev is None or not (seed.focal_px[i] > 0):
            continue
        f0 = seed.focal_px[i] if seed.focal_px[i] > 0 else float(np.median(seed.focal_px[usable]))
        q, n_matched = _fit_one_frame(ev, f0, seed.rotation[i], centre, xy1)
        if n_matched:
            focal[i], rot[i] = q[0], q[1:]

    # stage-1 residual, reported so the position's own evidence is visible rather than implied
    errs = []
    for j, i in enumerate(anchor):
        ev = evidence[int(seed.frames[i])]
        h = world_to_image(p[3 + 4 * j], p[4 + 4 * j:7 + 4 * j], centre, ev.width, ev.height)
        m = _match(h, ev, xy1)
        if m is not None:
            errs.append(np.linalg.norm(_project(h, m[0]) - m[1], axis=1))
    stage1 = float(np.median(np.concatenate(errs))) if errs else float("nan")

    return PTZFit(centre=centre, frames=seed.frames, focal_px=focal, rotation=rot,
                  fit_frames=seed.frames[anchor], centre_seed=centre_seed, stage1_px=stage1)
