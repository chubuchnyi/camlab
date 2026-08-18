# PREDICTION, written before the measurement: the focal deficit is a constant of the method

Written 2026-08-18, **before `ARG_CRO` was touched**. This document exists so that what comes back
cannot be re-read as whatever it turns out to be. `docs/held-out-clips.md` sets the rule: write the
claim down first, run it once, report what came back, and do not re-tune against the held-out half.

## What was found on the working half

18 clips from `CRO_MOR`, `ENG_FRA`, `MOR_POR`, `NET_ARG`, solved by the shipped chain and compared
to WorldPose (`the-degeneracy-measured-against-truth-2026-08-17.md`):

| | |
|---|---|
| position error | median **3.69 m**, range 0.98–6.43 |
| focal ratio, ours ÷ truth | median **0.9790**, mean 0.9803, **sd 0.0162**, range 0.944–1.005 |
| position vs focal ratio | **r = −0.97** |
| fitted | `position = 97.2 · (1 − focal_ratio) + 1.44 m`, R² = 0.934, residual sd **0.42 m** |

The reading: camlab lands with a focal about 2.1 % short and a camera correspondingly near, which
is the focal/distance degeneracy. If that 2.1 % is a property of the METHOD, a single constant
correction removes 61 % of the position error — median 3.69 m → 1.44 m. If it is a property of
these four matches, it removes nothing and would make other clips worse.

**That is the question, and only a match that had no part in producing the number can answer it.**

## The prediction

Spending **`ARG_CRO`**, 14 clips — the largest held-out match, because this is the session's main
actionable result and deserves the tightest test available. `ARG_FRA`, `BRA_KOR` and `FRA_MOR`
stay held out.

Same pipeline, unchanged: ingest 240 frames, AVATAR's PnLCalib anchor, the shipped chain,
`bench_vs_worldpose.py --camera camera_polished.json`. No parameter is tuned between here and there.

On the clips of `ARG_CRO` that solve:

1. **The focal ratio's median will fall in [0.970, 0.988].** A ±0.9 % band around 0.9790 — about
   ±0.55 of the working half's own spread. This is the load-bearing one: it says the deficit is a
   constant of the method rather than of a stadium.
2. **The fit will transfer**: `97.2 · (1 − f) + 1.44` will predict the per-clip position errors with
   a residual sd of **≤ 1.0 m** (0.42 m on the working half, so 2.4× slack for a new match).
3. **The position/focal correlation will again be strongly negative, r ≤ −0.85** (−0.97 here).
4. **The median position error will fall in [2.5, 5.0] m** (3.69 here). This one is an outcome of
   the others rather than an independent test, and is listed so it cannot be quoted as a success on
   its own.

## What refutes it

**Any of 1, 2 or 3 failing means the constant focal correction must not be shipped**, and the 2.1 %
is a fact about four stadiums rather than about camlab.

Specifically:

* focal-ratio median outside [0.970, 0.988] → the deficit is not constant.
* residual sd > 1.0 m → the linear relation does not transfer, and the 61 % figure is a fit to
  eighteen points.
* r > −0.85 → the error is not dominated by the degeneracy on clips the fit has not seen.

**A failure is reported as a failure.** It will not be met by widening the band, dropping a clip, or
fitting a second model to `ARG_CRO`. If the prediction misses, the honest outcome is that a
correction cannot be justified from this evidence, and `ARG_CRO` is spent either way.

## What is NOT being claimed

That correcting the focal makes camlab *right*. The fit's intercept is **+1.44 m** — the part that
stays when the focal is exact — and nothing here explains it. Candidates named and untested: the
pitch template (105×68 is assumed, and this repo's own register says 68 m and 72 m score bit for
bit identically, so the width is not observable from paint), the principal point (which the truth
moves by 60 px between matches), and radial distortion (17–37 px at the corners, which camlab does
not model at all).

Nor that the paint metric is wrong. It answers "does this camera put the markings on the paint" and
answers it correctly. Being 3.7 m from the truth moves the pitch in the image by 6.5 px, and the
correlation between distance and image error is −0.19 — no image-space metric can charge a camera
for this.
