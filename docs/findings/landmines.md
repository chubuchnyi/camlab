# Landmines

Things that made a run wrong, a number wrong, or a session expensive, and that the code in front of
you did not predict. **One line each, added in the session it was hit** — scattering them across
commit messages and findings docs is how the same fact gets rediscovered three times.

Ordered by how much they cost.

---

## Measurement

- **Never compare medians without comparing sample counts.** The first M-1 probe returned a
  confident, wrong verdict this way, and the focal had run away to 87 px unnoticed. Coverage and
  physicality guards exist because of it.
- **Seven samples agreeing on a binary outcome means nothing** — it happens by chance about once in
  sixty. A curvature probe found 7 markings all bowing the same way, median 2.72 px, a textbook
  pincushion signature. Over 514 markings it is 42/58, i.e. zero.
  (`lens-distortion-is-not-the-error.md`)
- **A search grid can fabricate its own answer.** The pure-rotation test read 8–22 px of "motion" on
  a synthetic *known-zero* rotation, because that was its own grid step. Two opposite findings were
  published and retracted before the control was run.
- **Validate an instrument against a known injected error before believing it.** Every retraction
  above would have been caught by one synthetic case with the answer known in advance.
- **`compare_line` once solved for equal normal coordinate** and therefore returned identically
  `0.0` offset on every frame. A metric reading exactly zero is broken, not perfect.
- **Radial anything must be binned about the OPTICAL AXIS, not the image centre.** This clip is
  cropped off-centre from 1080×1920, so the axis is at `(540, −334)` — 638 px away, outside the
  frame. A radial test binned on the crop centre measures the wrong radius.
  (`lens-distortion-is-not-the-error.md`)
- **Overlap is measured against the full projected length**, so a marking projecting 11,115 px can
  never be 25 % covered by anything, and an exact match at 0.2 px offset is discarded at 24 %.
  82 % of what looked like a detector problem is this. (#16)
- **A bound that DROPS samples is a ceiling, not a bound.** `match_px = 40` deleted every sample
  with no paint within it, so no number the paint metric could ever return exceeded 40 px — and on
  the frames where the camera was worst, no marking kept enough samples to score and the readout
  went *blank*. A human with a ruler on the overlay read larger than the headline on every frame he
  tried. He was measuring exactly what was being thrown away. (`the-metric-had-a-ceiling.md`)
- **A per-marking MEDIAN cannot be checked with a ruler.** A ruler lands where a line is furthest
  out; the median lands in the middle. Frame 30: worst line 56 px, worst spot 82 px. Report both or
  the human is right and the number is wrong every time.
- **Score a camera under its OWN principal point.** The residual route passed none, so it scored at
  the image centre while the overlay route drew at `cam["cx"], cam["cy"]` — picture and number were
  two different cameras, and no ruler could have reconciled them.
- **Four of the five solves in `runs/fan` were fitted at the image centre**; only `camera_axis` uses
  the real optical axis. Comparing them under one shared K measures a camera nobody solved — the
  first run of `bench_metric_ceiling.py` did that and ranked `camera_axis` worst on its own K.
- **`Residual` was built with five of its nine fields on two error paths**, so `frame_residual`
  raised `TypeError` whenever the focal was non-positive or the frame had no paint. Only bad
  cameras reach those lines, so the metric crashed precisely on the cameras worth measuring.
- **Hand edits live on the GPU box, not in the repo.** `runs/` is a docker volume
  (`/vol/camlab_runs`), and `scripts/deploy.sh` ships `git archive HEAD` — so a human's manual
  alignment is invisible locally and a redeploy does not carry it back. Pull it before assuming
  `camera_manual.json` is empty. (`the-search-fails-not-the-model.md`)
- **A fix that is committed but not deployed is not a fix.** The clip-wide position control was
  repaired locally and struck a second time the same day, on the box, against a solve shipped an
  hour earlier — because `deploy.sh` had not been run since the commit. It took that camera from
  21.9 px to 41.7 px, 83 of 120 frames worse. Deploy after fixing something a human touches.
- **"The backend is down" was a dead ssh tunnel.** The container was up, the WSL IP unchanged, only
  the local forward had gone. `ss -ltn | grep 8100` before anything else; the tunnel has no
  supervisor and nothing restarts it.
- **A clip-scoped position edit silently destroyed a hand-aligned frame.** "position applies to the
  whole clip" writes the shared position over EVERY frame, including ones tuned by eye. The
  rotation survives, but a rotation aimed from a different point is a worse camera than the solve
  it replaced: frame 28 went 3.6 px → 41.1 px, against 32.2 for the untouched solve. It now backs
  the file up and reports how many hand positions it displaced.
- **A good camera seed is worth about three frames.** Chaining a refit from a hand-aligned frame
  gives 5.5, 8.8, 14.7 px on the next three and is back to ~50 px by the fifth. Judging a seeding
  strategy on its median over twenty frames hides that entirely — it reads 50.4 → 49.1, "no
  effect", when the first three frames are ten times better.

## Geometry and conventions

- **Image-direction grouping is order-dependent.** Families spread 11° in the image against an 8°
  threshold, so which lines grouped together depended on the order they arrived in. Group by
  **world** direction.
- **Roll must be read in the level basis.** `asin(right[2])` gives the roll only when the camera is
  already level — the one case that tests nothing.
- **`np.cross` on 2-vectors was removed in numpy 2.** Hit twice, in `pitch3d_scene.py` and
  `vanishing.py`.
- **A pre-merge length cut destroys what the merge exists to reassemble.** `LSD_MIN_LENGTH` at 60 px
  left five fan-clip frames with *zero* lines, having discarded every fragment of every real
  marking. The length that matters is the merged one.
- **Vanishing points are unusable on a long lens.** 0.25 px of endpoint noise becomes ±25 % of
  focal. Built, measured, not wired.
- **`straight_markings()` excludes every arc**, so the centre circle and penalty arcs are detected in
  the image with no model counterpart to match against.

## Viewer

- **Canvas sized to its parent is a feedback loop.** Use `position:absolute; inset:0`.
- **Fit-to-view on a bounding sphere is wrong for a wide scene** — iterate on projected corners.
- **`scene.background` paints over a transparent canvas.** Use `renderer.setClearColor`.
- **`flyStep` hoists, `const held` does not** — the navigation block must sit above the render loop
  or it is in the temporal dead zone.
- **rAF is frozen in a background tab.** "W did not move the camera" was not evidence of anything.
  `fly(keys, dt)` returns metres so it can be tested without a browser.
- **The viewer was hardcoded to `camera_auto.json`** and silently showed the old solve after every
  refit. A human caught it, twice.

## Environment

- **`docker exec` without `-i` reads no stdin.**
- **The image built without the `[cv]` extra** served the viewer happily and returned 500 from the
  residual route only.
- **Never `git add -A` in the AVATAR tree** — concurrent agents work there, and it picked up an
  unfinished `bench_principal_point.py` belonging to someone else.
