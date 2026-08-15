# The ridge scales, measured from each clip's own paint — #38

Neither constant serves everything. `(2, 4, 7)` leaves `g11710897` scoring 4 markings a frame;
`(2, 4, 7, 14, 28)` takes `demo_14604680` from **1.42 px to 15.51** and `14604731` from 14.00 to
24.67 (`wide-ridge-scales-must-not-be-the-default-2026-08-15.md`). So it is not a constant.

## Reading the width without a camera, and without a scale

`paint.painted_width_px` thresholds every pixel against its own neighbourhood, keeps what is inside
the playing surface and is not turf, and takes the distance transform of what is left: twice that
is the local line width. No camera, no correspondence, and — crucially — **no ridge scale**, or the
measurement would be choosing its own input.

**The 90th percentile is the wrong statistic, and that cost an hour.** The wide lines are the near
ones and they are a small share of the painted pixels, so they live in the tail. p90 tops out at
10 px on every clip here, under what `(2, 4, 7)` already covers, and the ladder came back
`(2, 4, 7)` for every clip — including the two measured to need more. The 99th separates:

| clip | p90 | p99 | ladder | what a blanket wide set did |
|---|---|---|---|---|
| `MOR_POR_181952` | 8.8 | 20.0 | `2,4,7,13` | helped |
| `ENG_FRA_232015` | 5.6 | 18.2 | `2,4,7,13` | helped, 2.97 → 2.52 |
| `g11710897` | 10.0 | 18.4 | `2,4,7,13` | helped, markings 4 → 6 |
| `demo_14604680` | 7.2 | 14.0 | `2,4,7` | **wrecked it, 1.42 → 15.51** |
| `14604731` | 6.0 | 10.4 | `2,4,7` | hurt, 14.00 → 24.67 |

The ladder always starts at `(2, 4, 7)` and only extends: the far paint is narrow on every clip
measured, and dropping the small scales to chase the wide ones is how a clip loses its distant
markings. A scale answers for a line about twice its own size, so the ladder stops at the clip's
own p99 — which is why nothing here gets 28, and 28 looks like what did the damage.

## Twelve clips, re-solved, against the shipped constant

| clip | ladder | markings | across px | supported frames |
|---|---|---|---|---|
| `g11710897` | `2,4,7,13` | **4 → 8** | 10.50 → 19.69 | 38 → **40** |
| `ENG_FRA_232015` | `2,4,7,13` | 9 → 9 | 2.95 → 2.93 | 180 → 180 |
| `MOR_POR_181952` | `2,4,7,13` | 2 → 2 | 24.01 → 24.01 | 0 → 0 |
| the other nine | `2,4,7` | unchanged | **bit for bit** | unchanged |

**Nothing regressed**, which is the whole difference from the blanket set. Nine clips are
untouched because they were already right. `g11710897` doubles its markings — and does better than
the blanket wide set managed there, which reached 6.

`g11710897`'s `across` rising 10.50 → 19.69 is the same shape as the sky fix: a max over eight
markings is a harder question than a max over four, and the repo's rule is to read the count first.
40 of 40 frames now carry a verdict where 38 did.

## Shipped

`solve/pipeline.run` derives the ladder per clip when nothing else says otherwise, and reports it as
a stage line. The override chain is unchanged — auto → `CAMLAB_RIDGE_SCALES` or the viewer's *line
widths* selector → the shipped default — so a caller that names a set still gets it.

`RIDGE_SCALES` itself stays `(2, 4, 7)`: it is what a module gets with no clip in front of it, and
that is the right answer to a question asked without one.

## What this rests on

Three clips out of twelve move, and two of the four that motivated the threshold sit at 14.0 and
18.4 — a margin, not a separation. What makes it shippable is not the margin but that the nine
unchanged clips are unchanged **bit for bit**: the rule cannot hurt a clip it does not fire on, and
where it fires it was measured against both constants.
