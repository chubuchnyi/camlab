# The principal point: the paint cannot measure it, the pixels can, and it is where we assumed

Measured 2026-08-10. Started as camlab task #9 — "we assume `cx, cy = W/2, H/2` and PnLCalib
returns a measured `principal_point`, so we are overwriting a measurement" — and ended somewhere
else.

## What the agent on pitch3d's render thread measured first

They tested the same hypothesis on the broadcast clip, by holding the centre and refitting
everything else (`scripts/bench_principal_point.py`, commit 49210c8), and refuted it:

- **`cy` carries no information.** Swept ±900 px — wider than the image is tall — and the paint
  residual moves 1.415–1.443. A 2 % spread.
- **`cx` has a minimum and it is impossible.** The optimum sits +600 px off centre, 81 % across a
  1920-wide frame, with the focal walking monotonically alongside (4318 → 4099). That is a valley
  in `(cx, focal)`, not the lens axis.

Same shape as camlab's own M2 result for a different parameter: the paint objective has flat
directions, and adding intrinsics to it finds valleys rather than answers.

## Verified here, on a different clip and implementation

Their control was to bin the residual by **axis** rather than by radius. Repeated on camlab's fan
clip, over 12 anchor frames, n = 1432:

| | | | | |
|---|---|---|---|---|
| **radius** | 6.02 | 5.22 | 5.09 | 5.17 |
| **\|u−cx\|** | 5.96 | 5.27 | 5.02 | **4.59** |
| **\|v−cy\|** | 4.43 | 5.36 | 6.19 | **8.10** |

**The radial view is flat and it is hiding a factor of two.** Horizontally the error *falls* toward
the edge; vertically it nearly doubles. Radial distortion is symmetric in u and v by construction,
so whatever this is, it is not the lens. On the broadcast clip the asymmetry ran the other way —
`|v−cy|` peaked in the middle and fell — which is the point: the artefact is clip-specific, and
radial binning erases it in both.

**Their landmine holds: bin the axes separately before calling any rise radial.**

## The part they could not test, and it flips the conclusion

Their probe scores against the paint. camlab has a second instrument that does not — image→image
homographies, where `K⁻¹HK` must be a rotation if the camera only turned, and `cx` enters that
condition. Different objective, different degeneracy.

Sweeping `cx` across 63 long-gap maps, refitting both focals at every step:

| cx | as % of width | residual | median f_i |
|---|---|---|---|
| 108 | 10 % | 0.0957 | 2693 |
| 252 | 23 % | 0.0951 | 2453 |
| 396 | 37 % | 0.0916 | 2453 |
| **540** | **50 %** | **0.0900** | **2235** |
| 684 | 63 % | 0.0994 | 2035 |
| 828 | 77 % | 0.1129 | 2235 |
| 972 | 90 % | 0.1269 | 2235 |

**A minimum at 540 px, which is exactly W/2, rising 41 % by the frame edge.** The pixels measure
the principal point, and they say it is at the image centre.

## What this settles

1. **The assumption is correct**, not merely convenient. It moves to **verified** in the register —
   verified by an instrument that has no pitch model in it, which is the only kind of verification
   camlab accepts.
2. **Task #9 is closed as refuted-then-confirmed.** Do not free `cx` or `cy` against the paint:
   that is a valley, and pitch3d's probe walked into it far enough to nearly report a corner
   optimum as a result.
3. **The 1.8× focal disagreement is not the principal point.** That was M2's leading hypothesis for
   it and it is now dead, which is worth more than a plausible story: whatever separates the
   pixels' ~2400 px from the paint's 4315 px is still unexplained, and one wrong explanation has
   been removed.
4. **The vertical residual growth is the next thread**, and it is not a lens. On this clip a larger
   `|v−cy|` is a larger distance along the pitch from where the camera aims, so the obvious
   candidates are the paint's own quality at range and the plane assumption, not the camera.

## Limit of this measurement

`cy` was held at `H/2` while `cx` was swept. The pixel instrument constrains it in principle by the
same argument, and it has not been checked. On a 1080×608 crop `cy` has a third of the lever arm
`cx` does, so it is the weaker of the two and worth doing before either is called settled.

---

# The crop moves the principal point, and the pixels found it to the decimal

Same day, following the above. The `cy` the section above left unswept turned out to be the
interesting one.

The fan clip's frames are `1080×608+0+1294` cut out of a 1080×1920 source. **A crop moves the
image relative to the lens; the optical axis stays where the lens put it.** So the axis sits at
`cy = 1920/2 − 1294 = −334` in crop coordinates — 638 px above the crop, further than the crop is
tall — while every piece of code here assumed `H/2 = 304`.

Sweeping `cy` through the image→image maps, which know nothing about the crop:

| cy | residual | median f_i | |
|---|---|---|---|
| −900 | 0.0594 | 3134 | |
| −500 | 0.0457 | 2339 | |
| **−334** | **0.0418** | 2122 | **source centre — predicted by arithmetic** |
| 0 | 0.0775 | 1746 | |
| **304** | **0.1005** | 2339 | crop centre — what we assumed |
| 900 | 0.1428 | 3134 | |

**The minimum lands on −334, the arithmetic value, to the decimal**, and the assumed value scores
2.4× worse in an instrument precise to 0.05. Monotone away from it in both directions.

`cx` was unaffected because the crop is full-width — which is why the earlier sweep found `W/2` and
looked like a confirmation. It was, but only of half the statement.

Fixed in `ClipInfo.principal_point`. **This is a defect in pitch3d too:** `--crop auto` crops, and
`camera_from_calibration` takes `cx, cy` as the centre of whatever size it is handed. Every cropped
clip there carries the same error.

## And it does NOT explain the focal disagreement

Which is the point of writing this section rather than stopping at the good news. Re-deriving the
per-frame focal from the homographies with the corrected axis:

| | paint focal (median) | vs pixels |
|---|---|---|
| assumed `cy = 304` | 4294 px | 1.87× |
| true axis `cy = −334` | 4385 px | 1.91× |

**Marginally worse.** The principal point was M2's second hypothesis for the 1.8× after the first
one died, and it is dead too.

## One of the 1.8× was mine

Comparing the pixels' focal against the paint's turned out to be comparing two different
populations: the long-gap pairs are weighted toward *early* frames, where the clip has not zoomed
in yet, while the paint median runs over all frames including the zoomed-in tail at ~4900 px.

Per pair, against that pair's own two frames, gap 58, n = 23:

| | paint / pixels |
|---|---|
| at frame *i* | **1.59×** |
| at frame *j* | **1.50×** |

So the real disagreement is about **1.5×**, not 1.8×. Still a disagreement, and now a cleaner one.

**Both instruments agree on the zoom's shape and disagree on its scale.** Over one gap-58 pair the
pixels give f_j/f_i = 2650/1691 = 1.57 and the paint gives 4472/3028 = 1.48. A near-constant
multiplicative offset between two otherwise-consistent measurements is a much more specific thing
to chase than "they disagree", and it is what task #10 now chases.
