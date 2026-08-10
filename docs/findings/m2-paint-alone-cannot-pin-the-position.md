# The paint alone cannot pin the camera's position

Measured 2026-08-10, on the fan clip, with `camlab.measure` and `camlab.solve.ptz`.

## What was being attempted

M2's model: one optical centre for the whole clip, per-frame rotation, per-frame focal, fitted
directly to the painted lines. The first fit produced a camera and it looked reasonable —

```
centre  (4.72, -75.05, 22.80) m      seed (4.63, -74.89, 22.81), moved 0.18 m
focal   300-6559 px                  106/120 frames solved
anchor-frame paint residual 5.34 px
```

— and a centre that moves 18 cm from its seed after four ICP rounds is not a converged fit, it is
a fit that never had a reason to move. So before tuning anything, the question was whether the
objective can tell one position from another at all.

## The measurement

For each candidate centre, every anchor frame was allowed to re-fit **its own** focal and rotation
against that centre — i.e. the best the model can do from there — and the paint residual scored.

**Along the optical direction** (the axis focal and distance trade off on):

| offset | centre | paint px | n |
|---|---|---|---|
| −30 m | (6.5, −103.7, 31.5) | **3.64** | 518 |
| −20 m | (5.9, −94.2, 28.6) | 5.65 | 571 |
| −10 m | (5.3, −84.6, 25.7) | 5.63 | 719 |
| **0** | **(4.7, −75.0, 22.8)** | **5.44** | **895** |
| +10 m | (4.1, −65.5, 19.9) | 5.29 | 1054 |
| +20 m | (3.5, −55.9, 17.0) | 4.92 | 712 |
| +30 m | (2.9, −46.4, 14.1) | **4.46** | 577 |

**Sideways** (perpendicular; a focal change cannot imitate this):

| offset | paint px | n |
|---|---|---|
| −30 m | 5.69 | 880 |
| −20 m | 4.83 | 839 |
| −10 m | 4.99 | 1222 |
| **0** | 5.44 | 895 |
| +10 m | 6.73 | 403 |
| +20 m | 6.78 | 123 |
| +30 m | — | 0 |

## What it says

**Along the viewing direction the objective is flat over ±30 m, and what slope it has points the
wrong way.** Both ends of the sweep score *better* than the seed. A camera 30 m further back, with
a proportionally longer focal, puts the markings on the paint just as well — because that is what
the focal/distance trade-off means, and a plane gives no depth cue to break it.

**The apparent improvements are the coverage trap, not accuracy.** At −30 m the residual is 3.64 px
on **518** samples against 5.44 px on **895** at the seed: it did not fit the pitch better, it
moved most of the pitch out of frame, where it goes unscored. `measure.residual.compare()` refuses
a verdict on exactly this ratio, and the refusal is right — this table is what it protects against.

**Sideways there is some signal, and it is still not a minimum at the seed.** −20 m scores 4.83
against the seed's 5.44 on a comparable count. So the position is weakly constrained across the
view and essentially unconstrained along it.

## Consequence for M2

The PTZ model is not refuted — it fits the paint about as well as 120 free cameras do, using one
position instead of 120 (`camera_ptz.json`: median 16.82 px against the free model's 16.73 px over
the same eight frames, n 1355 against 1666). What is refuted is the idea that **the paint alone
decides where that one position goes.** It does not, and any position it reports is one of a
family tens of metres long.

So M2 needs a second instrument, measuring something the pitch plane cannot: **image→image
homographies from feature matching.** A camera rotating about a fixed centre satisfies

```
H(i→j) = K Rⱼ Rᵢᵀ K⁻¹
```

whatever the scene is — no pitch model, no calibration, no focal anywhere in its derivation. Over
long frame gaps that relation is not degenerate in `f`, so it measures the focal independently and
breaks the trade-off that flattens the sweep above.

And it does something the paint can never do: it **tests the fixed-centre premise directly.** If
the camera really does turn about one point, a rotation-only model explains the measured motion.
If it translates, parallax makes that impossible, and the residual says so — on a signal that has
nothing to do with the pitch.

## Note on where this claim came from

pitch3d's `fit_rigid_camera.py` says the same thing in its own docstring — that the paint's focal
minimum is shallow, and that a second instrument is why the script exists. That was an inherited
claim, and camlab does not run on inherited claims. It has now been measured here, independently,
on a different clip and a different implementation, and it holds. It moves to **verified** in
[`../inherited-claims.md`](../inherited-claims.md).

That is the useful shape: not "pitch3d says so", and not "pitch3d is unreliable so ignore it" —
but "pitch3d says so, and here is our own measurement of whether it is true."
