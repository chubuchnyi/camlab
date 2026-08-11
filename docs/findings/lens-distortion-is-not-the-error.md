# The lines do curve — by a third of a pixel, and not because of the lens

**Question asked:** a real lens bends straight lines, and every stage of this repo assumes they are
straight. How is that resolved, and should curvature limits be added?

**Answer, measured:** the bending is real and it is 0.37 px. The residual it is offered to explain
is 14–24 px. And its *direction is random*, which a lens cannot produce.

---

## What assumes straightness

All of it, so the question is fair:

| Stage | Assumption |
|-------|------------|
| `lines.merge_collinear` | pieces fuse only within 1.5° and 6 px of one infinite line |
| `line_error.compare_line` | a straight model segment against a straight detected one |
| `line_error.world_family` | two families, each perfectly parallel in the world |
| `solve.vanishing` | exact straightness — a curve has no single vanishing point |
| `core.field.straight_markings` | anything >5 cm off straight in the world is excluded outright |

A curved marking arrives at `merge_collinear` as several chords that disagree in angle, and gets
split into separate "markings" rather than bent. So the failure mode would be silent fragmentation,
not a visible error — which is why it had to be measured rather than reasoned about.

## The measurement

Connected runs of painted centreline, no line detector involved (a straight-line finder cannot be
used to ask whether lines are straight). Kept only runs longer than 120 px that a parabola fits to
better than 1.2 px, so what is measured is a smooth single marking and not a junction of two.
**Sag** is the parabola's departure from its own chord at mid-span.

| | fan clip (phone, cropped) | broadcast clip (long lens) |
|---|---|---|
| clean markings | 514 | 441 |
| median span | 202 px | 279 px |
| **median \|sag\|** | **0.37 px** | **0.22 px** |
| 90th percentile | 0.90 px | 1.67 px |
| bows *toward* the optical axis | 42 % | 51 % |
| bows *away* | 58 % | 49 % |
| \|sag\|, inner half of the field | 0.35 px | 0.27 px |
| \|sag\|, outer half | 0.37 px | 0.20 px |

Three independent reasons this is not lens distortion:

1. **The direction is a coin flip.** Radial distortion is a scalar function of radius: every
   straight line bows the same way relative to the optical axis — barrel out, pincushion in. 42/58
   and 51/49 are noise about zero. What is being measured is the ragged edge of painted turf.
2. **It does not grow with radius.** Distortion grows as r³. Here it is flat on the fan clip and
   *falls* on the broadcast clip.
3. **The scale is wrong by 40–65×.** 0.37 px against a 14–24 px residual.

The parabola's own residual after fitting is 0.39 px — the same size as the sag. The curvature
signal does not rise above the width of the paint.

### The seven-sample trap

A first pass used a stricter filter, found **7** markings, and reported *100 % bowing toward the
axis, median 2.72 px* — a clean pincushion signature. It was small-sample noise; the same
measurement over 514 markings gives 42/58. Seven samples agreeing on a binary outcome happens by
chance about once in sixty. **Recorded because the wrong version was momentarily convincing**, and
it is the third time in this repo a confident verdict has come from an unchecked sample count.

## The earlier "not radial" claim was right, and my reason for it was wrong

I had argued the residual was not radial because it grows with `|v−cy|` (4.43 → 8.10) while falling
with `|u−cx|` (5.96 → 4.59). That binned around the **centre of the crop** — but this clip is cut
off-centre from a 1080×1920 source, so the optical axis sits at `(540, −334)`, 638 px away and
outside the frame entirely. Distortion is radial about the *axis*, so the test was measuring the
wrong radius.

Re-binned around the true axis, the residual does grow: 14.2 → 19.4 px. But around the crop centre
it grows *more steeply*: 14.1 → 24.5 px. If a lens were responsible, the true axis would give the
cleaner trend, not the weaker one. The conclusion survives; the argument for it has been replaced.

## Where curvature limits *do* belong — as a filter, not a tolerance

The suggestion was to bound the radius. That is worth doing, but in the opposite direction from
compensating for distortion:

**Real paint is straight to 0.37 px over 200 px. That is a very tight, camera-free constraint**, and
this repo's open problem (#14) is telling markings apart from mowing stripes, shadow edges and goal
nets when local appearance provably cannot
(`local-appearance-cannot-find-markings.md`). A mown boundary follows a machine's path and a shadow
follows whatever cast it; neither is obliged to be straight to a third of a pixel. So straightness
is a *rejection* test, and it costs one parabola fit per candidate.

Whether it separates the actual confusions is not yet measured — that is the next step, against the
frames a human already labelled (8, 13, 16, 17, 18).

**It must not fire on genuinely curved markings.** Six detections of 514 bow more than 3 px:

| frame | sag | span | implied radius |
|-------|-----|------|----------------|
| 31 | 13.66 px | 276 px | 698 px |
| 9 | 12.85 px | 212 px | 439 px |
| 32 | 10.32 px | 262 px | 831 px |
| 33 | 8.12 px | 247 px | 939 px |
| 34 | 6.45 px | 232 px | 1043 px |
| 35 | 5.43 px | 217 px | 1081 px |

Frames 31–35 are one object drifting steadily across the frame as the camera pans — a centre circle
or penalty arc. **These have no counterpart in the model at all**, because `straight_markings()`
excludes every arc, so today they enter correspondence as evidence that nothing can match. That is a
real defect and it is adjacent to #16, but it is a *missing model*, not a bent lens.

## What is still open

`measure/pixel_motion.py` fits homographies between frame pairs, and a homography cannot represent
distortion at any magnitude. It remains a candidate for the ~1.8× focal disagreement (#10) — but
0.37 px of bow is far too small to move a focal by 80 %, so it is a weak one.
