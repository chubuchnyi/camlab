"""One image space per run, and the routes that hand it to the browser.

The defect this repo was carved out to stop repeating is a camera solved in a different image
space than the pixels it is compared against: pitch3d applies `--crop auto` at decode but leaves
the uncropped size on the clip record, so the camera fit gets a principal point 656 px outside an
image 608 px tall (`landmines.md`). Here `clip.json` records the size of the frames ON DISK, and
the viewer refuses a solve that disagrees with it.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from camlab.camera_file import read_camera, write_camera
from camlab.io.ingest import apply_crop
from camlab.runs import ClipInfo, runs_root
from camlab.server.app import app

client = TestClient(app)


def test_crop_is_clamped_not_raised():
    """A rect measured on one segment can overhang a later frame. A black bar beats a dead run."""
    img = np.zeros((100, 200, 3), np.uint8)
    assert apply_crop(img, None).shape == (100, 200, 3)
    assert apply_crop(img, (50, 40, 10, 20)).shape == (40, 50, 3)
    assert apply_crop(img, (500, 500, 190, 90)).shape == (10, 10, 3), "clamped to the frame"


def test_camera_file_round_trip(tmp_path):
    p = write_camera(
        tmp_path / "c.json", model="test", clip_id="x", width=1080, height=608,
        frames=np.arange(3), focal_px=np.array([1.0, 2.0, 3.0]),
        position=np.zeros((3, 3)), rotation=np.zeros((3, 3)),
    )
    blob = read_camera(p)
    assert blob["width"] == 1080 and blob["height"] == 608
    # The principal point is WRITTEN, not left for a reader to assume. Assuming it is what the
    # viewer's fov maths would get wrong, silently and plausibly.
    assert blob["cx"] == 540.0 and blob["cy"] == 304.0
    assert blob["frames"] == [0, 1, 2]


def test_read_camera_refuses_a_foreign_schema(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"schema": 999}')
    with pytest.raises(ValueError, match="schema"):
        read_camera(p)


@pytest.mark.skipif(not (runs_root() / "fan").exists(), reason="needs the ingested `fan` run")
class TestAgainstTheRealRun:
    """Against the real ingested clip, not a fixture — the numbers here were measured."""

    def test_clip_json_records_the_CROPPED_size(self):
        info = ClipInfo.load("fan")
        assert info.crop == (1080, 608, 0, 1294)
        assert (info.width, info.height) == (1080, 608), "the size of the frames on disk"
        assert (info.source_width, info.source_height) == (1080, 1920), "kept only to read back"

    def test_the_solve_lives_in_the_same_space_as_the_frames(self):
        """The check the viewer makes before it draws anything, made here so CI makes it too."""
        info = ClipInfo.load("fan")
        cam = client.get("/api/run/fan/camera").json()
        assert (cam["width"], cam["height"]) == (info.width, info.height)

    def test_unusable_frames_are_marked_not_removed(self):
        """The rule is R-6: a frame the solver could not use is MARKED, never dropped.

        This used to assert `sum(degenerate) > 0` on the ground that "this clip has a rank-poor
        tail". It did — frames 115-118 of `camera_auto.json` carry focals of 300, 20000, 300,
        20000, pinned at both search bounds. But the flag was being COPIED through four stages, so
        those four stayed flagged in `camera_smooth.json` long after the chain repaired them to
        4729, 4727, 4726, 4716, and the viewer drew them in its "could not use this" pink.

        Deriving the flag from the camera in hand fixed that, and re-solving then produced a clip
        with no unusable frame at all — so the old assertion failed for the right reason. What is
        actually contractual is the correspondence: every frame is present, and a frame is flagged
        if and only if this camera still shows it as unusable.
        """
        cam = client.get("/api/run/fan/camera").json()
        assert len(cam["frames"]) == 120, "a broken clip must not look like a shorter good one"
        lo, hi = 300.0, 20000.0
        for i, f in enumerate(cam["focal_px"]):
            unusable = not (f > 0) or f <= lo + 1e-6 or f >= hi - 1e-6
            assert bool(cam["degenerate"][i]) == unusable, (
                f"frame {i} has focal {f} and degenerate={cam['degenerate'][i]}"
            )

    def test_a_frame_comes_back_at_the_cropped_size(self):
        import io

        from PIL import Image  # noqa: PLC0415
        r = client.get("/api/run/fan/frame/0")
        assert r.status_code == 200
        assert Image.open(io.BytesIO(r.content)).size == (1080, 608)

    def test_a_frame_past_the_end_is_a_404_not_a_blank(self):
        assert client.get("/api/run/fan/frame/99999").status_code == 404


def test_a_crop_moves_the_principal_point():
    """The optical axis stays where the lens put it; the crop moves the image around it.

    Measured, not reasoned: sweeping cy through the image->image maps — which know nothing about
    any crop — puts the minimum at -334.0, the arithmetic value to the decimal, against a 2.4x
    worse score at the crop's own centre. docs/findings/m2-principal-point.md.

    pitch3d has this defect live: `--crop auto` crops and `camera_from_calibration` takes cx, cy as
    the centre of whatever size it is handed.
    """
    fan = ClipInfo(
        clip_id="t", source="x", source_sha256="0", width=1080, height=608, fps=30.0,
        n_frames=1, first_frame=0, crop=(1080, 608, 0, 1294),
        source_width=1080, source_height=1920,
    )
    assert fan.principal_point == (540.0, -334.0)
    assert fan.principal_point != (fan.width / 2, fan.height / 2), "the trap this exists to avoid"

    uncropped = ClipInfo(
        clip_id="t", source="x", source_sha256="0", width=1920, height=1080, fps=30.0,
        n_frames=1, first_frame=0, crop=None, source_width=1920, source_height=1080,
    )
    assert uncropped.principal_point == (960.0, 540.0), "no crop, no offset"
