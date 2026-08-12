"""Mowing stripes, measured in metres on the pitch rather than in pixels in the frame.

A mower cuts in straight passes of constant width, so the stripes are parallel and evenly spaced
**in the world**. In the image they are none of those things — perspective makes them converge and
narrow — which is why they fool a line finder and why `line_error` has to work so hard to keep them
out. Rectify the frame through a solved camera and they become what they are: a periodic signal in
metres.

That gives two things, and it is worth being clear which is which.

**A check on the camera, not an input to it.** The period only comes out constant if the camera is
right; a wrong one makes the stripes drift in width across the pitch. But you need a camera to
rectify at all, so this can only ever confirm a solve, never produce one.

**A statement about a detected line.** A "line" lying along a stripe boundary sits at a multiple of
the stripe period from its neighbours. A real marking does not — the pitch's spacings are 5.5, 11,
16.5, 9.15 m and nothing like a constant step.

**Not every pitch has stripes**, and the first job is to say so rather than to find a period in
noise. `stripe_period` returns None unless the autocorrelation shows a peak that stands well clear
of the profile's own roughness.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Metres between samples when rectifying. Finer than any stripe (a mower cuts 1.5–10 m) and coarse
#: enough that a 105 x 68 m pitch is a few hundred thousand samples rather than millions.
SAMPLE_M = 0.25

#: A period is believed only if its autocorrelation peak exceeds this. Below it, what is being
#: measured is the turf's own texture and the honest answer is "no stripes".
MIN_PEAK = 0.30

#: Stripe widths to look for, in metres. Narrower than 1.5 m is a domestic mower, wider than 12 m
#: is not a stripe pattern.
PERIOD_RANGE = (1.5, 12.0)


@dataclass(frozen=True)
class Stripes:
    """What the turf says about how it was cut.

    Attributes:
        period_m: Metres between stripe boundaries, or None when the pitch is not striped.
        peak: Height of the autocorrelation peak, 0–1. The confidence, and the thing that decides
            whether `period_m` is a measurement or a pattern found in noise.
        axis_deg: Direction the stripes run, in world degrees. 0 is along the touchline.
        contrast: Peak-to-peak of the rectified profile, in intensity units, after detrending.
            A striped pitch on television is 8–25; below ~4 there is nothing to see.
        n_samples: Turf samples the profile was built from.
    """

    period_m: float | None
    peak: float
    axis_deg: float
    contrast: float
    n_samples: int


def rectify_turf(bgr: np.ndarray, h_w2i: np.ndarray, *, extent=(52.5, 34.0),
                 step_m: float = SAMPLE_M) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sample the frame on a world grid over the pitch. `(grid_x, grid_y, intensity)`.

    Intensity is the green channel, which separates cut directions better than luminance: a mowing
    stripe is the same grass leaning two ways, so it differs in how it reflects rather than in
    colour, and the green channel carries most of that with the least of everything else.

    Samples outside the frame come back as NaN rather than as an edge pixel, so a camera seeing a
    third of the pitch reports a third of the pitch and not a wall of clamped values.
    """
    gx = np.arange(-extent[0], extent[0] + 1e-9, step_m)
    gy = np.arange(-extent[1], extent[1] + 1e-9, step_m)
    xx, yy = np.meshgrid(gx, gy)
    pts = np.column_stack([xx.ravel(), yy.ravel(), np.ones(xx.size)])
    q = pts @ np.asarray(h_w2i, float).T
    w = np.where(np.abs(q[:, 2]) > 1e-9, q[:, 2], 1e-9)
    uv = q[:, :2] / w[:, None]
    h, wid = bgr.shape[:2]
    ok = ((q[:, 2] > 0) & (uv[:, 0] >= 0) & (uv[:, 0] < wid - 1)
          & (uv[:, 1] >= 0) & (uv[:, 1] < h - 1))
    out = np.full(xx.size, np.nan)
    if ok.any():
        u = np.rint(uv[ok, 0]).astype(int)
        v = np.rint(uv[ok, 1]).astype(int)
        out[ok] = bgr[v, u, 1].astype(float)
    return gx, gy, out.reshape(xx.shape)


def _profile(field: np.ndarray, axis_deg: float, gx: np.ndarray, gy: np.ndarray):
    """Average the rectified turf along the stripe direction, leaving a 1-D profile across them."""
    a = np.radians(axis_deg)
    xx, yy = np.meshgrid(gx, gy)
    t = xx * np.sin(a) - yy * np.cos(a)             # coordinate ACROSS the stripes, metres
    finite = np.isfinite(field)
    if finite.sum() < 500:
        return None, None
    lo, hi = t[finite].min(), t[finite].max()
    if hi - lo < 8.0:
        return None, None
    edges = np.arange(lo, hi + SAMPLE_M, SAMPLE_M)
    idx = np.clip(np.digitize(t[finite], edges) - 1, 0, len(edges) - 2)
    vals = field[finite]
    total = np.bincount(idx, weights=vals, minlength=len(edges) - 1)
    count = np.bincount(idx, minlength=len(edges) - 1)
    prof = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    return edges[:-1] + SAMPLE_M / 2, prof


def stripe_period(t: np.ndarray, prof: np.ndarray, *, period_range=PERIOD_RANGE,
                  min_peak: float = MIN_PEAK) -> tuple[float | None, float, float]:
    """`(period in metres or None, peak height, detrended contrast)` by autocorrelation.

    Detrended first with a wide moving average: a pitch is brighter on the side the floodlights are
    on, and that ramp is a far larger signal than the stripes. Left in, the autocorrelation reports
    the ramp's own width and calls it a stripe.
    """
    good = np.isfinite(prof)
    if good.sum() < 40:
        return None, 0.0, 0.0
    t, prof = t[good], prof[good]
    k = max(3, int(round(period_range[1] * 2 / SAMPLE_M)) | 1)
    pad = np.pad(prof, k // 2, mode="edge")
    trend = np.convolve(pad, np.ones(k) / k, mode="valid")[:len(prof)]
    x = prof - trend
    contrast = float(np.percentile(x, 97) - np.percentile(x, 3))
    x = x - x.mean()
    denom = float(x @ x)
    if denom < 1e-9:
        return None, 0.0, contrast
    lo = int(period_range[0] / SAMPLE_M)
    hi = min(int(period_range[1] / SAMPLE_M), len(x) - 10)
    if hi <= lo:
        return None, 0.0, contrast
    ac = np.array([float(x[:-d] @ x[d:]) / denom for d in range(lo, hi)])
    # A LOCAL maximum, not the largest value in the range. The autocorrelation of any smooth signal
    # decays monotonically from lag zero, so the range maximum sits at the smallest lag allowed
    # whatever the turf looks like — the first version reported exactly 1.50 m, the lower bound,
    # on every frame of both clips. A period is a bump, and a bump has smaller values either side.
    interior = np.arange(1, len(ac) - 1)
    local = interior[(ac[1:-1] > ac[:-2]) & (ac[1:-1] > ac[2:])]
    if not len(local):
        return None, 0.0, contrast
    best = int(local[int(np.argmax(ac[local]))])
    peak = float(ac[best])
    if peak < min_peak:
        return None, peak, contrast
    return float((lo + best) * SAMPLE_M), peak, contrast


def measure(bgr: np.ndarray, h_w2i: np.ndarray, *, axes=None) -> Stripes:
    """Whether this pitch is striped, and if so how wide the stripes are, in metres.

    Tries a few stripe directions and keeps the strongest. Two are worth having: stripes run along
    the pitch or across it, and a groundsman occasionally cuts diagonals.
    """
    gx, gy, field = rectify_turf(bgr, h_w2i)
    n = int(np.isfinite(field).sum())
    best = Stripes(None, 0.0, 0.0, 0.0, n)
    for axis in (axes if axes is not None else (0.0, 45.0, 90.0, 135.0)):
        t, prof = _profile(field, axis, gx, gy)
        if t is None:
            continue
        period, peak, contrast = stripe_period(t, prof)
        if peak > best.peak:
            best = Stripes(period, peak, float(axis), contrast, n)
    return best
