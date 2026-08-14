# #14 now has something to be measured against: 3673 markings and 1451 non-markings

#14 has been parked twice, both times for the same stated reason — **only 12 negatives existed to
validate a filter against**, and "a discriminator cannot be evaluated on a clip that has nothing to
discriminate" (`straightness-is-not-the-discriminator-length-is.md`). That reason is now gone.

`scripts/harvest_negatives.py` labels every detected segment by projecting the model through the
clip's own camera and asking whether any marking lands along it. Over six distinct clips:

| clip | markings | non-markings | frames used | skipped, camera unsupported |
|---|---|---|---|---|
| `fan` | 756 | 328 | 120 | 0 |
| `broadcast` | 335 | 112 | 60 | 0 |
| `CRO_MOR_194948` | 984 | 176 | 120 | 0 |
| `NET_ARG_225042` | 250 | 189 | 57 | 3 |
| `14604731` | 1189 | 586 | 179 | 1 |
| `g14604660` | 159 | 60 | 33 | 7 |
| **total** | **3673** | **1451** | 569 | 11 |

A label is only as good as the camera behind it, so frames are used only where the residual says the
camera is supported, and the 11 that were not are counted rather than dropped quietly.

## Length is the discriminator, and #17 was right — measured on its own worst clip

| length cut | markings kept | non-markings kept |
|---|---|---|
| ≥ 100 px — **what ships** | 100.0 % | 100.0 % |
| ≥ 150 px | 92.4 % | **37.9 %** |
| ≥ 200 px | 79.5 % | 26.3 % |
| ≥ 250 px | 68.5 % | 16.6 % |
| ≥ 400 px | 47.3 % | 2.6 % |

`MIN_MERGED_PX = 100` still filters nothing at all, exactly as #17 recorded for 60. And the
separation holds on **every clip**, which is what #17 could not show:

| clip | markings / others | separation |
|---|---|---|
| `NET_ARG_225042` | 250 / 189 | 0.976 |
| `broadcast` | 335 / 112 | 0.976 |
| `CRO_MOR_194948` | 984 / 176 | 0.942 |
| `g14604660` | 159 / 60 | 0.880 |
| `14604731` | 1189 / 586 | 0.817 |
| `fan` | 756 / 328 | **0.720** |

Separation is AUC folded to [0.5, 1]. `fan` is the **weakest** of the six — and `fan` is the only
clip #17 had. Its conclusion was right and was drawn from its own worst case.

## The single-clip answer was the opposite one, and I nearly shipped it

Measured on `fan` alone, `on_paint` — the share of a segment's length actually sitting on painted
centreline — beat length outright, 0.839 against 0.720, and it is camera-free, so it can run before
any solve. Across six clips it goes the other way:

| feature | `fan` alone | six clips |
|---|---|---|
| `length_px` | 0.720 | **0.863** |
| `on_paint` | **0.839** | 0.668 |
| `row_frac` | 0.692 | 0.510 |

This is the mistake the register already names three times, and the write-up was one step away.

## Three traps in the labelling itself

**The camera's optical axis is not the clip's.** `line_errors` recommended passing
`ClipInfo.principal_point`; that property answers "where is the axis in the SOURCE frame", and on a
cropped clip it is somewhere else entirely. `fan` solved at (540, 304), the property derives
(540, −334) — 638 px apart. Scoring one frame through the wrong one found **1 model marking and 0
matches** against 8 and 7, and the whole first run reported *zero* segments over 120 frames with
every frame "unsupported". It reads exactly like a clip with no markings in it. The docstring now
says to use the camera's own `cx`/`cy`.

**A marking broken in two puts one half in the negative class.** `_assign_in_order` gives each model
marking one detected segment, so the second piece is labelled junk while looking exactly like paint.
It is separable because the classes are cleanly bimodal in distance-to-nearest-marking: on `fan`, 66
of 394 negatives lie within 5 px of a marking, 67 within 20 px, and the remaining 328 have a median
gap of **54 px**. The cut sits in the empty middle and costs 17 % of the negatives.

**A feature can be saturated by its own definition.** My first straightness column selected the paint
within ±2.5 px of a segment and reported the maximum deviation over that same band, so it could
never exceed 2.5. It duly "separated" the classes at 0.842. A cut sweep exposed it immediately —
every threshold from 2.5 up keeps 100 % of both classes. It is kept in the output as a column with
its explanation attached, so the answer is not re-derived from it by accident.

## Also found: two run directories are the same file

`CRO_MOR_194948` and `wp_194948` have the same `source_sha256` (`d5ff718385caba60`) and produce
byte-identical numbers — 1404 segments, 984 markings, 420 others, 120 frames. Any claim of the form
"measured across N clips" that walks `runs/` counts this clip twice. `wp_194948` is excluded from
every total above.

## What this does not yet say

**Nothing here shows the solve gets better.** Class separation is not the test; #17's own standard
is, and it is the right one — raising the cut from 60 to 100 there bought nine more frames under
20 px while the median did not move, which is what told it the removed segments were carrying no
fit. The equivalent sweep at 150 / 200 / 250 px, re-solving each clip and judging by the paint, is
the next step and has not been run. Until it has, `MIN_MERGED_PX` stays at 100.
