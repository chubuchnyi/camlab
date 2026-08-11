# The problem, stated for someone who has not seen this repo

Read this, then `docs/findings/landmines.md`. Everything below is measured; where it is not, it
says so.

---

## What camlab is for

One broadcast or phone clip of a football match goes in. A camera — position, orientation, focal
length, per frame — comes out, accurate enough that a 3D reconstruction of the same episode can be
rendered from a new viewpoint and **look right to a human eye**. Not a metric target. A person
looks at the overlay of the model pitch on the real frame and says whether the lines sit on the
paint.

The probe clip is `runs/fan`: 120 frames, 1080×608, cropped from a 1080×1920 phone video shot from
the stands at a floodlit night match. It pans and zooms.

## Where it stands

**Not good enough, and the reason is now known.** Five different solves sit between 30 and 47 px of
worst-line error. A human hand-aligning one frame in the viewer reached **3.6 px on that frame**.

| | worst line, median over 40 frames |
|---|---|
| `camera_refit` | 30.4 px |
| `camera_ptz_refit` | 36.4 px |
| `camera_auto` | 39.2 px |
| `camera_axis` | 41.7 px |
| `camera_ptz` | 46.6 px |
| **a human, frame 28** | **3.6 px** |

That gap is the whole problem.

## What it is not

Each of these was proposed, measured, and ruled out. Do not re-propose them without new evidence.

- **Lens distortion.** Real markings bow **0.37 px** median over 514 samples on the fan clip and
  0.22 px on a broadcast control. The direction is a coin flip (42 % / 58 %), where radial
  distortion forces one sign, and it does not grow with radius. It is 40–65× too small to explain
  a 14–24 px residual. → `findings/lens-distortion-is-not-the-error.md`
- **Missing degrees of freedom in the camera model.** The 3.6 px hand fit used the existing 7
  parameters and nothing else.
- **The principal point.** The 3.6 px hand fit used the *wrong* one — the image centre, on a clip
  whose optical axis is 638 px outside the frame. Worth re-solving under the right one (#19), but
  it cannot be the explanation.
- **The metric.** It was broken and is now fixed; see below. The fixed metric still shows the gap.

## What it is

Three measurements, on frame 28, with the same detected segments:

| | `refit.objective` | paint worst line |
|---|---|---|
| the solve | 93.7 | 32.2 px |
| the solve, after `refit_frame` | 77.3 | 16.5 px |
| the human's hand fit | **63.9** | **3.6 px** |
| the hand fit, after `refit_frame` | 63.6 | 3.9 px |

Read those four rows together:

1. **The objective is right.** It scores the hand fit best.
2. **The hand fit is a stable optimum.** Started there, the refit stays there.
3. **The search cannot reach it.** From its own seed the refit stops 14 objective points short.

So the failure is **the search and its seed**, not the model, the metric, or the objective.

Two ways of spreading one good camera across the clip were tried and measured:

- **Hold the position, refit focal and rotation per frame.** No effect: 7 frames of 15 improved,
  median 40.3 → 45.9 px. One frame ran the focal into its 20,000 px bound.
- **Seed each frame from the previous frame's refit, starting at the hand-aligned frame.** Worth
  about three frames: 5.5 / 8.8 / 14.7 px on frames 29–31 against the solve's 67.9 / 56.4 / 67.4,
  and back to ~50 px by frame 36. No gain over 20 frames (9 of 20).

The chain does not diverge — it **fails to follow**. Position moves 1 m and focal 113 px over twenty
frames while the operator pans and zooms. For contrast the unconstrained per-frame solve wanders
11 m of standard deviation in X and 7.7 m in Z across a clip shot by one person from one seat.

→ `findings/the-search-fails-not-the-model.md`

## Where the code is

| What | File | Notes |
|---|---|---|
| initial solve, one homography per frame → focal + pose | `src/camlab/solve/per_frame.py` | writes `camera_auto.json`; `focal_from_one_homography` is a log grid + golden section |
| refinement | `src/camlab/solve/refit.py` | `objective`, `refit_frame` (Nelder-Mead, 7 free), `refit_ptz` (block coordinate descent, shared centre) |
| shared-centre PTZ model | `src/camlab/solve/ptz.py` | |
| **what the objective actually minimises** | `src/camlab/measure/line_error.py` | correspondence + signed offset per marking |
| paint metric, the independent check | `src/camlab/measure/residual.py` | distance to painted centreline, no line detector involved |
| paint and marking masks | `src/camlab/measure/paint.py` | |
| line detection | `src/camlab/measure/lines.py` | Hough and LSD, Hough currently wins — see the table in its docstring |
| viewer and API | `src/camlab/server/` | `app.py` + `static/` |

**Two metrics, and they are not the same thing.** `line_error` compares *model lines to detected
lines* and is what the solver minimises. `residual` compares *model markings to painted pixels* and
involves no detector. Judge a camera with the second; it cannot be gamed by the detector.

`refit.objective` is `worst matched offset + MISS_PX * (number of markings with no correspondence)`,
with `MISS_PX = 60`.

## The thing to fix next

**The seed.** The next thing to try is carrying the camera between frames through the frame-to-frame
homography that `measure/pixel_motion.py` already fits, rather than copying the previous camera or
re-solving each frame independently. That gives the local search a starting point that has already
moved roughly where the camera went, which is the one thing the chaining experiment lacked. pitch3d
does this as `--camera-carry`; it is untested here.

After that, in order of measured value:

- **#14** — mowing stripes, shadow edges and goal nets enter the solve as markings. Local appearance
  provably cannot separate them (`findings/local-appearance-cannot-find-markings.md`). Candidate
  discriminators: straightness (#17 — real paint is straight to 0.37 px over 200 px), and family
  geometry (#13).
- **#18** — `straight_markings()` excludes every arc, so the centre circle and penalty arcs are
  detected in the image with no model counterpart and can never match. An arc is also a *stronger*
  constraint than a line: a circle of known radius projects to an ellipse whose shape pins focal and
  orientation without per-line correspondence.
- **#19** — re-solve every method at the true optical axis.

## Two things already fixed this session, so the numbers above are trustworthy

**The paint metric had a ceiling.** `match_px = 40` dropped every sample with no paint within it, so
no number it returned could exceed 40 px, and on the worst frames it returned nothing at all and the
panel showed a dash. A human with a ruler on the overlay read larger than the headline on every frame
he tried — he was measuring exactly what was being discarded. Far samples are now charged their true
distance. → `findings/the-metric-had-a-ceiling.md`

**Overlap was measured against the wrong length (#16).** A model marking's required overlap was a
fraction of its *projected* length; a marking running toward the horizon projects to 11,115 px, of
which only a few hundred are on screen, so no detector could ever cover a quarter of it and the
marking was recorded as a MISS costing 60. Model lines are now clipped to the image first. Measured
effect: match rate **74 % → 92 %**, misses per frame **1.6 → 0.5**. Refitting under the new rule
moves the median worst line 33.6 → 29.6 px over 20 frames — 10 better, 6 worse, 4 unchanged, so the
median gain is real but the win count is not decisive at that sample size; the asymmetry is that it
rescues disasters (121 → 46 px, 81 → 54, 74 → 33) and costs a few px on frames that were already
fine.

## How to work here

- `.venv/bin/python -m pytest` — 66 tests, ~6 s. Green does **not** mean the pipeline works.
- `.venv/bin/ruff check src/ tests/ scripts/`
- `.venv/bin/python scripts/bench_metric_ceiling.py fan camera_refit.json 3` — score a solve.
- `bash scripts/deploy.sh` — ship to the GPU box and open a tunnel on `localhost:8100`.
- **`runs/` is gitignored and lives as a docker volume on the GPU box.** A human's hand alignment
  is invisible locally until pulled; `calib/fan-hand-aligned-2026-08-11.json` is the committed copy.
- The user's eye is the ground truth. On any visual question, make one small change and let them
  judge; believe their verdict over a headless check.
- Sample sizes have produced three wrong confident verdicts in this repo. Seven samples agreeing on
  a binary outcome happens by chance about once in sixty. Count before concluding.
