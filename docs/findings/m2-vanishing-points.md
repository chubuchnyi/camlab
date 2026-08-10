# The third instrument works, and it cannot settle this clip

Measured 2026-08-10. `camlab.measure.lines` + `camlab.solve.vanishing`.

## Why it was built

Two focal estimates disagree by about 1.5×: the paint fit says ~4315 px, the image→image maps say
~2100–2500 px with an answer that walks with the baseline. Two instruments disagreeing is a puzzle.
Vanishing points share no machinery with either — no pitch scale, no camera position, no feature
matching, no ICP — so a third opinion should break the tie.

## It is correct

`f² = −[(u₁−cx)(u₂−cx) + (v₁−cy)(v₂−cy)]`, from `v₁ᵀ ω v₂ = 0` with square pixels and a known
principal point.

Synthetic controls, written before it was trusted this time: the closed form returns 2400.0 exactly
from a known camera's vanishing points, and the whole path — project a pitch, detect nothing, group
the segments, read the focal — returns 1800 / 2400 / 3200 / 4300 to within 2 %.

## And on the real clip it is unusable

Line detector over the paint centreline, Hough then merge co-linear pieces, 11–28 merged segments
per frame with a median length of 150–370 px:

| frame | 0 | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 100 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| focal px | 2892 | 2982 | 3878 | 3468 | 1114 | 1188 | 1887 | 4680 | 1245 | 679 | 5069 |

Median **2892 px**, range **679–5069**. A factor of 7.5, and not a zoom ramp — the clip's focal
rises smoothly by the paint's reckoning while this jumps.

## Why, measured rather than guessed

Endpoint noise added to the *synthetic* segments, where the true focal is 2400 and everything else
is exact:

| endpoint noise | median f | p16–p84 |
|---|---|---|
| 0 px | **2400** | 2400–2400 |
| 0.25 px | 2381 | **2134–3236** |
| 0.5 px | 2315 | **1866–5629** |
| 1.0 px | 2276 | 1668–3137 |
| 4.0 px | 1828 | 1470–3380 |

**A quarter of a pixel of endpoint noise already gives ±25 %; half a pixel gives a factor of three.**
Real detected segments carry a pixel or two. That is the whole of the 679–5069 spread.

The cause is geometric and was flagged in the module's own docstring before any of this ran: this
clip's lens is long — 13–20° horizontally — so the two vanishing points sit tens of thousands of
pixels outside the frame, and a fraction of a degree at the segment becomes an enormous move out
there. The estimator is not fragile; the *configuration* is.

## What this means

- **The instrument is right and stays.** It is cheap, it has no shared machinery, and on a
  wide-angle clip — where the vanishing points are close and well conditioned — it should be sharp.
  The weakness is specific to long lenses, not to the method.
- **It does not arbitrate the 1.5×.** Its median lands between the two contenders, which is exactly
  the uninformative outcome, and its spread is larger than the disagreement it was brought in to
  settle. Quoting 2892 as a third opinion would be quoting noise.
- **Task #10 is still open**, and the remaining separation — distortion against rolling shutter
  against translation — has to be done on the pixel maps, not here.

## What would make it usable here

In rough order of expected return: fit each family's lines jointly for a single vanishing point
instead of taking the RANSAC intersection (a maximum-likelihood VP over many long segments is far
better conditioned than any pair); weight by segment length; and report a confidence interval per
frame so a bad frame is visibly bad rather than silently averaged in. None of that changes the
geometry — it changes how much of the available evidence is actually used, and right now the
answer is "two segments' worth".
