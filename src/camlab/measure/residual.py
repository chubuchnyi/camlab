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

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from camlab.core.pitch import pitch_polylines
from camlab.measure.paint import centreline_pixels, paint_masks

#: Below this many scored markings, a frame's error is a max over too few things to be a verdict.
#: Four is `refit.MIN_MATCHED`, the same floor the solver already refuses to fit under. Measured
#: support on the clips here: broadcast 7, fan 6, and the clip that fooled this project 2.
MIN_SUPPORTING_MARKINGS = 4

#: How close the walk along a marking's normal must come to the detected centreline before it
#: counts as having crossed it. Not a fudge factor and not a tolerance the answer inherits — the
#: reported offset is the position of the minimum, so this only decides crossed-or-not.
#:
#: It has to sit above 1.0, and the reason is a defect one layer down. `paint.distance_from_mask`
#: extracts the centreline as the local maxima of a distance transform, and on a diagonal band that
#: comes out DISCONNECTED — the skeleton pixels sit two apart, so a ray crossing between them gets
#: no closer than 1.00 and a `< 1.0` test rejects a genuine crossing. That was measured as 11 % of
#: `fan`'s samples "having no paint", which was this constant and not the detector.
CROSSING_TOL = 1.5

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
        worst_across_px: Max over markings of that marking's **median across-line** error — the
            same shape as `worst_line_px`, but measured across the marking instead of to the
            nearest paint in any direction. This is the calibration error; `max_px` and
            `per_line[k][2]` are not. A line cannot be displaced along itself, so the along-line
            part of a nearest-neighbour distance is not an error at all — it is the detected paint
            running out. On `fan`'s far goal line the worst spot splits 11.75 px along against
            2.20 across, and along beats across on 63 % of all worst spots.
        per_line_across: `{marking index: (median across px, worst across px)}`. Two warnings on
            the second entry. A marking with no paint opposite it is ABSENT from this dict while
            still present in `per_line`, so the two do not share keys and code that zips them is
            wrong. And the max is contaminated: the normal is walked out to `match_px`, so where
            a marking's own paint is missing the walk reaches a NEIGHBOURING one and reports the
            distance to that. The median is what to read; the max is an upper bound at best.
        n_no_paint_across: Samples with paint somewhere near but **none across their own
            marking**. This is the detector's gap count, and it is what `worst spot` was silently
            charging to the camera.
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
    #: Defaulted so the two `_empty` paths and any older caller still construct. NaN reads as
    #: "not measured", which is what an unscoreable frame should say.
    worst_across_px: float = float("nan")
    per_line_across: dict = field(default_factory=dict)
    n_no_paint_across: int = 0

    @property
    def n_markings(self) -> int:
        """Markings with enough samples to be scored at all.

        The number to read before either error. `worst_line_px` is a max over markings, so on a
        frame holding two of them it is a max over two and means almost nothing — the third clip
        ingested here scores 3.24 px on 2 markings and 76 samples, against `fan`'s 6 and 165, and
        was briefly called solved on the strength of it. Fewer than `MIN_SUPPORTING_MARKINGS` and
        the error is not a verdict.
        """
        return sum(1 for v in self.per_line.values() if v[1] >= 8)

    @property
    def supported(self) -> bool:
        """Whether this frame's error means anything. See `n_markings`."""
        return self.n_markings >= MIN_SUPPORTING_MARKINGS

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


#: How many frames' paint to keep. Every scoring loop in this repo hammers ONE frame with many
#: cameras — a bootstrap anchor takes ~7000, the polish pass 6–8, the refit one per iteration — so
#: a cache of a handful covers all of them. A whole-clip sweep touches each frame once and gains
#: nothing from a bigger one, it would only hold memory: each entry is a float32 distance map and a
#: bool surface mask at full resolution, about 12 MB on 1920×1080.
EVIDENCE_CACHE = 4

_EVIDENCE: OrderedDict = OrderedDict()


def frame_evidence_cached(frame_path: Path):
    """`(dist, surface, spine, tree, width, height)` for one frame, computed once.

    **This is 98 % of a score.** Profiled on `broadcast` at 1920×1080, interleaved so background
    load cancels: a whole `frame_residual` is 463 ms and decode + `paint_masks` is 456 ms of it —
    the camera-dependent remainder is **7 ms**. And none of that 456 ms depends on the camera at
    all, so scoring one frame against N cameras recomputed the same pixels N times.

    Keyed on the file's path, size and modification time, so re-ingesting a clip invalidates it
    rather than serving the previous decode's paint under the new frame's name.
    """
    import cv2
    from scipy.spatial import cKDTree

    st = frame_path.stat()
    key = (str(frame_path), st.st_size, st.st_mtime_ns)
    hit = _EVIDENCE.get(key)
    if hit is not None:
        _EVIDENCE.move_to_end(key)
        return hit

    bgr = cv2.imread(str(frame_path))
    if bgr is None:
        raise FileNotFoundError(frame_path)
    height, width = bgr.shape[:2]
    dist, surface = paint_masks(bgr)
    spine = centreline_pixels(dist)
    got = (dist, surface, spine, cKDTree(spine) if len(spine) else None, width, height)
    _EVIDENCE[key] = got
    while len(_EVIDENCE) > EVIDENCE_CACHE:
        _EVIDENCE.popitem(last=False)
    return got


def clear_evidence_cache() -> None:
    """Drop it. For tests, and for a caller that has finished with a clip and wants the memory."""
    _EVIDENCE.clear()


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
    dist, surface, spine, tree, width, height = frame_evidence_cached(Path(frame_path))
    # Both of these used to build a Residual with five of its nine fields and raise TypeError. They
    # are the paths nothing exercises until a solve goes bad, so the metric crashed exactly on the
    # cameras worth measuring: `camera_ptz.json` has frames with a non-positive focal, and the
    # server's residual route returned 500 for them rather than "this camera is broken".
    if not (focal > 0):
        return _empty(frame, 0)
    if tree is None:
        return _empty(frame, 0)

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
    d, nn = tree.query(sub)
    n_unmatched = int((d > match_px).sum())
    own = owner[idx]

    # ACROSS the marking, not to the nearest paint in any direction. A line has no observable
    # displacement along itself, so the along-line part of `d` is not a camera error — it is the
    # detected paint running out (a player on the line, a worn stretch, a thin far line the
    # centreline extractor drops). Measured on `fan`: the far goal line's worst spot is 12.41 px,
    # of which 11.75 is along and 2.20 across, and along beats across on 63 % of all worst spots.
    # Quoting `d` there reports the detector's gaps as the camera's error.
    tangent = _sample_tangents(uv, owner)[idx]
    length = np.hypot(tangent[:, 0], tangent[:, 1])
    has_dir = length > 1e-9
    normal = (np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
              / np.where(has_dir, length, 1.0)[:, None])
    # Searched ALONG THE NORMAL rather than decomposed from the nearest neighbour. Decomposing
    # still charges a sample that has no paint opposite it at all: the nearest pixel is then far
    # along the line and its across component is whatever that pixel's sideways offset happens to
    # be. Walking the normal gives the third answer the decomposition cannot — **no paint here** —
    # which is a defect in the detector, not in the camera, and has to be counted as its own thing.
    across, on_normal = _across_on_normal(sub, normal, dist, match_px)
    # A sample with no direction cannot be measured this way, so the whole of its distance is
    # charged. `_build_samples` drops the one-point markings (the penalty and centre spots), so
    # today this only fires where two consecutive samples project to the same pixel. Kept because
    # the charge has to fall on the flattering side if that ever stops being true.
    across = np.where(has_dir, across, d)
    on_normal = on_normal & has_dir
    n_no_paint_across = int((~on_normal).sum())

    per_line, per_line_across = {}, {}
    for k in np.unique(own):
        m = own == k
        dk = d[m]
        per_line[int(k)] = (float(np.median(dk)), int(dk.size), float(dk.max()))
        # Only the samples that HAVE paint opposite them. A marking whose paint is missing is
        # unmeasured here and shows up in `n_no_paint_across` instead; averaging a made-up number
        # in would be the same mistake as the old `match_px` ceiling, in the other direction.
        ak = across[m & on_normal]
        if ak.size:
            per_line_across[int(k)] = (float(np.median(ak)), float(ak.max()))
    # A marking held up by three samples is not evidence about that marking; requiring a handful
    # stops the worst-line number being decided by a corner clipping the frame.
    solid = [v[0] for v in per_line.values() if v[1] >= 8]
    worst = float(max(solid)) if solid else float("nan")
    solid_across = [per_line_across[k][0] for k, v in per_line.items()
                    if v[1] >= 8 and k in per_line_across]
    worst_across = float(max(solid_across)) if solid_across else float("nan")

    return Residual(frame, float(np.median(d)), float(np.percentile(d, 90)), float(d.max()),
                    worst, per_line, int(d.size), int(inside.sum()), n_unmatched,
                    worst_across, per_line_across, n_no_paint_across)


def _across_on_normal(sub: np.ndarray, normal: np.ndarray, dist: np.ndarray,
                      limit: float, step: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    """How far ACROSS its own marking each sample is from the paint, and whether any was there.

    Walks each direction separately and takes the **first minimum** of `dist` that comes within
    `CROSSING_TOL` — the point where the ray crossed the painted centreline. The offset reported is
    where that minimum sits, so it inherits nothing from the tolerance and is accurate to half a
    step. Returns `(offset, found)`; `offset` is `inf` where `found` is False, and callers must
    drop those rather than charge them.

    Three things here were each, in turn, the whole measurement, and each was found by the number
    coming out wrong rather than by reading the code.

    *Bilinear, not rounded.* The detected centreline is one pixel wide, so a ray walked in rounded
    integer steps hops over it whenever the normal is near diagonal: rounding and testing
    `dist < 0.75` found paint across 70 % of `fan`'s samples against 97 % here.

    *First minimum, not first value under a threshold.* Reporting the offset at which `dist` first
    dropped below a tolerance quantises every good sample to 0.00 and reads "exactly on the paint"
    for anything inside it.

    *First minimum, not the smallest one.* Over a 40 px search a marking whose own paint is missing
    would otherwise snap onto the neighbouring marking and report that distance as its own.
    """
    h, w = dist.shape

    def sample(p: np.ndarray) -> np.ndarray:
        x = np.clip(p[:, 0], 0.0, w - 1.001)
        y = np.clip(p[:, 1], 0.0, h - 1.001)
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = x - x0, y - y0
        top = dist[y0, x0] * (1 - fx) + dist[y0, x0 + 1] * fx
        bot = dist[y0 + 1, x0] * (1 - fx) + dist[y0 + 1, x0 + 1] * fx
        return top * (1 - fy) + bot * fy

    def one_way(direction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = len(sub)
        low = np.full(n, np.inf)          # smallest `dist` seen so far
        at = np.full(n, np.inf)           # the offset it was seen at
        done = np.zeros(n, dtype=bool)
        for t in np.arange(0.0, limit + step, step):
            here = sample(sub + t * direction)
            nearer = ~done & (here < low)
            low[nearer], at[nearer] = here[nearer], t
            # Past the crossing: it came within tolerance and is now moving away again. Stopping
            # at the FIRST such minimum rather than the smallest over the whole ray is what keeps
            # a marking whose own paint is missing from snapping onto the next marking along.
            done |= ~done & (low <= CROSSING_TOL) & (here > low + 1e-6)
            if done.all():
                break
        # `at` is how far the walk went; `low` is what was still left when it turned around. Their
        # sum is the offset in both cases and that is why it is not two branches: where the ray
        # crossed the centreline `low` is ~0 and the answer is where the crossing was, and where it
        # was already walking away the minimum is at `at = 0` and the answer is the whole of `low`.
        # Reporting `at` alone gives 0.00 px for every sample within `CROSSING_TOL` of its paint,
        # in the direction that points away from it.
        return at + low, low <= CROSSING_TOL

    plus, ok_plus = one_way(normal)
    minus, ok_minus = one_way(-normal)
    best = np.where(ok_plus & (~ok_minus | (plus <= minus)), plus, minus)
    found = ok_plus | ok_minus
    return np.where(found, best, np.inf), found


def _sample_tangents(uv: np.ndarray, owner: np.ndarray) -> np.ndarray:
    """Each projected sample's direction along its **own** marking, in image pixels.

    A forward difference where the next sample shares the marking, a backward one at the far end,
    and zero for a marking of one point. Taken in the image rather than on the pitch because the
    decomposition it feeds is an image-space one, and perspective turns a straight world direction
    into a different image direction at every sample.
    """
    nxt, prv = np.roll(uv, -1, axis=0), np.roll(uv, 1, axis=0)
    use_next = np.append(owner[:-1] == owner[1:], False)
    use_prev = np.insert(owner[1:] == owner[:-1], 0, False)
    t = np.zeros_like(uv)
    t[use_next] = (nxt - uv)[use_next]
    only_prev = use_prev & ~use_next
    t[only_prev] = (uv - prv)[only_prev]
    return t


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
