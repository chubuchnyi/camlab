# Making it fast again: the chain is 1.3–1.8× and four of the last day's conclusions were wrong

Measured 2026-08-16 on the same laptop (i7-11850H, 16 threads, no GPU), against
`docs/findings/making-it-fast-2026-08-13.md`, which is the only performance work this repo had
done and which this doc contradicts in four places.

**The headline.** Three clips, every stage, base commit `066b7a9` against this branch, **all six
runs taken in one sitting** — see the warning about that below, which cost this document its first
set of numbers:

| clip | frames × size | segments/frame | before | now | |
|---|---|---|---|---|---|
| `broadcast` | 60 × 1920×1080 | 9 | 119.7 s | **70.6 s** | 1.70× |
| `CRO_MOR_194948` | 120 × 1920×1080 | 12 | 278.8 s | **156.5 s** | 1.78× |
| `fan` | 120 × 1080×608 | 7 | 188.6 s | **142.0 s** | 1.33× |

**Every number the chain reports is unchanged on all three** — `broadcast` scores across
7.24 / 4.32 / 4.27 px through the stages, worst line 6.81 / 4.00 / 3.88, worst spot
11.98 / 10.50 / 10.43, 60/60 frames at a median focal of 4201.9 px; `CRO_MOR_194948` 120/120 at
5962.7; `fan` 120/120 at 3001.8. The camera is bit for bit the one that was there before.

`fan` gets a third of what `CRO_MOR_194948` gets, and the spread is the useful part. `fan` is a
third of the pixels, so the paint stage is a smaller share of it, and this run is 97 s of 142 in
self-heal — SIFT, which is `measure_pairs` re-run per repaired frame in a process that cannot see
the descriptors `solve_carry` computed for the same frames. The stages this work touched move
1.3–2.4× on all three clips. The stage it did not touch is now two thirds of `fan`.

## The first warning, because it invalidated this document's first draft

**The same base commit measures 155.3 s and 119.7 s on the same machine on the same clip** — a
30 % spread — depending on what else was running. Every number in the first version of this file
came from timings taken over two hours as each change landed, and the machine's load moved from
3.8 to 1.6 across them. That table read as a progression from 155.3 s to 70.1 s, a 2.22×, and the
real figure is 1.70×. **A stage-by-stage progression assembled across sessions is not a
progression, it is a record of the machine's mood**, and the only fix is to re-run every point in
one sitting, which is where the table above comes from:

| `broadcast`, one session | total |
|---|---|
| `066b7a9`, the base | 119.7 s |
| the ridge map factored, `_turf` in `inRange` | 95.1 |
| the normal walk vectorised | 88.8 |
| `line_errors` stops rebuilding the pitch | 79.2 |
| `compare_line` stops recomputing its caller's unit vectors | 73.6 |
| the normal walk in blocks, dropping finished samples | 70.6 |
| the candidate loop vectorised | 71.7 — see §6, it is a wash HERE |

Every bench in `scripts/` prints `getloadavg()` and says so above 1.0. That is not decoration.

## The second warning: cProfile ranks by call count as much as by cost

cProfile said `compare_line` was **259 331 calls and 9.8 s of a 40.3 s `shared centre` stage**.
Vectorising it away — removing all 259 331 calls — changed that stage by **nothing measurable** on
`broadcast`, and `line_errors` itself by 0.685 → 0.698 ms.

cProfile adds roughly a microsecond of bookkeeping to every call it observes, so a function called
a quarter of a million times a stage is charged a second or two that does not exist outside the
profiler — and so are its callees, which is why `np.linalg.norm` appeared at a million calls. **A
profile is trustworthy for ranking functions with similar call counts and misleading across them.**
The fix is not to stop using it but to confirm with a wall clock on the function itself, which is
`scripts/bench_line_errors.py`.

The same profile was right about `straight_markings` (6300 calls, 5.1 s) and about the paint stage,
and both held up end to end. It was wrong by roughly an order of magnitude about the one function
in the list with a six-figure call count.

## The third thing to say: none of the 2026-08-13 numbers had a script

Every accuracy finding in this repo names a bench in `scripts/` that reproduces it. The
performance day names none — there was no timing harness anywhere in `scripts/` or `tests/`, and
`git log --diff-filter=A` says there never had been. That is why four of its conclusions could sit
unchallenged for three days while three of them were stale within one.

Nine land with this work, and they are the durable part of it:

| | |
|---|---|
| `bench_paint_breakdown.py` | the paint stage split to every primitive, **calling the shipped functions** |
| `bench_ridge_formulations.py` | four formulations of the ridge map, agreement checked at eleven thresholds |
| `bench_residual_warm.py` | the cold score, the warm score, and the normal walk's share of it |
| `bench_line_errors.py` | `line_errors` on a wall clock, with no profiler attached — see the second warning |
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

**And then it went too far the other way.** One pass over all 161 offsets for every sample is its
own waste: a sample sitting on its own paint reaches its minimum at the first offset and is
finished at the second, and on `broadcast` two thirds of the columns are done before `t` reaches
1 px. The walk now goes in geometrically growing blocks — 4, 8, 16, 32, 64, 128 — dropping the
samples that are finished after each. Geometric because neither end may pay for the other: a fixed
small block costs forty Python trips on the rays that really do run the whole 40 px, and that is
not a rare case, it is the direction pointing AWAY from the marking, which is half of every call.

| clip | walk before | walk now | | warm before | warm now | |
|---|---|---|---|---|---|---|
| `fan` | 11.2 ms | **1.3** | 8.6× | 12.1 ms | **2.1** | 5.8× |
| `broadcast` | 10.9 | **1.3** | 8.4× | 11.8 | **2.1** | 5.6× |
| `g11710897` | 10.5 | **2.1** | 5.0× | 11.5 | **2.9** | 4.0× |
| `CRO_MOR_194948` | 11.5 | **1.6** | 7.2× | 12.2 | **2.5** | 4.9× |

Both compactions are exact: a finished column's answer never changes again — that is what the old
loop's `~done &` guard said — and a carried running minimum is exact because a minimum is
associative. The old loop's `if done.all(): break` never fired on a real frame, because some sample
always fails to find paint; dropping columns rather than waiting for all of them is what that guard
was reaching for.

`tests/test_across_on_normal.py` pins the thing that matters here: **the block size is not part of
the answer.** `(1, 1)` checks every offset one at a time, `(400, 400)` does all 161 in one block
with no compaction at all, and three sizes between; all five must give the floats the original loop
gave. A carried minimum lost at a boundary, or an `at` attributed to the wrong block, can hide from
a single fixed size.

**`bench_residual_warm.py` had to be corrected to produce that table**, and the correction is the
lesson. It fed the walk random points on the playing surface with random directions — a far harder
distribution than a solve ever meets, since real normals point ACROSS real markings and most rays
find paint in the first pixel. Once the walk gained an early exit, that synthetic set reported it
as costing **167 % of the whole score it is part of**, which is the absurdity that showed it. It
now captures the arguments the real `frame_residual` passes and times those. An instrument that
invents its own input measures the input.

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

`line_errors` itself, timed with a wall clock rather than read off a profile:

| clip | segments | before | memo | + hoists | + vectorised (§6) |
|---|---|---|---|---|---|
| `broadcast` | 9 | 1.538 ms | 0.902 | **0.689** | 0.698 |
| `fan` | 7 | 1.811 | 1.164 | **0.864** | 0.877 |
| `CRO_MOR_194948` | 12 | 2.561 | 1.768 | 1.285 | **0.985** |

## 5. The candidate loop vectorised: nothing on two clips, 1.10× on the chain of a third

The inner loop compares one projected marking against every detected segment, and it was
`compare_line` 259 331 times a stage. Writing it once over N segments — `_candidates` — is the
obvious move, and the honest answer is that it depends entirely on N, which is 7 to 12 here:

| clip | segments/frame | `line_errors` loop | vectorised | whole chain |
|---|---|---|---|---|
| `fan` | 7 | 0.859–0.882 ms | 0.877–0.911 | not measurable |
| `broadcast` | 9 | 0.685–0.707 | 0.698–0.725 | 70.6 s → 71.7, i.e. a wash |
| `CRO_MOR_194948` | 12 | 1.279–1.322 | **0.985–1.013** | **167.9 s → 153.3, 1.10×** |

Three interleaved rounds each, minimum of 400 calls. Below about ten segments the numpy setup —
the fancy indexing, the broadcast, the `where` — costs what the Python loop cost, and above it the
loop loses. It is kept because it is a real 1.10× on a whole chain at twelve segments and free at
nine, and because segment counts go up when the paint gets better, not down. It is a good example
of the rule this repo already has for the sparse trick: **whether vectorising wins is a property of
the data, not of the technique.**

**And the first version of it was wrong in the last bit.** `(A * B).sum(axis=1)` is the natural way
to write a row-wise dot of 2-vectors and is **not** bit-for-bit `a @ b`: BLAS's two-element dot
fuses its multiply and add and rounds once, and every elementwise form rounds the product and then
the sum. `check_line_errors_equivalence.py` caught it immediately — offsets moved 1e-16 to 9e-14 on
**12 of 14 clips**. That is far below anything measured here and it still had to be fixed, because
`_assign_in_order` decides which segment a marking gets with `best == take`, an exact float
comparison. Probed over 20 000 random pairs:

```
(A * B).sum(axis=1)                        differs
A @ b            (a gemv, for fixed b)     differs
A[:,0]*B[:,0] + A[:,1]*B[:,1]              differs
np.einsum('ij,ij->i', A, B)                differs
np.matmul(A[:,None,:], B[:,:,None])        equal on every pair
(M, 2, 2) @ u    (a stack of gemvs)        equal on every pair
```

`_rowdot` is that fifth line and `tests/test_rowdot.py` pins it — including the negative half, that
the other four really do differ, so the next reader who finds `_rowdot` baroque meets a failing
test rather than a diff.

## 6. "Process parallelism. Refuted." — the direction was right, the number is now 2.8× not 1.0×

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

1. **SIFT is the biggest single thing in the chain now** — 11.0 s of a 31.2 s `carry` on
   `broadcast`, and 97 s of `fan`'s 142. Its own descriptor cache was checked and is correct (118
   `feats()` calls, 60 `detectAndCompute`, one per frame), so this is not recomputation *within* a
   stage; it is the cost of the method, and OpenCV already spreads it over ten cores. What IS
   recomputation is across stages: `solve_selfheal` runs `measure_pairs` again, in a different
   process, on frames `solve_carry` already described. A descriptor cache on disk is the shape of
   the fix, and on `fan` it is worth most of a stage that is two thirds of the run.
2. **The four stage scripts call `paint_masks(cv2.imread(...))` directly**, bypassing the evidence
   cache, and `smooth_camera` walks the clip twice with a four-entry cache. The pattern that fixes
   it is `frame_evidence_cached` plus `hold_frames`, both already in the repo.
3. **The per-frame loops are serial.** See §6: the ceiling is now 2.8×, not 1.0×, and the thing
   that would cash it in is those loops rather than `default_workers()`.
4. **`_assign_in_order` is a pure-Python DP** over (markings + 1) × (segments + 1) per family, run
   about 105 times per LM refit. Not measured on its own yet; it is what is left inside
   `line_errors` after §4 and §5.
5. **The paint stage is 34 ms and about half of it is `distanceTransform` and `thin`.** Both are
   OpenCV or already sparse. Getting past this means changing what is asked, which was the 2026-08-13
   document's closing sentence and is still true — it was just three functions early.

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
