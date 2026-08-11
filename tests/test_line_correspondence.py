"""A model marking must be judged on the part of it that is actually in the picture.

Overlap used to be required as a fraction of the marking's **projected** length. A marking running
toward the horizon projects to thousands of pixels; a detector can only ever return the few hundred
that are on screen. So the test asked for something impossible and threw the marking away as a
MISS, which then cost `MISS_PX = 60` in the refit objective — 82 % of what looked like a detector
failure was this. See `findings/the-metric-had-a-ceiling.md` and #16.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.measure.line_error import clip_to_image, compare_line


class TestClipToImage:
    def test_a_segment_wholly_inside_is_returned_unchanged(self):
        seg = np.array([[100.0, 100.0], [400.0, 300.0]])
        got = clip_to_image(seg, 1080, 608)
        assert np.allclose(got, seg)

    def test_a_segment_wholly_outside_is_none(self):
        assert clip_to_image(np.array([[-500.0, 100.0], [-200.0, 300.0]]), 1080, 608) is None
        assert clip_to_image(np.array([[100.0, 900.0], [400.0, 1200.0]]), 1080, 608) is None

    def test_a_horizon_bound_marking_keeps_only_its_visible_part(self):
        """The case that broke correspondence: 11,115 px projected, a few hundred on screen."""
        seg = np.array([[540.0, 300.0], [11_000.0, 300.0]])
        got = clip_to_image(seg, 1080, 608)
        assert got is not None
        assert np.isclose(got[0][0], 540.0)
        assert np.isclose(got[1][0], 1079.0), "must stop at the last column, not carry on to 11,000"
        assert np.linalg.norm(got[1] - got[0]) < 600

    def test_the_clipped_part_lies_on_the_original_line(self):
        seg = np.array([[-300.0, -200.0], [1400.0, 900.0]])
        got = clip_to_image(seg, 1080, 608)
        assert got is not None
        u = seg[1] - seg[0]
        nrm = np.array([-u[1], u[0]]) / np.linalg.norm(u)
        assert abs(float((got[0] - seg[0]) @ nrm)) < 1e-9
        assert abs(float((got[1] - seg[0]) @ nrm)) < 1e-9

    @pytest.mark.parametrize("y", [0.0, 607.0])
    def test_a_segment_along_an_edge_survives(self, y):
        got = clip_to_image(np.array([[-50.0, y], [1200.0, y]]), 1080, 608)
        assert got is not None, "a marking lying exactly along the frame edge is still visible"


def test_a_detected_segment_covering_the_visible_part_is_no_longer_rejected():
    """The measured failure, reproduced: an exact match discarded for insufficient overlap.

    A model marking projecting 11,115 px with 540 px of it on screen, and a detected segment
    sitting on that whole visible stretch. Against the projected length the overlap is 4.9 % and
    the marking is a MISS; against the visible length it is 100 % and it is what it obviously is.
    """
    projected = np.array([[540.0, 300.0], [11_000.0, 300.0]])
    detected = np.array([[545.0, 300.2], [1075.0, 300.2]])

    _off, _ang, ov, _p1, _p2 = compare_line(projected, detected)
    assert ov / np.linalg.norm(projected[1] - projected[0]) < 0.25, "the old denominator rejects it"

    visible = clip_to_image(projected, 1080, 608)
    off, ang, ov, _p1, _p2 = compare_line(visible, detected)
    assert ov / np.linalg.norm(visible[1] - visible[0]) > 0.9, "the visible one accepts it"
    assert abs(off) < 1.0, "and it was sitting on its paint the whole time"
    assert abs(ang) < 1.0
