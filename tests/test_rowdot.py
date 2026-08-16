"""`_rowdot` must be bit-for-bit `a @ b`, and the obvious rewrites of it are not.

`line_errors` compares one projected marking against every detected segment, and that inner loop
is now one vectorised pass instead of 259 000 Python calls a stage. The vectorising is only safe if
the row-wise dot it uses returns exactly what the scalar `compare_line` returned, because
`_assign_in_order` settles which segment a marking is given with `best == take` — an exact float
comparison — and a solve minimises the result about a hundred times a frame.

The first attempt used `(A * B).sum(axis=1)`, which is the natural spelling and differs in the last
bit: offsets moved by 1e-16 to 9e-14 on twelve of fourteen clips. This test is what stops that
coming back the next time someone reads `_rowdot` and thinks it is needlessly baroque.

The mechanism: BLAS's two-element dot fuses its multiply and add, so it rounds once; every
elementwise form rounds the product and then rounds the sum.
"""
from __future__ import annotations

import numpy as np
import pytest

from camlab.measure.line_error import _rowdot


def scalar(a, b):
    """What `compare_line` does, one pair at a time — the definition being matched."""
    return np.array([x @ y for x, y in zip(a, b, strict=True)])


@pytest.mark.parametrize("seed", range(4))
def test_rowdot_is_the_scalar_dot_with_a_vector_per_row(seed):
    rng = np.random.default_rng(seed)
    a = rng.normal(size=(20000, 2)) * 1000.0
    b = rng.normal(size=(20000, 2))
    assert np.array_equal(_rowdot(a, b), scalar(a, b))


@pytest.mark.parametrize("seed", range(4))
def test_rowdot_is_the_scalar_dot_with_one_shared_vector(seed):
    """The `nrm` and `u` case: one 2-vector against every row."""
    rng = np.random.default_rng(100 + seed)
    a = rng.normal(size=(20000, 2)) * 1000.0
    b = rng.normal(size=2)
    assert np.array_equal(_rowdot(a, b), scalar(a, np.broadcast_to(b, a.shape)))


def test_the_obvious_rewrites_really_do_differ():
    """The negative half, so the docstring's claim is checked and not just asserted.

    If numpy or the BLAS underneath it ever changes so that these agree, this test fails and
    `_rowdot`'s reason for existing should be re-read rather than the test deleted.
    """
    rng = np.random.default_rng(7)
    a = rng.normal(size=(20000, 2)) * 1000.0
    b = rng.normal(size=(20000, 2))
    want = scalar(a, b)
    assert not np.array_equal((a * b).sum(axis=1), want)
    assert not np.array_equal(a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1], want)
    assert not np.array_equal(np.einsum("ij,ij->i", a, b), want)


def test_a_stack_of_matrix_vector_products_already_agrees():
    """`_overlap`'s projection is `(M, 2, 2) @ u` and is deliberately NOT routed through `_rowdot`.

    A batched matrix-vector product takes the same BLAS path as the single one, so it needs no
    help. Pinned because the temptation on reading `_candidates` is to make it uniform.
    """
    rng = np.random.default_rng(3)
    f = rng.normal(size=(5000, 2, 2)) * 100.0
    u = rng.normal(size=2)
    assert np.array_equal(f @ u, np.array([m @ u for m in f]))


def test_rowdot_on_an_empty_set():
    got = _rowdot(np.zeros((0, 2)), np.zeros(2))
    assert got.shape == (0,)
