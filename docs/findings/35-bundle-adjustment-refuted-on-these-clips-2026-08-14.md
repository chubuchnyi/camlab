# #35: a global bundle adjustment is worse on the paint, every time, and says why

`cv2.detail.BundleAdjusterRay` takes the matched points between every pair and refines all
rotations and focals together, under exactly the model the carry stage assumes — a camera turning
about a fixed centre. The chain fights drift locally, one frame at a time from its nearest anchor;
this attacks the same thing globally. It was the most promising of the OpenCV methods.

**It makes every clip worse, from every seed.** `scripts/bench_bundle_adjust.py`, judged by
`frame_residual`, median worst line over the frames:

| clip | seeded from | before | after |
|---|---|---|---|
| `fan` | `camera_smooth.json` | **1.54 px** | 18.35 |
| `fan` | `camera_carry.json` | **1.96** | 39.15 |
| `g11710897` | `camera_polished.json` | **7.29** | 21.52 |
| `g11710897` | `camera_carry.json` | **14.08** | 19.66 |

Not marginal, not seed-dependent, and not confined to the clip that was already good.

## The gauge, which nearly produced the wrong conclusion

The first run moved **every** frame's rotation by 110.52°, spread 0.6°, and every frame then scored
`nan` — the pitch had left the picture entirely. That is not a failure of the adjuster: a ray bundle
adjustment constrains only the **relative** rotations, because a panorama has no world frame, so the
whole set is free to turn together and it duly does. Comparing that output to the seed would have
said "catastrophic" about a gauge convention.

The script now recovers the gauge by orthogonal Procrustes over the whole set — not by pinning
frame 0, so one badly adjusted frame cannot define the frame for the rest. After that the rotations
move 0.40–2.05° in the median, which is a plausible refinement size. The numbers above are all
post-correction.

## What it is actually doing, and it is consistent

The focal is dragged down every time, and **from two different seeds on the same clip it converges
to the same place**:

| clip | seed focal | adjusted focal |
|---|---|---|
| `g11710897` | 1702 | **1540** |
| `g11710897` | 1946 | **1540** |
| `fan` | 3320 | 3074 |
| `fan` | 2893 | 2881 |

So the adjuster is not diverging. It has a stable opinion of the focal and it disagrees with the
pitch model by 26 % on `g11710897`. That is the same disagreement #10 recorded between the paint and
the pixels, in the same direction.

The reason is visible in what it is fed. SIFT matches on these clips are on the hedge, the stands,
the boards, the crowd and the players — **not on the pitch plane, and at many different depths**. A
rotation-only model fitted to points at mixed depths cannot be the pitch's camera, and where the
camera also translates (a phone in a hand does) there is no rotation that explains them at all. The
adjuster minimises its own objective correctly and the objective is the wrong one.

## What would be worth trying, and what would not

Not worth trying: tuning it. The refinement mask, the term criteria and the confidence threshold do
not change what it is fitted to.

Worth trying: **restrict the features to the playing surface.** `paint_masks` already returns that
mask, and points on the pitch plane are the ones a homography can actually explain. That turns the
input from "everything in frame" into "the plane the model lives on", which is the difference
between the two objectives above. It is a small change to the probe script and is not done here.

Also unused and cheap: `cv2.detail.waveCorrect`, which removes the accumulated roll along a chain.
It addresses a real symptom the chain has, and it does not need the adjuster to be useful first.
