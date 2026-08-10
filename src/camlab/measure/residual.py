"""How far a camera's idea of the pitch is from the pitch that is actually painted.

This is the number window B shows to the eye. Having it as a number too is what lets a filter, a
model change or a hand edit be judged instead of admired: M3's live readout, M2's A/B, and task
#8's "did this filter help or just look calmer" all read this.

**Two rules it enforces, both learned by getting them wrong.**

*Score only what the frame can judge.* A marking projected into the crowd is unmeasurable, not
wrong, and letting it count would make an overlay look worse for pointing at something no evidence
covers.

*Never compare medians without comparing counts.* `paint_error` returns distances only for samples
that land on the playing surface, so a camera that has run away projects almost everything
off-surface, where it goes unscored, and posts a **flattering** median on the handful of survivors.
That is not a hypothetical: the first version of this measurement, in pitch3d, reported a confident
"one centre holds" off a fit whose focal had collapsed to 87 px on a 1080 px image. Every result
here therefore carries `n`, and :func:`compare` refuses a verdict when coverage collapses.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from camlab.core.pitch import pitch_polylines
from camlab.measure.paint import centreline_pixels, paint_masks

#: Marking samples per metre of polyline. The model draws centrelines, so this only has to be dense
#: enough that every visible marking contributes; 2/m puts ~1400 samples on a full pitch.
SAMPLES_PER_M = 2.0


@dataclass(frozen=True)
class Residual:
    """One frame's agreement with the paint.

    **Read `worst_line_px` first.** The median was the headline until a human looked at an overlay
    and said the obvious thing: some markings sit on their paint while the ones parallel to them
    are far off. A median over all samples cannot show that — the lines that fit outvote the lines
    that do not — and the failure it hides is the characteristic one, because a projected line that
    drifts onto a NEIGHBOURING parallel line finds paint at almost zero distance and scores as
    perfect. Per marking, that is visible. Pooled, it is not.

    Attributes:
        frame: Frame index.
        median_px: Median over all scored samples. Kept for continuity, no longer the verdict.
        p90_px, max_px: The tail, and the worst single sample.
        worst_line_px: The **worst marking's own median**. The number to quote.
        per_line: `{marking index: (median px, samples)}`, so "which line is wrong" is answerable.
        n: Samples scored. Read with any median, never without.
        n_projected: Samples that landed in the image at all.
        n_unmatched: Samples inside the image with **no paint within `match_px`**. These are not
            "large errors" that a median can absorb — they are markings the frame shows nothing
            for, and they used to be silently assigned the distance to whatever paint happened to
            be nearest, however far and however wrong.
    """

    frame: int
    median_px: float
    p90_px: float
    max_px: float
    worst_line_px: float
    per_line: dict
    n: int
    n_projected: int
    n_unmatched: int

    @property
    def coverage(self) -> float:
        """Scored samples as a fraction of the whole marking set. Low means "do not trust me"."""
        return self.n / max(_marking_samples().shape[0], 1)


_CACHE: dict[str, np.ndarray] = {}


def _marking_samples() -> np.ndarray:
    """Every painted marking, resampled evenly, as world ``(X, Y, 1)``."""
    _build_samples()
    return _CACHE["xy1"]


def _marking_owner() -> np.ndarray:
    """Which marking each sample came from — its index into ``pitch_polylines()``.

    Kept because pooling every sample into one median is what hid the characteristic failure: a
    camera can sit on one family of lines while the family parallel to it is metres off, and the
    lines that fit outvote the lines that do not.
    """
    _build_samples()
    return _CACHE["owner"]


def _build_samples() -> None:
    if "xy1" in _CACHE:
        return
    out, owner = [], []
    for k, poly in enumerate(pitch_polylines()):
        xy = np.asarray(poly, dtype=float)[:, :2]
        if len(xy) < 2:
            continue                       # the spots are points, not lines
        seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        run = np.concatenate([[0.0], np.cumsum(seg)])
        n = max(2, int(run[-1] * SAMPLES_PER_M))
        want = np.linspace(0.0, run[-1], n)
        out.append(np.column_stack([np.interp(want, run, xy[:, i]) for i in (0, 1)]))
        owner.append(np.full(n, k))
    pts = np.concatenate(out)
    _CACHE["xy1"] = np.column_stack([pts, np.ones(len(pts))])
    _CACHE["owner"] = np.concatenate(owner)


def world_to_image(focal: float, rvec: np.ndarray, centre: np.ndarray,
                   width: int, height: int,
                   cx: float | None = None, cy: float | None = None) -> np.ndarray:
    """The ``(3, 3)`` world→image map on the pitch plane Z=0, for one camera.

    Takes the camera as camlab stores it — focal, Rodrigues world→camera rotation, and the optical
    CENTRE — rather than a `K [R|t]`, because those are the numbers a human types into the panel.
    """
    theta = float(np.linalg.norm(rvec))
    if theta < 1e-12:
        rot = np.eye(3)
    else:
        k = np.asarray(rvec, dtype=float) / theta
        kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        rot = np.eye(3) + np.sin(theta) * kx + (1 - np.cos(theta)) * (kx @ kx)
    # The principal point is a PARAMETER, not the image centre. On a cropped clip the optical axis
    # is not at the middle of the frames on disk — this project's fan clip has it 638 px away — and
    # hardcoding width/2, height/2 here meant every paint number in the repo used the wrong K.
    cx = width / 2.0 if cx is None else cx
    cy = height / 2.0 if cy is None else cy
    kmat = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]])
    t = -rot @ np.asarray(centre, dtype=float)
    return kmat @ np.column_stack([rot[:, 0], rot[:, 1], t])


def frame_residual(frame_path: Path, focal: float, rvec, centre, frame: int = 0,
                   match_px: float = 40.0,
                   cx: float | None = None, cy: float | None = None) -> Residual:
    """Score one camera against one decoded frame.

    `frame_path` must be a frame written by `camlab ingest`, i.e. already cropped — the same image
    space the camera was solved in. Scoring against an uncropped frame silently measures a
    different thing and still returns a plausible number.

    `match_px` bounds the search. Unbounded nearest-paint was the original version and it is a trap
    in both directions: a marking with no paint near it borrows the distance to something across
    the frame, and a marking that has drifted onto a neighbouring line finds paint at ~0 and scores
    perfect. The bound turns the first case into `n_unmatched`, which is reported rather than
    averaged; the second is only visible per marking, which is what `worst_line_px` is for.
    """
    import cv2

    bgr = cv2.imread(str(frame_path))
    if bgr is None:
        raise FileNotFoundError(frame_path)
    height, width = bgr.shape[:2]
    if not (focal > 0):
        return Residual(frame, float("nan"), float("nan"), 0, 0)

    dist, surface = paint_masks(bgr)
    spine = centreline_pixels(dist)
    if not len(spine):
        return Residual(frame, float("nan"), float("nan"), 0, 0)

    from scipy.spatial import cKDTree
    tree = cKDTree(spine)

    xy1 = _marking_samples()
    h = world_to_image(focal, rvec, centre, width, height, cx=cx, cy=cy)
    q = xy1 @ h.T
    w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
    uv = q[:, :2] / w[:, None]

    owner = _marking_owner()
    inside = ((uv[:, 0] > 1) & (uv[:, 0] < width - 2)
              & (uv[:, 1] > 1) & (uv[:, 1] < height - 2))
    if not inside.any():
        return _empty(frame, 0)
    idx = np.flatnonzero(inside)
    sub = uv[idx]
    on = surface[np.rint(sub[:, 1]).astype(int), np.rint(sub[:, 0]).astype(int)] > 0
    idx, sub = idx[on], sub[on]
    if not len(idx):
        return _empty(frame, int(inside.sum()))

    d, _nn = tree.query(sub, distance_upper_bound=match_px)
    hit = np.isfinite(d)
    n_unmatched = int((~hit).sum())
    if not hit.any():
        return _empty(frame, int(inside.sum()), n_unmatched)
    d, own = d[hit], owner[idx[hit]]

    per_line = {}
    for k in np.unique(own):
        dk = d[own == k]
        per_line[int(k)] = (float(np.median(dk)), int(dk.size))
    # A marking held up by three samples is not evidence about that marking; requiring a handful
    # stops the worst-line number being decided by a corner clipping the frame.
    solid = [v[0] for v in per_line.values() if v[1] >= 8]
    worst = float(max(solid)) if solid else float("nan")

    return Residual(frame, float(np.median(d)), float(np.percentile(d, 90)), float(d.max()),
                    worst, per_line, int(d.size), int(inside.sum()), n_unmatched)


def _empty(frame: int, n_projected: int, n_unmatched: int = 0) -> Residual:
    nan = float("nan")
    return Residual(frame, nan, nan, nan, nan, {}, 0, n_projected, n_unmatched)


def compare(a: Residual, b: Residual, *, coverage_floor: float = 0.6) -> str:
    """Which of two cameras fits the paint better — or a refusal to say.

    A verdict is withheld when the challenger scores on far fewer samples than the incumbent. Those
    markings did not get better; they left the frame.
    """
    if not (a.n and b.n):
        return "no verdict: one side scored nothing"
    if b.n < coverage_floor * a.n:
        return (f"no verdict: B scored {b.n} samples against A's {a.n} "
                f"({b.n / a.n:.0%}) — it moved markings out of frame, it did not improve them")
    if a.n < coverage_floor * b.n:
        return (f"no verdict: A scored {a.n} samples against B's {b.n} "
                f"({a.n / b.n:.0%}) — not a fair comparison")
    delta = b.median_px - a.median_px
    verb = "better" if delta < 0 else "worse"
    return (f"B is {abs(delta):.2f} px {verb} "
            f"({a.median_px:.2f} -> {b.median_px:.2f}, n {a.n}/{b.n})")
