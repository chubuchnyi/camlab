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


def paint_masks(bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(distance to the nearest painted CENTRELINE, playing-surface mask)`` for one BGR frame.

    The distance is to the centreline, not to the nearest painted pixel. Paint near the goal is
    8–10 px wide, so "nearest painted pixel" is satisfied anywhere inside the band: an overlay
    visibly riding the band's edge would score a perfect 0.0 px. That is not a hypothetical — it is
    how a penalty arc once measured flawless while plainly sitting inside its own marking.
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

    lines = ((ridge >= RIDGE_CONTRAST) & (val >= RIDGE_MIN_V) & (surface > 0)).astype(np.uint8)
    inner = cv2.distanceTransform(lines, cv2.DIST_L2, 5)
    spine = (inner >= cv2.dilate(inner, np.ones((3, 3), np.uint8)) - 1e-3) & (inner > 0)
    dist = cv2.distanceTransform((~spine).astype(np.uint8), cv2.DIST_L2, 5)
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
