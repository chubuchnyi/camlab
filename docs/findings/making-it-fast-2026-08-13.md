# Making it fast: what worked, what did not, and two numbers I got wrong

Measured 2026-08-13, prompted by a question about Rust, threads and GPUs, and by the operator's note
that **the current clip lengths are not the target** — long video and eventually a live stream are.

That last point sets the bar. A 90-minute match at 25 fps is **135 000 frames**. At the day's
starting cost of 222 ms a frame, the paint detection alone is **8.3 hours**; real time needs 40 ms.

## Where the time actually was

Profiled `frame_residual` on `broadcast` at 1920×1080, interleaved so background load cancels:

| | |
|---|---|
| a whole score | 463 ms |
| decode + `paint_masks` | **456 ms — 98 %** |
| the camera-dependent remainder | **7 ms** |

And by `cProfile`: `paint_masks` 80 % of the total, of which `ridge_map` 42 % and `thin` 34 %.

## What worked

**Cache the paint per frame — 36.8×.** It depends only on the frame and `frame_residual` recomputed
it every call, so scoring one frame against N cameras re-detected the same pixels N times.
`paint.py` already carried a `FrameEvidence` dataclass whose docstring says "built once and reused
across every ICP round"; nothing used it.

| | before | after |
|---|---|---|
| one frame, first call | 453.9 ms | — |
| one frame, again | — | **12.3 ms** |
| `bench_bootstrap_gates`, one anchor | 3177 s | **87 s** |
| `polish_camera`, one clip | 27 s | **1 s** |

Bounded at four entries: an entry is a full-resolution distance map plus a surface mask, ~12 MB at
1920×1080, and every search loop here hammers one frame at a time. Keyed on path, size and mtime so
a re-ingest invalidates it.

**Thin the set pixels, not the frame — 17.5×.** A frame is 2 Mpx and its paint about 20 000 of them.
Zhang-Suen only ever deletes pixels that are already set, so the whole-image formulation did a
hundred times the arithmetic it needed. Bit-for-bit identical output on every clip.

| | | |
|---|---|---|
| `broadcast` | 106.9 → **6.1 ms** | 17.5× |
| `g14604660` | 94.8 → **5.3** | 17.7× |
| `CRO_MOR_194948` | 96.2 → **5.6** | 17.0× |
| `fan` | 28.7 → **2.8** | 10.1× |

Most of it is in *carrying* the working set rather than rescanning: `flatnonzero` over 2 Mpx each
pass gives back 33 ms of the 6. It is correct because thinning never turns a pixel back on, which
is pinned by an idempotence test.

**Stop reallocating in `ridge_map` — 2.1×.** Twelve scale-and-direction combinations each built four
fresh full-frame arrays: 24 allocations of 2 Mpx a call. Padding once and taking views costs
nothing. Bit-identical.

`paint_masks` end to end: **222 ms → 122**. The match figure goes 8.3 hours → 4.6.

## What did not work, with the numbers

**Process parallelism. Refuted.** Scoring 60 frames, each worker pinned to one OpenCV thread:

| workers | wall | cpu | cores busy |
|---|---|---|---|
| 1 | 16.6 s | 19.8 s | 1.2 |
| 2 | **14.0** | | | 
| 4 | 16.9 | | |
| 8 | **16.8** | **130.3** | **7.8** |
| 14 | 19.6 | | |

Eight cores genuinely busy, eight times the CPU, identical wall clock. **Memory bandwidth, not
compute** — and `paint_masks` says so directly, costing *more* per pixel as the frame grows: 64, 76,
107 ms/Mpx at 0.1, 0.5 and 2.1 Mpx, because it falls out of cache. `default_workers()` is 2, the
measured knee, and the harness stays for when the ceiling lifts.

**Parallelising SIFT. Refuted, and it corrected a repo claim.** `measure_pairs` looked like the
expensive half; across processes it got *slower*, 10.4 → 11.2 s. OpenCV already threads its own
operators and was using **10.8 cores**; `cv2.setNumThreads(1)` takes the same call from 12.7 s to
38.4. So the register's *"one core is the requirement — 342 ms on one thread against 324 on
sixteen"* was reading the Python half of a job whose OpenCV half was already spread over ten cores.

**The sparse trick, applied twice.** It made `thin` 17× faster and `ridge_map` **3× slower**.
`val >= RIDGE_MIN_V` covers 62–98 % of the frame, so there is nothing to skip, and fancy indexing
gives up the contiguity the dense version runs on. Sparsity is a property of the data, not a
technique.

**Reduced-resolution paint in the bootstrap.** The option is real and measured — at 0.25 the paint
is 15× faster and costs +1.2 to +2.4 px with the marking count unchanged — but in the bootstrap it
buys **nothing**: 389.5 s at full resolution against 380.0 s at 0.25. The cache had already removed
that cost, and what remains is LM refits against detected lines, which never touch the paint. It
also returned the half-turn twin rather than the right camera. Kept as a parameter, default full,
documented as for searching and never for a verdict.

## Two numbers I got wrong, and how they were caught

**"10× headroom on `ridge_map`."** I compared our function against a *different* function. A single
`MORPH_TOPHAT` is 10 ms against 109, but a top-hat asks "brighter than the neighbourhood" once and
`ridge_map` asks a directional question twelve times with a turf condition on each. Written out as
morphology exactly — a max over two points is a dilation by a two-point element, turf-on-both-sides
is an erosion by the same one — it is bit-identical and comes out 1.1–2.2×, because `cv2.dilate`
with a 15×15 kernel holding two set points still walks all 225. The honest ceiling is ~2×.

**Worst lines of 684 to 1381 px** from the first reduced-resolution probe. Absurd, so the instrument
was suspect and not the idea: I had resized the distance *map*, and `centreline_pixels` takes the
pixels where the transform is exactly zero, which interpolation destroys. Scaling the **spine's
coordinates** instead gives the real answer. The difference between nonsense and a usable trade was
which of the two objects gets stretched.

## Where this leaves the target

Rust is not the lever: the workload is memory-bound, a compiled language buys fusion, and OpenCV's
primitives are already fused — measured at the same 1.1–2.2× as simply not reallocating. A GPU would
help, its bandwidth being the thing this is short of, and it costs the README's "runs anywhere, no
GPU". Neither is worth doing before the remaining 122 ms is understood: it is ~60 unavoidable passes
over the frame plus two distance transforms, and getting past it means **changing what is asked**,
not how it is computed.
