# Making it fast again: the chain is 1.79× and four of the last day's conclusions were wrong

Measured 2026-08-16 on the same laptop (i7-11850H, 16 threads, no GPU), against
`docs/findings/making-it-fast-2026-08-13.md`, which is the only performance work this repo had
done and which this doc contradicts in four places.

**The headline.** The whole chain on `broadcast` — 60 frames at 1920×1080, same seed, same
machine — goes **155.3 s → 87.0 s, 1.79×**, and every number it reports is unchanged:

| stage | 2026-08-13 | now |
|---|---|---|
| carry | 47.3 s | 31.2 s |
| self-heal | 14.4 | 7.4 |
| shared centre | 53.4 | 27.8 |
| smooth | 21.4 | 10.9 |
| polish | 18.8 | 9.7 |
| **total** | **155.3 s** | **87.0 s** |
| across / worst line / worst spot | 4.27 / 3.88 / 10.43 px | **identical** |
| frames with a focal, median focal | 60/60, 4201.9 px | **identical** |

Three A/B rounds, interleaved old-tree/new-tree so background load falls on both. The old tree's
155.3 s is the README's own "155 s", which is the closest thing to a calibration this had.

## The first thing to say: none of the 2026-08-13 numbers had a script

Every accuracy finding in this repo names a bench in `scripts/` that reproduces it. The
performance day names none — there was no timing harness anywhere in `scripts/` or `tests/`, and
`git log --diff-filter=A` says there never had been. That is why four of its conclusions could sit
unchallenged for three days while three of them were stale within one.

Six land with this work, and they are the durable part of it:

| | |
|---|---|
| `bench_paint_breakdown.py` | the paint stage split to every primitive, **calling the shipped functions** |
| `bench_ridge_formulations.py` | four formulations of the ridge map, agreement checked at eleven thresholds |
| `bench_residual_warm.py` | the cold score, the warm score, and the normal walk's share of it |
| `bench_frame_parallel.py` | per-frame scaling across processes, decode and paint measured separately |
| `bench_chain.py` | the whole chain per stage, **against a copy** of the run directory |
| `bench_surface_resolution.py` | a refutation: a 4× on `_surface` that must not ship |
| `check_paint_equivalence.py` | old tree vs new tree, every array, every clip in `runs/` |
| `check_line_errors_equivalence.py` | old tree vs new tree, every field of every `LineError` |

Two habits are in them on purpose. Every bench prints the **load average** and says so when the
machine is busy, because a number taken under load is not comparable with one that was not, and
none of the 2026-08-13 tables record it. And `bench_chain.py` **never writes to the run directory
it is pointed at** — it copies the clip and sets `CAMLAB_RUNS` — because a benchmark that
overwrites the measurements it is being compared against is the run-directory landmine with a
stopwatch attached.

`bench_paint_breakdown.py` earned its own rule the hard way. Its first draft carried a private copy
of `ridge_map`'s loop, and so cheerfully reported the old cost of a function that had already been
rewritten. A stale run directory, in a measuring instrument. It times the shipped functions now.

---

## 1. "The honest ceiling on `ridge_map` is about 2×" — wrong by 5×. It is 10.9×.

The argument was: a `MORPH_TOPHAT` asks "brighter than the neighbourhood" once and `ridge_map` asks
a directional question twelve times with a turf condition on each, so there is nothing to win.

That is an argument about how many **questions** are asked, and it is right about that — the count
is unchanged below. It is not an argument about how many **passes over the frame** the questions
cost, and on a workload the same document called memory-bound, the passes are the only thing that
was ever going to matter.

The algebra factors. A maximum of differences sharing a left term is that term minus a minimum:

```
max over (d, dir) of [ val - max(v₊, v₋) ]   =   val - min over (d, dir) of max(v₊, v₋)
```

and **255 standing in for a non-turf neighbour** makes that combination's `max` the largest a value
can be, so the `min` discards it — exactly what the `-1000` fill was for, without the mask, the
`~both` temporary or the boolean scatter. Twelve subtractions become one. Twenty-four full-frame
bool allocations become none. And the whole inner loop then lives in 0..255, so it runs in
**uint8** rather than int16.

| clip | before | after | |
|---|---|---|---|
| `broadcast` 1920×1080 | 32.4 ms | **3.0** | 10.9× |
| `g11710897` 1080×1920 | 41.4 | **3.1** | 13.3× |
| `fan` 1080×608 | 6.3 | **0.9** | 7.3× |

The raw array is not bit-identical — where no combination passes the turf test the old code wrote
`-1000` and this writes `val - 255`, which is in [−255, 0]. Every consumer thresholds at a strictly
positive value (`RIDGE_CONTRAST` is 16, `AUTO_COARSE` starts at 12 with a fine step flooring at 6,
and the adaptive path clips to 0 first), so the two agree on every question anyone asks.
`bench_ridge_formulations.py` checks that at eleven thresholds rather than asserting it.

**The single hottest instruction in the old paint stage was `side[~both] = -1000`** — a hidden
full-frame allocation and a masked scatter, twelve times a frame, and the docstring above it said
the function had "stopped allocating".

## 2. Two stages costing 23 % of the paint were never named at all

The 2026-08-13 account of `paint_masks` is `ridge_map` 42 %, `thin` 34 %, "the rest". `_turf` and
`_surface` are in the rest, and they were 10.5 and 5.3 ms of a 65.6 ms stage.

`_turf` read three **strided** views of the HSV image — `hsv[..., 0]` has a stride of three, so
every comparison walks the interleaved buffer taking one byte in three — and built about seven
full-frame temporaries from them. `cv2.inRange` asks the identical question in one pass in the
layout the image is already in, and `cv2.calcHist` replaces the boolean gather feeding
`np.bincount`. **11.8 → 4.9 ms on `broadcast`, 2.2–2.5× over four clips, mask bit-identical.**

`_surface` is 5 ms of two rectangular closes at 45×45 and 61×61, on a mask whose only question is
"is this pixel on the pitch" — no sub-pixel meaning, so quarter resolution looked free. **It is
not, and this is the measurement that says so:** the reduced answer disagrees with the full one on
**8.3 % of `CRO_MOR_194948`'s pixels**, and disagrees *more* at half scale than at quarter, which
is the signature of a different connected component winning `CC_STAT_AREA` rather than a blurred
boundary. The surface mask decides which segments are on the pitch at all. Three of the four clips
move 0.1–1.5 % and would have shipped it. Kept as `bench_surface_resolution.py`, refuted.

**`paint_masks` end to end: 65.6 → 34.2 ms on `broadcast`, 87.8 → 40.6 on `g11710897`.**

## 3. "The camera-dependent remainder is 7 ms" — it is 12–13, it is 95 % of a warm score, and it was the wrong thing to ignore

2026-08-13 profiled a **cold** score: 463 ms, of which decode and `paint_masks` were 456, and spent
the day on the 456. That is the right call for a chain that scores each frame once.

It is the wrong number for almost everything else this repo does. Once the paint is cached — which
was that same day's largest win — every search loop pays the camera-dependent half over and over
and the paint half exactly once. A bootstrap anchor scores ~7000 cameras against one frame. An LM
refit issues about 105 objective evaluations per frame. The polish pass sweeps 6–8 candidates.

Measured with the paint cached and the camera nudged so nothing can be memoised on it:

| clip | warm score | the walk | share |
|---|---|---|---|
| `fan` | 12.0 ms | 11.5 ms | 96 % |
| `broadcast` | 12.2 | 12.1 | 99 % |
| `g11710897` | 12.0 | 11.4 | 95 % |
| `CRO_MOR_194948` | 13.2 | 12.5 | 95 % |

`_across_on_normal` was 161 Python trips per direction, each issuing about fourteen numpy calls
over a 300-element array: **2.3 KB of data through the interpreter, 322 times a score.** It is the
one part of the hot path the memory-bandwidth thesis cannot see, because it is not a bandwidth
problem — it is interpreter dispatch.

The walk is over `t` now rather than a loop over `t`: the running minimum **is**
`np.minimum.accumulate`, and both "where did it stop" and "where was the minimum reached" are
`argmax` over a boolean, because a cumulative minimum is non-increasing. Same arithmetic per
element, same dtype, same order, so **bit for bit** the same answer — pinned in
`tests/test_across_on_normal.py` against the loop it replaced, on eight seeds of adversarial
synthetic rays (parallel stripes with holes, so a rewrite taking the *global* minimum instead of
the *first* one fails) and on real paint.

**Warm score 12.0–13.2 → 2.9–3.8 ms, 3.2–4.1×.** The old loop's `if done.all(): break` never fired
on a real frame: some sample always fails to find paint.

## 4. What the profile says once the paint is not the answer

With the paint halved and the walk vectorised, `line_errors` — correspondence, the thing an LM
refit actually minimises — is **38 % of carry, 46 % of polish, 51 % of shared centre**. Nothing in
it was slow. All of it was repeated:

* `straight_markings()` takes **no arguments**, reads only the pitch constants, and rebuilt all 23
  polylines to hand back the same list — 6300 calls, **5.1 s of a 42.7 s carry stage**.
* `np.cos(np.radians(match_angle_deg))` sat **inside** the per-marking, per-segment loop, running
  on all 141 000 comparisons a stage for a value that depends on nothing in it.
* `compare_line` recomputed the model's unit direction (twice — once in itself, once in
  `_overlap`), the model's left normal, and the found segment's unit direction, all three of which
  its caller already had. `np.linalg.norm` was called **1 044 965 times** in one shared-centre run.
* the marking loop rebuilt `np.column_stack([world, np.ones(2)])` and re-derived `world_family`
  every evaluation — 209 000 allocations a stage for seventeen fixed 2×3 arrays.

All exact. `check_line_errors_equivalence.py` compares every field of every `LineError` — the
matched segment, offset, angle, overlap and both endpoints — on four frames a clip and **five
cameras a frame**, one solved and four deliberately wrong, because a refit spends almost all of its
evaluations off the optimum and that is where agreement has to hold too. **14 of 14 clips, 20 of 20
combinations each, identical.**

## 5. "Process parallelism. Refuted." — the direction was right, the number is now 2.8× not 1.0×

The 2026-08-13 table scored 60 frames at 16.6 s on one worker and 16.8 on eight, with 7.8 cores
busy, and concluded memory bandwidth. Two faults in the instrument and one in the workload:

**It never separated the decode from the paint.** Eight workers burning eight times the CPU for no
wall-clock gain is the signature of a bandwidth wall *and* the signature of eight processes
queueing on the same files, and the job measured was decode-and-paint.

**The pool's startup was inside the stopwatch.** `spawn` starts a fresh interpreter per worker,
each importing numpy, cv2 and scipy. This script's own first draft had the same fault and reported
**8.9 "cores busy" on a decode** — nonsense, and the nonsense is what showed it.
`resource.getrusage(RUSAGE_CHILDREN)` has the trap in reverse: it counts only children that have
already **exited**, so with a live pool it reports the previous configuration's teardown. Each
worker times its own CPU with `time.process_time()` here.

**And the workload changed.** `ridge_map` moved ~380 B/px on 2026-08-13 and moves ~115 now.

With the pool warm and the two halves separated, on `broadcast`, 60 frames, one OpenCV thread per
worker:

| workers | decode | paint | evidence (decode + paint + k-d tree) |
|---|---|---|---|
| 1 | 0.61 s | 3.75 s | 4.65 s |
| 2 | 0.33 (1.86×) | 2.31 (1.62×) | 2.49 (1.87×) |
| 4 | 0.21 (2.95×) | 1.73 (2.17×) | **1.75 (2.66×)** |
| 6 | 0.16 (3.83×) | **1.56 (2.40×)** | 1.67 (2.79×) |
| 8 | 0.15 (4.08×) | 1.66 | **1.65 (2.82×)** |
| 16 | 0.18 | 1.67 | 1.77 |

**The decode scales nearly linearly to four workers.** It is `libjpeg`, it is compute, and it was
never the bandwidth-bound half — it was simply never measured on its own.

**The paint's own diagnosis is confirmed, and it is now measured rather than inferred**: worker CPU
for the identical work goes 3.7 s at one worker to 19.1 s at sixteen. The same code doing the same
job burns five times the CPU when the memory system is contended. That is a bandwidth wall, stated
in the only currency that says so.

**But the wall is at 2.8×, not 1.0×.** `parallel.py` predicted exactly this — *"this is expected to
LIFT… once the traffic is cut the work becomes compute-bound and these workers start to matter"* —
and it has. The reasoning was right; the number it ships is stale.

**And it does not matter yet, which is the useful part.** Running the whole chain at
`CAMLAB_WORKERS` 2, 4 and 6 gives 94.5, 92.7 and 93.2 s — inside the noise. `map_items` has exactly
one caller, `verdict.judge`, and `judge` is not where the time is. **Raising `default_workers()`
on the strength of the microbenchmark above would be a change with no measured effect on anything
a user waits for.** It is left at 2. The work that would cash the 2.8× in is parallelising the
per-frame paint loops in the four stage scripts, and that is not done here.

---

## What is left, in order

1. **`compare_line` and `_overlap` are still 259 000 Python calls a stage** on 2-vectors. The
   redundant work is gone; what remains is one call per (marking, segment) pair, and it wants to be
   one vectorised call per marking over all segments. Worth ~10 s of a 28 s shared-centre stage.
2. **SIFT is 11.0 s of a 31.2 s carry** — 60 frames at 183 ms each, and OpenCV already spreads it
   over ten cores. Its descriptor cache was checked and is correct (118 `feats()` calls, 60
   `detectAndCompute`). It is not recomputation; it is the cost of the method. It is also computed
   afresh in `solve_selfheal`, in a different process, for frames `solve_carry` already did.
3. **`_across_on_normal` walks all 161 offsets for every sample**, and most samples find their
   paint in the first two or three. Chunking `t` and dropping finished columns is exact and
   probably another 3–5× on the warm score.
4. **The four stage scripts call `paint_masks(cv2.imread(...))` directly**, bypassing the evidence
   cache, and `smooth_camera` walks the clip twice with a four-entry cache. The pattern that fixes
   it is `frame_evidence_cached` plus `hold_frames`, both already in the repo.
5. **The per-frame loops are serial.** See §5: the ceiling is now 2.8×, not 1.0×.

## Corrected in the repo by this work

* `README.md` — *"One core is the whole requirement… 342 ms on one thread against 324 on sixteen"*.
  Refuted by `making-it-fast` on the day it was written, corrected in `landmines.md` and in
  `archive/`, and still shipped in the entry-point document three days later. The corrected version
  of a live fact was being kept in the archive, whose own README says not to read it as current.
* `parallel.py` — the retracted **10×** and an unsourced **20× on `thin`** were still the stated
  justification for keeping the process-pool harness. Replaced with what was measured.
* `parallel.py` and `landmines.md` — *"`ridge_map` makes 24 full passes over the frame"* against
  `making-it-fast`'s *"~60 unavoidable passes"*. The old loop made about 100 counting temporaries
  and scatters; the new one makes 26, so the sentence is finally true and now says which version it
  is about.
* `landmines.md` — *"`default_workers()` returns 1 on purpose"*. It returns 2, and has since
  2026-08-13.
* `paint.py` — `thin`'s *"costs about 20–50 ms a frame, which is 1.5× the residual"*. It is 5.5 ms
  and about 8 % of the stage, and that sentence was pointing optimisation attention at the wrong
  function.
* `README.md` / `STATUS.md` — *"89 tests"*. There are 181.
