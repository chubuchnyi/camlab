"""Frame-to-frame motion measured from the pixels, with no pitch model anywhere in it.

The paint cannot say where along its viewing ray the camera sits — measured, `findings/
m2-paint-alone-cannot-pin-the-position.md`: the residual is flat over ±30 m because focal and
distance trade off exactly on a plane. This is the instrument that breaks that tie, and it is
independent in the strongest sense: no calibration, no pitch, no focal anywhere in its derivation.

**The identity it rests on.** A camera turning about a fixed centre maps frame *i* to frame *j* by

    H(i→j) = K Rⱼ Rᵢᵀ K⁻¹

*whatever the scene is* — near, far, flat or not. Depth cancels, because nothing translated. So a
homography measured straight from matched features carries two things the pitch cannot give:

1. **The focal.** Over a large enough turn the relation is not degenerate in `f`, so `f` can be
   read off the measured maps. Over a small turn it is degenerate — `K R K⁻¹ → I` as the rotation
   goes to zero, for every `f` — which is why the gaps below reach to 59 frames and not just 1.
2. **A test of the fixed-centre premise itself.** If the camera translated, parallax means no
   single homography fits both the near stand and the far pitch, and the residual says so. That is
   a direct test of M-1's assumption on a signal with nothing to do with the pitch, and it is the
   one thing that can refute the whole PTZ model rather than merely fail to confirm it.

**What it cannot do.** It measures rotation *between* frames, so it pins the shape of the pan and
the focal, and says nothing about absolute position or absolute orientation. It is one half of a
pair: the paint says where the camera points and roughly how far it is; this says how it turned and
how long the lens is. Neither alone is a camera.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Frame gaps to measure over. Gap 1 pins the frame-to-frame jitter and is the only gap that can.
#: The long gaps are what make the focal identifiable at all: below a few degrees of turn,
#: `K R Rᵀ K⁻¹` is degenerate in `f`, so a fit given only consecutive pairs reads the focal off
#: nothing and returns its seed.
DEFAULT_GAPS = (1, 10, 30, 59)

#: MAGSAC++ threshold in pixels. Generous on purpose: the aim is a map that agrees with the bulk of
#: the frame, not a minimal-inlier fit that latches onto one advertising board.
RANSAC_PX = 3.0

#: Below this many inliers a pair is dropped rather than trusted. A homography from 20 matches on a
#: crowd is a number, not a measurement.
MIN_INLIERS = 40


@dataclass(frozen=True)
class PairMotion:
    """One measured image→image map.

    Attributes:
        i, j: Frame indices, `i < j`.
        h: (3, 3) homography mapping frame `i`'s pixels to frame `j`'s.
        inliers: How many matched features supported it.
        median_px: Median reprojection of those inliers through `h`. This is the map's own
            precision, and it bounds what any camera model fitted to it can claim.
    """

    i: int
    j: int
    h: np.ndarray
    inliers: int
    median_px: float


def measure_pairs(frame_paths: dict[int, object], gaps=DEFAULT_GAPS,
                  max_features: int = 4000) -> list[PairMotion]:
    """SIFT + MAGSAC image→image homographies over the requested frame gaps.

    `frame_paths` maps frame index to the decoded frame on disk. Pairs whose match is thin or whose
    homography does not reproduce its own inliers are dropped, and dropping is reported by absence
    rather than by a low-confidence entry: a bad map here would poison the focal it is being used
    to measure.
    """
    import cv2

    sift = cv2.SIFT_create(nfeatures=max_features)
    cache: dict[int, tuple] = {}

    def feats(f: int):
        if f not in cache:
            img = cv2.imread(str(frame_paths[f]), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise FileNotFoundError(frame_paths[f])
            cache[f] = sift.detectAndCompute(img, None)
        return cache[f]

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    frames = sorted(frame_paths)
    out: list[PairMotion] = []
    for gap in gaps:
        for i in frames:
            j = i + gap
            if j not in frame_paths:
                continue
            (k1, d1), (k2, d2) = feats(i), feats(j)
            if d1 is None or d2 is None or len(k1) < MIN_INLIERS or len(k2) < MIN_INLIERS:
                continue
            # Lowe's ratio test. Without it a stadium full of near-identical seats and repeated
            # advertising text produces confident nonsense matches.
            good = [m for m, n in matcher.knnMatch(d1, d2, k=2) if m.distance < 0.75 * n.distance]
            if len(good) < MIN_INLIERS:
                continue
            src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            h, mask = cv2.findHomography(src, dst, cv2.USAC_MAGSAC, RANSAC_PX,
                                         maxIters=5000, confidence=0.9999)
            if h is None or mask is None or int(mask.sum()) < MIN_INLIERS:
                continue
            keep = mask.ravel().astype(bool)
            p = np.column_stack([src.reshape(-1, 2)[keep], np.ones(int(keep.sum()))])
            q = p @ h.T
            w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
            err = np.linalg.norm(q[:, :2] / w[:, None] - dst.reshape(-1, 2)[keep], axis=1)
            out.append(PairMotion(i, j, h, int(keep.sum()), float(np.median(err))))
    return out


def _rotation_only_map(f: float, rot_i: np.ndarray, rot_j: np.ndarray,
                       width: int, height: int) -> np.ndarray:
    """`K Rⱼ Rᵢᵀ K⁻¹` — what the image→image map MUST be if the camera only turned."""
    k = np.array([[f, 0.0, width / 2.0], [0.0, f, height / 2.0], [0.0, 0.0, 1.0]])
    kinv = np.array([[1.0 / f, 0.0, -width / (2.0 * f)],
                     [0.0, 1.0 / f, -height / (2.0 * f)],
                     [0.0, 0.0, 1.0]])
    return k @ (rot_j @ rot_i.T) @ kinv


def rotation_only_error(pairs: list[PairMotion], focal: float, rotations: dict[int, np.ndarray],
                        width: int, height: int, grid: int = 7) -> np.ndarray:
    """Per-pair px disagreement between the measured map and a pure-rotation one.

    Scored on a grid inset from the border, because `K R Rᵀ K⁻¹` is exact at the principal point
    for **every** focal: a grid huddled near the centre would be blind to the one parameter this
    measurement exists to provide.
    """
    us = np.linspace(0.15 * width, 0.85 * width, grid)
    vs = np.linspace(0.15 * height, 0.85 * height, grid)
    pts = np.column_stack([g.ravel() for g in np.meshgrid(us, vs)] + [np.ones(grid * grid)])

    def apply(h):
        q = pts @ h.T
        w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
        return q[:, :2] / w[:, None]

    out = []
    for p in pairs:
        if p.i not in rotations or p.j not in rotations:
            out.append(np.nan)
            continue
        model = _rotation_only_map(focal, rotations[p.i], rotations[p.j], width, height)
        out.append(float(np.median(np.linalg.norm(apply(p.h) - apply(model), axis=1))))
    return np.asarray(out)


def fit_rotation_only(pairs: list[PairMotion], frames, width: int, height: int,
                      seed_focal: float, seed_rot: dict[int, np.ndarray],
                      grid: int = 7, max_nfev: int = 300):
    """Explain every measured map with ONE focal and a rotation per frame. Nothing else.

    This is the test that can refute the whole PTZ model rather than merely fail to confirm it. If
    the camera turns about a fixed point, `K Rⱼ Rᵢᵀ K⁻¹` can reproduce the measured maps down to
    their own precision. If it translates, parallax makes that impossible however the parameters
    are set — the far pitch and the near stand move by different amounts, and no homography covers
    both.

    So read the returned residual against the maps' own self-error, not against zero. Landing at
    the self-error means "a fixed centre explains everything the pixels show". Landing well above
    it means the camera moved.

    Returns `(focal, {frame: rotation matrix}, residual_px)`.
    """
    from scipy.optimize import least_squares

    frames = [int(f) for f in frames]
    index = {f: n for n, f in enumerate(frames)}
    pairs = [p for p in pairs if p.i in index and p.j in index]
    if len(pairs) < 4:
        raise ValueError(f"only {len(pairs)} usable pairs")

    us = np.linspace(0.15 * width, 0.85 * width, grid)
    vs = np.linspace(0.15 * height, 0.85 * height, grid)
    pts = np.column_stack([g.ravel() for g in np.meshgrid(us, vs)] + [np.ones(grid * grid)])

    def apply(h):
        q = pts @ h.T
        w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
        return q[:, :2] / w[:, None]

    measured = np.stack([apply(p.h) for p in pairs])

    def rod(r):
        th = float(np.linalg.norm(r))
        if th < 1e-12:
            return np.eye(3)
        k = r / th
        kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        return np.eye(3) + np.sin(th) * kx + (1 - np.cos(th)) * (kx @ kx)

    def unrod(m):
        th = float(np.arccos(np.clip((np.trace(m) - 1) / 2, -1, 1)))
        if th < 1e-9:
            return np.zeros(3)
        v = np.array([m[2, 1] - m[1, 2], m[0, 2] - m[2, 0], m[1, 0] - m[0, 1]])
        return v * (th / (2 * np.sin(th)))

    p0 = np.concatenate([[seed_focal]] + [
        [unrod(seed_rot[f]) if f in seed_rot else np.zeros(3)][0] for f in frames
    ])

    def residuals(q):
        f = q[0]
        rots = [rod(q[1 + 3 * n:4 + 3 * n]) for n in range(len(frames))]
        out = np.empty_like(measured)
        for n, p in enumerate(pairs):
            out[n] = apply(_rotation_only_map(f, rots[index[p.i]], rots[index[p.j]], width, height))
        return (out - measured).ravel()

    # Each pair sees the focal and the two rotations it relates, and nothing else.
    spar = np.zeros((measured.size, len(p0)), dtype=np.uint8)
    spar[:, 0] = 1
    for n, p in enumerate(pairs):
        rows = np.arange(n * grid * grid * 2, (n + 1) * grid * grid * 2)
        for f in (p.i, p.j):
            spar[np.ix_(rows, list(range(1 + 3 * index[f], 4 + 3 * index[f])))] = 1

    lo = np.full(len(p0), -np.inf)
    hi = np.full(len(p0), np.inf)
    lo[0], hi[0] = 200.0, 40000.0
    sol = least_squares(residuals, np.clip(p0, lo, hi), jac_sparsity=spar, bounds=(lo, hi),
                        x_scale="jac", loss="soft_l1", f_scale=2.0, max_nfev=max_nfev)
    per_pair = np.linalg.norm(sol.fun.reshape(len(pairs), -1, 2), axis=2)
    return (float(sol.x[0]),
            {f: rod(sol.x[1 + 3 * n:4 + 3 * n]) for n, f in enumerate(frames)},
            float(np.median(per_pair)))


def rotation_only_residual_px(pair: PairMotion, cx: float, cy: float, width: int, height: int,
                              grid: int = 9, bounds=(800.0, 20000.0)) -> tuple[float, float, float]:
    """Closest pure-rotation explanation of one measured map, **in pixels**. `(px, f_i, f_j)`.

    This is the number that decides whether the camera turned or travelled, so it is expressed in
    the same unit as the map's own precision (0.28–0.60 px) rather than in an abstract
    orthonormality norm — a residual you cannot compare to anything is a residual you will
    misread, and I misread it twice in opposite directions before writing this.

    **The focal search must be refined, not gridded.** A coarse grid over `f_i, f_j` fabricates
    residual out of nothing: on a synthetic PURE rotation of 8° at f=2400, a 34-point log grid
    returns 8.03 px, an 80-point grid 0.49 px, and a grid-seeded Nelder-Mead **0.0000 px**. The
    grid version cannot tell that case apart from a genuine 2 m translation at 60 m depth, which
    scores 15.7 px on the same coarse grid and 2.28 px refined. Every conclusion drawn from the
    coarse version was an artefact of its own step size.

    Calibration for reading the output, from those synthetics: a pure rotation gives 0, and about
    **1 px per metre** of camera translation at this clip's ~60–80 m viewing distance.
    """
    import itertools

    from scipy.optimize import minimize

    us = np.linspace(0.15 * width, 0.85 * width, grid)
    vs = np.linspace(0.15 * height, 0.85 * height, grid)
    pts = np.column_stack([g.ravel() for g in np.meshgrid(us, vs)] + [np.ones(grid * grid)])

    def apply(h):
        q = pts @ h.T
        w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
        return q[:, :2] / w[:, None]

    def kmat(f):
        return np.array([[f, 0.0, cx], [0.0, f, cy], [0.0, 0.0, 1.0]])

    def kinv(f):
        return np.array([[1.0 / f, 0.0, -cx / f], [0.0, 1.0 / f, -cy / f], [0.0, 0.0, 1.0]])

    measured = apply(pair.h)

    def cost(fi, fj):
        if not (bounds[0] * 0.5 < fi < bounds[1] * 2 and bounds[0] * 0.5 < fj < bounds[1] * 2):
            return 1e9
        m = kinv(fj) @ pair.h @ kmat(fi)
        det = np.linalg.det(m)
        if abs(det) < 1e-12:
            return 1e9
        m = m / np.sign(det) / abs(det) ** (1 / 3)
        u, _s, vt = np.linalg.svd(m)
        rot = u @ np.diag([1.0, 1.0, float(np.linalg.det(u @ vt))]) @ vt
        return float(np.median(np.linalg.norm(measured - apply(kmat(fj) @ rot @ kinv(fi)), axis=1)))

    coarse = np.geomspace(*bounds, 26)
    best, seed = np.inf, (coarse[0], coarse[0])
    for fi, fj in itertools.product(coarse, coarse):
        v = cost(float(fi), float(fj))
        if v < best:
            best, seed = v, (float(fi), float(fj))
    res = minimize(lambda q: cost(float(np.exp(q[0])), float(np.exp(q[1]))), np.log(seed),
                   method="Nelder-Mead",
                   options={"xatol": 1e-5, "fatol": 1e-6, "maxiter": 800})
    return float(res.fun), float(np.exp(res.x[0])), float(np.exp(res.x[1]))


def focals_from_homography(h: np.ndarray, cx: float, cy: float
                           ) -> tuple[float | None, float | None]:
    """`(focal of frame i, focal of frame j)` in pixels, from the map between them alone.

    Closed form, from Shum and Szeliski, *Construction of Panoramic Image Mosaics with Global and
    Local Alignment*. It holds under the same assumption the carry stage already makes and has
    already measured — a camera turning about a fixed centre — so it costs nothing beyond a
    homography this repo computes anyway, and it answers a question nothing else here answers
    independently: **what is the focal, without the pitch model?**

    Every other focal in camlab comes from fitting markings. This one comes from the pixels, so
    when the two agree the agreement means something, and when they disagree it localises the
    problem to one side or the other.

    `cv2.detail.focalsFromHomography` is the same maths and is **unusable from Python**: its C++
    signature writes `f0`, `f1`, `f0_ok`, `f1_ok` through references, which the binding cannot do
    for immutable Python numbers, so on OpenCV 5.0 it returns `None` whatever is passed.

    **`cx`, `cy` are not optional and are the whole trap.** The derivation assumes the optical axis
    is at the origin, and a homography measured between raw frames is in pixel coordinates with the
    origin in the corner. Passing one straight in gives a confident, wrong number rather than a
    failure. So the map is conjugated into axis-centred coordinates first, `T H T⁻¹` with `T` the
    shift by `(-cx, -cy)` — and those must be the CAMERA's `cx`/`cy`, not the image centre, which on
    a cropped clip are 638 px apart (`findings/the-principal-point-a-clip-runs-at-2026-08-14.md`).

    `None` where the form is degenerate, which is not rare and is not a bug: the denominators
    vanish for a pure translation and for a pan with no tilt, and a camera that has barely moved
    between two frames is close to both. A caller wanting one number per clip should take the
    median over the pairs that answered, and count the ones that did not.
    """
    t = np.array([[1.0, 0.0, -cx], [0.0, 1.0, -cy], [0.0, 0.0, 1.0]])
    hc = t @ np.asarray(h, dtype=float) @ np.linalg.inv(t)
    p = hc.ravel()

    def solve(d1: float, d2: float, v1: float, v2: float) -> float | None:
        if abs(d1) < 1e-12 and abs(d2) < 1e-12:
            return None
        a = v1 / d1 if abs(d1) > 1e-12 else None
        b = v2 / d2 if abs(d2) > 1e-12 else None
        # Two candidate f², from the two independent constraints. Prefer the one whose denominator
        # is larger, because the other is the one going singular.
        if a is not None and b is not None:
            f2 = a if abs(d1) > abs(d2) else b
            if f2 <= 0:
                f2 = b if f2 is a else a
        else:
            f2 = a if a is not None else b
        return float(np.sqrt(f2)) if f2 is not None and f2 > 0 else None

    f1 = solve(p[6] * p[7], (p[7] - p[6]) * (p[7] + p[6]),
               -(p[0] * p[1] + p[3] * p[4]),
               p[0] * p[0] + p[3] * p[3] - p[1] * p[1] - p[4] * p[4])
    f0 = solve(p[0] * p[3] + p[1] * p[4],
               p[0] * p[0] + p[1] * p[1] - p[3] * p[3] - p[4] * p[4],
               -p[2] * p[5], p[5] * p[5] - p[2] * p[2])
    return f0, f1
