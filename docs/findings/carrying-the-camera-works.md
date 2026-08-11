# Moving the camera before refining it: 38.5 → 22.7 px with no human in the loop

The search could not reach a good camera from its own seed, and a good seed copied to the next
frame was worth about three frames (`the-search-fails-not-the-model.md`). The reason copying failed
is now measured and it is not subtle: **the operator zooms.** Over 24 frames the focal goes 3476 →
5404 px, and a copied camera has not moved at all.

So move it first. `solve/carry.py` takes a camera through the image→image homography that
`measure/pixel_motion.py` fits from SIFT features — no pitch, no markings, no focal in its
derivation, which is why it cannot inherit the mistakes of the thing the refit is optimising.

## The instrument, checked before it was believed

`H(i→j) = K_j Rⱼ Rᵢᵀ K_i⁻¹` for a camera rotating and zooming about a fixed centre. Writing
`A = H K_i`, the rows of `K_j⁻¹A` must have equal norm, which pins `f_j` twice over — once from
each image axis:

    f_j = |a₁ − cx·a₃| / |a₃|      f_j = |a₂ − cy·a₃| / |a₃|

On synthetic pairs with the answer known in advance — pure pan, pure tilt, pure zoom, all three at
once, long lens — it recovers the focal to 1e-6 relative and the aim to 1e-4 degrees. A homography
carrying a translation term makes the two axes disagree, and that disagreement is returned rather
than averaged away. Degenerate input returns `None`, not a plausible camera.

On the real clip the two axes disagree by **0.001**, so the fan clip really is a rotation about a
fixed point, and the consecutive-frame homographies reproduce their own inliers to **0.30 px**.

## Walking away from one hand-aligned anchor

From frame 28, the frame a human aligned to 3.6 px. Paint metric, worst line, per frame:

| frame | auto | copy the camera | **carry it** | focal implied |
|---|---|---|---|---|
| 29 | 67.9 | 5.5 | 6.2 | 3476 |
| 31 | 67.4 | 14.2 | 8.2 | 3698 |
| 33 | 62.0 | 35.0 | 13.3 | 3992 |
| 35 | 69.0 | 64.9 | 12.3 | 4372 |
| 40 | 62.4 | 63.3 | 13.4 | 5092 |
| 45 | 25.7 | 35.9 | 21.9 | 5327 |
| 50 | 42.9 | 61.5 | 5.8 | 5355 |
| **median of 24** | **44.8** | **47.0** | **12.0** | |

- carry beats auto on **24 of 24** frames; copy on 9 of 24.
- carry beats copy on 23 of 24.
- The anchor holds under 20 px for **15 frames** carried, against **3** copied.

## With no human anywhere

Anchor on the solve's own frame 0, refitted, then carry and refit all the way to 119:

| | median worst line | frames under 20 px |
|---|---|---|
| `camera_auto` | 38.5 px | 13 of 119 |
| `camera_refit` (previous best) | 30.4 px | — |
| **carry from the solve** | **22.7 px** | **42 of 119** |

Better on 65 of 119 frames, and the best automatic result this repo has produced.

## What is still wrong: the chain drifts

A chain accumulates. By frame 70 the automatic run is at 66 px, and from about frame 85 the metric
returns nothing at all — the camera has drifted far enough that no marking has the samples to be
scored. **That is a failure and it is recorded as one**, not smoothed into the median above.

Two fixes, both cheap, neither tried:

- **Long-baseline pairs.** `measure_pairs` already takes `gaps=(1, 10, 30, 59)`. Carrying over a
  gap of 30 as well as 1 pins the drift against a frame far enough away that accumulated error
  cannot hide, and `pixel_motion.fit_rotation_only` already exists to fit all of them at once
  rather than sequentially.
- **Re-anchoring.** One hand-aligned frame carries ~15 frames under 20 px, so a 120-frame clip
  needs about eight anchors, not 120. That is the manual-override half of the design doing what it
  is for, and it is now a measured quantity rather than a guess.

## What this settles

The 30–47 px band across five solves was the local search failing from a bad seed, exactly as
`the-search-fails-not-the-model.md` argued from the hand fit. Given a seed that has already moved
to roughly the right place, the same objective, the same refit and the same 7 parameters produce
12 px next to an anchor and 22.7 px unaided.
