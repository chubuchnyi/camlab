"""Angles a human can check, and the round trip that makes them editable.

Written before the hand controls are wired, because the panel will display these and a human will
type into them: if the pair does not round-trip exactly, an edit silently becomes a different
camera and the person editing gets blamed for it.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.core.angles import (
    angles_from_rotation,
    matrix_from_rodrigues,
    rodrigues_from_matrix,
    rotation_from_angles,
)


@pytest.mark.parametrize(("yaw", "elev", "roll"), [
    (0.0, 0.0, 0.0),
    (56.1, -16.6, 2.5),          # the fan clip's frame 0, as the panel reads it
    (-120.0, -35.0, 0.0),
    (179.0, -5.0, -12.0),
    (45.0, 20.0, 30.0),
])
def test_angles_round_trip(yaw, elev, roll):
    got = angles_from_rotation(rotation_from_angles(yaw, elev, roll))
    assert got == pytest.approx((yaw, elev, roll), abs=1e-6)


def test_the_result_is_a_real_rotation():
    """Not merely close to one. A client posting a matrix could send something that is not."""
    r = rotation_from_angles(56.1, -16.6, 2.5)
    assert r.T @ r == pytest.approx(np.eye(3), abs=1e-9)
    assert float(np.linalg.det(r)) == pytest.approx(1.0, abs=1e-9)


def test_zero_roll_means_a_level_horizon():
    """The definition, checked rather than assumed: the camera's right axis is horizontal."""
    for yaw in (0.0, 37.0, -125.0):
        for elev in (-30.0, -5.0):
            r = rotation_from_angles(yaw, elev, 0.0)
            assert abs(float(r[0][2])) < 1e-9, "right must have no vertical component"


def test_the_angles_agree_with_the_real_camera_on_disk():
    """Against the shipped solve, so the panel's numbers and the stored ones are one camera."""
    from camlab.camera_file import read_camera
    from camlab.runs import ClipInfo, runs_root
    if not (runs_root() / "fan").exists():
        pytest.skip("needs the ingested `fan` run")
    cam = read_camera(ClipInfo.load("fan").dir / "camera_auto.json")
    for i in (0, 30, 60):
        rot = matrix_from_rodrigues(cam["rotation"][i])
        back = rotation_from_angles(*angles_from_rotation(rot))
        assert back == pytest.approx(rot, abs=1e-6), f"frame {i} does not survive the round trip"


def test_rodrigues_round_trips():
    for rvec in (np.zeros(3), np.array([0.1, -0.2, 0.3]), np.array([2.0, 0.5, -1.0])):
        assert rodrigues_from_matrix(matrix_from_rodrigues(rvec)) == pytest.approx(rvec, abs=1e-9)
