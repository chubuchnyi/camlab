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
- **A distance to the nearest paint charges the detector's holes to the camera.** A line cannot be
  displaced along itself, so where the detected centreline has a gap the nearest pixel is found
  further ALONG the same line and the distance is large with the camera exactly right. `fan`'s far
  goal line: 11.75 px along against 2.20 across, and along wins on 63 % of worst spots. Read
  `Residual.worst_across_px` for the solver; `worst spot` is the solver and the detector together
  and is 7.9× larger for that reason alone.
- **Walking a ray in rounded integer pixels hops over a 1-px skeleton.** The detected centreline is
  one pixel wide, so a near-diagonal normal steps across it without ever landing on it: rounded
  sampling found paint across 70 % of `fan`'s samples, bilinear 97 %. The missing 27 % were about
  to be published as gaps in the paint detector — a defect in a subsystem that does not have it,
  manufactured by the measurement. Sample a distance transform bilinearly, always.
- **A hit test with a tolerance quantises everything under it to zero.** "First offset where
  `dist < 1.0`" reports 0.00 px for every sample within a pixel, and the metric then reads *exactly
  on the paint*. Add back what the tolerance swallowed (`t + dist_at_t`), and parametrise the test
  at offsets that are not multiples of the walk step or nothing notices when it is removed.
- **The pitch size is not the error, and 68 m wide is not measured.** Re-scoring `fan` at 100–110 m
  puts 105 m ahead by 20×, so that is settled — but 68 m and 72 m score **bit-for-bit identically**,
  because the touchlines never land inside the frame and on the surface. The width is assumed on
  this clip, not measured, and no number would move if it were wrong.
- **A local maximum of a distance transform is not a skeleton.** `inner >= dilate(inner)` shipped
  as the centreline extractor for months and does not preserve connectivity: on `fan` frame 0 the
  paint mask has 854 connected components and it returned **1823**, longest run 184 px inside a
  3408 px band. On one synthetic connected arc it returns **27 pieces**. Use a real thinning
  algorithm — Zhang-Suen is 30 lines and gives back the mask's own component count exactly.
  Downstream cost of the broken version: `g11710897` yielded 2 lines a frame against 5, and 2 is
  below `refit.MIN_MATCHED`, so the clip was unfittable for a reason nothing pointed at.
- **The viewer seeds the solve from whichever camera is SELECTED, and four of those names are
  files the chain writes.** Picking `camera_smooth.json` makes the last stage overwrite what the
  first stage read: a second press compounds on the first with no way back, and the manual layer —
  keyed by file name — ends up laid over a different solve than it was aimed against. Happened on
  `CRO_MOR_194948`. `pipeline.run` now snapshots such a seed to `camera_seed_used.json` first.
- **The `degenerate` flag outlives the solve it describes.** Four stages wrote
  `degenerate=src.get("degenerate", ...)`, copying their source's list straight through, so a frame
  the FIRST solve could not fit stayed flagged however well the chain later repaired it. `fan`
  115-118: focals of 300/20000/300/20000 in `camera_auto.json` — correctly flagged, pinned at both
  search bounds — and 4729/4727/4726/4716 in `camera_smooth.json`, fixed four stages earlier and
  still drawn in the viewer's "could not use this frame" pink. `buildStrip` had already been made
  to distrust it; the camera body, the frustum and the trajectory had not. Both ends now derive it:
  `camera_file.degenerate_from` at the write, `unusable()` in the viewer for files already on disk.
- **A clip-scoped position write is shape-identical to a hand aim.** The viewer's "position applies
  to the whole clip" tick-box stamps an entry on EVERY frame — the shared position with that
  frame's own rotation and focal — and 117 of `fan`'s 120 manual entries are that, not aims.
  Feeding them to the solver put `--anchor 0` on a 31.55 px anchor where the curated file holds
  5.30, and frame 51 on **102.01 px** against 2.17. Separable exactly, not by heuristic: in a
  broadcast entry the rotation and focal are bit-identical to the solve underneath.
- **Never rank two stores of the same thing by which store they are.** Where an anchor was recorded
  says nothing about whether it is a good one. `solve_carry.py` now scores every candidate against
  the paint and prints all of them with the choice; the run's own file winning by priority is what
  produced the 102.01 px above.
- **A test whose two inputs never name the same key never forces the choice it exists to test.**
  The first round of hand-anchor tests passed both defects above for exactly that reason: the
  manual store and the calib store were given disjoint frame numbers.
- **The solver never read the viewer's hand edits.** Every edit the panel writes goes to the run's
  `camera_manual.json`; `solve_carry.py` read `calib/<clip>-hand-aligned-*.json`; and
  `solve/pipeline.py` passed `--no-hand` unconditionally, so the "solve this clip" button threw the
  operator's anchor away on every run and said nothing. Two stores that did not know about each
  other. Cost on `CRO_MOR_194948` frame 0: **24.17 px on 2 markings** from the untouched default
  against **3.67 px on 10** from the operator's pose, with `anchors_hand_aligned: []` and
  `rotation[0]` bit-identical to the shipped default in the output.
- **"N/N frames solved" in the viewer counted `focal_px > 0`.** A clip that has never been solved
  reads 120/120 off its default camera's focal of 4938.77. An operator read it as a result. Whether
  a camera is RIGHT is the worst-line number, never a frame count.
- **The anchor refit was position-locked while the rest of the chain was free.** `solve_carry.py`
  passed `free_position` to the per-frame refit and not to the anchor one — the single frame the
  whole chain hangs off. 7.06 px locked against 3.67 px free.
- **The arc gate rejects the TRUE camera on a zoomed frame.** `bootstrap_clip.py` demands 8+ arc
  samples on paint, and on `fan` 40 and 80 the operator has zoomed to 4499 and 4781 px so no arc is
  in the picture at all — the solved camera scores `arc_n = 0` and is thrown out. "Cannot be
  measured" is being read as "failed", which is R-6 broken against the solver rather than against a
  player. It is why frame 40 reports "no plausible camera at all" on a pool that holds a camera
  2.6 m from the truth.
- **A filter designed on one frame works on that frame.** An "inset from the edge of the playing
  surface" test separated markings from the advertising-board join perfectly on `fan` frame 8,
  where it was designed. Swept over four frames of `fan` and three of `broadcast` it HURTS on three
  of them — `fan` 40 goes 2.6 m to 10.3 m — because what it removes elsewhere is the touchline,
  which genuinely runs near the surface edge and is the longest line in the picture.
- **Scale the CENTRELINE's coordinates, not the distance map.** Computing the paint at reduced
  resolution and resizing `dist` back up reports worst lines of **684 to 1381 px** — pure noise —
  because `centreline_pixels` takes the pixels where the transform is exactly zero and
  interpolation leaves almost none. Scaling the spine's coordinates instead gives the real answer:
  half resolution costs +0.11 to +0.82 px for 5×, quarter costs +1.16 to +2.35 px for 15×, and the
  marking COUNT is unchanged at every scale. The difference between nonsense and a usable trade is
  which of the two objects you stretch.
- **A sparse rewrite wins or loses entirely on how sparse the data is.** Working the set pixels
  instead of the frame made `thin` **17× faster** — the paint is ~20 000 of 2 000 000 pixels. The
  identical trick on `ridge_map` is **3× SLOWER**, because `val >= RIDGE_MIN_V` covers 62–98 % of
  the frame so there is nothing to skip, and fancy indexing gives up the contiguity the dense
  version runs on. Measure the density before reaching for it.
- **"10× headroom" from a primitive that answers a different question is not headroom.** A single
  `MORPH_TOPHAT` is 10 ms against `ridge_map`'s 109, and that comparison is meaningless: the top-hat
  asks "brighter than the neighbourhood" once, `ridge_map` asks a directional question twelve times
  with a turf condition on each. Written as morphology *exactly* it comes out 1.1–2.2×, the same as
  simply not reallocating. The real ceiling was ~2×, and I quoted 10.
- **This workload is memory-bound, and more cores do nothing.** Scoring 60 frames on 8 processes,
  each pinned to one OpenCV thread: **7.8 cores busy, 130 s of CPU against 20, and the same 16.8 s
  wall clock**. `paint_masks` costs MORE per pixel as the frame grows — 64, 76, 107 ms/Mpx at 0.1,
  0.5 and 2.1 Mpx — because `ridge_map` makes 24 full passes and falls out of cache. Parallelism
  spreads the waiting, it does not shorten it. What worked was removing the work: caching the paint
  per frame is 36.8×. `parallel.default_workers()` returns 1 on purpose.
- **OpenCV already threads its own operators, so measure before parallelising them.** `measure_pairs`
  runs at **10.8 cores busy** unaided; a process pool over it came out slower (10.4 s → 11.2 s), and
  `cv2.setNumThreads(1)` takes it from 12.7 s to 38.4. The repo's own line — "one core is the
  requirement, 342 ms on one thread against 324 on sixteen" — was reading the Python half of a job
  whose OpenCV half was already on ten cores.
- **A worst-line number is a max over MARKINGS, so two cameras seeing different amounts of pitch
  cannot be ranked by it.** The anchor chooser written on 2026-08-13 compared the operator's own aim
  on `g11710897` — **22.51 px on 7 markings** — against the seed's untouched pose at **16.61 px on
  3**, took the seed, and left the clip unsolvable: that pose has a focal 32 % out and had pushed
  four markings off the picture. `MIN_SUPPORTING_MARKINGS` already says this and I broke it the same
  day I was enforcing it elsewhere. Rank by marking count first, error second.
- **The turf detector called the SKY the pitch.** `_turf` keyed on the frame's dominant bright
  saturated hue with no bound on where that hue could be. On `g11710897` — a phone at the touchline
  at dusk — the biggest such region is the sky, so the peak came out at **108**, which is blue: the
  turf mask read **100 % over the top quarter of the frame and 2 % over the bottom half**, the
  "playing surface" was the sky, the paint detector found "markings" in the tree canopy, and the
  metric reported ONE marking on a frame with a line plainly visible in it. The operator's anchors
  went from 1 marking to **7** once the peak was looked for among hues grass can be. If a clip
  scores absurdly few markings, check what `_turf` locked onto before anything else.
- **A fix in the repo is not a fix in the RUNNING server.** The atomic write below was committed
  and then a SECOND `camera_manual.json` was corrupted anyway — `runs/g11710897`, same stray `}`.
  The uvicorn process had been up since before the commit. Restart the server after touching it,
  and check `ps -o lstart=` against the commit time before concluding a fix did not work.
- **"auto-fit this frame" could leave a frame WORSE than it found it.** `refit._accept` compares
  the solver's own worst matched offset, which is not the paint's worst line: on `g14604660`
  frame 30 a fit lowered its own objective while taking the worst marking from **1.37 px to 1.85**
  against the paint, and the button wrote it. A button an operator presses on an already-good
  frame has to be judged by the judge, not by the thing being optimised.
- **`camera_manual.json` was written non-atomically from five places and got corrupted.**
  `runs/g15449383/camera_manual.json` was found holding a complete JSON object followed by a stray
  `}` — two writers interleaving — and it holds the one thing in this project that cannot be
  recomputed. Four routes plus the background solve thread each did a plain read-modify-
  `write_text`. Now `_write_manual`: temp file in the same directory, `os.replace`, under a lock.
- **`conic_disagreement(a, b, pts)` ignored `a` entirely.** Its body was `_distance(b, pts)` — how
  far the POINTS are from `b` — while its docstring promised the distance between two curves. Four
  completely different fitted ellipses on one frame all "disagreed" with the same predicted arc by
  exactly 180.2 px, which is what gave it away. Validated after the repair against circles 20 px
  apart, which is the rule this repo already carries and I had not applied to it.
- **Hough returns several straight chords of one arc, and they look like several markings.** On
  `broadcast` frame 0 three of the four second-family detections are all the near penalty arc —
  marking 22, 16.9 m of path across a 14.6 m chord. The 2+2 correspondence generator then has one
  usable straight marking in that family instead of three, and cannot produce the right camera at
  all: its best candidate puts the pitch **248.5 px** from where the truth does, against 1.2 px on
  `fan` frame 0. Every detection is on real paint, so no #14 filter would touch it.
- **Distance between optical centres is not distance between cameras.** Every "the pool holds a
  hypothesis N metres from the truth" number in this project's #11 work was measured that way, and
  on `broadcast` frame 0 the hypothesis whose centre sits **3.83 m** from the truth carries a focal
  of **20000** — pinned at the upper bound, +355 % — and matches **zero** lines. Its centre is
  close and the camera is nothing like the truth. A camera is position, orientation and focal at
  once; compare where two of them put the same pitch, in pixels.
  (`bench_bootstrap_gates.reprojection_gap`)
- **A spurious line costs nothing on a solved clip and everything in the bootstrap.** #14's
  precision half was measured against the residual on `fan` and `broadcast`, found worthless, and
  parked — but on a solved clip the camera is already right and a non-marking changes nothing.
  Where it bites is choosing four correspondences out of nine: on `fan` frame 8, **two of nine
  detected segments are 55–60 px from any marking**, and removing them moves the best hypothesis
  anywhere in the pool from 11.9 m to **3.7 m** and its focal from 28 % wrong to 2 %. Measure a
  detector defect where the decision is made, not where the answer is already known.
- **Check what is IN THE FRAME before blaming the detector.** `g15449383` scores two markings, and
  a day went into why the paint was being missed. Three markings reach the image at all and one of
  those never reaches the grass — it is a low side-on shot of the centre circle. Count what
  projects into the picture first; it is one cheap query and it ends the question.
- **Otsu splits a unimodal distribution in half.** Offered as the automatic replacement for the
  turf test's hardcoded `s > 70`, it picks 135 on `fan` and 134 on `broadcast` — nearly double the
  shipped value — because the saturation there is one mode and Otsu always returns a cut. The
  threshold wanted was below the mode, not at its middle.
- **A conclusion measured on one clip is a conclusion about one clip.** Most of what was settled on
  2026-08-11 — the overlap fix, the straightness refutation, the cross-ratio, the principal point —
  was measured on `fan` alone. Re-checked on `broadcast` and a third clip, the straightness result
  appeared to reverse, and the reversal turned out to rest on **7 and 3 observations**. Both halves
  are the lesson: check another clip, then count what the other clip actually gave you.
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
- **A pipeline stage that copies `cx, cy` from its input propagates a wrong K forever.** All four
  stages read `cx, cy = float(src["cx"]), float(src["cy"])` and none compared them to the clip's
  own optical axis, so every shipped fan camera carried the image centre on a clip cropped 638 px
  off it. `write_camera` now records `principal_point_offset_px`. Measured cost: 0.88 m of camera
  position on a 70 m shot, and 1.6 % of focal — small, and it had to be measured to know that.
- **`write_camera` validated nothing until 2026-08-12.** `runs/fan/camera_ptz.json` holds fourteen
  frames with a focal of **0.0**, which is not a degenerate camera but not a camera. The crash it
  caused downstream was fixed in `frame_residual` months later; the thing that wrote it was not
  touched. Found by a reviewer reading the files rather than the code.
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
- **The ssh link to the box drops on anything large.** A 130 MB `scp` died at the end, and a
  `deploy.sh` died mid-build ("client_loop: send disconnect: Broken pipe"). Split large transfers
  into 30 MB chunks with a retry each and reassemble on the far side; `scripts/tunnel.sh --watch`
  handles the forward.
- **`deploy.sh` ships HEAD, not the working tree** — it says so in its own header, and it still
  caught me: the "copy from frame" control was deployed BEFORE it was committed, so the box served
  the version without it and a human reported the button missing. Commit, then deploy, and check
  `curl http://localhost:8100/ | grep <the-new-id>` rather than trusting a green deploy.
- **A fix that is committed but not deployed is not a fix.** The clip-wide position control was
  repaired locally and struck a second time the same day, on the box, against a solve shipped an
  hour earlier — because `deploy.sh` had not been run since the commit. It took that camera from
  21.9 px to 41.7 px, 83 of 120 frames worse. Deploy after fixing something a human touches.
- **"The backend is down" was a dead ssh tunnel.** The container was up, the WSL IP unchanged, only
  the local forward had gone. `ss -ltn | grep 8100` before anything else; the tunnel has no
  supervisor and nothing restarts it. `scripts/tunnel.sh` exists for this.
- **The WSL VM sleeps when nothing is attached, and takes dockerd with it.** Every probe wakes it,
  it answers, and it sleeps again — so the box is alive from a shell and dead from a browser. Tell
  by `uptime -p` inside WSL reading minutes when it should read days, and every container saying
  "Up 1 second" with `restartcount=0`. Hold it open with a running `wsl.exe` process
  (`tunnel.sh` does); no Windows configuration change is needed.
- **A dockerd back from an unclean stop runs containers whose port binding never got established.**
  `docker inspect` says `PortBindings=map[8000/tcp:[{0.0.0.0 8000}]]`, `docker port camlab` prints
  nothing, and the app inside logs a healthy "Uvicorn running on http://0.0.0.0:8000". Nothing is
  wrong with the image or the code. `docker restart` does not fix it — the container has to be
  recreated, i.e. run `deploy.sh`.
- **A clip-scoped position edit silently destroyed a hand-aligned frame.** "position applies to the
  whole clip" writes the shared position over EVERY frame, including ones tuned by eye. The
  rotation survives, but a rotation aimed from a different point is a worse camera than the solve
  it replaced: frame 28 went 3.6 px → 41.1 px, against 32.2 for the untouched solve. It now backs
  the file up and reports how many hand positions it displaced.
- **A good camera seed is worth about three frames.** Chaining a refit from a hand-aligned frame
  gives 5.5, 8.8, 14.7 px on the next three and is back to ~50 px by the fifth. Judging a seeding
  strategy on its median over twenty frames hides that entirely — it reads 50.4 → 49.1, "no
  effect", when the first three frames are ten times better.
- **A run directory does not know which run wrote it, so a killed chain leaves the PREVIOUS run's
  later stages standing.** They are ordinary camera files with ordinary names and nothing says they
  are stale. On `g11710897` the carry stage ran at 21:50 and reached focal 2100, the operator's own
  anchor; `camera_smooth.json` — the name `FINAL_CAMERA` resolves to, the file anything downstream
  opens — was still the 15:37 file at focal **2777**, the pre-fix seed that scores three markings
  where the anchor scores seven. The directory read as a completed chain.
  Checked across every run afterwards: **eight of nine clips were in this state**, and on six of
  them the stale file was `camera_polished.json`, the chain's declared result, sitting six hours
  behind the `camera_smooth.json` it was supposedly built from. `pipeline.run` now deletes every
  output it is about to write before it writes any of them, so a killed run leaves gaps and never
  a lie; `tests/test_hand_anchors.py` fails if it stops.
- **Re-measure a stage's published numbers when the stage under it is re-run.** The polish gains in
  `pipeline.py` were taken at 09:0x against a `camera_smooth.json` the multi-anchor re-solve
  replaced at 15:1x. They were true when taken and describe nothing that is on disk now.

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
