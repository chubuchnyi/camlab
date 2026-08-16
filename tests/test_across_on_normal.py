"""`_across_on_normal` was a Python loop over `t`. It is two scans now, and it must not have moved.

The loop is 95 % of a warm `frame_residual` — the half that depends on the camera, which no amount
of paint caching removes — so it was worth rewriting, and the rewrite is worth pinning hard. What
is pinned is not "close enough": the arithmetic per element is unchanged, in the same dtype and the
same order, so the two must agree **bit for bit**. Anything less means the state machine was
translated wrong, and this metric is what the whole repo argues from.

The loop is reproduced here rather than kept in `residual.py` behind a flag, because a second
implementation in the shipped module is a second thing to keep true.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from camlab.measure.residual import CROSSING_TOL, _across_on_normal

RUNS = Path(__file__).resolve().parents[1] / "runs"


def loop_version(sub, normal, dist, limit, step=0.25):
    """`_across_on_normal` as it was written until the walk was vectorised, verbatim."""
    h, w = dist.shape

    def sample(p):
        x = np.clip(p[:, 0], 0.0, w - 1.001)
        y = np.clip(p[:, 1], 0.0, h - 1.001)
        x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = x - x0, y - y0
        top = dist[y0, x0] * (1 - fx) + dist[y0, x0 + 1] * fx
        bot = dist[y0 + 1, x0] * (1 - fx) + dist[y0 + 1, x0 + 1] * fx
        return top * (1 - fy) + bot * fy

    def one_way(direction):
        n = len(sub)
        low = np.full(n, np.inf)
        at = np.full(n, np.inf)
        done = np.zeros(n, dtype=bool)
        for t in np.arange(0.0, limit + step, step):
            here = sample(sub + t * direction)
            nearer = ~done & (here < low)
            low[nearer], at[nearer] = here[nearer], t
            done |= ~done & (low <= CROSSING_TOL) & (here > low + 1e-6)
            if done.all():
                break
        return at + low, low <= CROSSING_TOL

    plus, ok_plus = one_way(normal)
    minus, ok_minus = one_way(-normal)
    best = np.where(ok_plus & (~ok_minus | (plus <= minus)), plus, minus)
    found = ok_plus | ok_minus
    return np.where(found, best, np.inf), found


def _same(a, b):
    (across_a, found_a), (across_b, found_b) = a, b
    assert np.array_equal(found_a, found_b)
    # `inf` compares unequal to itself under `==` but equal under `array_equal`, which is what is
    # wanted here: an unfound sample must stay unfound and must stay `inf`.
    assert np.array_equal(across_a, across_b)


@pytest.mark.parametrize("seed", range(8))
def test_the_vectorised_walk_is_bit_for_bit_the_loop_on_synthetic_rays(seed):
    """A distance map with several parallel stripes, so a ray can cross more than one.

    That is the case the "first minimum, not the smallest" rule exists for, and a rewrite that
    took a global minimum would pass a single-stripe test and fail here.
    """
    rng = np.random.default_rng(seed)
    h, w = 240, 320
    yy = np.arange(h)[:, None] * np.ones(w)
    stripes = np.minimum.reduce([np.abs(yy - r) for r in (40, 90, 150, 205)]).astype(np.float32)
    # a few holes, so some rays find no paint at all in one direction
    stripes[100:140, 60:200] = 60.0

    n = 300
    sub = np.column_stack([rng.uniform(2, w - 3, n), rng.uniform(2, h - 3, n)])
    ang = rng.uniform(0, 2 * np.pi, n)
    normal = np.column_stack([np.cos(ang), np.sin(ang)])
    _same(_across_on_normal(sub, normal, stripes, 40.0),
          loop_version(sub, normal, stripes, 40.0))


def test_it_holds_where_every_sample_is_already_on_the_paint():
    """`at = 0` and the whole answer is `low` — the branch the docstring says is not a branch."""
    h, w = 60, 60
    dist = np.abs(np.arange(h)[:, None] - 30.0).astype(np.float32) * np.ones(w, np.float32)
    sub = np.column_stack([np.linspace(5, 55, 40), np.full(40, 30.0)])
    normal = np.column_stack([np.zeros(40), np.ones(40)])
    _same(_across_on_normal(sub, normal, dist, 40.0),
          loop_version(sub, normal, dist, 40.0))


def test_an_empty_sample_set_returns_empty_rather_than_raising():
    dist = np.zeros((10, 10), np.float32)
    across, found = _across_on_normal(np.zeros((0, 2)), np.zeros((0, 2)), dist, 40.0)
    assert across.shape == (0,) and found.shape == (0,) and found.dtype == bool


@pytest.mark.parametrize("clip", ["fan", "broadcast"])
def test_the_vectorised_walk_is_bit_for_bit_the_loop_on_a_real_frame(clip):
    """Against real paint, real normals and the real `match_px`, not a fixture.

    The synthetic cases can be designed to hit the interesting branches; only a real frame has the
    distribution of them that a solve actually meets.
    """
    frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
    if not frames:
        pytest.skip(f"{clip} is not ingested in this checkout")
    cv2 = pytest.importorskip("cv2")

    from camlab.measure.paint import paint_masks

    dist, surface = paint_masks(cv2.imread(str(frames[0])))
    spine = np.argwhere(dist == 0)[:, ::-1].astype(float)
    assert len(spine), "the frame has no paint, so this test would prove nothing"

    rng = np.random.default_rng(0)
    h, w = dist.shape
    # Samples spread over the playing surface, with directions of every orientation, which is a
    # harder set than a real projection gives: real markings come in two families.
    ys, xs = np.nonzero(surface > 0)
    take = rng.choice(len(xs), size=min(600, len(xs)), replace=False)
    sub = np.column_stack([xs[take], ys[take]]).astype(float)
    sub += rng.uniform(-0.5, 0.5, sub.shape)
    sub[:, 0] = np.clip(sub[:, 0], 1, w - 2)
    sub[:, 1] = np.clip(sub[:, 1], 1, h - 2)
    ang = rng.uniform(0, 2 * np.pi, len(sub))
    normal = np.column_stack([np.cos(ang), np.sin(ang)])

    _same(_across_on_normal(sub, normal, dist, 40.0),
          loop_version(sub, normal, dist, 40.0))
