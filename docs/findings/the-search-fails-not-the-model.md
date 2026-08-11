# A human fitted frame 28 to 3.6 px. The solver, on the same frame, sits at 32.2

Frames 28 and 29 were aligned **by hand** in the viewer, by eye, with the comment "this is the most
I could manage". They are the most useful thing measured in this repo so far, because they separate
three things that had been indistinguishable: whether the model can fit, whether the objective can
see a good fit, and whether the search can find one.

Answers: **yes, yes, no.**

---

## What the hand fit did

Scored with the paint metric (`frame_residual`, distance to painted centreline — no line detector
involved), each camera under its own K:

| frame 28 | focal | position | worst line | worst spot | scored samples | markings |
|---|---|---|---|---|---|---|
| solved | 3144 | (4.1, −76.6, 23.5) | **32.2 px** | 33.7 px | 300 | 8 |
| by hand | 3436 | (−3.0, −78.6, 25.2) | **3.6 px** | 13.2 px | 288 | 8 |

Nine times better on the same number of markings and 96 % of the samples, so this is not the
coverage collapse that `compare()` exists to refuse — the camera did not improve by pushing
markings out of frame.

Frame 29 went 67.9 → 34.5 px but its samples fell 331 → 178 (54 %). By the repo's own coverage
floor that is **no verdict**, and it is recorded as one.

## The model is not the ceiling

3.6 px was reached with the current 7-parameter camera, the current pitch dimensions, **no
distortion term**, and the principal point at the image centre — the one this clip does not have
(its optical axis is 638 px outside the frame). Everything that had been proposed as a missing
piece of the model was absent, and a human still got the overlay onto the paint.

So the ~30–47 px band that all five solves sit in (`the-metric-had-a-ceiling.md`) is not the model
failing to represent the frame.

## The objective is not the ceiling either

`refit.objective` on frame 28, with the same detected segments:

| | line_error worst | matched | refit objective |
|---|---|---|---|
| solved | 33.7 px | 6 of 7 | 93.7 |
| by hand | 3.9 px | 6 of 7 | **63.9** |

It prefers the hand fit, correctly. And it is a genuine local optimum: running `refit_frame` **from**
the hand fit leaves it there — 63.9 → 63.6, paint 3.6 → 3.9 px.

Note what 63.9 is made of: 3.9 px of real error plus a flat `MISS_PX = 60` for the one marking with
no correspondence. Fifteen times the error being minimised is a constant that depends only on
whether a line matches at all.

## The search is

`refit_frame` from the solver's own seed on frame 28: objective 93.7 → 77.3, paint 32.2 → 16.5 px.
It improves and then stops, 14 points of objective short of a minimum that exists and is stable.

Two attempts to spread the good camera across the clip, both measured, one of them useless:

**Holding the position at the hand-fit point and refitting focal and rotation per frame — no
effect.** 7 frames of 15 improved, median worst line 40.3 → 45.9 px. Frame 112 ran the focal into
its 20000 px bound. A coin flip is not a result and is recorded as one.

**Seeding each frame from the previous frame's refit, starting at the hand fit — good for about
three frames.**

| frame | auto | chained from 28 |
|---|---|---|
| 29 | 67.9 | **5.5** |
| 30 | 56.4 | **8.8** |
| 31 | 67.4 | **14.7** |
| 32 | 46.6 | 35.7 |
| 34 | 58.4 | 46.8 |
| 36 | 30.3 | 47.0 |
| median of 20 | 50.4 | 49.1 |

Ten times better immediately next to the anchor, decaying to nothing over five frames, no gain
across the run (9 of 20 improved — again a coin flip, again recorded as one).

The chained position barely moves: X −2.9 → −1.8, Y −78.6 → −79.5, Z 25.2 → 26.1 over twenty
frames, focal 3441 → 3554. It is not diverging. It is **failing to follow** — the operator is
panning and zooming and each single Nelder-Mead step cannot keep up, so the camera falls behind the
frame a little at a time until the correspondence breaks.

For contrast, the unconstrained per-frame solve wanders 11 m of standard deviation in X and 7.7 m
in Z (p10–p90: X 2.1 → 30.7 m, Z 9.6 → 25.9 m) across a clip shot by one person from one seat.

## What follows

The next thing to try is **propagating** the camera between frames instead of copying it: fit the
frame-to-frame homography (`measure/pixel_motion.py` already does this), carry the camera through
it, and refit from there. That gives the search a seed that has already moved to roughly the right
place, which is the one thing the chain above was missing. It is also what pitch3d's `--camera-carry`
does, so the idea is not new — only untested here.

Second: the `MISS_PX = 60` term dominating the objective means the search is mostly optimising
correspondence count, not fit. That is #16's territory — overlap measured against the full projected
length rejects markings that are sitting on their paint.

Third, and cheapest: **more anchors.** One hand fit is worth about ±3 frames, so a 120-frame clip
would need roughly twenty. That is a real cost, but it is a known one, and the manual layer already
exists (ADR-0002, `camera_manual.json`, kept separate from the solve on purpose).

## Not the ceiling, on measured evidence

- **Lens distortion** — markings bow 0.37 px, random direction, no growth with radius
  (`lens-distortion-is-not-the-error.md`).
- **The model's degrees of freedom** — 3.6 px reached without adding any.
- **The principal point** — 3.6 px reached at the *wrong* one. Still worth re-solving under the
  right one (#19), but it can no longer be the explanation for the 30–47 px band.
