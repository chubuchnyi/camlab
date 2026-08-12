"""Two conics compared, against cases whose answer is known before the code runs.

`conic_disagreement(a, b, pts)` promised "RMS pixel distance from `a`'s curve to `b`'s" and its
body was `_distance(b, pts)` — how far the POINTS are from `b`, with `a` never read. It was caught
by the number refusing to move: four completely different fitted ellipses on one frame all
"disagreed" with the same predicted arc by exactly 180.2 px.

`landmines.md` already carries the rule this breaks — validate an instrument against a known
injected error before believing it — so every case here has its answer fixed in advance.
"""

from __future__ import annotations

import numpy as np

from camlab.measure.ellipse import _fit_conic, conic_disagreement


def _circle(cx, cy, r, n=400):
    t = np.linspace(0, 2 * np.pi, n)
    return np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])


def test_a_conic_against_itself_is_zero():
    pts = _circle(300, 300, 200)
    c = _fit_conic(pts)
    assert conic_disagreement(c, c, pts) < 1e-6


def test_two_circles_twenty_pixels_apart_read_about_twenty():
    """The case the broken version could not see at all: it returned the same number whatever `a`
    was, so a right answer and a wrong one were indistinguishable."""
    inner, outer = _circle(300, 300, 200), _circle(300, 300, 220)
    pts = np.vstack([inner, outer])
    got = conic_disagreement(_fit_conic(inner), _fit_conic(outer), pts)
    # `_distance` is the algebraic distance normalised by the gradient — a first-order
    # approximation of the geometric one, so a few per cent, not exact.
    assert 18.0 < got < 23.0, got


def test_it_is_symmetric_enough_to_be_a_distance():
    inner, outer = _circle(300, 300, 200), _circle(300, 300, 220)
    pts = np.vstack([inner, outer])
    ab = conic_disagreement(_fit_conic(inner), _fit_conic(outer), pts)
    ba = conic_disagreement(_fit_conic(outer), _fit_conic(inner), pts)
    assert abs(ab - ba) < 3.0, (ab, ba)


def test_a_conic_that_runs_nowhere_near_the_points_says_so():
    """NaN is a real answer here. Returning a number computed from five stray pixels would be a
    verdict off no evidence, which is the failure this repo keeps finding."""
    pts = _circle(300, 300, 200)
    far = _fit_conic(_circle(9000, 9000, 50))
    assert np.isnan(conic_disagreement(far, _fit_conic(pts), pts))
