"""Carrying a camera through an image→image homography, checked against a known answer first.

Three confident verdicts in this repo came from instruments nobody had validated against an
injected error — one of them read 8–22 px of motion on a synthetic *known-zero* rotation, which
was its own grid step. So the real-clip numbers live in a bench script; these are the cases where
the answer is known in advance and the instrument has to reproduce it.
"""

from __future__ import annotations

import numpy as np
import pytest

from camlab.core.angles import matrix_from_rodrigues, rodrigues_from_matrix, rotation_from_angles
from camlab.solve.carry import carry

CX, CY = 540.0, -334.0          # the fan clip's real optical axis, well outside the frame


def _k(f):
    return np.array([[f, 0.0, CX], [0.0, f, CY], [0.0, 0.0, 1.0]])


def _homography(f_i, rot_i, f_j, rot_j):
    """The exact map a rotating, zooming camera about a fixed centre produces."""
    return _k(f_j) @ rot_j @ rot_i.T @ np.linalg.inv(_k(f_i))


@pytest.mark.parametrize("dyaw,delev,f_i,f_j", [
    (3.0, 0.0, 3400.0, 3400.0),          # pure pan
    (0.0, 2.0, 3400.0, 3400.0),          # pure tilt
    (0.0, 0.0, 3400.0, 3900.0),          # pure zoom
    (2.5, -1.5, 3400.0, 3050.0),         # all three at once
    (-6.0, 0.8, 5200.0, 4700.0),         # long lens, big pan
])
def test_it_recovers_a_rotation_and_zoom_it_was_given(dyaw, delev, f_i, f_j):
    rot_i = rotation_from_angles(57.0, -17.0, -0.8)
    rot_j = rotation_from_angles(57.0 + dyaw, -17.0 + delev, -0.8)
    h = _homography(f_i, rot_i, f_j, rot_j)

    got = carry(f_i, rodrigues_from_matrix(rot_i), [1.0, -70.0, 25.0], h, CX, CY)
    assert got is not None

    assert got.focal_px == pytest.approx(f_j, rel=1e-6), "the focal is pinned, not assumed"
    ang = np.degrees(np.linalg.norm(rodrigues_from_matrix(
        matrix_from_rodrigues(got.rotation) @ rot_j.T)))
    assert ang < 1e-4, f"recovered aim is {ang:.2e} deg off the truth"
    assert got.focal_disagreement < 1e-9, "a true rotation must show no disagreement between axes"
    assert np.allclose(got.position, [1.0, -70.0, 25.0]), "carrying does not move the camera"


def test_identity_leaves_the_camera_exactly_where_it_was():
    rot = rotation_from_angles(57.0, -17.0, -0.8)
    got = carry(3400.0, rodrigues_from_matrix(rot), [1.0, -70.0, 25.0], np.eye(3), CX, CY)
    assert got is not None
    assert got.focal_px == pytest.approx(3400.0, rel=1e-9)
    assert np.allclose(matrix_from_rodrigues(got.rotation), rot, atol=1e-9)


def test_a_translating_camera_is_flagged_rather_than_absorbed():
    """The one assumption: a fixed centre. When it is false the seed must say so.

    A homography that is not `K_j R_j Rᵢᵀ K_i⁻¹` for any rotation cannot be turned into a camera,
    and quietly returning the nearest one would hand the search a confident wrong start — the
    failure mode this whole module exists to fix, reintroduced one level up.
    """
    rot = rotation_from_angles(57.0, -17.0, -0.8)
    clean = _homography(3400.0, rot, 3400.0, rotation_from_angles(60.0, -17.0, -0.8))
    # A plane-induced parallax term: what a real translation adds on top of the rotation.
    skewed = clean @ (np.eye(3) + np.outer([0.0, 0.0, 1.0], [3e-4, 1e-4, 0.0]))

    honest = carry(3400.0, rodrigues_from_matrix(rot), [1.0, -70.0, 25.0], clean, CX, CY)
    shifted = carry(3400.0, rodrigues_from_matrix(rot), [1.0, -70.0, 25.0], skewed, CX, CY)
    assert honest is not None and shifted is not None
    assert shifted.focal_disagreement > 10 * max(honest.focal_disagreement, 1e-12), (
        "translation must show up as the two image axes disagreeing about the focal"
    )


def test_a_degenerate_homography_returns_none_not_a_camera():
    assert carry(3400.0, np.zeros(3), [0.0, -70.0, 25.0], np.zeros((3, 3)), CX, CY) is None
    singular = np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    assert carry(3400.0, np.zeros(3), [0.0, -70.0, 25.0], singular, CX, CY) is None
