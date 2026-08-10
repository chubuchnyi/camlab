# The paint metric does not measure camera error

Measured 2026-08-10, after a human looked at frames 8, 16, 17, 18, 29, 30, 31 and said the numbers
did not match what was on the screen. They do not, and this is why.

## What it does today, exactly

1. Sample the **model** pitch markings at 2 points per metre — about 1400 world points, each
   tagged with which marking it came from.
2. Project them through the camera. `world_to_image` builds `K` with **`cx = width/2`,
   `cy = height/2`**.
3. Keep the ones landing inside the image and on the detected playing surface.
4. For each survivor, find the **nearest detected paint pixel within 40 px**.
5. Report the median, p90, max, the worst marking's own median, and how many found nothing.

So the quantity is: *how far a projected model point is from the nearest paint of any kind, in any
direction, where paint was detected, capped at 40 px.*

That is not "how wrong is the camera", and the gap is not subtle.

## The demonstration

Take frame 0's solved camera, perturb it by a **known** amount, and see what the metric says.

| perturbation | worst line | median | n | unmatched |
|---|---|---|---|---|
| **none (as solved)** | **29.94** | **7.27** | 308 | 0 |
| tilt 0.25° | **17.74** | **5.57** | 296 | 0 |
| tilt 0.5° | 22.99 | 8.60 | 291 | 0 |
| tilt 1.0° | 24.42 | 13.71 | 263 | 18 |
| pan 0.25° | 31.89 | **6.47** | 310 | 0 |
| pan 0.5° | 34.50 | **6.11** | 312 | 0 |
| pan 1.0° | 33.94 | **6.90** | 306 | 10 |
| roll 0.5° | 31.48 | **6.71** | 301 | 0 |
| roll 1.0° | 31.76 | **6.42** | 296 | 3 |
| camera up 2 m | 37.30 | 15.24 | 285 | 35 |
| camera up 10 m | **18.59** | 9.08 | 180 | 8 |

Three things, any one of which disqualifies it:

**The solved camera is not at a minimum.** Tilting 0.25° makes both numbers better. The metric does
not think the answer we ship is the best answer available.

**It is nearly blind to pan and roll.** A full degree of pan changes the median from 7.27 to 6.90 —
*better*. A degree of roll, 7.27 to 6.42 — better again. Those are large, visible errors.

**Moving the camera 10 m into the air improves the worst line**, 29.94 → 18.59, by pushing half the
pitch out of frame: 180 samples instead of 308.

## Why it is blind, mechanically

**Distance to the nearest pixel of a line is a perpendicular distance.** Slide a projected line
*along its own direction* and every sample still lands on paint at ~0. A whole family of camera
error — the one pan produces — is invisible by construction. This is the largest hole and it is
structural, not a threshold to tune.

**There is no correspondence.** It matches to whatever paint is nearest, not to the paint of *that
marking*. Inside 40 px, a goal-area line snaps happily to the goal line, and reports success.

**The principal point is wrong.** `world_to_image` hardcodes `width/2, height/2`. This clip's
optical axis is at `cy = −334`, 638 px away — measured, and already fixed in `ClipInfo`, and never
threaded into the metric. **Every paint number in this repo is computed with the wrong `K`.**

**It saturates.** The 40 px bound means `max_px` reads 39.x on every frame the user flagged: the
statistic is reporting its own ceiling. Beyond the bound, error becomes a count, not a magnitude.

**It penalises the paint detector.** A correctly projected marking over paint the detector missed —
worn, shadowed, under a player — counts as unmatched. The camera is charged for the detector.

**It scores 11–26 % of the pitch.** The rest is off-surface or out of frame and simply absent.

## The frames that prompted this

| frame | worst | median | max | n | unmatched |
|---|---|---|---|---|---|
| 8 | 24.35 | 11.69 | 39.28 | 235 | 21 |
| 16 | 16.19 | 11.81 | 39.60 | 162 | 13 |
| 17 | 15.36 | 11.01 | 39.85 | 132 | 12 |
| 18 | 15.49 | 11.73 | 39.08 | 134 | 15 |
| 29 | 28.46 | 16.66 | 39.69 | 269 | 62 |
| 30 | 31.58 | 17.93 | 39.95 | 266 | 58 |
| 31 | 37.23 | 18.19 | 39.90 | 236 | 84 |

`max` is the bound on every one of them. Frame 31 discards **84 of 320** projected samples — a
quarter of the evidence — and reports 18.19 for the rest.

## What a correct measurement looks like

The eye compares **lines to lines**: "this line is thirty pixels below where it should be." The
metric compares points to point-clouds. So:

1. **Correspondence-aware.** Match a detected segment to the model line it *is* — `measure/lines.py`
   now produces merged segments, so this is available — and measure against that one, not the
   nearest.
2. **Two numbers per line, not one distance**: perpendicular **offset** and **angle**. Both are
   what a human reads off the screen, and the angle is exactly what nearest-pixel throws away.
3. **Two-way.** For every model line predicted visible, is there paint where predicted? For every
   detected segment, is there a model line? Both misses are errors, and neither is currently one.
4. **Unbounded, or bounded far above the errors being measured.** A statistic that saturates cannot
   rank two bad cameras.
5. **Calibrated against known error.** Displace the camera by a known amount; the metric must
   report a number that grows with it. That test is the table above, and today it fails.

Point 5 is the one that matters. The vanishing-point estimator was validated that way before it was
trusted, and it is the only instrument here that has not had to be retracted. The paint metric —
the one every conclusion in this project rests on — never was.
