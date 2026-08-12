# What is true right now

Last measured 2026-08-12. Read this and `findings/landmines.md`; that is the cold start.

---

## The chain works

A clip goes in, a camera comes out, and the camera is right by the only test that counts — the
projected pitch lands on the painted one.

| clip | **across** | worst line | worst spot | markings | no paint across | under 20 px |
|---|---|---|---|---|---|---|
| `fan` (1080×608, phone, stands, floodlit night) | **1.88 px** | 1.69 px | 14.75 px | 6 | 11 % | 120/120 |
| `broadcast` (1920×1080, professional) | **2.83 px** | 2.75 px | 12.72 px | 7 | 6 % | 60/60 |
| `g15449383` (1920×1080) | 4.53 px | 2.92 px | 72.60 px | **2** | 23 % | not a verdict |

**Read the markings column first.** Every error here is a max over the markings a frame scores, so
on a frame holding two of them it is a max over two. The third clip was called solved on the
strength of "40 of 40 frames under 20 px" and it is not: it scores 2 markings and 76 samples where
`fan` scores 6 and 165. `Residual.supported` and `bench_metric_ceiling.py` now say so rather than
leaving it to be noticed.

**`across` is the camera. `worst spot` is the camera plus the detector**, and on `fan` it is 7.9×
larger for that reason alone — measured 2026-08-12 and it changes what the remaining error is. A
nearest-paint distance charges a hole in the detected centreline to the camera: over a gap the
nearest pixel is far ALONG the same line, and a line cannot be displaced along itself. `fan`'s far
goal line splits **11.75 px along against 2.20 across**, and along beats across on 63 % of all
worst spots. The `no paint across` column is that defect on its own — 11 % of `fan`'s samples have
no detected centreline opposite them at all, which is task #14's subsystem, not the solver's.

## The pipeline, and why each stage is there

1. **anchor** — a hand-aligned frame, or frame 0 refitted from the default. One hand anchor is
   worth about sixty frames.
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

All five behind one button in the viewer, and one call in `solve/pipeline.py`.

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

Everything lands in `camera_manual.json`, laid over the solve, which is never rewritten.

- the seven numbers, typed
- **drag** the camera in the 3D view — translate or rotate, the gizmo sends the three angles the
  server speaks, never a matrix
- **keyboard**: arrows for X/Y, PgUp/PgDn for Z, shift+arrows for aim, `[ ]` roll, `− =` focal,
  `alt` for a fifth of the step, `, .` for frames
- **copy from frame N**, then nudge
- **flip 180°**
- reset this frame, or every edit

## Open, and why

**#14 — tell a marking from a mowing stripe, a shadow edge or a goal net.** Three signals measured:

| signal | verdict |
|---|---|
| straightness | **points the wrong way on `fan`** — non-markings are straighter, 0.13 px against 0.20 over 208 markings and 88 others. Untested elsewhere: `broadcast` yields 7 non-markings and `g15449383` yields 3 markings, and neither is a sample |
| cross-ratio | camera-free and selective on paper (8.7 % of the range at 0.05), but 70 % of impostor quads pass: both the admissible values and the observed ones pile into 1.0–1.2 |
| length | **the only thing that helped** — 216 px against 86 px, and a 100 px cut took 81 → 90 frames under 20 px |

Length is a filter, not a discriminator: 39 % of non-markings still get through. Cheap geometric
signals are exhausted.

**#11 — find the first camera automatically.** Five ranking attempts: 113 m → 113 m → 20.9 m →
54 m → 128 m from the truth. The generator is fine — the right answer *is* in the pool, 4.8 m from
the truth with the focal 11 % off. Choosing is what fails, and not because the chooser is bad:
between the half-turn symmetry and the focal/distance trade, many cameras genuinely fit. It needs
information the markings do not carry.

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

Measured on an i7-11850H laptop with no GPU: the full chain over 60 frames of 1920×1080 takes
**155 s** and peaks at 1.1 GB; the per-frame work is **340 ms** and 180 MB. **One core is the
requirement** — 342 ms a frame on one thread against 324 ms on sixteen, which is noise. Several
stages are parallel across frames and are not parallelised; that is undone work, not a limit.

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
