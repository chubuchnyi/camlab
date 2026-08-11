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
