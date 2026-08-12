"""The transfer file, which is where a zoom used to be thrown away.

pitch3d's schema 1 held `focal` as one scalar for a whole clip. Measured, collapsing to that costs
65 % of the accuracy on the fan clip — 1.69 px becomes 4.88 and five frames of thirty leave the
20 px band — and nothing at all on clips that do not zoom. Schema 2 writes it per frame.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from camlab.io.export_npz import SCHEMA, SCHEMA_2_KEYS, export_npz, read_npz
from camlab.runs import ClipInfo, list_runs

CALIB = Path(__file__).resolve().parents[1] / "calib"


def _a_solved_clip():
    for cid in list_runs():
        p = ClipInfo.load(cid).dir / "camera_smooth.json"
        if p.exists():
            return cid, json.loads(p.read_text())
    pytest.skip("no solved clip on disk")
    return None


def test_every_key_is_present_on_every_camera(tmp_path):
    """A key that is sometimes there is a branch every reader has to know about. The first version
    of this exporter wrote the old scalar `focal` only when the focal was constant, which was the
    right instinct against a silent loss and the wrong shape."""
    cid, cam = _a_solved_clip()
    export_npz(cam, tmp_path / "c.npz", clip_id=cid)
    blob = np.load(tmp_path / "c.npz", allow_pickle=False)
    assert set(blob.files) == set(SCHEMA_2_KEYS)
    assert int(blob["schema"]) == SCHEMA


def test_the_focal_survives_the_round_trip_frame_by_frame(tmp_path):
    cid, cam = _a_solved_clip()
    export_npz(cam, tmp_path / "c.npz", clip_id=cid)
    got = read_npz(tmp_path / "c.npz")
    want = np.asarray(cam["focal_px"], float)
    assert got["focal_px"].shape == want.shape, "per frame, not one number"
    assert np.allclose(got["focal_px"], want), "and the same numbers"
    assert np.allclose(got["position"], np.asarray(cam["position"], float))


def test_the_homography_is_rebuilt_from_the_parameters_beside_it(tmp_path):
    """Not copied. A file that carries a homography disagreeing with its own focal and pose is a
    file where two readers get two different cameras, and nothing shows it."""
    from camlab.measure.residual import world_to_image

    cid, cam = _a_solved_clip()
    export_npz(cam, tmp_path / "c.npz", clip_id=cid)
    got = read_npz(tmp_path / "c.npz")
    for i in (0, len(got["frames"]) // 2, len(got["frames"]) - 1):
        want = world_to_image(got["focal_px"][i], got["rvecs"][i], got["position"][i],
                              int(got["width"]), int(got["height"]),
                              cx=float(got["cx"]), cy=float(got["cy"]))
        assert np.allclose(got["world_to_image"][i], want)


def test_a_non_positive_focal_is_refused(tmp_path):
    cid, cam = _a_solved_clip()
    broken = dict(cam)
    f = list(map(float, cam["focal_px"]))
    f[1] = 0.0
    broken["focal_px"] = f
    with pytest.raises(ValueError, match="not a camera"):
        export_npz(broken, tmp_path / "c.npz", clip_id=cid)


def test_schema_1_is_refused_by_name_rather_than_read_as_if_it_were_2():
    """The old fixture is still on disk and still pinned by the golden test. Reading it here must
    say what it is and why it cannot be used, not raise a KeyError from four lines in."""
    old = CALIB / "Colombia-1-0-Congo-DR1080p.npz"
    if not old.exists():
        pytest.skip("the schema-1 fixture is not present")
    with pytest.raises(ValueError, match="schema 1"):
        read_npz(old)
