# What is true right now

Last measured 2026-08-12. Read this and `findings/landmines.md`; that is the cold start.

---

## The chain works

A clip goes in, a camera comes out, and the camera is right by the only test that counts — the
projected pitch lands on the painted one, judged by eye as well as by the number.

| clip | **across** | worst line | worst spot | markings | no paint across | under 20 px |
|---|---|---|---|---|---|---|
| `fan` (1080×608, phone, stands, floodlit night) | **1.82 px** | 1.65 px | 15.54 px | 6 | 2 % | 120/120 |
| `broadcast` (1920×1080, professional) | **2.96 px** | 2.75 px | 12.14 px | 7 | 1 % | 60/60 |
| `CRO_MOR_194948` (1920×1080, one hand anchor) | **4.22 px** | 4.04 px | 13.87 px | 9 | — | 120/120 |
| `g15449383` (1920×1080) | 4.47 px | 3.49 px | 72.60 px | **2** | **21 %** | not a verdict |

**Read the markings column first.** Every error here is a max over the markings a frame scores, so
on a frame holding two it is a max over two. `g15449383` was called solved on "40 of 40 frames under
20 px" and is not; `Residual.supported` now refuses that rather than leaving it to be noticed.

**`across` is the camera. `worst spot` is the camera plus the paint detector** — 7.9× larger on
`fan` for that reason alone, because a nearest-paint distance charges a hole in the detected
centreline to the camera, and a line cannot be displaced along itself. Full measurement:
`findings/worst-spot-is-the-detector-not-the-camera-2026-08-12.md`.

`CRO_MOR_194948` is the first clip solved from an operator's own anchor in the viewer, and it took
three fixes landing the same day to work at all: the solver did not read hand edits, the anchor
refit was position-locked, and the centreline extractor was not a thinning algorithm. Before them
it scored 2 markings at 26.84 px and no verdict.

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

## Two degeneracies, both measured, both real

**The pitch is exactly symmetric under a half-turn.** Rotate a solved camera 180° about the centre
spot and it scores *bit for bit* the same — 2.1 px on 307 samples either way. Nothing in the
markings can say which half is being looked at and no solver ever will. The viewer has a
`flip 180°` button; choosing needs something off the pitch, or an eye.

**Focal trades against distance on a plane.** The free solve strings its positions along a line —
99 % of the variance along one direction, 108 m of it — pointed 13–25° off the line of sight. That
line is not a trajectory, it is the degeneracy drawn in space. It is **not flat**, though: sliding
along it and re-refitting gives 1.89 px at the optimum against 4.33 px three metres away, so the
position is pinned to about a metre. It only looked flat because nobody had searched along it.

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

## Open, and why

Each of these has a findings doc with the numbers; what is here is the verdict and the pointer.

**#14 — tell a marking from a mowing stripe, a shadow edge, a net or an advertising board.**

*Recall is done* (2026-08-12). The "centreline" was the local maxima of a distance transform, which
is not a thinning algorithm and does not preserve connectivity — `fan` frame 0: 854 mask components
returned as **1823**. Zhang-Suen returns 846, the mask's own count. `g11710897` goes from **2 lines
a frame to 5**, and two is below `refit.MIN_MATCHED`, so that clip could not be fitted at all
before. `fan` gaps 4 % → 2 %.

*Precision is parked for want of data, not ideas* (2026-08-13). Over seven clips the detected
lines are **315 markings and 12 non-markings** — there is nothing to validate a filter against. Two
more candidates were measured and are in `findings/11-is-blocked-by-14-2026-08-12.md`: turf support
at a wide scale (clean on `fan` frame 8, does not survive twelve samples) and "does paint continue
past the segment's ends", whose sign turned out to be the **opposite** of the guess — straight
markings 0 %, arc pieces 58 %, because `merge_collinear` already extends a straight marking over its
whole painted run. Resume when the pitch-level clips have cameras good enough to label against.

*The older reading, kept because the mechanism is real* —
`findings/11-is-blocked-by-14-2026-08-12.md`. On `fan` frame 8 two of nine detected segments are
55–60 px from any marking, and both lie along the **join between the grass and the advertising
hoarding**. Feeding the generator the seven real ones moves the best hypothesis in the pool from
11.9 m to **3.7 m** and the focal from 28 % wrong to 2.1 %.

Every cheap signal is refuted with numbers: straightness points the *wrong* way on `fan`
(non-markings are straighter, 0.13 px against 0.20); cross-ratio passes 70 % of impostor quads;
length is a filter with 39 % leakage and actively *prefers* the hoarding join, which is 567 px long;
and an inset-from-the-surface-edge test, designed on frame 8, hurts on three of the seven frames it
was then swept over. Untried and geometric: whether a segment on the grass and one raised above it
transform differently under the frame-to-frame homography.

Also recorded there and deliberately not fixed: the turf test's hardcoded `s > 70` drops the
**sunlit** half of `g15449383` — the rejected pixels are *brighter* than the accepted ones — and
sweeping it 70 → 15 improves not one measured number.

**#11 — find the first camera automatically. It works on one anchor of six**, which is one more
than the register records: `bootstrap_clip.py fan --frame 0` returns **1.0 px over three probe
frames on 298 samples**, 3.11 m from the truth with the focal 1.7 % off, and reports the half-turn
twin correctly. The register's 10.7 px on 66 samples is out of date.

The other five print *"no plausible camera at all"*. On `fan` 40 the cause was a defect in the gate
rather than in the search — the arc test demanded 8+ arc samples and the operator had zoomed until
no arc was in the picture, so it threw out the **true** camera along with everything else. It now
abstains where it has no evidence, the same rule `MIN_SUPPORTING_MARKINGS` applies to markings.

Two register claims did not survive re-measurement: *"the right answer is in the pool 4.8 m from the
truth"* (11.9 m on `fan` 8, 2.6–2.8 m on `fan` 0 and 40 — it varies by frame) and *"choosing is what
fails"* (on `fan` 8 the pool's best is 11.9 m, so no chooser could find it).

**#23 — a camera that really travels.** Deferred: no such clip exists yet. The trap is written
down — a real dolly move and the focal/distance degeneracy look identical in the 3D view, and on a
pure plane translation and rotation are not separable at all.

## The one check that does not use the markings

Mowing stripes are evenly spaced **in metres**. Rectify through the camera and they become
periodic, and on `fan` the period holds at 11.00 m ± 2.3 % while the operator zooms 1.61×, with a
focal-to-period correlation of −0.19. Breaking the camera breaks it as predicted: focal ×1.25 gives
8.75 m, and 11.00 / 8.75 = 1.257.

Two cautions. Not every pitch is striped — `broadcast` is 3 frames of 20, and that is its turf. And
a **wrong camera looks the same as an unstriped pitch**, because stripes are only periodic once
rectified correctly. A check to run on a camera you already believe, never a way to find one.

## Ruled out, so nobody spends the afternoon again

- **Lens distortion.** Markings bow 0.37 px, in a random direction (42/58), and it does not grow
  with radius. 40–65× too small for the residual it was offered to explain.
- **The principal point.** 638 px apart gives 2.11 px against 1.78 px through the same chain. The
  camera's other six parameters absorb it. The consistency rule stands — a camera is valid only
  under its own K — but there is nothing to fix.
- **Random-search bootstrap.** 4 000, 20 000 and 60 000 candidates return the *identical* wrong
  camera.

## Getting the camera out

`scripts/export_camera.py <clip>` writes `calib/<clip>.npz`, **schema 2**: `focal_px` and
`position` per frame, every key present on every camera, `zoom_ratio` and `centre_spread_m` so
"does this clip zoom" and "is this one camera" need no arithmetic. `world_to_image` is rebuilt from
the focal and pose beside it rather than copied.

pitch3d's schema 1 held `focal` as one scalar for a whole clip. Collapsing to it costs **65 % of
the accuracy** on `fan` — 1.69 px becomes 4.88 and five frames of thirty leave the band — and
nothing on clips that do not zoom. `read_npz` refuses schema 1 by name; there is no compatibility
branch, because pitch3d is being changed rather than accommodated.

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

## Running it

```bash
.venv/bin/python -m pytest                    # 89 tests, ~6 s
bash scripts/deploy.sh                        # ship HEAD to the box and open the tunnel
bash scripts/tunnel.sh                        # just the tunnel, if it dropped
bash scripts/tunnel.sh --watch                # keep it up
```

The viewer does the rest: upload an mp4, it decodes and gets a labelled default camera, align one
frame by eye, press **solve this clip**.
