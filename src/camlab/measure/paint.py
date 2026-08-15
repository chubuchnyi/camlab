"""Find the painted lines in a frame — camlab's only source of truth.

Everything else in this repo is a claim: the homographies, the thresholds, the focal bounds, the
whole notion that one camera explains the clip. This module is what those claims are checked
*against*, because it reads the video and nothing else.

Ported from pitch3d's `poseannot/pitch_evidence.py` at 78f94b7 and trimmed to the mask pipeline —
camlab decodes its frames to disk up front, so none of the caching or the video plumbing came
across. The constants below are pitch3d's, measured on broadcast footage, and they are on
camlab's unverified list until a phone clip has been checked against them
(`docs/inherited-claims.md`).

**Why paint and not keypoints.** A keypoint detector's output is another model's opinion. A painted
line is in the pixels. When window B shows a drawn line sitting next to a real one, the distance
between them is this number, and no amount of internal consistency elsewhere can argue with it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


#: Paint is a bright ridge with turf on BOTH sides, and that is what separates it from everything
#: else white in a stadium: an advertising board is flat inside and has board, not turf, beside its
#: edge; a player's shorts have shirt or skin beside them. The scales bracket the painted width
#: from the far touchline (~2 px) to the goal area (~14 px).
#:
#: **That bracket is a broadcast camera's, and a phone at the touchline breaks it.** Measured on
#: `g11710897` frame 39, where the near touchline is **34-54 px** wide against a largest scale of 7:
#:
#:     (2, 4, 7)            7 segments, **0** of them on that line
#:     (2, 4, 7, 14, 28)   10 segments, **5** on it
#:
#: The solve then aligns to what it can see, which on that frame is the advertising hoarding: all
#: seven segments sit in the 43-50 % band at the top of the playing surface, and the widest, most
#: obvious line in the picture contributes nothing.
#:
#: This branch recorded the opposite two days earlier -- "the ridge scales do not need widening,
#: refuted" -- measured on frames 0 and 1, where the same line is far away and narrow. Both
#: readings are right about their own frame, which is the point: the usable scale depends on how
#: far the paint is, and on a pitch-level clip that varies enormously WITHIN one frame.
#:
#: Overridable while that is settled: auto (this default) -> `CAMLAB_RIDGE_SCALES` -> per call.
def _ridge_scales() -> tuple[int, ...]:
    import os

    raw = os.environ.get("CAMLAB_RIDGE_SCALES")
    if not raw:
        return (2, 4, 7)
    try:
        got = tuple(int(x) for x in raw.replace(",", " ").split() if x)
    except ValueError:
        return (2, 4, 7)
    return got or (2, 4, 7)


RIDGE_SCALES = _ridge_scales()

#: A scale in `ridge_map` is the offset at which "is there turf on both sides" is asked, so a scale
#: `s` answers for a line about `2s` wide. The shipped `(2, 4, 7)` therefore brackets paint up to
#: ~14 px, which is a broadcast lens, and two clips are measured past it.
#:
#: **Measured, and it is a narrow separation.** The painted width can be read from a frame with no
#: camera and no scale — threshold each pixel against its own neighbourhood, keep what is inside
#: the playing surface and is not turf, and the distance transform of that gives half the width at
#: every point. Across five frames a clip, the 90th percentile:
#:
#:     g11710897        10.0     wide scales HELP  (markings 4 -> 6)
#:     MOR_POR_181952    8.8     wide scales help
#:     demo_14604680     7.2     wide scales WRECK it (1.42 -> 15.51 px)
#:     14604731          6.0     wide scales hurt   (14.00 -> 24.67)
#:
#: The ordering is right and the margin is 7.2 against 8.8, on two clips a side. That is not enough
#: to set a constant by, which is why this returns a LADDER derived from the number rather than a
#: yes/no on a threshold, and why it is checked by re-solving every clip rather than by argument.
def scales_for_width(p99_px: float, *, ratio: float = 1.8, cap: int = 24) -> tuple[int, ...]:
    """The ridge scales that bracket paint whose 99th-percentile width is `p99_px`.

    Always starts at the shipped `(2, 4, 7)` — the far paint is narrow on every clip measured, and
    dropping the small scales to chase the wide ones is how a clip loses its distant markings.
    Extends geometrically only as far as the frame's own paint goes, so a clip whose widest line is
    14 px never gets a scale of 28 looking for something that is not there.
    """
    out = [2, 4, 7]
    want = max(2.0, p99_px / 2.0)
    while out[-1] < want and out[-1] < cap:
        nxt = int(round(out[-1] * ratio))
        if nxt <= out[-1] or nxt > cap:
            break
        out.append(nxt)
    return tuple(out)
RIDGE_CONTRAST = 16
RIDGE_MIN_V = 95

#: `RIDGE_CONTRAST` is an ABSOLUTE brightness step, and it was set on two floodlit clips. Measured
#: over nine (`docs/findings/daylight-and-automatic-thresholds.md`), the value that would equalise
#: coverage ranges 20..117 — a factor of six — so no single number serves them. The alternative is
#: to ask the question locally: "is this pixel brighter than the turf immediately around it", which
#: is what the ridge test means and what `adaptiveThreshold` computes. `ADAPTIVE_C` is how far above
#: the local mean a pixel must sit; OpenCV SUBTRACTS its `C`, so it is passed negated.
ADAPTIVE_BLOCK = 51
ADAPTIVE_C = 4

#: Turf is one narrow hue per clip, so it is measured from the frame rather than hardcoded: a fixed
#: 25..95 band also admits a stand full of yellow shirts, which then pass the "turf on both sides"
#: test and paint the crowd with phantom markings.
HUE_HALFWIDTH = 7

#: …but the peak may only be looked for among hues grass can actually be. OpenCV's hue runs 0..180,
#: green sits around 35..85, and **the search used to be unbounded**. On `g11710897` — a phone at
#: the touchline at dusk — the biggest bright saturated region in the frame is the SKY, so the peak
#: came out at **108**, which is blue. The consequences, all on one frame:
#:
#:     turf mask     top quarter 100 %, bottom half 2 %
#:     playing surface   the sky, and 2 % of the actual grass
#:
#: and so no marking could be scored, the paint detector found "markings" in the tree canopy, and
#: the metric reported one marking on a frame with a plainly visible line in it.
#:
#: This does NOT go back to a fixed band — the hue is still measured from the frame, and the width
#: around it is still `HUE_HALFWIDTH`. It only refuses to call something grass that no grass is.
GRASS_HUE_RANGE = (25, 95)


def _turf(hsv: np.ndarray) -> np.ndarray:
    """Turf pixels, keyed to this frame's own dominant hue **among the hues grass can be**."""
    import cv2

    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lit = (s > 80) & (v > 80)
    if not lit.any():
        return np.zeros(h.shape, dtype=bool)
    hist = np.bincount(h[lit].ravel(), minlength=180).astype(np.float32)
    smooth = cv2.GaussianBlur(hist.reshape(-1, 1), (1, 5), 0).ravel()
    lo, hi = GRASS_HUE_RANGE
    band = smooth[lo:hi + 1]
    if not band.any():
        # No green anywhere. Returning the unbounded peak would hand back the sky; returning
        # nothing says "there is no pitch in this picture", which is the honest answer and lets
        # every caller's own emptiness guard fire.
        return np.zeros(h.shape, dtype=bool)
    peak = lo + int(np.argmax(band))
    return (np.abs(h.astype(np.int16) - peak) <= HUE_HALFWIDTH) & (s > 70) & (v > 70)


def _surface(turf: np.ndarray) -> np.ndarray:
    """The playing surface as a filled region — paint and players are on it, the crowd is not.

    A region rather than a colour test, because a point landing exactly ON a painted line is not
    turf-coloured and must still count as having evidence.
    """
    import cv2

    filled = cv2.morphologyEx(turf.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((45, 45), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(filled, 8)
    if count < 2:
        return filled
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return cv2.morphologyEx(
        (labels == biggest).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((61, 61), np.uint8)
    )


def _shift(a: np.ndarray, dy: int, dx: int, fill) -> np.ndarray:
    out = np.full_like(a, fill)
    rows, cols = a.shape
    out[max(0, -dy):rows + min(0, -dy), max(0, -dx):cols + min(0, -dx)] = a[
        max(0, dy):rows + min(0, dy), max(0, dx):cols + min(0, dx)
    ]
    return out


def _ridge_over_threshold(
    ridge: np.ndarray, *, adaptive: bool, block: int = ADAPTIVE_BLOCK, c: int = ADAPTIVE_C
) -> np.ndarray:
    """Which ridge pixels count as paint — by a fixed step, or against the local turf."""
    import cv2

    if not adaptive:
        return ridge >= RIDGE_CONTRAST
    # The ridge fill is -1000 where the "turf on both sides" test failed; clip it to 0 so the
    # local mean is not dragged down by pixels that were never candidates.
    u8 = np.clip(ridge, 0, 255).astype(np.uint8)
    hit = cv2.adaptiveThreshold(
        u8, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, -c
    )
    # A local maximum in a flat neighbourhood still clears "above the local mean", so keep the
    # requirement that there is a real ridge at all.
    return (hit > 0) & (ridge > 0)


#: The self-tuning search. `RIDGE_CONTRAST` and `ADAPTIVE_C` are both constants someone chose; this
#: chooses nothing and asks the frame instead. The objective is total length of merged markings —
#: what every stage downstream actually consumes — and NOT their count, because the runaway daylight
#: clip returns 1300+ "lines" of turf texture and no marking among them.
#: The range brackets the 20..117 the nine clips were measured to need.
AUTO_COARSE = (12, 24, 36, 48, 60, 75, 90, 110)
AUTO_FINE_STEP = 6

#: Painted pixels per megapixel, above which the paint stage has already failed and nothing
#: downstream is worth running. Measured over nine clips: the ones that work sit at 3300-9300,
#: the ones that have given up at 48000-52000 (findings §4). Resolution-free, so it compares a
#: 4K overhead with a phone. This is a CEILING on the search, not a target.
PAINT_CEILING_PX_PER_MPX = 10000.0


def _merged_length(ridge, val, surface, t: int) -> tuple[float, float]:
    """``(total merged length, painted px per megapixel)`` at ridge threshold ``t``.

    Both, because the length ALONE is gameable and was measured to be: lowering the threshold
    merges turf texture into long spurious lines, so a search that only maximises length runs
    to the bottom of its range and reports 389 "markings" on a pitch that has 17. The second
    number is what says the paint stage has given up.
    """
    from .lines import detect_segments, merge_collinear

    mask = (ridge >= t) & (val >= RIDGE_MIN_V) & (surface > 0)
    if not mask.any():
        return 0.0, 0.0
    dist = distance_from_mask(mask)
    px_per_mpx = float((dist == 0).sum()) / (ridge.size / 1e6)
    segs = detect_segments(dist, surface)
    if not len(segs):
        return 0.0, px_per_mpx
    merged = merge_collinear(segs)
    if not len(merged):
        return 0.0, px_per_mpx
    total = float(np.hypot(merged[:, 2] - merged[:, 0], merged[:, 3] - merged[:, 1]).sum())
    return total, px_per_mpx


def auto_contrast(bgr: np.ndarray) -> tuple[int, float]:
    """``(threshold, score)`` this frame wants — coarse-to-fine, no constant to set.

    A plain sweep of every candidate was tried and abandoned for cost (22 thresholds over nine
    clips exceeded ten minutes). This pays for the ridge map once and searches ~10 thresholds
    instead of 22, which is where the time actually goes.
    """
    return auto_contrast_from(*ridge_map(bgr))


def auto_contrast_from(ridge, val, surface) -> tuple[int, float]:
    """`auto_contrast` for a ridge map already computed.

    Maximise merged length **subject to** the paint stage not having given up. Without the
    constraint the search pins at the bottom of its range on 4 of 10 sample clips.
    """
    scored: dict[int, tuple[float, float]] = {}

    def evaluate(t: int) -> None:
        if t > 0 and t not in scored:
            scored[t] = _merged_length(ridge, val, surface, t)

    def pick() -> int:
        ok = [t for t, (_, px) in scored.items() if px <= PAINT_CEILING_PX_PER_MPX]
        # Nothing admissible means the surface stage failed, not the threshold. Take the
        # strictest candidate and let the caller's pre-flight check refuse the clip.
        return max(ok, key=lambda t: scored[t][0]) if ok else max(scored)

    for t in AUTO_COARSE:
        evaluate(t)
    best = pick()
    evaluate(best - AUTO_FINE_STEP)
    evaluate(best + AUTO_FINE_STEP)
    best = pick()
    return best, scored[best][0]


@dataclass(frozen=True)
class ClipContrast:
    """The paint threshold a clip wants, and how well its own frames agree on it."""

    contrast: int
    """The value to use — the median over the sampled frames."""
    spread: tuple[int, int]
    """Lowest and highest a single frame chose. A wide spread is the flat objective, not zoom."""
    per_frame: tuple[int, ...]
    settled: bool
    """False when the frames disagree so much that the median is not a clip property."""


#: How far the per-frame choices may range before the median stops meaning anything. Measured over
#: four clips at five frames each: the tightest was 6..18 and the loosest 6..48, so this refuses
#: nothing today — it exists to be reported, and to fire on a clip that is worse than any seen.
SETTLED_RATIO = 8.0


def auto_contrast_for_clip(frames, *, min_frames: int = 3) -> ClipContrast:
    """The threshold for a CLIP, from an iterable of its BGR frames.

    **Not per frame.** Measured on four clips, five frames each: the winning threshold moves
    6..48 on the tripod broadcast clip, whose lighting does not change at all. The objective is
    flat enough that one frame does not determine it, and a per-frame threshold would make the
    paint stage jitter underneath a per-frame camera solve. The median over several frames is a
    clip property; a single frame's pick is not.
    """
    picks = [auto_contrast(f)[0] for f in frames]
    if len(picks) < min_frames:
        raise ValueError(f"need at least {min_frames} frames to call a threshold a clip property, "
                         f"got {len(picks)}")
    lo, hi = min(picks), max(picks)
    return ClipContrast(
        contrast=int(np.median(picks)),
        spread=(lo, hi),
        per_frame=tuple(picks),
        settled=hi <= lo * SETTLED_RATIO,
    )


def ridge_map(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(ridge, value, surface)`` — everything before the threshold, which is the expensive half.

    Split out so a search over thresholds pays for the ridge once instead of once per candidate.

    The arithmetic is unchanged and the output is bit-for-bit what the shift-based version returned;
    what changed is that it stopped allocating. Twelve scale-and-direction combinations each built
    four fresh full-frame arrays — 24 allocations of 2 Mpx a call — where padding once and taking
    **views** into the padded copy costs nothing and the temporaries can be reused. Measured:
    132.5 ms to 64.1 on `broadcast`, 112.1 to 64.7 on `CRO_MOR_194948`, 111.5 to 67.2 on
    `g14604660`.

    Two other formulations were measured and are not here, so nobody spends the afternoon:

    *OpenCV morphology.* `min(v - v₊, v - v₋)` is `v - max(v₊, v₋)`, and a max over two points is a
    dilation by a two-point structuring element; "turf on both sides" is an erosion by the same one.
    Exactly equivalent, and it comes out the same 1.1–2.2× — because `cv2.dilate` with a 15×15
    kernel holding two set points still walks all 225.

    *Sparse, over the pixels that could be paint.* The trick that made `thin` 17× faster loses here
    by **3×**: `val >= RIDGE_MIN_V` covers 62–98 % of the frame, so there is almost nothing to skip,
    and fancy indexing gives up the contiguity that makes the dense version fast.

    And the ceiling is about 2×, not the 10× a single `MORPH_TOPHAT` suggests — a top-hat asks
    "brighter than the neighbourhood" in one pass and this asks a directional question twelve times
    with a turf condition on each. Getting more means changing what is asked, which changes the
    evidence.
    """
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    turf = _turf(hsv)
    surface = _surface(turf)
    val = hsv[..., 2].astype(np.int16)

    pad = max(RIDGE_SCALES)
    height, width = val.shape
    # 255 outside the frame, so a pixel whose neighbour is off-picture reads as hugely darker than
    # it and never wins the max — the same thing `_shift`'s fill did.
    vpad = np.full((height + 2 * pad, width + 2 * pad), 255, np.int16)
    vpad[pad:pad + height, pad:pad + width] = val
    tpad = np.zeros((height + 2 * pad, width + 2 * pad), bool)
    tpad[pad:pad + height, pad:pad + width] = turf

    ridge = np.full(val.shape, -1000, np.int16)
    hi = np.empty(val.shape, np.int16)
    side = np.empty(val.shape, np.int16)
    both = np.empty(val.shape, bool)
    for d in RIDGE_SCALES:
        for dy, dx in ((1, 0), (0, 1), (1, 1), (1, -1)):
            def win(a, sy, sx, d=d, dy=dy, dx=dx):
                return a[pad + sy * d * dy:pad + sy * d * dy + height,
                         pad + sx * d * dx:pad + sx * d * dx + width]

            np.maximum(win(vpad, 1, 1), win(vpad, -1, -1), out=hi)
            np.subtract(val, hi, out=side)
            np.logical_and(win(tpad, 1, 1), win(tpad, -1, -1), out=both)
            side[~both] = -1000
            np.maximum(ridge, side, out=ridge)
    return ridge, val, surface


#: How many thinning passes before giving up. A painted band is 2-14 px wide here and each pass
#: peels one pixel from each side, so anything real converges in single figures; the cap exists so
#: a pathological mask cannot spin.
THIN_MAX_PASSES = 32


def thin(mask: np.ndarray, max_passes: int = THIN_MAX_PASSES) -> np.ndarray:
    """Zhang-Suen thinning: the paint mask reduced to a **connected** one-pixel centreline.

    This replaced a local-maximum test on the distance transform — `inner >= dilate(inner)` — which
    is not a thinning algorithm and does not preserve connectivity. Measured on `fan` frame 0: the
    mask has 854 connected components and that test returned **1823**, so it was cutting connected
    bands into pieces, and its longest run was 184 px against a 3408 px band. Zhang-Suen returns
    846 — the mask's own count, because preserving connectivity is what it is for — and a longest
    run of 979 px. On frame 40 the longest run goes 68 px to 734.

    What that buys, measured end to end:

    | clip | lines/frame | total line px | worst line | across | gaps |
    |---|---|---|---|---|---|
    | `fan` | 9 -> 9 | 3640 -> 3667 | 1.72 -> **1.69** | 1.98 -> **1.84** | 4% -> **2%** |
    | `broadcast` | 7 -> 7 | 3162 -> 3234 | 2.42 -> **2.38** | 2.89 -> **2.60** | 1% -> 1% |
    | `g11710897` | **2 -> 5** | **332 -> 715** | | | |
    | `g14604660` | 6 -> 7 | 2924 -> 3070 | | | |
    | `g15449383` | 1 -> 1 | 952 -> 915 | 2.72 -> 3.47 | 3.82 -> 4.50 | 22% -> 22% |

    `g11710897` is the one that matters: it is unsolved, and at two lines a frame it is below
    `refit.MIN_MATCHED` and cannot be fitted at all. Five can.

    `g15449383` gets worse and is reported rather than buried. It scores **two markings**, so by
    this repo's own `MIN_SUPPORTING_MARKINGS` its errors are a max over two and are not a verdict —
    they are not allowed to decide this either way.

    Costs about 20-50 ms a frame, which is 1.5x the residual on a 1920x1080 clip.
    """
    b = np.pad((np.asarray(mask) > 0).astype(np.uint8), 1)
    if not b.any():
        return b[1:-1, 1:-1].astype(bool)
    height, width = b.shape
    flat = b.ravel()

    # P2..P9 as flat-index offsets, in Zhang-Suen's clockwise order from north. The ORDER is the
    # algorithm: `crossings` counts 0->1 transitions around the ring, and a different order counts
    # something else and deletes pixels that hold a curve together.
    off = np.array([-width, -width + 1, 1, width + 1,
                    width, width - 1, -1, -width - 1], dtype=np.int64)

    # Only the SET pixels, carried as a working set that only ever shrinks — thinning never turns a
    # pixel back on. The frame is 2 Mpx and the paint is about 20 000 of them, so the whole-image
    # formulation did a hundred times the arithmetic: 106.9 ms against 6.1 on `broadcast`, 94.8
    # against 5.3 on `g14604660`, **17x**, bit-for-bit the same answer. Rescanning with
    # `flatnonzero` each pass instead of carrying the set gives back most of it — that costs 33 ms
    # of the 6.
    idx = np.flatnonzero(flat)
    for _ in range(max_passes):
        changed = False
        for step in (0, 1):
            if not idx.size:
                break
            nb = [flat[idx + o] for o in off]
            count = nb[0].astype(np.int16)
            for k in range(1, 8):
                count += nb[k]
            ring = nb + [nb[0]]
            crossings = np.zeros(idx.size, np.int16)
            for i in range(8):
                crossings += (ring[i] == 0) & (ring[i + 1] == 1)
            if step == 0:
                ok = (nb[0] * nb[2] * nb[4] == 0) & (nb[2] * nb[4] * nb[6] == 0)
            else:
                ok = (nb[0] * nb[2] * nb[6] == 0) & (nb[0] * nb[4] * nb[6] == 0)
            kill = (count >= 2) & (count <= 6) & (crossings == 1) & ok
            if kill.any():
                flat[idx[kill]] = 0
                idx = idx[~kill]
                changed = True
        if not changed:
            break
    return b[1:-1, 1:-1].astype(bool)


def distance_from_mask(lines: np.ndarray, *, method: str = "thin") -> np.ndarray:
    """Distance to the painted CENTRELINE, from a boolean paint mask.

    `method="localmax"` is the local-maximum test this shipped with until 2026-08-12. It is kept
    because every camera in `runs/` was fitted under it and a camera is only valid under the
    evidence it was fitted to — so reproducing an old number needs the old centreline. It is not
    the default and should not be: see `thin`.
    """
    import cv2

    if method == "localmax":
        inner = cv2.distanceTransform(lines.astype(np.uint8), cv2.DIST_L2, 5)
        spine = (inner >= cv2.dilate(inner, np.ones((3, 3), np.uint8)) - 1e-3) & (inner > 0)
    elif method == "thin":
        spine = thin(lines)
    else:
        raise ValueError(f"centreline method {method!r} is not one of 'thin', 'localmax'")
    return cv2.distanceTransform((~spine).astype(np.uint8), cv2.DIST_L2, 5)


def paint_masks(
    bgr: np.ndarray, *, contrast: int | str | None = None, adaptive: bool = False,
    block: int = ADAPTIVE_BLOCK, c: int = ADAPTIVE_C
) -> tuple[np.ndarray, np.ndarray]:
    """``(distance to the nearest painted CENTRELINE, playing-surface mask)`` for one BGR frame.

    The distance is to the centreline, not to the nearest painted pixel. Paint near the goal is
    8–10 px wide, so "nearest painted pixel" is satisfied anywhere inside the band: an overlay
    visibly riding the band's edge would score a perfect 0.0 px. That is not a hypothetical — it is
    how a penalty arc once measured flawless while plainly sitting inside its own marking.

    Three ways to decide which ridge pixels are paint, in order of how much a human sets:

    ``contrast=None, adaptive=False``  the shipped fixed `RIDGE_CONTRAST` step.
    ``adaptive=True``                  a local step, `c` above the neighbourhood mean.
    ``contrast="auto"``                the threshold this frame's own markings want. Nothing set.

    Default is the fixed step: every camera in `runs/` was solved under it, and a camera is only
    valid under the evidence it was fitted to.
    """
    ridge, val, surface = ridge_map(bgr)

    if contrast == "auto":
        contrast = auto_contrast_from(ridge, val, surface)[0]
    if contrast is not None:
        over = ridge >= int(contrast)
    else:
        over = _ridge_over_threshold(ridge, adaptive=adaptive, block=block, c=c)

    dist = distance_from_mask(over & (val >= RIDGE_MIN_V) & (surface > 0))
    return dist, surface


def centreline_pixels(dist: np.ndarray) -> np.ndarray:
    """The painted centreline as ``(N, 2)`` ``(u, v)`` image coordinates."""
    return np.argwhere(dist == 0)[:, ::-1].astype(float)


@dataclass(frozen=True)
class FrameEvidence:
    """One frame's paint, prepared for repeated queries.

    Building this is the expensive part of any fit — ~0.4 s a frame — and it does not depend on the
    camera, so it is built once and reused across every ICP round and every model variant. That is
    what makes an A/B between two camera models cheap enough to actually run.
    """

    frame: int
    tree: object          # scipy.spatial.cKDTree over `spine`
    spine: np.ndarray     # (N, 2) painted centreline pixels, (u, v)
    surface: np.ndarray   # (H, W) playing-surface mask
    width: int
    height: int


def frame_evidence(frame_path, frame: int = 0) -> FrameEvidence | None:
    """Paint evidence for one decoded frame, or None if the frame shows no paint at all."""
    import cv2
    from scipy.spatial import cKDTree

    bgr = cv2.imread(str(frame_path))
    if bgr is None:
        raise FileNotFoundError(frame_path)
    dist, surface = paint_masks(bgr)
    spine = centreline_pixels(dist)
    if not len(spine):
        return None
    h, w = bgr.shape[:2]
    return FrameEvidence(frame, cKDTree(spine), spine, surface, w, h)


def painted_width_px(bgr: np.ndarray) -> float | None:
    """The 99th percentile of the painted line width in this frame, or `None` if no pitch is in it.

    **No camera and no ridge scale enter this**, which is what makes it usable to CHOOSE the ridge
    scales: threshold every pixel against its own neighbourhood, keep what lies inside the playing
    surface and is not turf, and the distance transform of what is left gives half the local width
    at every point.

    The 99th and not the median or the 90th: on a camera near the pitch the wide lines are the near
    ones and they are a small share of the painted pixels, so they live in the tail. Measured, the
    90th tops out at 10 px on every clip here — under what the shipped scales already cover —
    including the two whose near paint is 34-54 px.
    """
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    turf = _turf(hsv)
    surface = _surface(turf)
    if not surface.any():
        return None
    hit = cv2.adaptiveThreshold(hsv[..., 2], 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                cv2.THRESH_BINARY, ADAPTIVE_BLOCK, -ADAPTIVE_C)
    cand = ((hit > 0) & (surface > 0) & (~turf)).astype(np.uint8)
    if int(cand.sum()) < 200:
        return None
    return float(np.percentile(2.0 * cv2.distanceTransform(cand, cv2.DIST_L2, 5)[cand > 0], 99))


def scales_for_clip(frames, sample: int = 5) -> tuple[int, ...]:
    """The ridge scales this clip's own paint asks for. `frames` is an iterable of image paths."""
    import cv2

    got = []
    paths = list(frames)
    step = max(1, len(paths) // sample)
    for path in paths[::step][:sample]:
        bgr = cv2.imread(str(path))
        if bgr is None:
            continue
        w = painted_width_px(bgr)
        if w is not None:
            got.append(w)
    return scales_for_width(float(np.median(got))) if got else _ridge_scales()
