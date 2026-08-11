# A first camera with no seed: the generator works, the chooser does not

**Status: unfinished, and the numbers say so.** Written down because two approaches have now been
measured and both fail in ways worth not repeating.

## What is being solved

Everything after a first camera works — carry, self-heal, one shared centre, 120 of 120 frames
under 20 px. Both clips that got there were handed a starting camera by pitch3d. Seven of the nine
sample clips have none. This is the whole remaining gap.

## Attempt 1: sample cameras at random — refuted

Position around the pitch, aim at a random point on it, focal over a wide range, keep the best by
`refit.objective`. On fan frame 8, whose answer is 2.1 px on 307 scored samples:

    4 000 tries   17.3 px,  22 samples, focal 8045
    20 000 tries  17.3 px,  22 samples, focal 8045
    60 000 tries  17.3 px,  22 samples, focal 8045

Identical. The search converges and converges wrong, because `worst offset + MISS_PX × misses`
gives a camera that frames almost no pitch almost nothing to miss. A floor on how much of the model
lands in frame moves it onto the right order — focal 10 987 → 4027, coverage 91 → 297 — and stops
at 7.7 px, which is not a seed worth chaining from.

## Attempt 2: search the correspondences instead — the generator is right

`solve/bootstrap.py`. Two facts collapse the combinatorics with no camera assumed:

- the markings form exactly **two world-parallel families**, and each meets at its own vanishing
  point in the image, so the detected lines split into two groups before any camera exists;
- parallel markings appear in the image in the **same order** as in the world, so choosing two
  detected lines and two model markings fixes the assignment up to which end is which.

Four line correspondences give a homography — lines map by `l_world ∝ Hᵀ l_image`, two linear
equations each, eight for nine unknowns and an SVD. `focal_from_one_homography` then pins the focal
by requiring that homography to come from a real rotation.

It behaves: 14 detected segments on fan frame 8 split cleanly into 8 and 6, and 20 000 hypotheses
yield 4680 physically plausible cameras in 12 s.

## And the chooser is wrong

| | best found | samples | focal | distance from the truth |
|---|---|---|---|---|
| fan frame 8 (truth 2.1 px, 307 samples, focal 2828) | 7.0 px | 186 | **300** — the lower bound | 113 m |
| with a physical gate and ranked by paint | 8.2 px | 137 | 1011 | 113 m |
| broadcast frame 30 (truth 4.5 px, 300 samples, focal 4212) | 27.8 px | 134 | 9865 | — |
| with a physical gate and ranked by paint | 23.2 px | 198 | 1601 | 113 m |

Both land about 113 m from the true camera, on the far side of the pitch, scoring 137–198 samples
where the true camera scores 300. **A wrong camera that sees half the pitch can satisfy the paint
as well as a right one that sees all of it**, and neither the line objective nor the paint residual
distinguishes them on a single frame.

## What to try next, in order

1. **Score across frames, not one.** A wrong camera is wrong differently on the next frame; the
   right one survives being carried. Cheap — the carry and the paint metric both already exist —
   and it is the strongest filter available that has not been used.
2. **Demand coverage comparable to the best candidate**, not merely above a floor. The truth scored
   307 samples on fan; nothing that scores 137 should have been ranked first.
3. **Break the pitch's symmetry.** A football pitch is 180°-rotation symmetric in its markings, so
   two camera positions fit identically and nothing in the markings can choose. That needs
   something outside them — the stands, the goals' surroundings, or a human. Worth confirming this
   is what the 113 m is before building for it.
