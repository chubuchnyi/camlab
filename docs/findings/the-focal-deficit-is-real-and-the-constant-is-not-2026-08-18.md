# The prediction held on a held-out match, and the thing it was written to justify did not

Measured 2026-08-18 on **`ARG_CRO`**, 14 clips of a match no number in this repo had ever been drawn
on. The claim was committed first, at `58004d4`, and the code that scores it at `9fb18f2`, before
either had seen a figure from the match.

## The verdict, as the committed bands asked for it

Ten of the fourteen clips got a PnLCalib anchor and are in the test. Four did not and are out, by
the same rule that took five clips out of the working half's twenty-three — no anchor, or on
AVATAR's own `KNOWN_HARD` list. **Both conditions are settled before the chain runs**, which is what
makes them a filter rather than a result.

| prediction | band | `ARG_CRO` | |
|---|---|---|---|
| 1 focal ratio, median | [0.970, 0.988] | **0.9879** | pass, by 0.00015 |
| 2 fit transfers, residual sd | ≤ 1.0 m | **0.57 m** | pass |
| 3 position vs focal | r ≤ −0.85 | **−0.937** | pass |
| 4 position error, median | [2.5, 5.0] m | **2.76 m** | pass |

All four. And the honest report of that is not "confirmed" — it is this:

**Prediction 1 passed by fifteen ten-thousandths.** The median landed at 0.98785 against a ceiling of
0.988. Had the band been written [0.970, 0.987] — an equally arbitrary choice at the time — the
load-bearing prediction would have failed.

## What the pass actually says, and what it does not

The document's own words for prediction 1: *"it says the deficit is a constant of the method rather
than of a stadium."* Set the pass aside for a moment and read the two medians:

| | median focal ratio | correction it needs |
|---|---|---|
| working half, 18 clips, 4 matches | 0.9788 | **+2.16 %** |
| `ARG_CRO`, 10 clips | 0.9879 | **+1.23 %** |

**The two halves want corrections that differ by nearly a factor of two.** The band was ±0.9 %, wide
enough to admit a match needing half the correction, so it admitted one. The test was passed and it
was not sharp enough to answer the question it was written for — which is a fact about how I wrote
it, available for inspection since it was committed before the run.

What *did* transfer, and transferred well, is the **relation**. `97.2 · (1 − f) + 1.44` predicts the
per-clip position error of a match it was never fitted to, to a residual sd of 0.57 m with a bias of
−0.05 m, and the correlation on unseen data is −0.94. That is not a curve fit surviving its own
training set; it is the focal/distance degeneracy behaving the same way in a fifth stadium.

So the split is:

* **the mechanism is a constant of the method** — confirmed on data that had no part in producing it;
* **the size of the deficit is a property of the stadium** — 2.16 % against 1.23 %, and no single
  number serves both.

## Then whether to ship the correction is a measurement, not an inference

The first estimate said no, and it was arithmetic: push `ARG_CRO`'s focal up by the working half's
2.16 % and its median ratio goes from 1.2 % short to 0.9 % long, which the fit prices at about the
same error it started with — 2.62 m to 2.72 m, i.e. nothing, or slightly worse.

**That estimate is wrong, and it is worth recording why it was tempting.** It assumes the camera
stays put when the focal moves. It does not: correcting the focal and letting rotation and position
re-converge on the paint is a different camera from the one the fit describes. Measured on
`ARG_CRO_220954` — focal ×1.0216, then `refit_frame_lm`'s own residual with the focal held fixed:

    camera_polished          2.99 m from truth   focal 0.9921   paint 7.6 px
    focal corrected          2.06 m from truth   focal 1.0135   paint 9.8 px

The corrected camera fits the paint **worse** and stands a metre **closer to the truth**, with a
focal that overshot. Which is the degeneracy stated from the other end, and the reason no amount of
reasoning about the fitted line could have answered this.

`scripts/apply_focal_correction.py` is that operation. The correction cannot live inside the chain —
every stage fits the focal to the paint, so a corrected focal handed to the front is simply
un-corrected on the way through. It is post-processing or it is nothing.

The full run over all 28 measured clips is what decides it, and is not in this document.

## What is not claimed

That the intercept is explained. **+1.44 m survives a perfect focal** and nothing here says what it
is made of; the candidates named in the prediction are still the candidates — the 105×68 template,
the principal point, and the radial distortion camlab does not model.

That the paint metric is at fault. It answers "does this camera put the markings on the paint" and
the corrected camera scores worse on it while being closer to the truth, which is the metric being
right about its own question and blind to this one.

## The bug I nearly reported

The first verdict printed **28 clips**. `bench_vs_worldpose.py` walks every run directory, so the
file named `argcro.json` held the working half too, and the score was the held-out match pooled with
the very clips it was supposed to be independent of — 18 of the 28 rows carrying the result they
were meant to test. The tell was the count: 14 clips were ingested and 10 anchored, and no reading
of that gives 28.

Pooled, it read focal 0.9808 and r = −0.957. Alone, 0.9879 and −0.937. Both pass, which is exactly
why it was worth catching — a contaminated number that happens to agree is still not evidence.
`out/worldpose/argcro-only.json` is the ten rows the table above is computed from.

## Cost

`ARG_CRO` is spent and is in `SPENT_MATCHES`. `ARG_FRA`, `BRA_KOR` and `FRA_MOR` — 27 clips — remain
held out.
