"""Synthetic controls FIRST, this time.

The last instrument built here was trusted before it was checked against an answer known in
advance, and it produced two confident findings in opposite directions, both artefacts of its own
search grid. So: a camera with a known focal, its pitch projected, the segments handed to the
estimator, and the focal it returns compared with the one it was built from — before any of this
touches a real frame.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.core.pitch import pitch_polylines
from camlab.solve.vanishing import (
    focal_from_segments,
    focal_from_vanishing_points,
)

W, H = 1080, 608


def _look_at(centre, target):
    fwd = np.asarray(target, float) - np.asarray(centre, float)
    fwd /= np.linalg.norm(fwd)
    down = np.array([0.0, 0.0, -1.0])
    right = np.cross(down, fwd)
    right /= np.linalg.norm(right)
    return np.vstack([right, np.cross(fwd, right), fwd])


def _project(pts_xy, focal, rot, centre, cx, cy):
    """World points on Z=0 -> image px, and a mask of what is in front of the camera."""
    k = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]])
    xyz = np.column_stack([np.asarray(pts_xy, float), np.zeros(len(pts_xy))])
    cam = (xyz - np.asarray(centre, float)) @ rot.T
    front = cam[:, 2] > 1e-6
    uv = (cam @ k.T)
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = uv[:, :2] / uv[:, 2, None]
    return uv, front


def _pitch_segments(focal, centre, cx, cy, target=(0.0, 0.0, 0.0), min_len=25.0):
    """The straight pitch markings, projected and cut into image segments."""
    rot = _look_at(centre, target)
    segs = []
    for poly in pitch_polylines():
        xy = np.asarray(poly, float)[:, :2]
        if len(xy) < 2:
            continue
        # ONE segment per straight marking, from its endpoints — not one per polyline vertex.
        # pitch_polylines returns dense paths (the first is 211 points), and cutting those into
        # consecutive pairs makes 253 fragments of ~29 px. That is not what a line detector
        # produces, and it breaks the grouping: among hundreds of tiny near-collinear fragments,
        # RANSAC finds a spurious far-away vanishing point that is within tolerance of parts of
        # BOTH families and claims 233 of them. Real detectors emit merged lines; so does this.
        d = xy[-1] - xy[0]
        n = np.linalg.norm(d)
        if n < 1e-9:
            continue
        perp = np.abs(np.cross(np.column_stack([d / n] * len(xy)).T[:, :2], xy - xy[0])) \
            if False else np.abs((xy - xy[0]) @ np.array([-d[1], d[0]]) / n)
        if perp.max() > 0.05:
            continue          # not straight in the WORLD: a circle or an arc, not a family member
        uv, front = _project(xy[[0, -1]], focal, rot, centre, cx, cy)
        if not front.all() or not np.isfinite(uv).all():
            continue
        if np.hypot(*(uv[1] - uv[0])) < min_len:
            continue
        segs.append([uv[0, 0], uv[0, 1], uv[1, 0], uv[1, 1]])
    return np.asarray(segs, dtype=float)


class TestTheIdentity:
    """The closed form, independent of any detection."""

    def test_two_perpendicular_directions_give_back_the_focal(self):
        """Build the vanishing points from a known camera and read the focal off them."""
        focal, cx, cy = 2400.0, 540.0, 304.0
        rot = _look_at((3.0, -70.0, 22.0), (0.0, 0.0, 0.0))
        k = np.array([[focal, 0.0, cx], [0.0, focal, cy], [0.0, 0.0, 1.0]])
        # A vanishing point is where a world DIRECTION projects, i.e. K R d.
        v1 = k @ rot @ np.array([1.0, 0.0, 0.0])
        v2 = k @ rot @ np.array([0.0, 1.0, 0.0])
        got = focal_from_vanishing_points(v1, v2, cx, cy)
        assert got.ok
        assert got.focal_px == pytest.approx(focal, rel=1e-6)

    def test_it_refuses_rather_than_invents_when_no_focal_exists(self):
        """A positive dot product means no focal makes those directions perpendicular."""
        got = focal_from_vanishing_points([1540.0, 304.0], [2540.0, 304.0], 540.0, 304.0)
        assert not got.ok
        assert np.isnan(got.focal_px)
        assert "no real focal" in got.reason

    def test_a_direction_parallel_to_the_image_plane_carries_no_information(self):
        got = focal_from_vanishing_points([1.0, 0.0, 0.0], [900.0, 304.0, 1.0], 540.0, 304.0)
        assert not got.ok
        assert "infinity" in got.reason


class TestEndToEndOnASyntheticPitch:
    """Project a real pitch through a known camera, detect nothing, group, and recover the focal."""

    @pytest.mark.parametrize("focal", [1800.0, 2400.0, 3200.0, 4300.0])
    def test_the_focal_comes_back(self, focal):
        cx, cy = W / 2.0, H / 2.0
        segs = _pitch_segments(focal, (3.0, -70.0, 22.0), cx, cy)
        assert len(segs) >= 6, "the synthetic frame must show enough straight markings to group"
        got = focal_from_segments(segs, cx, cy, tol_deg=0.5)
        assert got.ok, got.reason
        assert got.focal_px == pytest.approx(focal, rel=0.02)

    def test_it_finds_two_families_and_not_one_twice(self):
        cx, cy = W / 2.0, H / 2.0
        segs = _pitch_segments(2400.0, (3.0, -70.0, 22.0), cx, cy)
        got = focal_from_segments(segs, cx, cy, tol_deg=0.5)
        assert got.n1 >= 3 and got.n2 >= 3
        # The two vanishing points must be genuinely different, or one family was found twice.
        assert np.linalg.norm(np.asarray(got.v1) - np.asarray(got.v2)) > 100.0

    def test_a_wrong_principal_point_biases_the_answer(self):
        """Worth knowing the sensitivity: this instrument needs cx, cy and does not measure them.

        camlab has cy wrong by 638 px on any cropped clip unless ClipInfo.principal_point is used,
        so the size of that bias is the difference between a third opinion and a third guess.
        """
        cx, cy = W / 2.0, H / 2.0
        segs = _pitch_segments(2400.0, (3.0, -70.0, 22.0), cx, cy)
        right = focal_from_segments(segs, cx, cy, tol_deg=0.5)
        wrong = focal_from_segments(segs, cx, cy + 638.0, tol_deg=0.5)
        assert right.ok
        assert abs(right.focal_px - 2400.0) < abs(wrong.focal_px - 2400.0) or not wrong.ok, (
            "a 638 px principal-point error must not leave the estimate unchanged — "
            f"right {right.focal_px:.0f}, wrong {wrong.focal_px if wrong.ok else 'refused'}"
        )
