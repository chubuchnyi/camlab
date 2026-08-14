# Detail moved out of STATUS.md, 2026-08-14

`STATUS.md` is the cold start and had grown to 282 lines against an agreed ~150. These four
sections are the ones that restate a docstring or a findings doc rather than saying what is
true now, so they live here and STATUS points at them. Nothing was deleted.

## The pipeline, and why each stage is there

1. **anchors** — EVERY frame the operator has aimed, not one. The pipeline passed `--anchor 0`
   while `solve_carry` had always accepted a list, so eleven of `g11710897`'s twelve aims were
   discarded on every press of the solve button. And they are ranked by **markings first, error
   second**: a worst-line number is a max over the markings a frame scores, so 22.51 px on 7 and
   16.61 px on 3 are not comparable, and ranking them by the number alone is what kept that clip
   unsolvable.
2. **carry** (`solve/carry.py`) — take the camera to the next frame through the image-to-image
   homography, then refit. Copying instead loses the track in three frames, because the operator
   zooms: the focal runs 3476 → 5404 over 24 frames of `fan`.
3. **self-heal** (`scripts/solve_selfheal.py`) — find the frames the chain lost, re-seed each from
   its nearest good neighbour on **both** sides, offering a plain copy as well as a carry, and keep
   whichever the paint prefers. 97 → 120 of 120 in one round. All four candidate kinds win
   somewhere: copy+fit 8, carry+fit 7, copy 7, carry 2.
4. **shared centre** (`scripts/solve_shared_centre.py`) — the camera is one point. Slide along the
   line the free solve strung itself out on and keep the best. Better on the paint **and**
   renderable.
5. **smooth** (`scripts/smooth_camera.py`) — median-filter each parameter, keeping only the frames
   the paint agrees with. Focal jitter 5.22 → 3.52 px/frame, roll 0.034 → 0.026 °/frame.
6. **polish** (`scripts/polish_camera.py`) — go back over the frames the chain left worst and offer
   each the nearest better frame on either side, and the slerp between them. Kept only if it beats
   what is there *and* scores on no fewer markings. Worst frame in the clip: `broadcast` 7.03 →
   4.33, `14604731` 28.73 → 22.74, `fan` 4.06 → 3.21; on `NET_ARG_225042` eight frames sitting at
   40–60 px went to 5–7. Medians barely move, which is right — only outliers are touched.

All six behind one button in the viewer, and one call in `solve/pipeline.py`. The chain's output is
`camera_polished.json`, read off `STAGES` rather than named in code.


## What the numbers mean

**`across`** is the worst marking's own median distance to the paint measured **along its normal**,
and it is the only one of the three that is the camera alone. **`worst line`** is the same median
taken to the nearest paint in any direction. **`worst spot`** is the worst single sample on that
marking — what a ruler finds, because a human measures a line where it is furthest out — and it is
a joint reading of the camera and the paint detector.

Read all three. A marking pivoted about the middle of its overlap reports an offset of zero and is
far out at both ends, which is why the median alone is not enough; and a large gap between `worst
spot` and `across` says the paint is being lost, which is real but is a different subsystem's
defect.

The metric had a ceiling until 2026-08-11: `match_px = 40` deleted every sample with no paint
within it, so nothing could exceed 40 px and the readout went blank on the worst frames. A human
with a ruler read larger than the headline on every frame he tried, and was right.


## Editing by hand

Everything lands in `camera_manual.json`, laid over the solve, which is never rewritten. **And the
solver reads it** — that was not true until 2026-08-12, and the button that ran the chain discarded
the operator's anchor on every press without saying so. On `CRO_MOR_194948` frame 0 the difference
is 2 markings at 26.84 px against **9 markings at 3.54 px**. `solve/hand.py` is the one reader.

- the seven numbers, typed
- **auto-fit this frame** — aim it roughly, the solver finishes it. A rough aim at 445 px comes back
  at 4.7 px on `broadcast` frame 0, and 2.6 on a second press because LM is local. It refuses
  rather than damages: `refit._accept` takes the fit only if the worst offset fell and no
  correspondence was lost. Under `MIN_MATCHED` matches it says *aim closer* instead, which is the
  opposite advice for the opposite problem.
- **drag** the camera in the 3D view — translate or rotate, the gizmo sends the three angles the
  server speaks, never a matrix. The rotate gizmo runs at a quarter speed (a fifth again with Alt)
  because aiming at 70 m is a tenth-of-a-degree job, and the frustum, the frame plane, the seven
  numbers and the markings on the video all follow the hand live rather than jumping on release.
- **keyboard**: arrows for X/Y, PgUp/PgDn for Z, shift+arrows for aim, `[ ]` roll, `− =` focal,
  `alt` for a fifth of the step, `, .` for frames
- **copy from frame N**, then nudge
- **flip 180°**
- reset this frame, or every edit


## Hardware, and the absence of models

**No GPU, no neural network, no ML runtime.** SIFT + MAGSAC for frame-to-frame motion, distance
transform + Hough/LSD for the markings, `scipy.optimize` for the fit, a k-d tree for the residual.
Nothing trained, nothing downloaded, no checkpoint to lose.

Measured on an i7-11850H laptop with no GPU. `paint_masks` is **122 ms** a frame at 1920×1080,
down from 222 on 2026-08-13, and scoring the same frame again is **12.3 ms** rather than 454.

**"One core is the requirement" was wrong** and is corrected in
`findings/making-it-fast-2026-08-13.md`: OpenCV already threads its own operators and
`measure_pairs` runs at 10.8 cores busy unaided. What does not parallelise is the rest, and not
because of the GIL — 8 worker processes give 7.8 cores busy, 130 s of CPU against 20, and the
**same** wall clock. The workload is memory-bound. `paint_masks` costs 64, 76, 107 ms per megapixel
at 0.1, 0.5 and 2.1 Mpx, dearer per pixel as it grows, because it falls out of cache.

The GPU box exists because it is always on and reachable, not because anything needs it.

