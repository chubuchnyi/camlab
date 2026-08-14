"""The focal from one image-to-image map: exact in theory, and refuted on this footage.

`focals_from_homography` is the closed form from Shum and Szeliski. It is worth having tested
rather than deleted, because the reason it does not help here is a property of the *clips*, not of
the maths, and that reason will change on other footage.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from camlab.measure.pixel_motion import focals_from_homography

CX, CY = 540.0, 304.0


def _rotation_homography(focal: float, deg: float) -> np.ndarray:
    k = np.array([[focal, 0.0, CX], [0.0, focal, CY], [0.0, 0.0, 1.0]])
    # A pan AND a tilt. The form is degenerate for a pure pan, which is not a defect: with one
    # rotation axis the two constraints it solves collapse into one.
    r = cv2.Rodrigues(np.deg2rad([deg * 0.6, deg, 0.0]))[0]
    return k @ r @ np.linalg.inv(k)


@pytest.mark.parametrize("focal", [800.0, 2896.0, 4500.0])
@pytest.mark.parametrize("deg", [0.5, 3.0, 12.0])
def test_it_is_exact_on_a_true_rotation(focal, deg):
    """No tolerance, because there is no error to tolerate: this is algebra on an exact input, and
    a version that is merely close is a version with a sign or an index wrong."""
    f0, f1 = focals_from_homography(_rotation_homography(focal, deg), CX, CY)
    assert f0 is not None and f1 is not None
    assert abs(f0 - focal) < 1e-6 * focal
    assert abs(f1 - focal) < 1e-6 * focal


def test_the_principal_point_is_not_optional():
    """The derivation assumes the optical axis is at the origin. A homography between raw frames is
    in corner-origin pixels, and feeding one in unshifted gives a confident wrong number rather
    than a failure — which is the dangerous direction."""
    h = _rotation_homography(2896.0, 3.0)
    right, _ = focals_from_homography(h, CX, CY)
    wrong, _ = focals_from_homography(h, 0.0, 0.0)
    assert abs(right - 2896.0) < 1e-3
    assert wrong is None or abs(wrong - 2896.0) > 100.0, (
        f"an unshifted map returned {wrong}, close enough to be believed"
    )


#: What the estimator needs, measured rather than asserted. Noise is applied to the
#: correspondences and the homography re-fitted the way `measure_pairs` does it, 25 trials:
#:
#:     rotation   0.1 px noise   0.3 px   1.0 px
#:     0.5 deg      20.2 %        58.9 %   58.5 %
#:     3.0 deg       0.2 %         2.9 %    6.1 %
#:
#: Our measured maps sit at 0.17-0.60 px, and consecutive frames at 30-60 fps turn a fraction of a
#: degree, so this repo's own pairs are the top-left cell. That is why the focal from a neighbour
#: pair is unusable here, and it is a fact about the footage: give it a few degrees and it works.
def test_half_a_degree_of_rotation_is_not_enough_at_our_map_precision():
    rng = np.random.default_rng(0)
    got = {}
    for deg in (0.5, 3.0):
        h = _rotation_homography(2896.0, deg)
        found = []
        for _ in range(15):
            p = rng.uniform([0, 0], [1080, 608], size=(400, 2))
            q = np.column_stack([p, np.ones(len(p))]) @ h.T
            q = q[:, :2] / q[:, 2, None]
            hm, _ = cv2.findHomography(p + rng.normal(0, 0.3, p.shape),
                                       q + rng.normal(0, 0.3, q.shape), cv2.USAC_MAGSAC, 3.0)
            if hm is None:
                continue
            f0, _ = focals_from_homography(hm, CX, CY)
            if f0:
                found.append(f0)
        got[deg] = abs(float(np.median(found)) - 2896.0) / 2896.0

    assert got[0.5] > 0.2, f"half a degree got within {got[0.5]:.1%}; the finding has changed"
    assert got[3.0] < 0.1, f"three degrees is {got[3.0]:.1%} out; the estimator regressed"
    assert got[3.0] < got[0.5]
