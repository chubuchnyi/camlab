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
#:
#: Raised from 60 to 100 on measurement. LENGTH turned out to be the discriminator that
#: STRAIGHTNESS was expected to be and is not (#17): real markings on the fan clip run a median of
#: 216 px while everything else the finder returns runs 86 px. Refitting all 120 frames at each cut:
#:
#:      cut    segments/frame   refit median   frames under 20 px
#:        0         16.4           2.19 px          81/120
#:      100         10.2           2.18 px          90/120     <-
#:      120          9.3           2.22 px          89/120
#:      150          8.2           2.57 px          87/120
#:      200          6.5          14.0  px          collapses; the solve runs out of evidence
#:
#: Nine more frames, and the median does not move — so what is being removed was carrying none of
#: the fit. Past ~150 the cut starts taking real markings with it.
MIN_MERGED_PX = 100.0

#: Applied to LSD's RAW fragments, before merging, and it must stay small. LSD cuts a marking into
#: many short pieces, so a cut here removes the pieces the merge is supposed to reassemble — set to
#: 60 px it left frames 41, 43, 50, 66 and 73 of the fan clip with ZERO lines, having thrown away
#: every fragment of every real marking. The length that matters is the MERGED one, and
#: `MIN_MERGED_PX` is where it belongs. This only kills single-pixel noise.
LSD_MIN_LENGTH = 12.0

#: A merged segment must lie on painted centreline over at least this fraction of its length, or it
#: is not a marking. Hough is happy to draw a line along a player's leg, the goal net or a shadow
#: edge — all straight, all on the playing surface, none of them paint — and the metric then
#: measures the camera against a footballer. Measured on the fan clip: real markings score 73-100 %,
#: the false ones 32 / 41 / 48 %. Nothing observed sits near this line.
MIN_ON_PAINT = 0.65


def detect_segments(dist: np.ndarray, surface: np.ndarray | None = None,
                    method: str = "hough") -> np.ndarray:
    """`(N, 4)` segments `[x1, y1, x2, y2]` from a paint distance map.

    `dist` is `measure.paint.paint_masks`'s first return: zero on the painted centreline. `surface`
    restricts to the playing area, which keeps advertising boards and the stand's own straight
    edges out — they are excellent straight lines and they belong to no pitch family.

    `"hough"` is the probabilistic Hough transform; `"lsd"` is OpenCV 5's line segment detector.
    **Hough is the default, measured over 40 frames of the fan clip on the same paint mask** — the
    decisive number being paint coverage, the share of painted centreline pixels lying under some
    detected segment, which needs no camera and so cannot be won by luck:

    ===================  ======  =========  =========
    ..                   Hough   LSD thin   LSD band
    lines/frame median      16          8          8
    paint covered        46.6 %     26.7 %     24.4 %
    worst frame          37.0 %     12.6 %     10.1 %
    on-paint median       0.96       0.94       0.90
    ms/frame                49         60         59
    ===================  ======  =========  =========

    I briefly made LSD the default on the grounds that it returned fewer segments and was therefore
    "cleaner", without checking whether what went missing was real. It was: half the paint coverage.

    **This choice cannot fix a marking that is not paint.** The mowing-stripe boundary a human
    caught the metric measuring against is already in `dist` — it is a bright narrow ridge with
    turf on both sides, which is what `paint_masks` looks for — so it arrives here as evidence and
    no line finder can tell it apart. See `findings/local-appearance-cannot-find-markings.md`.
    """
    import cv2

    mask = (dist == 0).astype(np.uint8)
    if surface is not None:
        mask = (mask & (surface > 0)).astype(np.uint8)
    if not mask.any():
        return np.zeros((0, 4), dtype=float)

    if method == "lsd":
        raw = cv2.createLineSegmentDetector().detect(mask * 255)[0]
        if raw is None:
            return np.zeros((0, 4), dtype=float)
        raw = raw.reshape(-1, 4).astype(float)
        keep = np.hypot(raw[:, 2] - raw[:, 0], raw[:, 3] - raw[:, 1]) >= LSD_MIN_LENGTH
        raw = raw[keep]
    else:
        found = cv2.HoughLinesP(mask, rho=1, theta=np.pi / 360.0, threshold=HOUGH_THRESHOLD,
                                minLineLength=HOUGH_MIN_LENGTH, maxLineGap=HOUGH_MAX_GAP)
        if found is None:
            return np.zeros((0, 4), dtype=float)
        raw = found.reshape(-1, 4).astype(float)
    if not len(raw):
        return np.zeros((0, 4), dtype=float)
    merged = merge_collinear(raw)
    return merged[[on_paint_fraction(s, dist) >= MIN_ON_PAINT for s in merged]] \
        if len(merged) else merged


def on_paint_fraction(seg: np.ndarray, dist: np.ndarray, tol_px: float = 2.0) -> float:
    """What fraction of a segment's length actually sits on painted centreline.

    Hough only asks whether enough pixels are collinear; it does not ask whether they are paint.
    A player's leg against grass, the goal net, the edge of a shadow — all straight, all on the
    playing surface. Without this the metric ends up measuring the camera against a footballer,
    which is exactly what a human saw it doing.
    """
    n = max(20, int(np.hypot(seg[2] - seg[0], seg[3] - seg[1]) / 3))
    t = np.linspace(0.0, 1.0, n)
    u = np.rint(seg[0] + t * (seg[2] - seg[0])).astype(int)
    v = np.rint(seg[1] + t * (seg[3] - seg[1])).astype(int)
    ok = (u >= 0) & (u < dist.shape[1]) & (v >= 0) & (v < dist.shape[0])
    if not ok.any():
        return 0.0
    return float((dist[v[ok], u[ok]] <= tol_px).mean())


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
