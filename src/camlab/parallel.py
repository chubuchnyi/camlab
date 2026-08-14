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

**So `default_workers()` returns 2** — the measured knee, 1.14× and no waste — and the harness stays
wired for when the ceiling lifts. It will: the ceiling is 24 passes over the frame in `ridge_map`,
and the OpenCV primitive that answers the same question does it in one, measured at 10× there and
20× on `thin`. Cut the traffic and this becomes compute-bound, at which point these workers scale.

Sizing matters more than any of this. A clip here is 40–180 frames; a full match at 25 fps is
**135 000**, which at today's 222 ms a frame is 8.3 hours for the paint alone, and real time needs
40 ms. So the order is: fewer passes first, then cores, then — only if it is still not enough — a
GPU, whose memory bandwidth is the thing this workload is actually short of.

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
    # Two, measured rather than chosen. Scoring 60 frames, three repeats, medians: 16.0 s on one
    # worker, **14.0 s on two (1.14x)**, 16.1 on three, 16.9 on four, 16.8 on six. The ceiling is
    # memory bandwidth, not cores, so past two the extra processes only queue for the same RAM.
    #
    # This is expected to LIFT. The ceiling exists because `ridge_map` makes 24 full passes over
    # the frame; replacing those with the OpenCV primitives that do the same job in one is a
    # measured 10x on that function and 20x on `thin`, and once the traffic is cut the work becomes
    # compute-bound and these workers start to matter. The harness is here early on purpose.
    return max(1, min(2, (os.cpu_count() or 2) - 1))


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

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    # **`spawn`, not the platform default**, which on Linux is `fork` — and under `fork` this pool
    # deadlocks inside the solver.
    #
    # `verdict.judge` is the last thing `solve_carry` does and the only caller of `map_items`, so
    # from the moment `default_workers()` went from 1 to 2 on 2026-08-13 **every solve ended in a
    # hang**. Measured on `g11710897`, one anchor, nothing else changed:
    #
    #     fork, 2 workers    still hung at 3000 s — parent and both children in `futex_do_wait`
    #     spawn, 2 workers   22 s
    #     no pool at all     23 s, and every reported number identical to the spawn run
    #
    # It reads as "this clip is slow", which is why it survived a day and four abandoned runs.
    #
    # **The mechanism is not established.** The obvious candidate — forking a process that has
    # already started OpenCV's threads, so the child inherits mutexes held by threads that do not
    # exist in it — did NOT reproduce on a synthetic probe: cv2 in the parent, cv2 in eight forked
    # children, completes fine. So what is recorded here is what was measured, not a diagnosis, and
    # the probe lives in `tests/test_parallel_pool.py` so the next person starts from a fact.
    #
    # A spawned worker starts a fresh interpreter and re-imports, which is why `fn` has to be
    # importable by name — already required above — and why `MIN_ITEMS_FOR_A_POOL` exists.
    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=min(n, len(todo)), mp_context=ctx) as pool:
        if ordered:
            return list(pool.map(fn, todo))
        return [f.result() for f in pool.map(fn, todo)]
