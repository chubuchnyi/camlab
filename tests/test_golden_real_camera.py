"""The copied core still recovers the real camera — ported from pitch3d's one non-fake test.

`calib/Colombia-1-0-Congo-DR1080p.npz` is a camera measured off the real broadcast clip (#119),
7 kB, committed so this runs anywhere. Everything else in this repo can be checked against a
fixture someone wrote; this is checked against a lens that existed.

Its job here is narrower than in pitch3d: it is the **acceptance test for the copy**. camlab took
`core/` by hand and is going to change the camera contract (spec §3.4, per-frame focal). This
pins what must survive that: if these numbers move, either the copy is wrong or the contract
change broke the solve — and either way it is not something to nudge until it passes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from camlab.core.field import FieldCalibration
from camlab.core.plane_camera import REALIZABLE_PX, camera_from_calibration
from camlab.core.projection import camera_center

CALIB = Path(__file__).resolve().parents[1] / "calib" / "Colombia-1-0-Congo-DR1080p.npz"
WIDTH, HEIGHT = 1920, 1080


@pytest.fixture(scope="module")
def fit():
    if not CALIB.exists():
        pytest.skip(f"missing the committed measurement {CALIB}")
    blob = np.load(CALIB)
    w2i = np.asarray(blob["world_to_image"], dtype=float)
    cal = FieldCalibration(
        homographies=np.linalg.inv(w2i),          # FieldCalibration stores image->world
        frames=np.asarray(blob["frames"], dtype=int),
        confidence=np.ones(len(blob["frames"]), dtype=float),
    )
    return camera_from_calibration(cal, width=WIDTH, height=HEIGHT)


def test_the_measurement_is_still_the_clip_we_think_it_is():
    """Guards the fixture: a refit npz makes every number below about a different clip."""
    if not CALIB.exists():
        pytest.skip(f"missing the committed measurement {CALIB}")
    blob = np.load(CALIB)
    assert set(blob.files) == {"focal", "centre", "rvecs", "frames", "world_to_image"}
    assert blob["world_to_image"].shape == (60, 3, 3)
    assert np.array_equal(blob["frames"], np.arange(60))


def test_a_real_pinhole_comes_back_out(fit):
    """The whole point of the refusal: a real camera lands at float noise, not near the line."""
    assert fit.realizable
    assert fit.camera is not None
    assert fit.reprojection_px < REALIZABLE_PX
    assert fit.reprojection_px == pytest.approx(0.0, abs=1e-3)


def test_the_focal_is_recovered_from_the_homographies_alone(fit):
    """4169.32 px, from Zhang's constraint and nothing else — no focal was supplied."""
    assert fit.focal_px == pytest.approx(4169.32, abs=0.5)


def test_it_is_one_camera_not_sixty(fit):
    """Sixty frames, one optical centre. This is the property free homographies cannot have."""
    centres = np.stack([camera_center(fit.camera, i) for i in range(60)])
    assert centres.shape == (60, 3)
    assert float(np.abs(centres - centres[0]).max()) < 1e-6


def test_the_camera_is_where_a_broadcast_camera_would_be(fit):
    """(-2.29, -70.13, 17.22) m: beyond the touchline, above the pitch, near the halfway line."""
    c = camera_center(fit.camera, 0)
    assert c == pytest.approx([-2.292, -70.134, 17.220], abs=0.01)
    assert c[2] > 0, "a camera under the pitch means the world got mirrored (#118)"
