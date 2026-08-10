"""Readable camera angles, and back again.

A camera's orientation is three numbers whichever way you write it, but only some ways can be
checked against a photograph. An Euler triple in a Z-up world cannot: nobody can look at a frame
and say whether `rx` is 0.31 rad. These three can:

* **yaw** — the bearing the camera points, from +X, counter-clockwise seen from above
* **elevation** — of the optical axis; negative is looking down at the pitch
* **roll** — the tilt of the horizon; zero is level, and a handheld phone stays within a few
  degrees of it, which is why a solve reading 47.7 degrees is visibly nonsense

This is the pair that makes hand editing possible: the panel shows these, a human changes one, and
the server turns it back into the rotation the camera actually needs. The browser never sends a
matrix — a raw 3x3 from a client can express things that are not a rotation, and then "this is a
camera" stops being a guarantee.
"""

from __future__ import annotations

import numpy as np


def rotation_from_angles(yaw_deg: float, elev_deg: float, roll_deg: float) -> np.ndarray:
    """World→camera rotation, OpenCV convention: rows are the camera's axes in world coordinates.

    Row 0 is the camera's right, row 1 its down (image y runs down), row 2 its forward. Built in
    that order rather than as a product of axis rotations, because the three angles are *defined*
    by that basis and reconstructing them from an Euler product would be a different convention
    that happens to agree at zero.
    """
    yaw, elev, roll = np.radians([yaw_deg, elev_deg, roll_deg])
    fwd = np.array([np.cos(elev) * np.cos(yaw), np.cos(elev) * np.sin(yaw), np.sin(elev)])

    # The level basis first: right is horizontal, so the horizon is flat.
    world_down = np.array([0.0, 0.0, -1.0])
    right = np.cross(world_down, fwd)
    n = np.linalg.norm(right)
    if n < 1e-9:
        # Straight up or straight down: yaw and roll become the same rotation and the horizon has
        # no direction. Pick one rather than divide by zero — the caller is nowhere near this.
        right = np.array([1.0, 0.0, 0.0])
    else:
        right = right / n
    down = np.cross(fwd, right)

    # Then roll about the optical axis, which is what tilts the horizon.
    c, s = np.cos(roll), np.sin(roll)
    right_r = c * right + s * down
    down_r = -s * right + c * down
    return np.vstack([right_r, down_r, fwd])


def angles_from_rotation(rot: np.ndarray) -> tuple[float, float, float]:
    """`(yaw, elevation, roll)` in degrees from a world→camera rotation. Inverse of the above."""
    rot = np.asarray(rot, dtype=float)
    right, fwd = rot[0], rot[2]
    yaw = float(np.degrees(np.arctan2(fwd[1], fwd[0])))
    elev = float(np.degrees(np.arcsin(np.clip(fwd[2], -1.0, 1.0))))

    # Roll measured IN the level basis, not off the right vector's vertical component. After a
    # roll, right_r[2] = sin(roll) * down_z, and down_z depends on the elevation — so reading
    # asin(right[2]) gives the roll only when the camera is level, which is exactly the case that
    # tests nothing. Rebuild the zero-roll basis at this (yaw, elev) and take the angle within it.
    world_down = np.array([0.0, 0.0, -1.0])
    right0 = np.cross(world_down, fwd)
    n = np.linalg.norm(right0)
    if n < 1e-9:
        return yaw, elev, 0.0
    right0 = right0 / n
    down0 = np.cross(fwd, right0)
    roll = float(np.degrees(np.arctan2(float(right @ down0), float(right @ right0))))
    return yaw, elev, roll


def rodrigues_from_matrix(rot: np.ndarray) -> np.ndarray:
    """Rotation matrix → Rodrigues vector, the form `camera_*.json` stores."""
    rot = np.asarray(rot, dtype=float)
    theta = float(np.arccos(np.clip((np.trace(rot) - 1.0) / 2.0, -1.0, 1.0)))
    if theta < 1e-9:
        return np.zeros(3)
    v = np.array([rot[2, 1] - rot[1, 2], rot[0, 2] - rot[2, 0], rot[1, 0] - rot[0, 1]])
    return v * (theta / (2.0 * np.sin(theta)))


def matrix_from_rodrigues(rvec: np.ndarray) -> np.ndarray:
    """Rodrigues vector → rotation matrix."""
    rvec = np.asarray(rvec, dtype=float)
    theta = float(np.linalg.norm(rvec))
    if theta < 1e-12:
        return np.eye(3)
    k = rvec / theta
    kx = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + np.sin(theta) * kx + (1.0 - np.cos(theta)) * (kx @ kx)
