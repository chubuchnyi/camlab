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
        worst_line_px: The **worst marking's own median**. The number to quote. Unbounded: a
            reading of 90 px means 90 px, where this used to saturate silently at `match_px`.
        per_line: `{marking index: (median px, samples, worst sample px)}`. The third entry is
            what a ruler on the overlay finds, because a human points at a line's worst END, not
            at its middle — median 13 px against worst sample 74 px on one measured frame.
        n: Samples scored. Read with any median, never without.
        n_projected: Samples that landed in the image at all.
        n_unmatched: Samples inside the image with **no paint within `match_px`**. Still counted,
            because "this marking has no paint under it at all" and "it is 45 px off" are
            different claims about the camera even when the number is the same. What changed is
            that they are no longer *dropped* — see `frame_residual`.
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

    `match_px` no longer bounds the search — it only decides what gets **counted** as unmatched.
    Bounding it dropped those samples from the distances, so no reported number could exceed 40 px
    and the readout went blank on the frames where the camera was worst. Charging them in full
    understates (the nearest paint is closer than the paint the marking should have hit) but cannot
    flatter, which is the direction a metric is allowed to be wrong in.

    The other trap is unchanged and is handled elsewhere: a marking that has drifted onto a
    NEIGHBOURING line finds paint at ~0 px and scores perfect. Nothing in a distance-to-paint
    measurement can see that; `line_error.line_errors` is what does, by insisting on correspondence.
    """
    import cv2

    bgr = cv2.imread(str(frame_path))
    if bgr is None:
        raise FileNotFoundError(frame_path)
    height, width = bgr.shape[:2]
    # Both of these used to build a Residual with five of its nine fields and raise TypeError. They
    # are the paths nothing exercises until a solve goes bad, so the metric crashed exactly on the
    # cameras worth measuring: `camera_ptz.json` has frames with a non-positive focal, and the
    # server's residual route returned 500 for them rather than "this camera is broken".
    if not (focal > 0):
        return _empty(frame, 0)

    dist, surface = paint_masks(bgr)
    spine = centreline_pixels(dist)
    if not len(spine):
        return _empty(frame, 0)

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

    # NOT bounded at match_px. The bound used to DROP every sample with no paint within it, which
    # made 40 px a ceiling no reported number could exceed — and a human with a ruler on the overlay
    # read a larger distance than `worst line` on every frame he tried, because the errors he was
    # pointing at were the ones being discarded. Worse, a badly wrong camera loses every sample of
    # every marking and the readout went BLANK (`bench_metric_ceiling.py`: frames 40, 70, 80).
    #
    # An unmatched sample's distance to the nearest paint is charged in full. That distance is a
    # LOWER bound on how wrong the marking is — the true error is to the paint it should have hit,
    # which is further — so it can understate but never flatter. `n_unmatched` is still reported,
    # because "this marking has no paint under it" and "it is 45 px off" are different claims.
    d, _nn = tree.query(sub)
    n_unmatched = int((d > match_px).sum())
    own = owner[idx]

    per_line = {}
    for k in np.unique(own):
        dk = d[own == k]
        per_line[int(k)] = (float(np.median(dk)), int(dk.size), float(dk.max()))
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
