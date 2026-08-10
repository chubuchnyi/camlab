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
        cam = client.get("/api/run/fan/camera").json()
        assert len(cam["frames"]) == 120, "a broken clip must not look like a shorter good one"
        assert sum(cam["degenerate"]) > 0, "this clip has a rank-poor tail; it must be flagged"

    def test_a_frame_comes_back_at_the_cropped_size(self):
        import io

        from PIL import Image  # noqa: PLC0415
        r = client.get("/api/run/fan/frame/0")
        assert r.status_code == 200
        assert Image.open(io.BytesIO(r.content)).size == (1080, 608)

    def test_a_frame_past_the_end_is_a_404_not_a_blank(self):
        assert client.get("/api/run/fan/frame/99999").status_code == 404
