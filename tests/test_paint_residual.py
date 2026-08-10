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
    good = Residual(0, 8.0, 20.0, 30.0, 12.0, {}, n=1400, n_projected=1400, n_unmatched=0)
    # "better" median on 2% of the samples — the shape of every wrong verdict in this repo so far
    runaway = Residual(0, 2.0, 5.0, 8.0, 3.0, {}, n=30, n_projected=30, n_unmatched=0)
    verdict = compare(good, runaway)
    assert "no verdict" in verdict
    assert "out of frame" in verdict
    # And a fair pair still gets a verdict.
    fair = Residual(0, 4.0, 9.0, 14.0, 6.0, {}, n=1350, n_projected=1350, n_unmatched=0)
    assert "no verdict" not in compare(good, fair)


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


class TestPixelMotionAgainstKnownAnswers:
    """Synthetic controls for the pure-rotation test, which is the measurement M2 turns on.

    These exist because the measurement was wrong twice, in opposite directions, before anyone
    checked it against an answer that was known in advance. A coarse focal grid fabricates residual
    in proportion to how much rotation a pair contains — which is the very quantity being read — so
    a PURE rotation of 8 degrees scored 8 px, indistinguishable from a genuine 2 m translation at
    15.7 px. Refining the focal search takes the pure cases to 0.0000.
    """

    W, H, CX, CY = 1080, 608, 540.0, -334.0

    def _k(self, f):
        return np.array([[f, 0.0, self.CX], [0.0, f, self.CY], [0.0, 0.0, 1.0]])

    def _kinv(self, f):
        return np.array([[1 / f, 0.0, -self.CX / f], [0.0, 1 / f, -self.CY / f], [0.0, 0.0, 1.0]])

    def _rot(self, axis, deg):
        th = np.radians(deg)
        k = np.asarray(axis, float)
        k /= np.linalg.norm(k)
        kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
        return np.eye(3) + np.sin(th) * kx + (1 - np.cos(th)) * (kx @ kx)

    def _score(self, h):
        from camlab.measure.pixel_motion import PairMotion, rotation_only_residual_px
        px, _fi, _fj = rotation_only_residual_px(
            PairMotion(0, 1, h, 999, 0.0), self.CX, self.CY, self.W, self.H)
        return px

    @pytest.mark.parametrize(("name", "fi", "fj", "deg"), [
        ("small turn", 2400.0, 2400.0, 3.0),
        ("large turn", 2400.0, 2400.0, 8.0),
        ("turn while zooming", 2400.0, 3600.0, 8.0),
        ("long lens", 4300.0, 4300.0, 8.0),
    ])
    def test_a_pure_rotation_scores_zero(self, name, fi, fj, deg):
        h = self._k(fj) @ self._rot([0.2, 1.0, 0.3], deg) @ self._kinv(fi)
        assert self._score(h) < 0.01, f"{name}: a pure rotation must be explained exactly"

    def test_a_translating_camera_does_not(self):
        """The plane-induced homography of a camera that moved 2 m at 60 m depth.

        Also the calibration for reading real numbers: roughly 1 px per metre at this geometry.
        """
        rot = self._rot([0.2, 1.0, 0.3], 8.0)
        h = self._k(2400.0) @ (rot + np.outer([2.0, 0, 0], [0, 0, 1.0]) / 60.0) @ self._kinv(2400.0)
        assert self._score(h) > 1.0, "parallax must not be absorbable by any focal pair"


def test_the_worst_line_sees_what_a_pooled_median_cannot(fan):
    """A human looked at an overlay and said some markings fit while their parallels are far off.

    The pooled median cannot show that — the lines that fit outvote the lines that do not — and it
    is the characteristic failure, because a projected line drifting onto a NEIGHBOURING parallel
    line finds paint at almost zero distance and scores perfect.

    Measured on frame 0: the two long sides of the penalty box, both running along X and parallel
    to each other, come back at 29.9 px and 2.9 px. The median over everything is 7.3 px and shows
    neither.
    """
    r = _score(fan, 0)
    assert r.worst_line_px > 3 * r.median_px, (
        "if the worst marking is not far worse than the pooled median on this frame, either the "
        "clip changed or the per-line split stopped working"
    )
    solid = {k: v for k, v in r.per_line.items() if v[1] >= 8}
    assert len(solid) >= 5, "need several markings with real support to make the split meaningful"
    spread = max(v[0] for v in solid.values()) / min(v[0] for v in solid.values())
    assert spread > 5, f"markings should disagree by a lot on this camera, got {spread:.1f}x"


def test_unmatched_samples_are_reported_not_absorbed(fan):
    """Unbounded nearest-paint let a marking with no paint near it borrow a distance from across
    the frame. Bounded, those become a COUNT, which a median cannot dilute."""
    info, cam = fan
    r = frame_residual(info.frame_path(30), cam["focal_px"][30], cam["rotation"][30],
                       cam["position"][30], frame=30, match_px=40.0)
    assert r.n_unmatched > 0, "frame 30 has markings the frame shows no paint for"
    loose = frame_residual(info.frame_path(30), cam["focal_px"][30], cam["rotation"][30],
                           cam["position"][30], frame=30, match_px=10_000.0)
    assert loose.n_unmatched == 0
    assert loose.n > r.n, "a looser bound absorbs them into the score instead of reporting them"


class TestParallelFamiliesComeFromTheWorld:
    """Grouping parallel markings by their IMAGE direction is order-dependent and breaks.

    Perspective spreads a parallel family apart: on real frames of the fan clip markings 1, 8 and
    11 — parallel in the world — span 22.1 to 32.5 degrees in the image, eleven degrees against an
    8 degree threshold. A greedy first-fit grouping then puts them in different families depending
    on the order they are visited, and the order-preserving assignment cannot forbid two of them
    from claiming the same detected segment. A human saw exactly that on frames 16 and 18.
    """

    def test_a_pitch_has_exactly_two_families(self):
        import collections

        from camlab.measure.line_error import straight_markings, world_family
        fam = collections.defaultdict(list)
        for k, world in straight_markings():
            fam[world_family(world)].append(k)
        assert len(fam) == 2, f"a rectangular pitch has two, got {dict(fam)}"
        assert all(len(v) >= 5 for v in fam.values()), "neither family should be a stray"

    def test_the_two_families_are_perpendicular(self):
        from camlab.measure.line_error import straight_markings, world_family
        dirs = {0: [], 1: []}
        for _k, world in straight_markings():
            d = world[1] - world[0]
            dirs[world_family(world)].append(np.degrees(np.arctan2(d[1], d[0])) % 180.0)
        a = np.median([min(x, 180 - x) for x in dirs[0]])
        b = np.median([min(x, 180 - x) for x in dirs[1]])
        assert a < 10 and b > 80, f"families should be ~0 and ~90 deg apart, got {a:.0f}, {b:.0f}"

    @pytest.mark.skipif(not (runs_root() / "fan").exists(), reason="needs the ingested `fan` run")
    def test_no_two_markings_claim_the_same_detected_line(self, fan):
        """The invariant the whole assignment exists to enforce, on the frames it failed on."""
        import collections

        import cv2

        from camlab.measure.line_error import line_errors
        from camlab.measure.lines import detect_segments
        from camlab.measure.paint import paint_masks
        info, cam = fan
        for f in (16, 17, 18, 30):
            bgr = cv2.imread(str(info.frame_path(f)))
            dist, surface = paint_masks(bgr)
            errs = line_errors(detect_segments(dist, surface), cam["focal_px"][f],
                               cam["rotation"][f], cam["position"][f],
                               info.width, info.height, cx=cam["cx"], cy=cam["cy"])
            seen = collections.Counter(
                tuple(np.round(e.found_uv.ravel(), 1)) for e in errs if e.matched)
            dupes = {k: c for k, c in seen.items() if c > 1}
            assert not dupes, f"frame {f}: {len(dupes)} segment(s) claimed twice"
