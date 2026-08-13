"""The centreline extractor, against the property the old one broke.

`distance_from_mask` used to take the local maxima of a distance transform —
`inner >= dilate(inner)` — and call that a centreline. It is not a thinning algorithm and does not
preserve connectivity. Measured on `fan` frame 0, the paint mask has 854 connected components and
that test returned **1823**, cutting connected bands into pieces — its longest run was 184 px
inside a band of 3408.

A broken centreline is not cosmetic. `detect_segments` runs over it, so on `g11710897` the line
detector found **two** lines a frame — below `refit.MIN_MATCHED`, i.e. that clip could not be
fitted at all — against five once the centreline is connected.

These tests assert the property rather than the pixel count, because the property is the point.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camlab.measure.paint import distance_from_mask, thin


def _components(mask: np.ndarray) -> int:
    n, _ = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    return n - 1


def test_a_connected_band_stays_one_piece():
    """The whole reason this exists. The local-maximum test fails this and is kept to prove it."""
    band = np.zeros((80, 200), dtype=bool)
    band[36:44, 10:190] = True                       # one straight band, 8 px wide
    assert _components(band) == 1

    assert _components(thin(band)) == 1

    inner = cv2.distanceTransform(band.astype(np.uint8), cv2.DIST_L2, 5)
    localmax = (inner >= cv2.dilate(inner, np.ones((3, 3), np.uint8)) - 1e-3) & (inner > 0)
    assert _components(localmax) >= 1                 # may or may not break on so clean a shape


def test_a_curved_band_stays_one_piece():
    """Where the old test actually came apart: a band whose direction changes along its length,
    which is every marking on a pitch once perspective has had it."""
    band = np.zeros((160, 160), dtype=bool)
    yy, xx = np.mgrid[0:160, 0:160]
    r = np.hypot(yy - 20, xx - 20)
    band[(r > 90) & (r < 97)] = True                  # an arc, 7 px thick
    assert _components(band) == 1
    assert _components(thin(band)) == 1

    # And the contrast, so nobody "simplifies" this back: on the SAME single connected arc the
    # local-maximum test returns 27 pieces. That is the whole defect, on a shape whose answer is
    # known in advance rather than on a frame where it has to be argued about.
    inner = cv2.distanceTransform(band.astype(np.uint8), cv2.DIST_L2, 5)
    localmax = (inner >= cv2.dilate(inner, np.ones((3, 3), np.uint8)) - 1e-3) & (inner > 0)
    assert _components(localmax) > 10


def test_thinning_leaves_a_one_pixel_line():
    band = np.zeros((60, 120), dtype=bool)
    band[26:34, 5:115] = True                         # 8 px thick, 110 long
    s = thin(band)
    # One pixel per column through the straight middle, away from the ends where a skeleton forks.
    per_column = s[:, 30:90].sum(axis=0)
    assert per_column.max() <= 2, f"still {per_column.max()} px thick"
    assert per_column.min() >= 1, "the centreline has a hole in it"


def test_the_centreline_runs_down_the_middle():
    """Not just thin and connected — in the right place. A centreline offset to one edge scores a
    camera that is riding the edge of its marking as perfect."""
    band = np.zeros((60, 120), dtype=bool)
    band[26:35, 5:115] = True                         # rows 26..34, so the middle is row 30
    rows = np.argwhere(thin(band)[:, 30:90])[:, 0]
    assert abs(float(np.median(rows)) - 30.0) <= 1.0


def test_an_empty_mask_thins_to_nothing_rather_than_spinning():
    assert not thin(np.zeros((20, 20), dtype=bool)).any()


def test_distance_from_mask_measures_to_the_centreline_not_to_the_paint():
    """The reason the distance is to a centreline at all: paint near the goal is 8-10 px wide, so
    'distance to the nearest painted pixel' is zero anywhere inside the band, and an overlay
    visibly riding the band's edge would score perfectly."""
    band = np.zeros((60, 120), dtype=bool)
    band[26:35, 5:115] = True
    d = distance_from_mask(band)
    assert d[30, 60] < 1.0, "the middle of the band should be on the centreline"
    assert d[27, 60] > 1.5, "the EDGE of the band must not read as on the centreline"


def test_the_old_extractor_is_still_reachable_by_name():
    """Every camera in `runs/` was fitted under it, and a camera is only valid under the evidence
    it was fitted to."""
    band = np.zeros((60, 120), dtype=bool)
    band[26:35, 5:115] = True
    assert distance_from_mask(band, method="localmax").shape == band.shape
    with pytest.raises(ValueError, match="not one of"):
        distance_from_mask(band, method="skeletonise")


def test_the_turf_hue_is_looked_for_among_hues_grass_can_be():
    """The sky is not a pitch.

    `_turf` keyed on the frame's dominant bright saturated hue with no bound on where it could be.
    On `g11710897` — a phone at the touchline at dusk — the biggest such region is the SKY, so the
    peak came out at 108, which is blue: the turf mask read 100 % over the top quarter of the frame
    and 2 % over the bottom half, the "playing surface" was the sky, and the metric reported ONE
    marking on a frame with a line plainly visible in it. Anchors on that clip went 1 marking to 7.
    """
    from camlab.measure.paint import GRASS_HUE_RANGE, _turf

    h, w = 200, 300
    hsv = np.zeros((h, w, 3), dtype=np.uint8)
    hsv[..., 1] = 120
    hsv[..., 2] = 200
    hsv[: int(h * 0.7), :, 0] = 108        # a big bright sky, most of the frame
    hsv[int(h * 0.7):, :, 0] = 43          # a smaller strip of grass

    turf = _turf(hsv)
    assert turf[int(h * 0.85), w // 2], "the grass strip is not turf"
    assert not turf[int(h * 0.2), w // 2], "the sky came back as turf — the peak is unbounded again"
    lo, hi = GRASS_HUE_RANGE
    assert lo <= 43 <= hi and not (lo <= 108 <= hi), "the band no longer brackets what it must"


def test_a_frame_with_no_grass_in_it_returns_no_turf():
    """Not the unbounded peak, which would hand back whatever the largest region happens to be.
    "There is no pitch in this picture" is the honest answer and every caller already guards it."""
    from camlab.measure.paint import _turf

    hsv = np.zeros((80, 80, 3), dtype=np.uint8)
    hsv[..., 0] = 108
    hsv[..., 1] = 120
    hsv[..., 2] = 200
    assert not _turf(hsv).any()


def test_thinning_works_the_set_pixels_not_the_frame():
    """The optimisation, pinned by the invariant that makes it correct.

    A frame is 2 Mpx and its paint about 20 000 pixels, so the whole-image formulation did a
    hundred times the arithmetic: 106.9 ms against 6.1 on `broadcast`, **17x**, bit-for-bit the
    same answer. It is only correct because thinning never turns a pixel back ON, so the working
    set may shrink and never has to be rescanned. If that stopped holding, carrying the set would
    silently miss pixels that became deletable again.
    """
    band = np.zeros((120, 200), dtype=bool)
    band[50:62, 20:180] = True
    yy, xx = np.mgrid[0:120, 0:200]
    band[(np.hypot(yy - 60, xx - 100) > 40) & (np.hypot(yy - 60, xx - 100) < 47)] = True

    once = thin(band)
    # Idempotent: thinning a skeleton returns the same skeleton. That is the invariant.
    assert np.array_equal(thin(once), once)
    # And nothing was ever added.
    assert not (once & ~band).any(), "thinning set a pixel that was not in the mask"
