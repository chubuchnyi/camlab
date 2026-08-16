"""Does the per-frame work scale across processes? — and which half of it does not.

`parallel.py` and `docs/findings/making-it-fast-2026-08-13.md` both carry the same conclusion:
scoring 60 frames takes 16.6 s on one worker and 16.8 s on eight, with 130.3 s of CPU and 7.8 cores
genuinely busy, therefore *"memory bandwidth, not compute"*, therefore `default_workers()` is 2.

Three things about that measurement are worth re-doing rather than repeating.

**It never separated the decode from the paint.** The job each worker ran was decode *and*
`paint_masks` — the doc's own profile says the pair is 456 ms of a 463 ms score — and a JPEG decode
is `libjpeg` and page cache, not a numpy pass. Eight workers burning eight times the CPU for no
wall-clock gain is the signature of a bandwidth wall AND the signature of eight processes queueing
on the same files. This runs three jobs — `decode`, `paint` and `evidence` (decode + paint + the
k-d tree, the real unit of work) — so the two can be told apart.

**The pool's startup was inside the stopwatch.** `spawn` starts a fresh interpreter per worker and
each one imports numpy, cv2 and scipy: about a second of CPU, times the worker count, charged to a
four-second job. The first draft of this script had the same fault and reported 8.9 "cores busy" on
a *decode* — which is nonsense, and the nonsense is what showed it. The pool is created and warmed
before the clock starts here. `resource.getrusage(RUSAGE_CHILDREN)` has the same trap in reverse:
it only counts children that have already EXITED, so with a live pool it reports the teardown of
the previous configuration. Each worker times its own CPU with `time.process_time()` and reports
it, which is the only figure that means what "cores busy" wants it to mean.

**The workload it measured no longer exists.** That table was taken when `ridge_map` moved about
380 bytes per pixel per frame; the factored uint8 version moves about 115. If the wall was
bandwidth, cutting the traffic threefold should move the knee — and if the knee does not move, the
wall was never bandwidth. Either answer is worth having.

    python scripts/bench_frame_parallel.py broadcast --frames 60 --workers 1,2,4,8,16
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"


def _init(threads: int, src: str) -> None:
    sys.path.insert(0, src)
    import cv2
    if threads > 0:
        cv2.setNumThreads(threads)
    # Pay for the imports here, in the initializer, so the timed region measures the work.
    import scipy.spatial  # noqa: F401

    from camlab.measure import paint  # noqa: F401


def _timed(fn, path):
    t = time.process_time()
    fn(path)
    return time.process_time() - t


def decode(path: str) -> float:
    import cv2
    return _timed(cv2.imread, path)


def paint(path: str) -> float:
    """Decode and paint. Subtracting `decode` from this is the paint stage's own scaling."""
    import cv2

    from camlab.measure.paint import paint_masks

    def job(p):
        bgr = cv2.imread(p)
        if bgr is not None:
            paint_masks(bgr)
    return _timed(job, path)


def evidence(path: str) -> float:
    """The real unit: decode, paint, centreline, k-d tree — what `frame_evidence` does."""
    import cv2
    from scipy.spatial import cKDTree

    from camlab.measure.paint import centreline_pixels, paint_masks

    def job(p):
        bgr = cv2.imread(p)
        if bgr is None:
            return
        dist, _surface = paint_masks(bgr)
        spine = centreline_pixels(dist)
        if len(spine):
            cKDTree(spine)
    return _timed(job, path)


JOBS = {"decode": decode, "paint": paint, "evidence": evidence}


def run(job: str, paths: list[str], workers: int, threads: int, repeat: int):
    """`(best wall, worker cpu at that wall)`, with the pool already up and warm."""
    fn = JOBS[job]
    best = (1e9, 0.0)
    if workers <= 1:
        _init(threads, str(HERE / "src"))
        for _ in range(repeat + 1):                       # +1: the first pass warms
            t = time.perf_counter()
            cpu = sum(fn(p) for p in paths)
            best = min(best, (time.perf_counter() - t, cpu))
        return best

    ctx = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=workers, mp_context=ctx, initializer=_init,
                             initargs=(threads, str(HERE / "src"))) as pool:
        for _ in range(repeat + 1):
            t = time.perf_counter()
            cpu = sum(pool.map(fn, paths, chunksize=1))
            best = min(best, (time.perf_counter() - t, cpu))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--frames", type=int, default=60)
    ap.add_argument("--workers", default="1,2,4,8,16")
    ap.add_argument("--jobs", default="decode,paint,evidence")
    ap.add_argument("--cv2-threads", type=int, default=1,
                    help="threads each worker gives OpenCV; 0 leaves OpenCV alone")
    ap.add_argument("--repeat", type=int, default=2)
    args = ap.parse_args()

    frames = sorted((RUNS / args.clip / "frames").glob("*.jpg"))[:args.frames]
    if not frames:
        raise SystemExit(f"no frames for {args.clip}")
    paths = [str(p) for p in frames]
    # Warm the page cache so the first configuration is not charged for every other one's reads.
    for p in paths:
        with open(p, "rb") as fh:
            fh.read()

    load = os.getloadavg()
    print(f"{args.clip}: {len(paths)} frames   cpu_count {os.cpu_count()}   "
          f"cv2 threads/worker {args.cv2_threads or 'unpinned'}   "
          f"load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; treat every row as an upper bound ***")

    worker_counts = [int(x) for x in args.workers.split(",")]
    for job in args.jobs.split(","):
        print(f"\n  {job}")
        print(f"  {'workers':>8}{'wall s':>10}{'worker cpu':>12}{'cores':>8}{'ms/frame':>11}"
              f"{'speedup':>10}{'efficiency':>12}")
        base = None
        for n in worker_counts:
            wall, cpu = run(job, paths, n, args.cv2_threads, args.repeat)
            base = base if base is not None else wall
            print(f"  {n:>8}{wall:>10.2f}{cpu:>12.1f}{cpu / wall:>8.1f}"
                  f"{wall * 1e3 / len(paths):>11.1f}{base / wall:>9.2f}x"
                  f"{100 * base / wall / n:>11.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
