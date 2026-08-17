# What is true right now

Last measured 2026-08-16. Read this and `findings/landmines.md`; that is the cold start.

**There is a ground truth now, and it says the camera is 1.2–5.0 m out of position while the paint
metric prefers it that way.** 89 broadcast clips with per-frame measured `K`, `R`, `t` are on disk
(`~/AVATAR/models/worldpose/`, GT in `~/AVATAR/WorldPose/cameras/`); four are already ingested here
because the clip id *is* the WorldPose id. Against them `camera_polished.json` comes out 1.17 /
3.82 / 5.01 m from the real camera with 0.999× / 0.981× / 0.974× of its focal, and **86–99 % of that
displacement is along the line of sight** — and it scores *better* on `across` than the true camera
does (3.88 px against 30.01 on `CRO_MOR_194948`). So `across` is a floor, not a certificate: past
~3 px it cannot rank two cameras that both sit near the paint. The fourth clip,
`MOR_POR_181952`, is 16.24 m and **1.551× of focal** out — not thin evidence about a roughly right
camera, simply wrong. Full measurement, and what was *not* established:
`findings/the-metric-cannot-see-depth-2026-08-16.md`.

**A run directory is only as current as its last complete run.** Until 2026-08-14 a killed chain
left the previous run's later stages standing, and eight of nine clips were in that state — six of
them with `camera_polished.json`, the chain's declared result, six hours behind the
`camera_smooth.json` it claims to be built from. `pipeline.run` now clears what it is about to
write. Numbers quoted from a run directory that predate this are suspect;
`findings/pitch-level-clips-2026-08-13.md` has the measurement.

---

## The chain works

A clip goes in, a camera comes out, and the camera is right by the only test that counts — the
projected pitch lands on the painted one, judged by eye as well as by the number.

| clip | **across** | worst line | worst spot | markings | no paint across | under 20 px |
|---|---|---|---|---|---|---|
| `fan` (1080×608, phone, stands, floodlit night) | **1.82 px** | 1.65 px | 15.54 px | 6 | 2 % | 120/120 |
| `broadcast` (1920×1080, professional) | **2.96 px** | 2.75 px | 12.14 px | 7 | 1 % | 60/60 |
| `CRO_MOR_194948` (1920×1080, one hand anchor) | **4.22 px** | 4.04 px | 13.87 px | 9 | — | 120/120 |
| `g11710897` (1080×1920, phone at the touchline) | 4.34 px | 3.09 px | 13.41 px | 6 | — | 38/40 · wider ridge scales |
| `g15449383` (1920×1080) | 4.47 px | 3.49 px | 72.60 px | **2** | **21 %** | not a verdict |

**Read the markings column first.** Every error here is a max over the markings a frame scores, so
on a frame holding two it is a max over two. `g15449383` was called solved on "40 of 40 frames under
20 px" and is not; `Residual.supported` now refuses that rather than leaving it to be noticed.

**`across` is the camera. `worst spot` is the camera plus the paint detector** — 7.9× larger on
`fan` for that reason alone, because a nearest-paint distance charges a hole in the detected
centreline to the camera, and a line cannot be displaced along itself. Full measurement:
`findings/worst-spot-is-the-detector-not-the-camera-2026-08-12.md`.

`g11710897` is the first pitch-level clip to complete the whole chain — 158 s, and it needs
`CAMLAB_RIDGE_SCALES=2,4,7,14,28`, because its near touchline is 34–54 px wide against a largest
shipped scale of 7. The remaining error is a real offset on that near line, ~13 px on frame 39
against a 4.34 px clip median, not a mis-solve.
`findings/25-the-chain-runs-now-and-the-camera-is-still-wrong-2026-08-14.md` — **and its section 4
is wrong**, see the correction at its end.

`CRO_MOR_194948` is the first clip solved from an operator's own anchor in the viewer, and it took
three fixes landing the same day to work at all: the solver did not read hand edits, the anchor
refit was position-locked, and the centreline extractor was not a thinning algorithm. Before them
it scored 2 markings at 26.84 px and no verdict.

## The pipeline

**anchors → carry → self-heal → shared centre → smooth → polish**, all six behind one button
and one call in `solve/pipeline.py`, whose docstring carries what each stage bought and why it
sits where it does. The chain's output is `camera_polished.json`, read off `STAGES` rather than
named in code. The measurements behind each stage are in
`archive/status-detail-2026-08-14.md`.

## What the numbers mean

**`across`** is the worst marking's median distance to its paint along that marking's own
normal — the camera alone. **`worst line`** is the same taken to the nearest paint in any
direction. **`worst spot`** is the worst single sample, and is the camera *and* the paint
detector together. Read all three, and read the markings count first. Longer, with the metric's
own history: `archive/status-detail-2026-08-14.md`.

## Two degeneracies, both measured, both real

**The pitch is exactly symmetric under a half-turn.** Rotate a solved camera 180° about the centre
spot and it scores *bit for bit* the same — 2.1 px on 307 samples either way. Nothing in the
markings can say which half is being looked at and no solver ever will. The viewer has a
`flip 180°` button; choosing needs something off the pitch, or an eye.

**Focal trades against distance on a plane.** The free solve strings its positions along a line —
99 % of the variance along one direction, 108 m of it — pointed 13–25° off the line of sight. That
line is not a trajectory, it is the degeneracy drawn in space. It is **not flat**, though: sliding
along it and re-refitting gives 1.89 px at the optimum against 4.33 px three metres away, so the
position is pinned to about a metre. It only looked flat because nobody had searched along it.

**And the optimum is in the wrong place.** Measured against the WorldPose ground truth 2026-08-16:
the solved camera sits 1.17–5.01 m from the real one, 86–99 % of it along the line of sight, with a
focal short by the matching 0.1–2.6 %. So the residual is pinned to a metre around a point that is
up to five metres from the camera. The pinning is real; what it pins to is not the answer.

## Editing by hand

Everything lands in `camera_manual.json`, laid over the solve, which is never rewritten — and
**the solver reads it**, which was not true until 2026-08-12. `solve/hand.py` is the one reader
and its docstring holds the three discriminators that were measured and refuted. The viewer's
controls and what each was worth: `archive/status-detail-2026-08-14.md`.

## Half the ground truth is kept back

WorldPose gives 89 clips from eight matches. Four matches are the working half and four —
`ARG_CRO`, `ARG_FRA`, `BRA_KOR`, `FRA_MOR`, 41 clips — are **held out and not measured on**, because
a claim cannot be checked against the evidence that produced it and this repo has retracted about
thirty conclusions that were right about the clips they were measured on. Split by MATCH, since
clips of one match share a stadium, a rig and a camera. `docs/held-out-clips.md` is the rule,
`scripts/worldpose_split.py` is the source of truth, and spending a match is a one-way door.

## Open, and why

Each of these has a findings doc with the numbers; what is here is the verdict and the pointer.

**#14 — tell a marking from a mowing stripe, a shadow edge, a net or an advertising board.**

*Recall is done* (2026-08-12). The "centreline" was the local maxima of a distance transform, which
is not a thinning algorithm and does not preserve connectivity — `fan` frame 0: 854 mask components
returned as **1823**. Zhang-Suen returns 846, the mask's own count. `g11710897` goes from **2 lines
a frame to 5**, and two is below `refit.MIN_MATCHED`, so that clip could not be fitted at all
before. `fan` gaps 4 % → 2 %.

*Precision now has a validation set* (2026-08-14,
`findings/14-has-a-validation-set-now-2026-08-14.md`). `scripts/harvest_negatives.py` labels every
detected segment against the clip's own camera: **3673 markings and 1321 non-markings** over six
clips, where the stated blocker had been twelve. **Length separates on every clip** (0.713–0.975)
and #17 was right — it measured on `fan`, the weakest of the six. `MIN_MERGED_PX = 100` still
filters nothing; ≥ 150 px keeps 92.4 % of markings and 40.0 % of the rest.

**Nothing is shipped from it.** Class separation is not the test — #17's re-solve sweep is, and it
has not been run. Three things in that doc are worth reading before touching this: the single-clip
answer was the *opposite* one, 130 of the negatives turned out to be arc chords and were found by
looking at a picture rather than a table, and the largest source of false lines on a broadcast frame
is the **goal net**, whose segments are long and which a length cut therefore does not reach.

Two earlier candidates are in `findings/11-is-blocked-by-14-2026-08-12.md`: turf support at a wide
scale, and "does paint continue past the segment's ends", whose sign was the **opposite** of the
guess because `merge_collinear` already extends a straight marking over its whole painted run.

*The older reading, kept because the mechanism is real* —
`findings/11-is-blocked-by-14-2026-08-12.md`. On `fan` frame 8 two of nine detected segments are
55–60 px from any marking, and both lie along the **join between the grass and the advertising
hoarding**. Feeding the generator the seven real ones moves the best hypothesis in the pool from
11.9 m to **3.7 m** and the focal from 28 % wrong to 2.1 %.

Every cheap signal is refuted with numbers: straightness points the *wrong* way on `fan`
(non-markings are straighter, 0.13 px against 0.20); cross-ratio passes 70 % of impostor quads;
length is a filter with 39 % leakage and actively *prefers* the hoarding join, which is 567 px long;
and an inset-from-the-surface-edge test, designed on frame 8, hurts on three of the seven frames it
was then swept over. Untried and geometric: whether a segment on the grass and one raised above it
transform differently under the frame-to-frame homography.

Also recorded there and deliberately not fixed: the turf test's hardcoded `s > 70` drops the
**sunlit** half of `g15449383` — the rejected pixels are *brighter* than the accepted ones — and
sweeping it 70 → 15 improves not one measured number.

**#11 — find the first camera automatically. It works on one anchor of six**, which is one more
than the register records: `bootstrap_clip.py fan --frame 0` returns **1.0 px over three probe
frames on 298 samples**, 3.11 m from the truth with the focal 1.7 % off, and reports the half-turn
twin correctly. The register's 10.7 px on 66 samples is out of date.

The other five print *"no plausible camera at all"*. On `fan` 40 the cause was a defect in the gate
rather than in the search — the arc test demanded 8+ arc samples and the operator had zoomed until
no arc was in the picture, so it threw out the **true** camera along with everything else. It now
abstains where it has no evidence, the same rule `MIN_SUPPORTING_MARKINGS` applies to markings.

Two register claims did not survive re-measurement: *"the right answer is in the pool 4.8 m from the
truth"* (11.9 m on `fan` 8, 2.6–2.8 m on `fan` 0 and 40 — it varies by frame) and *"choosing is what
fails"* (on `fan` 8 the pool's best is 11.9 m, so no chooser could find it).

**#23 — a camera that really travels.** Deferred: no such clip exists yet. The trap is written
down — a real dolly move and the focal/distance degeneracy look identical in the 3D view, and on a
pure plane translation and rotation are not separable at all.

## The one check that does not use the markings

Mowing stripes are evenly spaced **in metres**. Rectify through the camera and they become
periodic, and on `fan` the period holds at 11.00 m ± 2.3 % while the operator zooms 1.61×, with a
focal-to-period correlation of −0.19. Breaking the camera breaks it as predicted: focal ×1.25 gives
8.75 m, and 11.00 / 8.75 = 1.257.

Two cautions. Not every pitch is striped — `broadcast` is 3 frames of 20, and that is its turf. And
a **wrong camera looks the same as an unstriped pitch**, because stripes are only periodic once
rectified correctly. A check to run on a camera you already believe, never a way to find one.

## Ruled out, so nobody spends the afternoon again

- ~~**Lens distortion.**~~ **Re-opened 2026-08-16 — measured on one lens, and it does not
  generalise.** On that clip the markings bow 0.37 px in a random direction (42/58), which stands
  for that clip. The WorldPose ground truth carries **27–34 px** of it in the corners of all four of
  its clips here — 0.07 px at the optical axis, 15.32 px at 800–1100 px radius — and that is the
  whole of the 30 px `across` the true camera scores. It costs only 0.22 px at the median, so it is
  an edge-of-frame effect, not a global one.
  `findings/the-metric-cannot-see-depth-2026-08-16.md` §5.
- **The principal point.** 638 px apart gives 2.11 px against 1.78 px through the same chain. The
  camera's other six parameters absorb it. The consistency rule stands — a camera is valid only
  under its own K — but there is nothing to fix.
- **Random-search bootstrap.** 4 000, 20 000 and 60 000 candidates return the *identical* wrong
  camera.
- **OpenCV's global camera methods, two of three** (2026-08-14,
  `findings/35-bundle-adjustment-refuted-on-these-clips-2026-08-14.md`). `BundleAdjusterRay` is
  worse on the paint from four seeds and two clips — `fan` 1.54 → 18.35 px — because it fits one
  rotation to points at mixed depths, and at 1.5 m the pitch spans 2–100 m in one frame; masking
  the features to the pitch makes it worse still. `waveCorrect` is worse on both clips because it
  *invents* an up direction over a world frame this repo measures. Both replace a measurement with
  something a stitching pipeline has to assume. Only `focalsFromHomography` survived, and only on
  pairs **seconds** apart.
- **The focal from neighbouring frames.** Exact in theory and 96.9 % out in practice: it needs a
  few degrees of turn and consecutive frames at 30 fps give 0.06°. Seconds apart it works — 29 % at
  two, 10.8 % at four (`findings/the-focal-from-pixels-needs-seconds-not-frames-2026-08-14.md`).

## What can be measured without solving anything

`scripts/bootstrap_hint.py`, for narrowing somebody else's search rather than answering:

| | |
|---|---|
| focal from two perpendicular vanishing points, one frame, no naming | 4.4–6.3 % on four clips, 25 % on a fifth |
| focal from a homography seconds apart | independent of the above; where they agree, that is the confidence |
| does the camera turn or travel | `rotation_only_residual_px`, ~1 px per metre of translation |

**Gated in degrees of field of view, and the gate is the point.** Ungated, the vanishing-point
construction returned 97 px on `g11710897` and 305 on `g14604660` — 200° and 120° across, 94–95 %
out, and stated as confidently as the good answers. Seen from pitch level the pitch is edge-on, the
two marking families are nearly parallel in the image and their vanishing points collapse together.
It is ill-conditioned exactly where the pitch-level clips live, so it abstains there.

## Getting the camera out

`scripts/export_camera.py <clip>` writes `calib/<clip>.npz`, **schema 2**: `focal_px` and
`position` per frame, every key present on every camera, `zoom_ratio` and `centre_spread_m` so
"does this clip zoom" and "is this one camera" need no arithmetic. `world_to_image` is rebuilt from
the focal and pose beside it rather than copied.

pitch3d's schema 1 held `focal` as one scalar for a whole clip. Collapsing to it costs **65 % of
the accuracy** on `fan` — 1.69 px becomes 4.88 and five frames of thirty leave the band — and
nothing on clips that do not zoom. `read_npz` refuses schema 1 by name; there is no compatibility
branch, because pitch3d is being changed rather than accommodated.

## Hardware, and what it costs

CPU only. No GPU, no neural network, no ML runtime, nothing trained, nothing downloaded.
What that costs and what it buys: `archive/status-detail-2026-08-14.md`.

The whole chain is **2.05× faster** than on 2026-08-13 over **every clip in `runs/`** — 2891 s of
wall clock down to 1413 s across fourteen clips and 1160 frames, per clip **1.79× to 2.24×**. The
paint stage is 34 ms a frame from 66; scoring one camera against a frame whose paint is cached is
2.1 ms from 11.8; the chain detects each frame's paint 431 times a clip where it used to be 551
and the floor is 300; and SIFT is described once a frame per process rather than once per call.

**The camera did not move.** Not "the metric agrees" — the five camera files each chain writes were
compared byte for byte between the two trees on all fourteen clips: **70 files, none of them one
byte different**, and again on `g11710897` under a non-default ridge ladder. `check_paint_equivalence`
and `check_line_errors_equivalence` say the same thing one level down, including the adaptive and
auto thresholds and the painted width #38 derives its scales from.
`findings/making-it-fast-again-2026-08-16.md` has the tables and the nine benches that reproduce
them, and it **contradicts `findings/making-it-fast-2026-08-13.md` in four places**: the ~2×
ceiling on `ridge_map` (it was 10.9×), the 7 ms camera-dependent remainder (12–13 ms, and 95 % of
a warm score), "process parallelism, refuted" (the per-frame unit now gets 2.8× on eight workers,
not 1.0×), and the two stages — `_turf` and `_surface` — that its account of `paint_masks` never
named and that were 23 % of it.

Read that one first if you are about to make this faster. The older doc's own target — the
remaining 122 ms of `paint_masks` — was not where the chain's time was.

## Running it

```bash
.venv/bin/python -m pytest                    # 181 tests, ~12 s
bash scripts/deploy.sh                        # ship HEAD to the box and open the tunnel
bash scripts/tunnel.sh                        # just the tunnel, if it dropped
bash scripts/tunnel.sh --watch                # keep it up
```

The viewer does the rest: upload an mp4, it decodes and gets a labelled default camera, align one
frame by eye, press **solve this clip**.
