# The number under the overlay could not exceed 40 px, and the ruler could

**Reported:** "all the methods give a terrible result and none is different from what was there
before" — and, separately, "on the overlay there is always a value worse than `worst line`, why is
it always understated?"

Both are correct. The second is a bug with three compounding causes; the first survives being
measured properly.

---

## Why the headline was always smaller than the ruler

`residual.worst_line_px` was `max over markings of (that marking's MEDIAN sample distance)`, over
samples that found paint **within `match_px = 40`**. Three cuts, every one of which removes large
errors and only large errors:

1. **The bound censored, it did not just count.** `tree.query(..., distance_upper_bound=40)` returns
   infinity past the bound and those samples were dropped from the distance array. So 40 px was a
   ceiling no number this module could exceed.
2. **On the worst frames it returned nothing at all.** With 40–70 % of samples beyond the bound, no
   marking retained the 8 matched samples required to be scored, `worst_line_px` was `NaN`, and the
   panel showed a dash. The metric went quiet exactly where it should have been loudest.
3. **A median is not where a ruler lands.** A human measures a line at the end where it is furthest
   out. The median is the middle. On frame 0 that is 29.9 px against 32.9 px; on frame 30, 56 px
   against 82 px.

Measured across the fan clip with `scripts/bench_metric_ceiling.py`, before the fix:

| frame | reported `worst line` | same, uncapped | worst actual sample | samples with no paint within 40 px |
|---|---|---|---|---|
| 0 | 10.7 | 11.5 | 74.3 | 9 % |
| 30 | 15.8 | 17.9 | 61.7 | 9 % |
| 40 | **—** | 69.7 | 90.9 | 54 % |
| 50 | 19.6 | 63.0 | 156.0 | 70 % |
| 70 | **—** | 70.0 | 108.7 | 40 % |
| 80 | **—** | 45.6 | 84.8 | 50 % |
| **median of 11** | **13.3** | **21.2** | **73.6** | **27 %** |

The three blanks are the three worst frames.

## Two more faults found while measuring this

**The picture and its score were different cameras.** The overlay route projects with
`cx, cy = cam["cx"], cam["cy"]`; the residual route passed neither and defaulted to the image
centre. This clip is cropped off-centre, so its optical axis is 638 px outside the frame — for
`camera_axis.json`, the only solve fitted at the real axis, the number was computed 638 px away
from where the overlay was drawn. No ruler laid on that picture could have agreed with that number.

**`frame_residual` crashed on bad cameras.** Two error paths built `Residual` with five of its nine
fields and raised `TypeError`. Only a non-positive focal or a paintless frame reaches them, so the
metric failed precisely on the cameras worth measuring — `camera_ptz.json` could not be scored at
all, and the server returned 500 rather than "this camera is broken".

## What the numbers are once it is fixed

Bound now **counts** rather than censors: a sample past `match_px` is charged its true distance to
the nearest paint. That understates (the true error is to the paint the marking *should* have hit,
which is further away) but it cannot flatter, which is the direction a metric is allowed to be
wrong in. `n_unmatched` is still reported, because "no paint under this marking at all" and "45 px
off" are different claims about a camera.

Each solve scored under **its own** K, 40 frames of the fan clip:

| solve | worst line | worst spot | samples with no paint within 40 px |
|---|---|---|---|
| `camera_refit` | **30.4** | 47.8 | 2 % |
| `camera_ptz_refit` | 36.4 | 69.5 | 12 % |
| `camera_auto` | 39.2 | 59.8 | 7 % |
| `camera_axis` | 41.7 | 59.7 | 7 % |
| `camera_ptz` | 46.6 | 74.4 | 12 % |

**The first report stands.** Five solves — per-frame homography, refit, PTZ, PTZ+refit, and the one
fitted at the true optical axis — land between 30 and 47 px. That spread is not a difference a human
can see on a 1080 px frame, and none of them is close to right. The earlier claims of improvement
(54.0 → 24.3 px for refit) were `line_error`'s worst *matched* offset, which drops every model line
too wrong to match at all: a second self-selecting subset, measured the same way and wrong for the
same reason.

## What this does not explain

Five different parameterisations converging on the same error means the ceiling is **upstream of the
solver**. The candidates, with what is known about each:

- **#16, correspondence.** Overlap is measured against the full projected length, so 82 % of what
  looks like detector failure is a marking being rejected while sitting on its paint. Cheapest fix,
  largest measured share.
- **#14, what is being fed in.** Mowing stripes, shadow edges and goal nets enter as markings. Local
  appearance provably cannot separate them (`local-appearance-cannot-find-markings.md`).
- **The principal point.** Four of five solves were fitted at the image centre on a clip whose axis
  is 638 px outside the frame. `camera_axis` is the control and it is not better — but it is also
  the only one whose K was right, so this is untested rather than refuted.

**Not** lens distortion: real markings bow 0.37 px, in a random direction, and it does not grow with
radius (`lens-distortion-is-not-the-error.md`).
