"""Does a camera survive the round trip through a homography and back out?

The M1 viewer draws whatever `per_frame_cameras` returns, straight into a three.js scene. Every
convention on that path — where the principal point is, which way image y runs, whether `position`
is the centre or the translation, which handedness the world has — is a place where a sign error
produces a picture that looks *almost* right. Almost right is the expensive kind: pitch3d carried a
mirrored world for weeks because the pitch is symmetric about Y=0 and no marking metric can see it
(#118).

So this builds a homography from a camera whose answer is known, and checks the same camera comes
back out. If it does, the conventions agree end to end.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.solve.per_frame import (
    DEGENERATE_DET_RATIO,
    focal_from_one_homography,
    per_frame_cameras,
)

WIDTH, HEIGHT = 1080, 608


def _rodrigues(r: np.ndarray) -> np.ndarray:
    theta = float(np.linalg.norm(r))
    if theta < 1e-12:
        return np.eye(3)
    k = r / theta
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * kx + (1 - np.cos(theta)) * (kx @ kx)


def _look_at(centre: np.ndarray, target: np.ndarray) -> np.ndarray:
    """World→camera rotation for a camera at `centre` looking at `target`, OpenCV convention.

    Camera +Z forward, +Y down, +X right. "Down" is resolved against world -Z, i.e. gravity, which
    is what a levelled camera does and what makes the recovered roll zero rather than arbitrary.
    """
    fwd = target - centre
    fwd = fwd / np.linalg.norm(fwd)
    down = np.array([0.0, 0.0, -1.0])
    right = np.cross(down, fwd)
    right = right / np.linalg.norm(right)
    down = np.cross(fwd, right)
    return np.vstack([right, down, fwd])          # rows are the camera axes in world coords


def _plane_homography(focal: float, rot: np.ndarray, centre: np.ndarray) -> np.ndarray:
    """Image→world homography for the pitch plane Z=0, for a camera (focal, rot, centre)."""
    k = np.array([[focal, 0.0, WIDTH / 2.0], [0.0, focal, HEIGHT / 2.0], [0.0, 0.0, 1.0]])
    t = -rot @ centre
    w2i = k @ np.column_stack([rot[:, 0], rot[:, 1], t])   # drop the Z column: the plane is Z=0
    return np.linalg.inv(w2i)


#: A camera roughly where the fan clip's turns out to be — 70 m out, 22 m up, looking at the pitch
#: centre — so the round trip is exercised in the regime it is actually used in, not at a
#: convenient one.
TRUTH_CENTRE = np.array([3.0, -70.0, 22.0])
TRUTH_FOCAL = 3000.0


@pytest.fixture(scope="module")
def truth():
    rot = _look_at(TRUTH_CENTRE, np.array([0.0, 0.0, 0.0]))
    h = _plane_homography(TRUTH_FOCAL, rot, TRUTH_CENTRE)
    return rot, h


def test_the_camera_comes_back_out(truth):
    """Focal, position and rotation all recovered from the homography alone."""
    rot, h = truth
    got = per_frame_cameras(h[None], np.array([0]), WIDTH, HEIGHT)

    assert got.focal_px[0] == pytest.approx(TRUTH_FOCAL, rel=1e-3)
    assert got.position[0] == pytest.approx(TRUTH_CENTRE, abs=0.05)
    assert not got.degenerate[0]
    # The rotation is stored as Rodrigues; compare the matrices, since two Rodrigues vectors can
    # differ by 2*pi about the same axis and still be the same rotation.
    assert _rodrigues(got.rotation[0]) == pytest.approx(rot, abs=1e-3)


def test_position_is_the_centre_not_the_translation(truth):
    """`C = -Rᵀt`, and confusing the two puts the camera under the pitch — the shape of #118."""
    rot, h = truth
    got = per_frame_cameras(h[None], np.array([0]), WIDTH, HEIGHT)
    t = -rot @ TRUTH_CENTRE
    assert got.position[0][2] > 0, "a camera below the pitch means a convention is inverted"
    assert not np.allclose(got.position[0], t, atol=1.0), "that is `t`, not the optical centre"


def test_a_zoom_is_recovered_frame_by_frame(truth):
    """Six frames, focal ramping 1.66x — the fan clip's measured zoom. Nothing is shared."""
    rot, _ = truth
    focals = np.linspace(3000.0, 3000.0 * 1.66, 6)
    hs = np.stack([_plane_homography(f, rot, TRUTH_CENTRE) for f in focals])
    got = per_frame_cameras(hs, np.arange(6), WIDTH, HEIGHT)
    assert got.focal_px == pytest.approx(focals, rel=2e-3)
    # And the position must NOT drift while only the focal changes. If it does, focal and distance
    # are trading off — the exact degeneracy that made this repo's first fit run away to 5 px.
    assert np.abs(got.position - TRUTH_CENTRE).max() < 0.05


def test_a_rank_poor_homography_is_marked_not_dropped(truth):
    """Relative to the clip's own median, because an absolute threshold cannot work.

    pitch3d's absolute `_SINGULAR_DET = 1e-12` misses the real cases by six orders of magnitude:
    fan frames 115 and 117 sit at 1.0e-6 and 5.3e-8 against a clip median of 3.4e-3.
    """
    _rot, h = truth
    collapsed = h.copy()
    collapsed[:, 1] = collapsed[:, 0] * 1e-5          # second column nearly parallel to the first
    hs = np.stack([h, h, collapsed, h])
    got = per_frame_cameras(hs, np.arange(4), WIDTH, HEIGHT)

    assert got.degenerate.tolist() == [False, False, True, False]
    assert len(got) == 4, "marked, and still present — R-6 applies to frames too"
    dets = np.abs(np.linalg.det(hs))
    assert dets[2] < DEGENERATE_DET_RATIO * np.median(dets)


def test_the_focal_search_reports_how_sure_it_is(truth):
    """A shallow minimum must be visible, not implied. The residual is returned alongside."""
    _rot, h = truth
    f, cost = focal_from_one_homography(np.linalg.inv(h), WIDTH, HEIGHT)
    assert f == pytest.approx(TRUTH_FOCAL, rel=1e-3)
    assert cost < 1e-6, "an exact pinhole should sit at the bottom of Zhang's residual"
