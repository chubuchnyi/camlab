"""The residual is camlab's ground truth, so it gets tested against real pixels, not a fixture.

Two things are pinned here. That the measurement agrees with what the eye sees in window B — a
frame the overlay visibly fits scores low, a frame it visibly misses scores high, and a frame with
no camera scores nothing at all. And that the comparison REFUSES a verdict when coverage collapses,
because that is the failure mode that produced a confident wrong answer once already.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.camera_file import read_camera
from camlab.measure.residual import Residual, compare, frame_residual, world_to_image
from camlab.runs import ClipInfo, runs_root

pytestmark = pytest.mark.skipif(not (runs_root() / "fan").exists(),
                                reason="needs the ingested `fan` run")


@pytest.fixture(scope="module")
def fan():
    info = ClipInfo.load("fan")
    return info, read_camera(info.dir / "camera_auto.json")


def _score(fan, i):
    info, cam = fan
    return frame_residual(info.frame_path(i), cam["focal_px"][i], cam["rotation"][i],
                          cam["position"][i], frame=i)


def test_a_frame_the_overlay_fits_scores_low(fan):
    """Frame 0 is where the projected goal frame lands on the real goal, by eye."""
    r = _score(fan, 0)
    assert r.n > 200
    assert r.median_px < 12, "the eye says this one fits; the number must agree"


def test_a_frame_the_overlay_misses_scores_high(fan):
    """Frame 60 is where the goal is visibly ~70 px out. Same code, same clip, worse camera."""
    lo, hi = _score(fan, 0), _score(fan, 60)
    assert hi.median_px > lo.median_px * 1.8
    # And the comparison must survive the coverage guard rather than be waved through.
    assert "no verdict" not in compare(lo, hi) or hi.n < 0.6 * lo.n


def test_a_frame_with_no_camera_scores_nothing_rather_than_zero(fan):
    """Degenerate frame 116: focal pinned at the bound, optical axis behind the camera.

    `n == 0` and a NaN median. The trap this guards is the opposite — a camera that projects
    nothing onto the surface has no error to report, and reporting 0.0 px would make the worst
    frame in the clip look like the best.
    """
    r = _score(fan, 116)
    assert r.n == 0
    assert np.isnan(r.median_px)


def test_compare_refuses_when_coverage_collapses():
    """The exact failure that produced a confident wrong verdict in pitch3d's first probe."""
    good = Residual(0, 8.0, 20.0, n=1400, n_projected=1400)
    runaway = Residual(0, 2.0, 5.0, n=30, n_projected=30)   # "better" median, 2% of the samples
    verdict = compare(good, runaway)
    assert "no verdict" in verdict
    assert "out of frame" in verdict
    # And a fair pair still gets a verdict.
    assert "no verdict" not in compare(good, Residual(0, 4.0, 9.0, 1350, 1350))


def test_world_to_image_round_trips_a_known_camera():
    """The projection used for scoring must be the same one the solver decomposed."""
    from camlab.solve.per_frame import per_frame_cameras

    focal, centre = 3000.0, np.array([3.0, -70.0, 22.0])
    fwd = -centre / np.linalg.norm(centre)
    down = np.array([0.0, 0.0, -1.0])
    right = np.cross(down, fwd)
    right /= np.linalg.norm(right)
    rot = np.vstack([right, np.cross(fwd, right), fwd])
    w2i = world_to_image(focal, _rodrigues_inv(rot), centre, 1080, 608)

    got = per_frame_cameras(np.linalg.inv(w2i)[None], np.array([0]), 1080, 608)
    assert got.focal_px[0] == pytest.approx(focal, rel=1e-3)
    assert got.position[0] == pytest.approx(centre, abs=0.05)


def _rodrigues_inv(rot):
    theta = float(np.arccos(np.clip((np.trace(rot) - 1) / 2, -1, 1)))
    if theta < 1e-9:
        return np.zeros(3)
    v = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    return v * (theta / (2 * np.sin(theta)))
