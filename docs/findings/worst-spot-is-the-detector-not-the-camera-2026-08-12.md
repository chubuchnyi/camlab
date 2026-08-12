# `worst spot` is 7.9× the camera's actual error, and the rest is the paint detector

Measured 2026-08-12, on `runs/fan/camera_smooth.json` unless another camera is named. The question
was why the headline error is 15 px when the overlay looks aligned, and what to do to reduce it.

The answer is that ~7/8 of it is not the camera. Two hypotheses were tested and refuted first, so
they are recorded before the one that held.

## Refuted: lens distortion

If an uncorrected radial term were the error, it would grow with distance from the optical axis.
Over 6097 scored samples, binned by radius from the principal point (540, 304):

| radius from the axis | median error | p95 |
|---|---|---|
| 4–173 px | 1.44 px | 9.68 px |
| 173–253 px | 0.95 px | 4.41 px |
| 253–352 px | 0.84 px | 1.94 px |
| 352–459 px | 0.89 px | 2.52 px |
| 459–610 px | 1.21 px | 4.65 px |

Pearson r(radius, error) = **−0.105**, and the worst bin is the one at the centre. This is an
independent confirmation of `lens-distortion-is-not-the-error.md` on a different camera and a
different statistic.

## Refuted: the pitch is not 105 × 68

The laws of the game fix the penalty box at 16.5 m deep and the goal area at 5.5 m **whatever the
pitch measures**, and allow 100–110 × 64–75 for the pitch itself. So the length is observable
separately from the camera's distance — a longer pitch moves the goal line relative to a box that
cannot move with it. Re-scoring the same camera against each candidate size:

| length | 64 m wide | 68 m | 72 m |
|---|---|---|---|
| 100 m | 37.57 px | 34.38 | 34.38 |
| 102 m | 36.66 | 34.63 | 34.63 |
| **105 m** | **1.70** | **1.70** | **1.70** |
| 108 m | 41.66 | 38.12 | 38.12 |
| 110 m | 48.50 | 43.50 | 43.50 |

105 m by a factor of 20. This is a re-score without a refit, so it is biased toward the size the
camera was fitted at — but no refit absorbs a 20× margin, and 1 m of goal line is 27 px here.

**A side result worth keeping: 68 m and 72 m are bit-for-bit identical.** Nothing scored on `fan`
depends on the pitch width at all — the touchlines never land inside the frame and on the surface.
The width is not measured on this clip, it is assumed, and no number here would move if it were
wrong.

## What it actually is

Rank the markings by their worst sample, and the error is not spread over the pitch — two markings
hold nearly all of it, both at the far goal:

| marking | worst sample | px per metre | worst sample in **metres** |
|---|---|---|---|
| goal area front, far (x = 47) | 14.11 px | 31.4 | 0.450 m |
| goal line, far (x = 52.5) | 12.41 px | 27.5 | 0.451 m |
| the D, far | 5.52 px | 17.9 | 0.308 m |
| penalty box front, far (x = 36) | 4.15 px | 33.6 | 0.124 m |
| everything else | ≤ 2.4 px | | ≤ 0.12 m |

Two unrelated markings at 0.450 and 0.451 m is not a geometric error. It is one mechanism.

Decompose each worst sample's displacement into the component **along** its marking and the
component **across** it:

| marking | worst spot | along | across |
|---|---|---|---|
| goal line, far | 12.41 px | **11.75** | 2.20 |
| goal area front, far | 14.11 px | **8.84** | 5.53 |
| the D, far | 5.65 px | 1.23 | 5.38 |
| penalty box front, far | 4.15 px | 2.44 | 2.65 |
| all worst spots | 5.08 px | 2.60 | 1.80 |

**Along beats across on 63 % of worst spots.** And a line has no observable displacement along
itself: the along component is not a camera error at all, it is the detected centreline running out
and the nearest pixel being found further down the same line. `worst spot` was charging holes in
the detector to the solver.

It is not the "drifted onto a neighbouring line" trap either — of the 45 samples with an across
error over 5 px, **2** matched paint belonging to a different marking.

## The fix, and the mistake inside the fix

`frame_residual` now also walks each sample out along its marking's own **normal** and reports the
first offset at which the distance transform says a centreline is underfoot. That gives the third
answer a nearest-neighbour query cannot: *no paint here*, which is a defect in another subsystem
and is counted as `n_no_paint_across` rather than charged as an offset.

The first implementation of that walk sampled the distance transform at **rounded integer pixels**,
and reported that 34 % of `fan`'s samples had no paint across them. That was its own arithmetic: the
detected centreline is one pixel wide, so a ray stepped in rounded pixels hops over it whenever the
normal is near diagonal. Same frames, same paint, same threshold, only the sampling changed:

| sampling | paint found across |
|---|---|
| rounded pixel, `dist < 0.75` | 70 % |
| rounded pixel, `dist < 1.5` | 97 % |
| **bilinear, `dist < 1.0`** | **97 %** |

Had it shipped, 27 % of the samples would have been published as gaps in the paint detector — a
defect in a subsystem that does not have it, invented by the measurement. `tests/test_verdict.py`
rasterises a 45° line through a real `cv2.distanceTransform` and fails under the rounded version.

A sub-pixel correction goes with it: the hit test fires anywhere within a pixel of the centreline,
so reporting the walk's step alone quantises every good sample to 0.00 px and the metric reads
"exactly on the paint" for anything under 1 px. The parametrised offsets in the test are 1.3, 2.3
and 6.7 px, none of them a multiple of the 0.5 px step, so deleting the correction fails it.

## Where it leaves the three clips

| clip | **across** — the camera | worst line | worst spot | markings | no paint across |
|---|---|---|---|---|---|
| `fan` | **1.88 px** | 1.69 px | 14.75 px | 6 | 11 % |
| `broadcast` | **2.83 px** | 2.75 px | 12.72 px | 7 | 6 % |
| `g15449383` | 4.53 px | 2.92 px | 72.60 px | 2 | 23 % — and not a verdict |

The `across` and `worst line` columns agree closely, which is the expected result and not a
tautology: where paint is present, the nearest pixel *is* across the line. They diverge exactly
where the paint is missing, and that is what the last column counts.

## What this changes about the next move

The solver is not where the remaining error on `fan` is. Its worst marking sits **1.88 px** from
the paint measured perpendicular to itself, and the median marking is under a pixel — inside the
12 cm width of the painted line at this scale.

What is left is the detector: 11 % of `fan`'s samples and 23 % of `g15449383`'s have no detected
centreline opposite them. That is task #14's subsystem. Tuning the solver further would be fitting
to a measurement that is already at its floor, and improving the paint detection is what would move
both the number and the overlay.
