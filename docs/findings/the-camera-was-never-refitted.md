# The camera was never recomputed, and when it is, it improves three- to fivefold

Measured 2026-08-10, prompted by the user asking the obvious question nobody had: *did you
recompute the camera?*

No. Every picture in this repo — the overlay, the offsets, the 100 px errors a human could see —
has been the **same camera all along**: `camera_auto.json`, the per-frame decomposition of
pitch3d's homographies, computed before any of the measurement work. What changed was the ruler,
not the thing being measured.

## Correcting the principal point changes nothing, and that is informative

The clip is cropped, so its optical axis sits at `cy = −334` and not at the crop's centre of 304 —
measured to the decimal by the image→image maps. Re-solving with the true axis:

| | worst offset, median over 10 frames | offset median | matched | missed |
|---|---|---|---|---|
| `cy = 304` (as shipped) | 97.3 px | 82.1 px | 43 | 26 |
| `cy = −334` (true axis) | 97.7 px | 82.0 px | 43 | 26 |

**Identical.** And it has to be: the homography is fixed, it maps the pitch into the image whatever
`K` is assumed, and decomposing it with a different principal point only redistributes the *same*
homography into different `(f, R, C)`. The projected line lands in exactly the same place.

So the principal point cannot matter to a per-frame model at all. It can only matter where
something is **shared across frames** — a PTZ fit with one position, where a wrong `K` forces a
wrong trade-off between focal and distance. Worth knowing before spending anything on it.

## What does matter: the solver optimised an objective now known to be broken

`solve/ptz.py` and the per-frame seed were both fitted by ICP against *nearest paint within
40 px* — the metric later shown not to measure camera error at all. So the question is not whether
the camera is optimal; it is whether it is anywhere near a camera that fits.

Local refit of `(focal, rotation, position)` per frame against the **line** metric:

| frame | as solved | refitted | Δ focal | Δ position |
|---|---|---|---|---|
| 0 | 29.5 px | **7.7 px** | −4 px | 0.38 m |
| 16 | 150.1 px | **30.6 px** | +48 px | 0.48 m |
| 17 | 169.1 px | **36.8 px** | +58 px | 0.78 m |
| 30 | 105.2 px | **14.9 px** | +154 px | 0.90 m |
| 60 | 27.9 px | 27.9 px | 0 | 0.00 m |

**Half a metre and a few per cent of focal, and the error falls three- to fivefold.** The shipped
camera is not slightly off; it is sitting somewhere the old objective liked, with a far better
camera a rounding error away in parameter space.

## The honest caveat

The refit's matched count falls to 4/7 or 5/7 on most frames, against a 40 px penalty per miss. So
part of the gain is the optimiser buying error by dropping a marking, and the true improvement is
smaller than the table suggests. The penalty needs to be a proper part of the objective rather than
a constant bolted on, and frame 60 did not move at all — the optimiser found no descent from
2/6 matched, which is its own signal that the correspondence there is too thin to fit through.

## What follows

1. **Re-solve every frame against the line metric**, with the miss penalty properly inside the
   objective rather than added afterwards.
2. **Then re-fit PTZ** against the same objective. It is the model that stands to gain from the
   principal-point correction, and it is the only one whose result would mean anything new.
3. **Do not spend more on the principal point for per-frame models.** Measured: no effect, by
   construction.

None of this can be ranked properly until the correspondence bugs are out (#14) — a fit that can
match fewer lines to look better is a fit that will.
