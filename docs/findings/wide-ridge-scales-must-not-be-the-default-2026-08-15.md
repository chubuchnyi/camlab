# Wide ridge scales help four clips, wreck one, and must not be the default

Asked to make `RIDGE_SCALES = (2, 4, 7, 14, 28)` the default and run everything. The run says no.

Twelve clips, each solved twice from the same `camera_start.json` in the same order, so the only
difference is the scale set. `scripts/bench_ridge_scales.py`, judged by the verdict against the
paint. **Read the markings column first** — an `across` is a max over the markings a frame scores,
so a smaller number on fewer markings is not an improvement.

| clip | markings | across px | supported frames |
|---|---|---|---|
| `demo_14604680` | 8 → **7** | 1.42 → **15.51** | 60 → 60 |
| `14604731` | 3 → 3 | 14.00 → **24.67** | 56 → 53 |
| `g11710897` | **4 → 6** | 10.50 → 18.58 | 38 → **40** |
| `stadium_a` | 7 → 7 | 1.25 → 1.43 | 60 → 60 |
| `g14604660` | 5 → 5 | 1.78 → 1.81 | 40 → 40 |
| `14604731_Copy` | 6 → 6 | 1.28 → 1.36 | 180 → 180 |
| `CRO_MOR_194948` | 9 → 9 | 3.88 → 3.83 | 120 → 120 |
| `wp_194948` | 9 → 9 | 3.96 → 3.84 | 120 → 120 |
| `MOR_POR_181952` | 3 → 3 | 21.89 → 21.42 | 0 → 0 |
| `g15449383` | 2 → 2 | 5.90 → 5.56 | 0 → 0 |
| `NET_ARG_225042` | 8 → 8 | 5.73 → **5.06** | 60 → 60 |
| `ENG_FRA_232015` | 9 → 9 | 2.97 → **2.52** | 180 → 180 |

**`demo_14604680` goes from 1.42 px to 15.51 and loses a marking.** An eleven-fold regression on a
clip that was solved is the end of the argument: a default that does that is not a default. And
`14604731` nearly doubles, 14.00 → 24.67, losing three supported frames.

Against six clips whose gain is between 0.03 and 0.45 px. That is the trade, and it is not close.

## `g11710897` is the exception, and it reads backwards on purpose

10.50 → 18.58 px looks like the worst regression in the table and is the clearest win in it: the
markings go **4 → 6** and the supported frames 38 → 40. A max over six markings is a harder
question than a max over four, and the repo's own rule is to read the count first. This is the same
shape as the sky fix, where the error got worse and became true.

So the clip that motivated the change still wants it — as a per-clip setting, which is what
`CAMLAB_RIDGE_SCALES` and the viewer's *line widths* control already are.

## One number here is not comparable to the earlier one

`g11710897` was measured at 9.16 → 4.34 px on 2026-08-14 and reads 10.50 → 18.58 here. Different
seed: that run started from `camera_smooth.json` with the operator's twelve anchors, this one from
`camera_start.json`, which finds two. The A/B is internally consistent — both columns share a seed —
and neither column should be quoted against the other run's numbers.

## And two clips are missing from the table

`fan` and `broadcast` have no `camera_start.json`, so the harness skipped them: the two
best-measured clips in the repo are absent from the comparison that decides a global default. That
is a gap in the evidence, not a result, and it is why the conclusion here is "do not change the
default" rather than "wide is worse".

## Where this leaves it

`RIDGE_SCALES` stays `(2, 4, 7)`. The wide set stays what it is — a control in the panel and an
environment variable — and the clips measured to want it are `g11710897` and `MOR_POR_181952`,
both of which have paint wider than the shipped bracket. What is actually needed is a scale set
chosen **per clip from its own paint**, since the width is measurable without a camera; that is a
task, not a constant.
