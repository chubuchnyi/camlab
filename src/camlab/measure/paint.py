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
RIDGE_SCALES = (2, 4, 7)
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


def _turf(hsv: np.ndarray) -> np.ndarray:
    """Turf pixels, keyed to this frame's own dominant hue."""
    import cv2

    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lit = (s > 80) & (v > 80)
    if not lit.any():
        return np.zeros(h.shape, dtype=bool)
    hist = np.bincount(h[lit].ravel(), minlength=180).astype(np.float32)
    peak = int(np.argmax(cv2.GaussianBlur(hist.reshape(-1, 1), (1, 5), 0)))
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


def _merged_length(ridge, val, surface, t: int) -> float:
    """Total length of markings that survive the merge, at ridge threshold ``t``."""
    from .lines import detect_segments, merge_collinear

    mask = (ridge >= t) & (val >= RIDGE_MIN_V) & (surface > 0)
    if not mask.any():
        return 0.0
    segs = detect_segments(distance_from_mask(mask), surface)
    if not len(segs):
        return 0.0
    merged = merge_collinear(segs)
    if not len(merged):
        return 0.0
    return float(np.hypot(merged[:, 2] - merged[:, 0], merged[:, 3] - merged[:, 1]).sum())


def auto_contrast(bgr: np.ndarray) -> tuple[int, float]:
    """``(threshold, score)`` this frame wants — coarse-to-fine, no constant to set.

    A plain sweep of every candidate was tried and abandoned for cost (22 thresholds over nine
    clips exceeded ten minutes). This pays for the ridge map once and searches ~10 thresholds
    instead of 22, which is where the time actually goes.
    """
    return auto_contrast_from(*ridge_map(bgr))


def auto_contrast_from(ridge, val, surface) -> tuple[int, float]:
    """`auto_contrast` for a ridge map already computed."""
    scored = {t: _merged_length(ridge, val, surface, t) for t in AUTO_COARSE}
    best = max(scored, key=lambda t: scored[t])
    for t in (best - AUTO_FINE_STEP, best + AUTO_FINE_STEP):
        if t > 0 and t not in scored:
            scored[t] = _merged_length(ridge, val, surface, t)
    best = max(scored, key=lambda t: scored[t])
    return best, scored[best]


def ridge_map(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(ridge, value, surface)`` — everything before the threshold, which is the expensive half.

    Split out so a search over thresholds pays for the ridge once instead of once per candidate.
    """
    import cv2

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    turf = _turf(hsv)
    surface = _surface(turf)
    val = hsv[..., 2].astype(np.int16)

    ridge = np.full(val.shape, -1000, np.int16)
    for d in RIDGE_SCALES:
        for dy, dx in ((1, 0), (0, 1), (1, 1), (1, -1)):
            side = np.minimum(
                val - _shift(val, d * dy, d * dx, 255), val - _shift(val, -d * dy, -d * dx, 255)
            ).astype(np.int16)
            both = _shift(turf, d * dy, d * dx, False) & _shift(turf, -d * dy, -d * dx, False)
            side[~both] = -1000
            np.maximum(ridge, side, out=ridge)
    return ridge, val, surface


def distance_from_mask(lines: np.ndarray) -> np.ndarray:
    """Distance to the painted CENTRELINE, from a boolean paint mask."""
    import cv2

    inner = cv2.distanceTransform(lines.astype(np.uint8), cv2.DIST_L2, 5)
    spine = (inner >= cv2.dilate(inner, np.ones((3, 3), np.uint8)) - 1e-3) & (inner > 0)
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
