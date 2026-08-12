# The problem, stated for someone who has not seen this repo

Read this, then `STATUS.md`, then `findings/landmines.md`. Everything below is measured; where it
is not, it says so.

---

## What camlab is for

One broadcast or phone clip of a football match goes in. A camera — position, orientation, focal
length, per frame — comes out, accurate enough that a 3D reconstruction of the same episode can be
rendered from a new viewpoint and **look right to a human eye**. Not a metric target. A person
looks at the model pitch drawn over the real frame and says whether the lines sit on the paint.

Two clips are in the repo. `fan`: 120 frames, 1080×608, cropped from a 1080×1920 phone video shot
from the stands at a floodlit night match, panning and zooming 1.6×. `broadcast`: 60 frames,
1920×1080, a professional camera at a different match.

## What works

**Both clips are solved**, and the second is checked against an outside source.

| | worst line, median | frames under 20 px | camera movement between frames |
|---|---|---|---|
| `fan` | 2.11 px | 120/120 | 0.00 m |
| `broadcast` | 3.98 px | 59/60 | 0.00 m |

On `broadcast` the answer lands 2.06 m from pitch3d's, fitted from PnLCalib keypoints by an
unrelated route, with focals agreeing to 1.1 % — while scoring better against the paint than it
does, 3.98 px against 9.49.

The chain is: anchor on one frame, **carry** the camera to the next through the image-to-image
homography and refit, **self-heal** the frames it loses by re-seeding them from their good
neighbours, collapse to **one shared centre** by searching the degeneracy line, then **smooth**.
`docs/STATUS.md` has the per-stage numbers and why each stage exists.

## What does not, and why it is not a matter of effort

**Getting the first camera automatically (#11).** Everything above needs a seed. With one
hand-aligned frame the chain reaches 2.11 px; with none it reaches 7.75 px and 100 of 120 frames.
Five ranking attempts on the automatic bootstrap moved the answer 113 m → 20.9 m → 54 m → 128 m
from the truth without landing it, and the generator is not at fault — the right camera *is* in its
pool, 4.8 m from the truth with the focal 11 % off.

Choosing is what fails, because two degeneracies make many cameras genuinely correct:

- **The pitch is exactly symmetric under a half-turn.** Rotating a solved camera 180° about the
  centre spot scores *bit for bit* the same, 2.1 px on 307 samples either way. No solver will ever
  choose; the information is not in the markings.
- **Focal trades against distance on a plane.** The free solve strings its positions along a line —
  99 % of the variance along one direction over 108 m — which is that trade drawn in space.

Both are measured, not argued. Breaking them needs something off the pitch: the stands, the
scoreboard, which way the teams attack, or a person.

**Telling a marking from a mowing stripe, a shadow edge or a goal net (#14).** Local appearance
provably cannot (`findings/local-appearance-cannot-find-markings.md`). Three geometric signals have
been measured since:

| signal | verdict |
|---|---|
| straightness | points the **wrong way**: non-markings are straighter, 0.14 px against 0.21 |
| cross-ratio | camera-free, selective on paper, and 70 % of impostor quads pass |
| length | the only one that helped — 216 px against 86 px, and a 100 px cut took 81 → 90 frames under 20 px |

Length is a filter, not a discriminator. Cheap geometric signals are exhausted.

## Where the code is

| what | file |
|---|---|
| move a camera to the next frame through the pixels | `src/camlab/solve/carry.py` |
| refine one frame — Nelder-Mead, and the Levenberg-Marquardt that replaced it | `src/camlab/solve/refit.py` |
| the whole chain as one call | `src/camlab/solve/pipeline.py` |
| the candidate generator for a first camera | `src/camlab/solve/bootstrap.py` |
| **what the refit minimises** — model lines against detected ones | `src/camlab/measure/line_error.py` |
| **the judge** — model markings against painted pixels, no detector involved | `src/camlab/measure/residual.py` |
| the arcs, and scoring a camera by where it puts them | `src/camlab/measure/ellipse.py` |
| the mowing stripes, in metres | `src/camlab/measure/stripes.py` |
| frame-to-frame homographies, SIFT + MAGSAC, no pitch model anywhere | `src/camlab/measure/pixel_motion.py` |
| line detection, Hough and LSD | `src/camlab/measure/lines.py` |
| the viewer and its API | `src/camlab/server/` |

**Two metrics, and they are not the same thing.** `line_error` compares model lines to *detected*
lines and is what the solver minimises. `residual` compares model markings to *painted pixels* and
involves no detector. Judge a camera with the second; it cannot be gamed by the first.

Read `worst_line_px` and `worst_spot` together. The first is the worst marking's own median; the
second is the worst single sample on it, which is what a ruler finds. A marking pivoted about the
middle of its overlap reports zero offset and is far out at both ends.

## The one check that uses no markings at all

Mowing stripes are evenly spaced in metres, so rectified through a right camera their period holds
while the operator zooms — on `fan`, 11.00 m ± 2.3 % across a 1.61× zoom, focal-to-period
correlation −0.19. Every other number in this repo comes from the painted lines and therefore
shares whatever the line finder gets wrong; this one does not.

It cannot find a camera, only confirm one, and not every pitch is striped.

## How to work here

- `.venv/bin/python -m pytest` — 89 tests, ~6 s. Green does **not** mean the pipeline works.
- The evidence is the rendered overlay plus the numbers from `scripts/bench_*` and
  `scripts/check_stripes.py`.
- **A human's eye outranks the metric.** It has been right against it three times this month: the
  ruler that read larger than the headline, the frame the bad-frame test called fine while a
  marking was 70 px out at its end, and the copy-a-neighbour fix that beat carry-then-refit on
  every frame it was tried on.
- **Count before concluding.** Three confident wrong verdicts in this repo came from unchecked
  sample sizes; seven samples agreeing on a binary outcome happens by chance about once in sixty.
- `findings/landmines.md` is where a new trap goes, in the session it is hit.
