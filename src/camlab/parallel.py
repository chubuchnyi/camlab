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

**And then the part that was left did not parallelise either — and that stopped being true on
2026-08-16.** Scoring 60 frames of `broadcast`, each worker pinned to one OpenCV thread so nothing
oversubscribes, the August table read 16.6 s on one worker and 16.8 on eight with 7.8 cores busy:
eight times the CPU for an identical wall clock. Re-measured with the pool created and **warmed
before the clock starts**, with each worker timing its own CPU, and with the decode separated from
the paint:

| workers | decode | paint | evidence — decode + paint + k-d tree |
|---|---|---|---|
| 1 | 0.61 s | 3.75 s | 4.65 s |
| 2 | 0.33 (1.86×) | 2.31 (1.62×) | 2.49 (1.87×) |
| 4 | 0.21 (2.95×) | 1.73 (2.17×) | **1.75 (2.66×)** |
| 6 | 0.16 (3.83×) | **1.56 (2.40×)** | 1.67 (2.79×) |
| 8 | 0.15 (4.08×) | 1.66 | **1.65 (2.82×)** |
| 16 | 0.18 | 1.67 | 1.77 |

Three things in that the August table could not say. **The decode scales nearly linearly to four
workers** — it is `libjpeg`, it is compute, and it was never the bandwidth-bound half; it was
simply never measured on its own. **The paint's bandwidth wall is real and is now measured rather
than inferred**: worker CPU for the identical work goes 3.7 s at one worker to 19.1 s at sixteen,
which is the same code burning five times the CPU because the memory system is contended. And
**the wall is at 2.8×, not 1.0×**, because `ridge_map` moved ~380 bytes per pixel then and moves
~115 now.

Two traps in measuring this, both of which this file's first attempt fell into. `spawn` starts a
fresh interpreter per worker and each imports numpy, cv2 and scipy — about a second of CPU each,
charged to a four-second job if the pool is created inside the stopwatch; the draft reported
**8.9 "cores busy" on a decode**, which is nonsense, and the nonsense is what showed it. And
`resource.getrusage(RUSAGE_CHILDREN)` counts only children that have already **exited**, so with a
live pool it measures the previous configuration's teardown. `scripts/bench_frame_parallel.py` is
the harness.

**`default_workers()` still returns 2, and deliberately.** Raising it to 4 or 6 and running the
whole chain gives 92.7 s and 93.2 s against 94.5 — inside the noise — because `map_items` has
exactly one caller, `verdict.judge`, and `judge` is not where the time is. The 2.8× is real and is
not reachable from here: cashing it in means parallelising the per-frame paint loops in the four
stage scripts, which is undone work rather than a limit.

Sizing matters more than any of this. A clip here is 40–180 frames; a full match at 25 fps is
**135 000**, which at 34 ms a frame is 1.3 hours for the paint alone, and real time needs 40 ms.
So the order is: fewer passes first, then cores, then — only if it is still not enough — a GPU,
whose memory bandwidth is the thing this workload is actually short of.

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
    # Two, and the reason changed on 2026-08-16 without the number changing. It used to be the
    # measured knee of a workload that stopped scaling past 1.14×. That knee has moved: the
    # per-frame unit now gets 2.66× on four workers and 2.82× on eight (table above).
    #
    # It stays at 2 because raising it buys nothing HERE. `map_items` has exactly one caller —
    # `verdict.judge` — and running the whole chain at 2, 4 and 6 workers gives 94.5, 92.7 and
    # 93.2 s, which is inside the noise. Spending the 2.8× means parallelising the per-frame paint
    # loops in the four stage scripts, and until that is done more workers only cost memory.
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
