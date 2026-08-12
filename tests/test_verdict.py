"""The two ways this project has reported a camera as better than it was.

Both are real events, not hypotheticals, and each has a test here that fails if the mechanism
comes back.

**Reporting a max over two markings as a verdict.** `g15449383` was called solved on "40 of 40
frames under 20 px" while scoring two markings and 76 samples a frame, against `fan`'s six and
165. The number was correct arithmetic over evidence that could not carry it.

**Charging the detector's gaps to the camera.** `worst spot` is the distance to the nearest paint
in any direction, so where the detected centreline has a hole the nearest pixel is far ALONG the
same line and the distance is large — with the camera exactly right. On `fan`'s far goal line that
is 11.75 px along against 2.20 across.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.measure.residual import (
    MIN_SUPPORTING_MARKINGS,
    Residual,
    _across_on_normal,
)
from camlab.measure.verdict import Verdict


def _residual(markings: int, samples_each: int = 40) -> Residual:
    per_line = {k: (1.0, samples_each, 3.0) for k in range(markings)}
    return Residual(0, 1.0, 2.0, 3.0, 1.0, per_line, markings * samples_each, 900, 0)


def test_a_frame_with_too_few_markings_is_not_a_verdict():
    assert _residual(MIN_SUPPORTING_MARKINGS).supported
    thin = _residual(MIN_SUPPORTING_MARKINGS - 1)
    assert not thin.supported
    assert thin.n_markings == MIN_SUPPORTING_MARKINGS - 1


def test_markings_are_counted_only_when_they_have_samples_behind_them():
    """Eight samples is the floor `frame_residual` uses; a corner clipping the frame is not a
    marking, and counting it would put `n_markings` over the line on evidence that is not there."""
    r = Residual(0, 1.0, 2.0, 3.0, 1.0,
                 {0: (1.0, 40, 3.0), 1: (1.0, 40, 3.0), 2: (1.0, 40, 3.0), 3: (1.0, 3, 3.0)},
                 123, 900, 0)
    assert r.n_markings == 3
    assert not r.supported


def test_the_g15449383_shape_refuses_to_report_a_number():
    """Two markings, every frame under 20 px, and the summary must not read as a result."""
    v = Verdict(worst_line_px=3.24, worst_spot_px=63.8, worst_across_px=2.0,
                markings=2, samples=76, n_frames=40, n_supported=0, under_20=40)
    assert not v.supported
    assert "NO VERDICT" in v.line()
    # The numbers still appear — hiding them would lose the evidence that the clip was scored at
    # all — but never as the leading claim.
    assert not v.line().startswith("across")


def test_a_supported_verdict_counts_under_20_over_supported_frames_only():
    v = Verdict(worst_line_px=1.7, worst_spot_px=15.0, worst_across_px=1.9,
                markings=6, samples=165, n_frames=120, n_supported=120, under_20=120)
    assert v.supported
    assert "120/120 supported frames under 20 px" in v.line()


def test_no_frame_scored_says_so_rather_than_returning_nan():
    assert Verdict(np.nan, np.nan, np.nan, 0, 0, 0, 0, 0).line() == "no frame could be scored at all"


# ---------------------------------------------------------------------------------------------
# Across-the-line, against paint whose true offset is known by construction.
# ---------------------------------------------------------------------------------------------

def _distance_transform_of_a_horizontal_line(height: int, width: int, row: float) -> np.ndarray:
    """`dist[y, x] = |y - row|` — exactly what `paint_masks` returns for one straight marking."""
    yy = np.arange(height, dtype=np.float32)[:, None]
    return np.abs(yy - row) * np.ones((1, width), dtype=np.float32)


# Deliberately not multiples of the 0.5 walk step. On those the walk lands on the answer by luck
# and the sub-pixel correction can be deleted without a test noticing.
@pytest.mark.parametrize("offset", [0.0, 1.3, 2.3, 6.7])
def test_across_recovers_a_known_offset(offset):
    dist = _distance_transform_of_a_horizontal_line(200, 300, row=100.0)
    sub = np.column_stack([np.linspace(20, 280, 60), np.full(60, 100.0 + offset)])
    normal = np.tile(np.array([0.0, 1.0]), (60, 1))
    across, found = _across_on_normal(sub, normal, dist, limit=40.0)
    assert found.all()
    # Tighter than the 0.5 step, so this fails if the walk reports `t` without the correction.
    assert np.allclose(across, offset, atol=0.2), f"{np.median(across)} for a true {offset}"


def test_a_diagonal_marking_is_found_at_all():
    """The bilinear sampling, against the case that motivated it.

    A real `paint_masks` distance transform is zero only on the rasterised centreline pixels, and
    a ray walked in rounded integer steps hops across a 1-px diagonal without ever landing on one.
    Sampling `dist` with rounding and a `< 0.75` hit test found paint across 70 % of `fan`'s
    samples; bilinearly, 97 %. The 27 % would have been booked as holes in the detector.
    """
    import cv2

    mask = np.ones((200, 200), dtype=np.uint8)
    d = np.arange(200)
    mask[d, d] = 0                                    # a 45-degree marking, one pixel wide
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)

    t = np.arange(40, 160, 2.0)
    sub = np.column_stack([t, t])                     # samples sitting ON the line
    normal = np.tile(np.array([-1.0, 1.0]) / np.sqrt(2.0), (len(t), 1))
    across, found = _across_on_normal(sub, normal, dist, limit=40.0)
    assert found.all(), f"{(~found).sum()} of {len(t)} diagonal samples found no paint at all"
    assert np.median(across) < 0.75


def test_a_gap_in_the_paint_is_reported_as_a_gap_and_not_as_camera_error():
    """The finding this whole change exists for.

    A model line sitting exactly on its paint, with a stretch of that paint missing. The
    nearest-neighbour distance over the hole is large — it is measured to where the paint resumes,
    far along the line. Across the line there is nothing, and that must come back as "no paint
    here", never as an offset the camera is responsible for.
    """
    from scipy.spatial import cKDTree

    dist = _distance_transform_of_a_horizontal_line(200, 300, row=100.0)
    dist[:, 120:200] = 40.0                       # the detector lost this stretch entirely
    sub = np.column_stack([np.linspace(20, 280, 60), np.full(60, 100.0)])
    normal = np.tile(np.array([0.0, 1.0]), (60, 1))

    across, found = _across_on_normal(sub, normal, dist, limit=40.0)
    in_gap = (sub[:, 0] >= 120) & (sub[:, 0] < 200)
    assert not found[in_gap].any(), "paint was invented across a stretch that has none"
    assert found[~in_gap].all()
    assert np.allclose(across[~in_gap], 0.0, atol=0.5), "the camera is exactly right here"

    # And the nearest-neighbour distance — the `worst spot` statistic — does charge it.
    spine = np.argwhere(dist == 0)[:, ::-1].astype(float)
    nn, _ = cKDTree(spine).query(sub)
    assert nn[in_gap].max() > 30.0, "if this stops being large the test no longer proves anything"
    assert nn[~in_gap].max() < 1.0
