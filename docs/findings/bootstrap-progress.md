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
3. **The pitch's 180° symmetry is real, measured, and not fixable by ranking.** Rotating a solved
   camera by 180° about the centre spot — position `(x, y, z) → (−x, −y, z)`, yaw `+180°` — gives
   *bit-for-bit identical* numbers:

   | | as solved | rotated 180° |
   |---|---|---|
   | fan frame 8 | 2.1 px, 307 samples | **2.1 px, 307 samples** |
   | broadcast frame 30 | 4.5 px, 300 samples | **4.5 px, 300 samples** |

   The markings cannot say which half of the pitch is being looked at, because a football pitch is
   symmetric under that rotation. Two answers, exactly equally good, and no amount of better
   scoring will separate them — the information is not in the markings. Breaking it needs something
   outside them: the stands, the scoreboard, which way the teams attack, or one click from a human.

   Note this is **not** what the 113 m above is. The bootstrap's answer is not the mirror of the
   truth either, so there are two separate problems: this ambiguity, which is fundamental, and the
   chooser, which is merely wrong.


---

# Where it got to, and where it stopped

**A clip can now be solved with nothing from outside.** Not as well as with a seed from pitch3d,
and the gap is entirely in the seed.

| seed | chain result |
|---|---|
| pitch3d `scene.json` | **2.11 px**, 120/120 frames under 20 px |
| bootstrap, ranked by worst line | 7.75 px, 100/120 |
| bootstrap, ranked by pooled median | 13.44 px, 114/120 |

## What made the difference, measured

**The pooled median separates a right camera from a wrong one; `worst_line_px` does not.**

    fan frame 8   truth       pooled median  1.7 px,  0.3 % of markings with no paint under them
                  candidate                 16.3 px,  6.8 %
                  candidate                 12.2 px,  2.5 %

Worst line is the right number for judging a camera already close — it is what catches one marking
sitting on its neighbour's paint. For *discrimination* it is nearly useless, because one bad
marking is as likely in a good camera as a bad one. Ranking the search by the pooled median instead
took the winner from 113 m off the truth to 54 m, and adding `n_unmatched` — the direct statement
"you predicted a marking here and there is no paint here" — as a rejection at 5 % tightened it
further.

**The truth was always in the candidate pool.** At 200 000 hypotheses there is one 4.8 m from the
true camera with the focal 11 % off. The generator was never the problem; every failure has been in
choosing.

## And it still does not find the true camera

The best seed is 21–54 m away with a focal three times off, and it fits the markings almost as
well as the truth does. That is not a bug to be tuned out. Two degeneracies were measured this
session and both are real:

- the pitch is **exactly** symmetric under a half-turn, so two cameras fit bit for bit identically;
- focal and distance trade off on a plane, so a family of cameras along the line of sight fit to
  within a pixel.

There genuinely are many cameras that fit the markings. Choosing between them needs information the
markings do not contain.

## Two ways on, and they are different in kind

1. **The centre circle (#18).** It is the one marking that projects to an *ellipse*, and an
   ellipse's SHAPE — not just its size — pins focal and orientation without any correspondence.
   It changes as the camera slides sideways or changes focal, which are exactly the two errors the
   current seed makes. This attacks the cause rather than the ranking.
2. **One hand-aligned frame per clip.** Measured this session at about sixty frames' worth of
   anchor, and it gives 2.11 px on 120 of 120. It is not automation, but it is minutes per clip and
   it works today.

What is NOT worth another round: tuning the ranking. Two rounds of that moved the answer sideways
— 113 m to 54 m, one score better and one worse — without ever landing it.

---

# #18: the arcs. What worked, what did not, and where I stopped

**Modelled and scoreable now.** `measure/ellipse.arc_markings()` returns the two curved markings —
derived from the pitch model by the same 5 cm test `straight_markings()` excludes them with, not
hardcoded — and `arc_paint_distance()` scores a camera by where it puts them.

**It separates.** fan frame 8:

| camera | arcs to nearest paint | arc points in frame |
|---|---|---|
| **truth** | **1.5 px** | 35 |
| line-fitted candidate | 7.9 px | 17 |
| line-fitted candidate | 5.7 px | 12 |
| line-fitted candidate | — | **0** — the arcs are off-frame entirely |

That last row is the strongest part: a wrong camera does not merely score badly on the arcs, it
often fails to put them in the picture at all, which is a disqualification rather than a number.

**Detecting the ellipse does not work, and the failure is worth knowing.** Two attempts:

- RANSAC conic on painted pixels with the detected straight lines removed. Returns something with
  200–600 inliers at under 2 px RMS on every real frame, and it is not the arc: axis ratios of 69:1
  and 970:1, and after an eccentricity bound, axes four times too large. What remains after the
  lines are removed is still mostly line-like, and the largest consistent conic through it is a
  shallow curve through noise.
- Connected components with a parabola fit — the method that *did* find the arc when measuring lens
  distortion. Finds no curved run at all here: the arc's paint arrives in fragments too short.

And it did not matter. The arc is present — projecting it through a known camera lands all 35 of
its points in frame with paint a median of 1.5 px away — so there was never a detection problem to
solve. **A camera hypothesis already says where the arc should be.** Asking whether paint is there
is cheaper and decisive. I built a detector for a question that did not need one.

## Where the bootstrap stands after all this

Four ranking attempts, each measured:

| ranking | winner's distance from the truth |
|---|---|
| line objective, single frame | 113 m |
| + physical gate, ranked by paint | 113 m |
| + carried to two probe frames | 20.9 m |
| + pooled median instead of worst line | 54 m |
| + arcs required to land on paint | 128 m, but the focal is finally in the right range |

The arc constraint does what it was meant to — candidates now come back at focal 2096–3718 against
a truth of 2828, where before they were at 300–1600 — and the winner is still not the truth.

**Stopping here.** Five rounds of ranking have moved the answer around without landing it, and the
thing that has landed it every time is one hand-aligned frame: 2.11 px on 120 of 120, measured
repeatedly. The automatic route needs a different idea, not another weight.
