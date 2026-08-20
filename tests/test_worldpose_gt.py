"""The WorldPose ground-truth import, and the one sign convention that inverts the whole thing.

WorldPose stores the `t` of `X_c = R X_w + t`; camlab stores the camera CENTRE. They differ by
`C = -Rᵀt`, and getting it wrong does not raise, does not look wrong in a file, and puts the camera
underground — which is why the conversion is pinned here rather than left to the reader.

The real-data test is skipped without the dataset (it is 1.7 GB and lives outside the repo), so CI
proves the algebra and a developer's machine proves the file on disk.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.import_worldpose_gt import CAMERAS, distortion_shift_px, gt_path  # noqa: E402

cv2 = pytest.importorskip("cv2")

#: The clip whose numbers are quoted in `findings/the-metric-cannot-see-depth-2026-08-16.md`.
GOLDEN = "CRO_MOR_194948"


def test_centre_conversion_is_not_the_translation():
    """`C = -Rᵀt` on a camera whose centre is known by construction, and `t` is nowhere near it."""
    C = np.array([0.0, -88.0, 18.6])
    # Looking from behind a goal-less halfway line toward the pitch centre: +Y and slightly down.
    fwd = -C / np.linalg.norm(C)
    right = np.cross(fwd, [0, 0, 1.0])
    right /= np.linalg.norm(right)
    R = np.stack([right, np.cross(fwd, right), fwd])
    t = -R @ C

    assert np.allclose(-R.T @ t, C, atol=1e-9)
    # The trap: `t` is 90 m from the centre it is mistaken for, and both are plausible-looking
    # 3-vectors. Nothing but this identity separates them.
    assert np.linalg.norm(t - C) > 80.0


def test_distortion_shift_is_zero_without_coefficients():
    """The diagnostic reports the effect of `k`, so an undistorted camera must read exactly zero."""
    K = np.array([[5720.0, 0, 960.0], [0, 5720.0, 540.0], [0, 0, 1.0]])
    R = cv2.Rodrigues(np.array([1.9, 0.0, 0.0]))[0]
    t = -R @ np.array([0.0, -88.0, 18.6])
    assert distortion_shift_px(K, R, t, np.zeros(5)) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.skipif(not gt_path(GOLDEN).exists(), reason="WorldPose ground truth not on this box")
def test_the_ground_truth_puts_the_camera_where_a_broadcast_camera_stands():
    """The world frame is undocumented, so it is asserted from the file — this is that assertion.

    If WorldPose's origin were a pitch corner, or its up axis were Y, these bounds would fail and
    every metre quoted against this dataset would be wrong. `import_worldpose_gt` reads the frame
    the way this test describes and nothing else checks it.
    """
    d = np.load(gt_path(GOLDEN))
    R, t = d["R"], d["t"]
    C = np.einsum("nji,nj->ni", R, -t)

    assert C.shape[0] == len(d["K"]) > 1000, "expected a per-frame camera for the whole clip"
    # A broadcast gantry: above the pitch, behind a touchline, near the halfway line.
    assert 10.0 < C[:, 2].min() and C[:, 2].max() < 25.0, "height off the pitch plane"
    assert np.abs(C[:, 0]).max() < 30.0, "not near the halfway line"
    assert 60.0 < np.abs(C[:, 1]).min(), "not behind a touchline"
    # A fixed head: it pans, tilts and zooms, and does not travel. This is what the shared-centre
    # stage assumes about broadcast clips, and it is measured here rather than hoped.
    assert np.ptp(C, axis=0).max() < 0.01, "the ground-truth camera centre moved"


@pytest.mark.skipif(not gt_path(GOLDEN).exists(), reason="WorldPose ground truth not on this box")
def test_the_lens_has_distortion_camlab_cannot_represent():
    """Pins the re-opened `STATUS.md` entry: this is not the 0.37 px lens that was ruled out."""
    d = np.load(gt_path(GOLDEN))
    shift = distortion_shift_px(d["K"][0], d["R"][0], d["t"][0], d["k"][0])
    assert shift > 20.0, f"expected tens of px of distortion at the frame edge, got {shift:.2f}"


@pytest.mark.skipif(not gt_path(GOLDEN).exists(), reason="WorldPose ground truth not on this box")
def test_the_focal_changes_within_one_clip():
    """The reason this repo exists: a one-focal-per-clip camera cannot represent these."""
    fx = np.load(gt_path(GOLDEN))["K"][:, 0, 0]
    assert fx.max() / fx.min() > 1.05, "expected a zoom inside the clip"


@pytest.mark.skipif(not CAMERAS.exists(), reason="WorldPose ground truth not on this box")
def test_every_ingested_worldpose_clip_can_be_matched_by_name():
    """The clip id IS the WorldPose id — the fact that went unnoticed (see `landmines.md`)."""
    from camlab.runs import runs_root

    root = runs_root()
    if not root.exists():
        pytest.skip("no runs/ on this box")
    matched = [d.name for d in root.iterdir()
               if (d / "clip.json").exists() and gt_path(d.name).exists()]
    # Not a fixed count: clips get ingested. What is pinned is that the join works at all, so a
    # rename of either side fails here instead of silently producing an empty validation set.
    assert matched, "no ingested clip matched a WorldPose camera by name"
