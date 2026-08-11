# It was not the residual. It was the simplex.

Eight frames of the fan clip are hand-aligned and land, evenly, at 4.8–5.5 px of paint error. That
made "did the search find the right camera" a question with an answer for the first time, so four
objectives could be compared instead of argued about. Each refits from the solve's own seed; each
is scored the same way, against the paint.

| | median worst line |
|---|---|
| the seed (`camera_auto`) | 34.7 px |
| **a human, by eye** | **5.1 px** |
| what shipped — worst \|offset\|, Nelder-Mead | 13.8 px |
| mean \|offset\| instead of worst, Nelder-Mead | 27.0 px |
| endpoint residual, Nelder-Mead | 29.3 px |
| **endpoint residual, Levenberg-Marquardt, soft-L1** | **2.0 px** |

The same residual is 29.3 px under a simplex and 2.0 px under least squares. **The residual was not
the problem and the optimiser was.**

## What the old objective fed back

    worst |offset| over matched markings  +  MISS_PX * (markings with no match)

One scalar, from about six lines, minimised by a derivative-free simplex over seven parameters.
Two things thrown away:

- **Every line but the worst.** Move the worst marking and the other five do not register.
- **The angle, entirely.** It was measured, returned by `compare_line`, and never used. A marking
  pivoted about the middle of its overlap reports an offset of *zero* — perfect by this objective —
  while both its ends are far out. That is the gap between `worst line` and `worst spot` in the
  viewer, and on `camera_auto` it is 38.4 px against 59.3 px.

## What replaced it

`endpoint_residuals`: for each matched marking of visible length `L`, shifted `d` and rotated
`theta`, both of its own ends miss by `d ± (L/2)·tan(theta)`. Offset and angle in one unit, with no
invented weight between them, and a **vector** rather than a scalar — so `least_squares` sees every
marking and a Jacobian.

`refit_frame`'s docstring argued a gradient method would stall on the steps the objective takes as
correspondences appear and vanish. Measured, that is wrong: a finite-difference Jacobian at
`diff_step=1e-2` steps over them cleanly and soft-L1 keeps one bad correspondence from steering.

## The whole clip

Anchored on five frames (0, 8, 19 hand-aligned; 60, 90 from the solve), carried through the pixel
homographies, refitted with least squares:

| | worst line | worst spot | samples | markings | under 20 px |
|---|---|---|---|---|---|
| `camera_auto` | 38.4 | 59.3 | 176 | 6 | 13/120 |
| `camera_carry` | 21.9 | 44.0 | 162 | 6 | 59/120 |
| **`camera_lm`** | **2.0** | **15.9** | 166 | 6 | **104/120** |

Coverage holds: 166 scored samples against `camera_auto`'s 176 and the same six markings per frame,
so this is not the flattering median a runaway camera posts on the handful of survivors. `worst
spot` falling 59.3 → 15.9 is the endpoint residual doing exactly what it was built for.

**Better than the human**, on 104 of 120 frames.

## What is still wrong

- **Sixteen frames are not under 20 px**, and they cluster: 66, 67, 70, 71, 75, 80, 81, 87 — the
  stretch between the two anchors that were taken from the solve rather than from a person. More
  hand anchors there is the cheap test.
- **The position still wanders**: std 1.9 / 3.6 / 1.0 m with a single-frame step of 10.8 m. Less
  than `camera_carry`'s 2.9 / 4.7 / 2.1 and 11.5 m, but a person in a seat does not do this. The
  focal/distance degeneracy on a plane is still being exploited, and the trajectory is still not
  renderable even though every frame's overlay is now nearly exact. That is #10, and it is now the
  largest open problem rather than a curiosity.
- **The fit disagrees with the human about which camera it is.** On frame 0 the human is at
  (−2.6, −81.5, 25.5) with focal 3575 and least squares at (3.5, −70.3, 22.2) with focal 3026 —
  twelve metres apart, both fitting the paint. Two cameras, one pitch plane, no way to choose
  between them from markings alone.
