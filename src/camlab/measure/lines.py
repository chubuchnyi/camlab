"""Long straight segments out of the painted lines.

The vanishing-point focal needs **merged** lines, not fragments. Its synthetic controls showed
exactly how badly: given 253 pieces of ~29 px instead of 17 whole markings, RANSAC finds a spurious
far vanishing point that is within tolerance of parts of *both* families and claims 233 of them.
The estimator is fine; it was being fed rubble.

So this does two things, and the second is the one that matters:

1. Hough over the paint centreline, which returns many short co-linear pieces of each marking.
2. **Merge them.** Pieces that lie on the same image line and overlap or nearly touch become one
   segment spanning their full extent.

What it does not do is decide which pitch line a segment is. That is the correspondence problem,
and it is the hard half of auto-aim; vanishing points deliberately do not need it — only that
segments of one family are parallel to each other.
"""

from __future__ import annotations

import numpy as np

#: Hough parameters, over the centreline mask rather than an edge map. The centreline is already
#: one pixel wide, so a low vote threshold is right — the evidence is thin by construction.
HOUGH_THRESHOLD = 30
HOUGH_MIN_LENGTH = 25
HOUGH_MAX_GAP = 12

#: Two segments belong to the same marking if their directions agree to this and they sit on the
#: same line to within `MERGE_OFFSET_PX`. Angle first, because a small angular error over a long
#: line is a large offset at its far end, and the reverse is not true.
MERGE_ANGLE_DEG = 1.5
MERGE_OFFSET_PX = 6.0

#: After merging, anything shorter than this is dropped. A short segment's direction is noisy, and
#: direction is the *only* thing the vanishing point reads.
MIN_MERGED_PX = 60.0


def detect_segments(dist: np.ndarray, surface: np.ndarray | None = None) -> np.ndarray:
    """`(N, 4)` segments `[x1, y1, x2, y2]` from a paint distance map.

    `dist` is `measure.paint.paint_masks`'s first return: zero on the painted centreline. `surface`
    restricts to the playing area, which keeps advertising boards and the stand's own straight
    edges out — they are excellent straight lines and they belong to no pitch family.
    """
    import cv2

    mask = (dist == 0).astype(np.uint8)
    if surface is not None:
        mask = (mask & (surface > 0)).astype(np.uint8)
    if not mask.any():
        return np.zeros((0, 4), dtype=float)

    raw = cv2.HoughLinesP(mask, rho=1, theta=np.pi / 360.0, threshold=HOUGH_THRESHOLD,
                          minLineLength=HOUGH_MIN_LENGTH, maxLineGap=HOUGH_MAX_GAP)
    if raw is None:
        return np.zeros((0, 4), dtype=float)
    return merge_collinear(raw.reshape(-1, 4).astype(float))


def _line_params(seg: np.ndarray) -> tuple[float, float]:
    """`(angle in [0, pi), signed offset)` of the infinite line through a segment."""
    dx, dy = seg[2] - seg[0], seg[3] - seg[1]
    ang = np.arctan2(dy, dx) % np.pi
    n = np.array([-np.sin(ang), np.cos(ang)])          # unit normal
    return float(ang), float(n @ seg[:2])


def merge_collinear(segments: np.ndarray, angle_deg: float = MERGE_ANGLE_DEG,
                    offset_px: float = MERGE_OFFSET_PX,
                    min_len: float = MIN_MERGED_PX) -> np.ndarray:
    """Fuse co-linear pieces into whole markings, spanning their full extent.

    Union-find over "same infinite line", then each group is replaced by the two points furthest
    apart along its own direction. Deliberately not a re-fit: the extremes are what a family test
    cares about, and averaging the pieces' directions would let a short noisy fragment pull a long
    clean marking off its own axis.
    """
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    n = len(segments)
    if n == 0:
        return segments

    params = np.array([_line_params(s) for s in segments])
    tol_a = np.radians(angle_deg)

    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            da = abs(params[i, 0] - params[j, 0])
            da = min(da, np.pi - da)                    # angles wrap at pi, not 2pi
            if da > tol_a:
                continue
            if abs(params[i, 1] - params[j, 1]) > offset_px:
                continue
            parent[find(i)] = find(j)

    out = []
    for root in set(find(i) for i in range(n)):
        members = [i for i in range(n) if find(i) == root]
        pts = np.vstack([segments[members][:, :2], segments[members][:, 2:]])
        # Longest member's direction, not the mean: a long clean marking should not be steered by
        # a short noisy piece that happened to land on it.
        lengths = np.hypot(segments[members][:, 2] - segments[members][:, 0],
                           segments[members][:, 3] - segments[members][:, 1])
        s = segments[members][int(np.argmax(lengths))]
        d = np.array([s[2] - s[0], s[3] - s[1]])
        d = d / (np.linalg.norm(d) + 1e-12)
        t = pts @ d
        a, b = pts[int(np.argmin(t))], pts[int(np.argmax(t))]
        if np.hypot(*(b - a)) >= min_len:
            out.append([a[0], a[1], b[0], b[1]])
    return np.asarray(out, dtype=float).reshape(-1, 4)
