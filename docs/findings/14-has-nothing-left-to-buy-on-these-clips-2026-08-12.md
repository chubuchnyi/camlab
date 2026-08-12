# #14: measured on every ingested clip, and there is nothing left for it to buy

Measured 2026-08-12, starting from "11 % of `fan`'s marking samples have no detected paint across
them" and asking what a better detector would win. The answer, on the five clips on disk, is
nothing that can be measured — and two thirds of the 11 % was not the detector.

## Two thirds of the gap was the measurement

`_across_on_normal` walked a marking's normal and called it a crossing at `dist < 1.0`. Printing
the distance profile along one failing normal:

```
t=-6.0   dist=2.20      t=-3.0   dist=2.20
t=-5.0   dist=1.00      t=-2.0   dist=3.00
t=-4.0   dist=1.40      t= 0.0   dist=4.00
```

The minimum is **exactly 1.00** and the test was strictly below it. That 1.00 is not luck: the
centreline `paint.distance_from_mask` extracts comes out **disconnected** on a diagonal band —
consecutive skeleton pixels sit two apart — so a ray crossing between them cannot get closer than
one pixel. Fixed by walking each direction and reporting the first *minimum* rather than the first
value under a threshold, so the answer no longer inherits the tolerance.

| clip | no paint across, before | after |
|---|---|---|
| `fan` | 11 % | **4 %** |
| `broadcast` | 6 % | **1 %** |
| `g15449383` | 23 % | **21 %** |

Which relocates the whole question: missing paint is not a general problem, it is one clip's.

## That clip does not show the markings

`g15449383` scores two markings a frame. Projecting the model through its camera and counting what
lands in the image **at all**, before any paint test:

| marking | in the image | on the surface |
|---|---|---|
| touchline +y | 5 frames of 5 | 0 |
| halfway line | 5 | 5 |
| centre circle | 5 | 5 |

Three markings reach the frame and one of them never reaches the grass. Looking at frame 0 confirms
it: a low side-on shot in daylight, one straight line and one arc, the bottom third of the pitch in
deep shadow, advertising boards and empty stands filling the top half.

**No detector adds a marking that is not in the picture.** The two markings are found; the 21 % of
samples with no paint across them are on those two markings, and they do not become a third one.

## A real defect, found on the way, with no measured payoff

The turf test is `hue within ±7 of the frame's peak, and s > 70, and v > 70`. On `g15449383`:

| clip | right hue | passes turf | rejected pixels | accepted turf |
|---|---|---|---|---|
| `g15449383` | 35 % | **14 %** | V 126, S 54 | V 99 |
| `g11710897` | 41 % | 38 % | V 48, S 162 | V 251 |
| `g14604660` | 48 % | 45 % | V 106, S 21 | V 170 |
| `fan` | 85 % | 82 % | V 222, S 27 | V 195 |

Read the `g15449383` row twice: the pixels being **rejected are brighter than the ones accepted**
(126 against 99). This is not shadow being lost, it is the *sunlit* half of the pitch being lost,
because sunlit artificial turf in that stadium is washed out to S 54 and the floor is a hardcoded
70. It is the same disease `RIDGE_CONTRAST` already has written up in
`daylight-and-automatic-thresholds.md`: an absolute constant set on two floodlit clips.

So it was swept, 70 down to 15, on both clips end to end:

| s > | `g15449383` markings | gaps | across | `fan` markings | gaps | across |
|---|---|---|---|---|---|---|
| 70 | 2.0 | 22 % | 3.82 | 6.0 | 4 % | 1.98 |
| 45 | 2.0 | 23 % | 4.03 | 6.0 | 3 % | 1.98 |
| 25 | 2.0 | 22 % | 4.19 | 6.0 | 3 % | 1.98 |
| 15 | 2.0 | 21 % | 4.57 | 6.0 | 2 % | 1.98 |

The surface mask would grow from 14 % to about 35 % of the image and **not one measured number
improves**; `across` gets slightly worse. So the constant is left alone and written down here
instead. It is a real defect that will matter on a daylight clip that actually frames the pitch,
and it is not one today.

Otsu was tried as the automatic replacement and is wrong for this: it picks 135 on `fan` and 134 on
`broadcast` against the shipped 70, because the saturation inside the hue band there is unimodal and
Otsu splits any distribution in half. The cut wanted is *below* the turf mode, not at its middle.

## Where this leaves the task

On the five clips ingested, #14's two halves measure like this:

- **recall** — 4 % on `fan`, 1 % on `broadcast`, and on `g15449383` the markings are absent from the
  frame rather than missed. Nothing to win.
- **precision** — the clips where spurious lines actually exploded, `15449387` at 64 lines a frame
  and `15750079` at **1967**, are not on disk any more. `g11710897` and `g14604660` yield 7 and 6
  lines a frame, which is not a precision problem.

And what does block `g11710897` and `g14604660` is already written in
`what-blocks-the-other-clips.md`: neither has a starting camera, and the bootstrap that would find
one returns 10.7 px on `fan` — a clip that is solved. That is **#11**, not #14.

#14 should not be worked further until there is a clip on disk where a measurement says it costs
something.
