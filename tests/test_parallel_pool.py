"""The pool must not deadlock against OpenCV, which is the only reason it is worth testing.

`default_workers()` went from 1 to 2 on 2026-08-13. `verdict.judge` is the last thing
`solve_carry` does and it is the one caller of `map_items`, so from that moment **every solve ended
in a hang**. Measured on `g11710897`, one anchor, nothing else changed:

    fork, 2 workers     still hung at 3000 s — parent and both children in `futex_do_wait`
    spawn, 2 workers    22 s
    no pool at all      23 s, and every reported number identical to the spawn run

It looked exactly like "this clip is slow", which is why it survived a day and four abandoned runs.

**The mechanism is not established, and this test does not claim one.** The obvious candidate —
forking after OpenCV has started its threads, so a child inherits mutexes held by threads that do
not exist in it — did not reproduce: the probe below completes under `fork` as well. So the test
pins the property that was actually measured (the pool returns, and it is spawned) rather than a
story about why.

Run in a subprocess with a timeout, because the failure mode is a hang: asserting it in-process
would take the whole suite down with it rather than reporting.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Long enough that a slow machine importing cv2 twice does not fail, short enough that a real
#: deadlock is reported in under a minute. The work itself is milliseconds.
POOL_TIMEOUT_S = 90

SCRIPT = textwrap.dedent("""
    import numpy as np
    from camlab.parallel import map_items

    # A module-level name in a real module, because a spawned worker re-imports rather than
    # inheriting — a closure would fail to pickle and never reach the pool at all.
    from camlab.measure.paint import paint_masks


    def work(seed):
        import cv2
        img = np.full((80, 120, 3), 40, np.uint8)
        img[38:42, 10:110] = 250
        # Touch OpenCV in the PARENT first, then again in each child. That order is the whole
        # point: a fork after cv2 has run is what deadlocks.
        cv2.GaussianBlur(img, (3, 3), 0)
        return int(img.sum()) + seed


    if __name__ == "__main__":
        import cv2
        cv2.GaussianBlur(np.zeros((64, 64, 3), np.uint8), (3, 3), 0)
        got = map_items(work, list(range(8)), workers=2)
        assert got == [work(i) for i in range(8)], got
        print("OK", len(got))
""")


def test_the_pool_does_not_deadlock_after_opencv_has_run(tmp_path):
    script = tmp_path / "pool_probe.py"
    script.write_text(SCRIPT)
    try:
        p = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                           timeout=POOL_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"map_items did not return within {POOL_TIMEOUT_S}s with 2 workers after OpenCV had "
            "run in the parent. That is the fork-inherited-mutex deadlock; the pool needs a spawn "
            "context."
        )
    assert p.returncode == 0, f"stdout={p.stdout!r} stderr={p.stderr[-800:]!r}"
    assert "OK 8" in p.stdout, p.stdout


def test_the_pool_is_spawned_rather_than_forked():
    """States the mechanism, so removing the context does not merely make the test above flaky on
    machines fast enough to win the race."""
    import inspect

    from camlab import parallel

    src = inspect.getsource(parallel.map_items)
    assert 'get_context("spawn")' in src, "the pool is back on the platform default start method"
    assert "mp_context" in src, "the context is created and not passed to the executor"
