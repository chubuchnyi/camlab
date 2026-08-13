"""Run per-frame work on several cores, because it is per-frame and there are sixteen of them.

The repo has recorded the state for a while and called it what it is: *"One core is the requirement
— 342 ms a frame on one thread against 324 ms on sixteen, which is noise. Several stages are
parallel across frames and are not parallelised; that is undone work, not a limit."*

**Measure which half before parallelising it.** The obvious target was SIFT, the expensive half of
a carry stage, and parallelising it across processes made things *slower* — 10.4 s serial against
11.2 s on fourteen workers. OpenCV threads its own operators, and it was already doing so:

| on `broadcast`, 60 frames | wall | cpu | cores busy |
|---|---|---|---|
| `measure_pairs` — SIFT, BFMatcher, MAGSAC | 12.7 s | 137.1 s | **10.8** |
| `paint_masks` × 15 | 3.1 s | 4.1 s | **1.3** |
| `measure_pairs` with `cv2.setNumThreads(1)` | 38.4 s | 38.3 s | 1.0 |

So the OpenCV-heavy half is already spread over the machine and a process pool only oversubscribes
it. What is genuinely serial is the numpy-and-Python work — `paint_masks`, the ridge loop, the
thinning — and that is what belongs here.

This also corrects the repo's own line, which read "One core is the requirement — 342 ms a frame on
one thread against 324 ms on sixteen, which is noise". The 342 was already using ten cores inside
OpenCV; what did not move was the Python half.

**And then the part that was left did not parallelise either.** Scoring 60 frames of `broadcast`,
each worker pinned to one OpenCV thread so nothing oversubscribes:

| workers | wall | cpu | cores busy |
|---|---|---|---|
| 1 | 16.6 s | 19.8 s | 1.2 |
| 2 | 15.2 s | | |
| 4 | 16.3 s | | |
| 8 | **16.8 s** | **130.3 s** | **7.8** |
| 14 | 19.6 s | | |

Eight cores genuinely busy, eight times the CPU burned, and the wall clock **identical**. That is
memory bandwidth, not compute — and `paint_masks` confirms it directly, costing *more* per pixel as
the picture grows because it falls out of cache:

| | | |
|---|---|---|
| 1920×1080, 2.1 Mpx | 222 ms | 107 ms/Mpx |
| 960×540, 0.5 Mpx | 39 ms | 76 ms/Mpx |
| 480×270, 0.1 Mpx | 8 ms | 64 ms/Mpx |

`ridge_map` makes 24 full passes over the frame. The cores wait on RAM.

**So `default_workers()` returns 1**, and this module stays as the harness plus the measurement
that says why. What actually helped was removing the work rather than spreading it: caching the
paint per frame is 36.8× on any loop that scores one frame many times, because it does not touch
the memory a second time at all. The lever left is fewer passes over the image, not more cores.

**Order matters against the cache.** `measure/residual.py` caches the paint per frame and that is a
36.8× on any loop scoring one frame with many cameras. Parallelism divides the wall clock of what is
left; caching removes work outright. Cache first, then this, or the cores are spent redoing the same
pixels faster.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import Any


#: Leave two cores for the machine — one for whoever is watching the run and one for the OS. Capped
#: at 16 because past that the frames are usually gone before the pool is warm.
def default_workers() -> int:
    """How many processes to use, unless told otherwise.

    `CAMLAB_WORKERS` overrides it, and `CAMLAB_WORKERS=1` disables the pool entirely — which is the
    thing to reach for when a stack trace from inside a worker is unreadable, or when a profiler
    needs the work in one process.
    """
    env = os.environ.get("CAMLAB_WORKERS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    # One, deliberately. Measured above: eight workers burn eight times the CPU for the same wall
    # clock. Set CAMLAB_WORKERS to try again on a machine with more memory bandwidth, or on a
    # workload that is not 24 passes over a 2 Mpx frame.
    return 1


#: Below this many items the pool costs more than it saves — a process start is tens of
#: milliseconds and the work here is hundreds, so a handful of frames is a wash and a couple is a
#: loss.
MIN_ITEMS_FOR_A_POOL = 6


def map_items(fn: Callable[[Any], Any], items: Iterable[Any], *,
              workers: int | None = None, ordered: bool = True) -> list:
    """`[fn(x) for x in items]`, on several processes when that is worth it.

    `fn` must be importable by name in a fresh interpreter — a module-level function, not a closure
    or a lambda — because that is how it reaches the workers. A closure raises `PicklingError` at
    submit time rather than silently running serially, which is the right way round.

    Falls back to a plain loop for one worker or a short list, so a caller never has to ask.
    """
    todo = list(items)
    n = workers if workers is not None else default_workers()
    if n <= 1 or len(todo) < MIN_ITEMS_FOR_A_POOL:
        return [fn(x) for x in todo]

    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=min(n, len(todo))) as pool:
        if ordered:
            return list(pool.map(fn, todo))
        return [f.result() for f in pool.map(fn, todo)]
