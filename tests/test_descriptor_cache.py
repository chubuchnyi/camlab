"""SIFT is described once a frame per process, and re-ingesting a clip must invalidate it.

`measure_pairs` used to hold its descriptor cache inside the call. That is right for `solve_carry`,
which makes one call over the whole clip, and wrong for `solve_selfheal`, which calls it a pair at
a time inside three nested loops and so re-described the same frames dozens of times.

What is pinned here is the pair of properties a cache has to have to be allowed near a measurement:
it returns the same answer as computing it again, and it notices when the file underneath changes.
The second is the one that bites — `docs/findings/landmines.md` has the run-directory version of it,
where a stale downstream output was served under a fresh run's name for six hours.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from camlab.measure import pixel_motion as PM

RUNS = Path(__file__).resolve().parents[1] / "runs"


def two_frames():
    for clip in ("broadcast", "fan", "g11710897"):
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        if len(frames) >= 2:
            return frames[0], frames[1]
    pytest.skip("no ingested clip in this checkout")


def test_the_same_frame_is_described_once_and_the_answer_does_not_change():
    cv2 = pytest.importorskip("cv2")
    a, b = two_frames()
    PM.clear_descriptor_cache()

    calls = {"n": 0}
    real = cv2.SIFT_create

    class Counting:
        def __init__(self, inner):
            self._inner = inner

        def detectAndCompute(self, *args, **kw):
            calls["n"] += 1
            return self._inner.detectAndCompute(*args, **kw)

    cv2.SIFT_create = lambda **kw: Counting(real(**kw))
    try:
        first = PM.measure_pairs({0: a, 1: b}, gaps=(1,))
        after_first = calls["n"]
        # the shape `solve_selfheal` has: the same pair, again and again
        second = PM.measure_pairs({0: a, 1: b}, gaps=(1,))
        third = PM.measure_pairs({0: a, 1: b}, gaps=(1,))
    finally:
        cv2.SIFT_create = real

    assert after_first == 2, f"two frames should cost two descriptions, got {after_first}"
    assert calls["n"] == 2, f"the repeats should cost none, got {calls['n'] - 2} more"
    assert len(first) == len(second) == len(third) == 1
    for got in (second, third):
        assert np.array_equal(first[0].h, got[0].h), "a cache hit changed the homography"
        assert first[0].inliers == got[0].inliers
        assert first[0].median_px == got[0].median_px


def test_touching_the_frame_invalidates_it(tmp_path):
    """A re-ingest writes new pixels under the same name. Serving the old descriptors then is the
    same defect as a run directory serving yesterday's `camera_polished.json`."""
    cv2 = pytest.importorskip("cv2")
    a, b = two_frames()
    copy_a, copy_b = tmp_path / "000000.jpg", tmp_path / "000001.jpg"
    copy_a.write_bytes(a.read_bytes())
    copy_b.write_bytes(b.read_bytes())

    PM.clear_descriptor_cache()
    before = PM.measure_pairs({0: copy_a, 1: copy_b}, gaps=(1,))
    assert before, "the fixture frames produced no pair; pick different ones"

    # the same NAME, different pixels and a different mtime
    swapped = cv2.flip(cv2.imread(str(copy_a)), 1)
    cv2.imwrite(str(copy_a), swapped)
    os.utime(copy_a, (0, 0))

    after = PM.measure_pairs({0: copy_a, 1: copy_b}, gaps=(1,))
    if after:
        assert not np.array_equal(before[0].h, after[0].h), \
            "the frame was replaced and the cache served the old descriptors"


def test_the_cache_is_bounded():
    PM.clear_descriptor_cache()
    assert len(PM._DESCRIPTORS) == 0
    a, b = two_frames()
    PM.measure_pairs({0: a, 1: b}, gaps=(1,))
    assert 0 < len(PM._DESCRIPTORS) <= PM.DESCRIPTOR_CACHE
    PM.clear_descriptor_cache()
    assert len(PM._DESCRIPTORS) == 0
