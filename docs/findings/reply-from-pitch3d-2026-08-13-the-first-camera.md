# The first camera — how pitch3d gets one with nobody in the room, and what else camlab is missing

Written 2026-08-13 from `/home/chubuchnyi/AVATAR`, answering two questions asked together: *what
does pitch3d have that camlab does not*, and *how did pitch3d solve the first frame that camlab
still places by hand*.

Same rule as the 2026-08-12 exchange: every claim names the file, the line or the run it comes
from. Where nothing has been measured, it says so rather than estimating.

Two numbers in the first draft of this file were wrong and were caught by camlab's own
`inherited-claims.md` before it was committed. Both corrections are kept in place rather than
quietly fixed — §4.4 and §6.7. The register works.

---

## The answer in one line

**pitch3d has no first-frame problem because it never has to *find* a correspondence. Its landmarks
arrive already named.**

Everything in §1–§3 is a consequence of that one difference. §5 is what to do about it. **§6.1 is
the item worth more than all of them, and it needs no model, no licence and no GPU** — so if this
document is read in a hurry, read §6.1 first.

## 1. How pitch3d gets a camera on a frame it has never seen

`adapters/models/pnlcalib_backend.py` wraps the public **PnLCalib** field-calibration network —
two HRNet-v2-w48 heads, one for pitch *keypoints* and one for pitch *lines* (Gutiérrez-Pérez &
Agudo, 2024). Each frame goes in alone. What comes out is not "a painted line here": it is
**id → world**, resolved through PnLCalib's `keypoint_world_coords_2D` table, which the adapter
**imports from the installed checkout rather than copying**, so the mapping always matches the
weights actually loaded (`pnlcalib_backend.py:44-46`):

```python
wp = s["kw"][kid - 1] if kid <= _N_MAIN else s["ka"][kid - 1 - _N_MAIN]
uv.append([d["x"] * w_orig, d["y"] * h_orig])   # normalised → original image px
world.append([float(wp[0]), -float(wp[1])])     # metres, centre-origin, Z = 0
```

Two solver paths hang off that same front half:

| path | what it does | class |
|---|---|---|
| `detect_keypoints` | emits named image↔world correspondences **plus** point-on-line rows from the line head; downstream fit is a **RANSAC + confidence-weighted DLT** | `KeypointFieldCalibrator` |
| `calibrate_frames` | delegates the whole solve to PnLCalib's `FramebyFrameCalib` — points **and** lines, mode + RANSAC voting, PnL line refinement, **L/R plane disambiguation** — and returns a full pinhole | `CameraModuleFieldCalibrator` |

The floor is four correspondences: `solve_homography` refuses below
`2·n + m < 8 or n < (2 if m else 4)` (`calibration.py:254`), and RANSAC's minimal sample is
literally `rng.choice(n, size=4, replace=False)` (`calibration.py:356`).

**Four named points are a homography.** No hypothesis pool, no ranking, no seed, no chaining.
Frame 0 is solved exactly the way frame 59 is, and neither knows the other exists.

The temporal step comes **after**, not before. `scripts/fit_rigid_camera.py` re-solves the 60
independent 8-parameter homographies as one camera: `params = [focal, Cx, Cy, Cz, rvec per frame]`
— 4 + 3F against 8F (`fit_rigid_camera.py:329`). That is pitch3d's analogue of
`solve_shared_centre.py`, and it is a constraint on frames already solved, never a route to the
first one.

### The evidence it runs unseeded

- **`fan`, 1080×1920 portrait phone clip.** After `adapters/io/framing.py` measured the crop from
  the pixels (`1080×608+0+1294`, grass 29 % → 82 %), **PnLCalib solved 120/120 frames** where the
  raw uncropped frame solved **0 of 8**. 234 s on the GPU box. No human touched it.
- **This repo's own record.** `findings/bootstrap-progress.md`: *"Both clips that got there were
  handed a starting camera by pitch3d."* The answer was written down here before the question was
  asked.

## 2. That is precisely the half camlab's bootstrap fails at

`findings/bootstrap-progress.md` is unusually clear about which half is broken:

> the generator is right … 20 000 hypotheses yield 4680 physically plausible cameras in 12 s
> … **And the chooser is wrong** … Both land about 113 m from the true camera, on the far side of
> the pitch, scoring 137–198 samples where the true camera scores 300.

**Names delete the chooser.** There is nothing to rank when the correspondence is a dictionary
lookup. That 113 m twin is a camera which satisfies *anonymous* paint; it cannot satisfy "this
segment is `Small rect. left main`".

camlab has already measured, from the other direction, what names are worth.
`findings/11-is-blocked-by-14-2026-08-12.md`: feeding the generator the seven real segments instead
of nine detected ones moves the best hypothesis in the pool from **11.9 m to 3.7 m** and the focal
from **28 % wrong to 2.1 %**. Same quantity, bought with a hand instead of a model.

`findings/is-a-model-worth-training.md` reached the identical conclusion on the matching side:
*"A model with LINE CLASSES would fix all 11 — with names, correspondence stops being a search and
becomes a lookup."* Three documents in this repo point at the same missing input.

### Two things about camlab's own bootstrap worth stating plainly

**It is not wired to anything.** `scripts/bootstrap_clip.py` is complete and well argued, and it
appears in no `STAGES` entry, no `cli.py` subcommand and no HTTP route. The only mention in the
viewer is an apology (`server/static/index.html:976`):

```js
err(`${want} has no camera. Nothing here can make a first one from a clip alone yet — `
  + `that is the open problem (see docs/findings/bootstrap-progress.md).`);
```

**And its physical gate rejects the clip class this repo just opened.** `bootstrap_clip.plausible`
requires `5.0 < h.position[2] < 45.0`; `findings/pitch-level-clips-2026-08-13.md` records that the
operator's own camera on `g11710897` sits at **1.5 m**, so the bootstrap *"would reject the true
camera outright — before any paint is consulted."* Whatever fixes the anchor has to work at head
height, and one of the two candidate fixes has a stated broadcast prior in it.

## 3. The socket for names is already built here

`src/camlab/core/pitch.py:88` — `pitch_plane_line_segments` returns the 17 straight `Z = 0` pitch
lines keyed by **SoccerNet's own class names**, and the docstring says why:

> Class names are SoccerNet's, which PnLCalib's line head also emits, so a detection keyed by name
> looks up its world line here directly.

The receiver is written, tested, and in this repo's world frame — `seg()` carries the #118 `Y`
negation across the boundary *together with* the names, deliberately. Only the producer is missing.

## 4. What it costs — and why the model should still not go inside camlab

1. **Licence.** PnLCalib is **GPL-2.0-only**; its weights are SoccerNet-trained and SoccerNet is
   research-only by its own FAQ. pitch3d's mitigation is that it is never vendored — imported by
   dotted path from `$PNLCALIB_REPO`, weights on the box. `is-a-model-worth-training.md` already
   ruled on this and the ruling stands.
2. **Weight.** 131.9 M params across two heads, 2 × ~265 MB of checkpoints.
3. **Speed.** ~**4.2 s/frame on CPU**, 439 ms/frame on GPU — against camlab's **340 ms/frame for
   the entire chain on one core**. As a per-frame stage it would end the thing that makes this repo
   fast.
4. **It does not always produce a camera.** On `fan`, PnLCalib solved 120/120 frames and no
   realizable pinhole existed anywhere near them. pitch3d shipped that scene with a synthetic
   772 px stand-in and said so in the log; positions on the pitch were real (they come from the
   homography), a novel view did not exist.

   > **Correction, and camlab made it.** The figure pitch3d quoted for a week was **12 382 px**,
   > and `inherited-claims.md` shows it was measured in the wrong image space — `--crop auto` had
   > moved the homographies into a 1080×608 rect while the fit was handed 1080×1920, putting the
   > principal point 656 px outside an image 608 px tall. **The correct-space value is 18 313 px.**
   > The number was wrong and the conclusion is stronger, not weaker.

**camlab scores 1.82 px on that same clip, and that number is a real pinhole with a focal and a
position.** On the one clip where both repos have a result, camlab's is the better object. The
2026-08-12 exchange measured the same thing on `broadcast` from the other end: pitch3d's `rigid_119`
sits **2.06 m along its own sight line** at **9.47 px against camlab's 4.17**.

The split is clean and it is the whole recommendation:

> **Initialisation is pitch3d's strong half. Refinement is camlab's.** Take the first, keep the
> second, and do not put the model inside camlab's loop.

## 5. The proposal — an anchor generator, out of process and out of licence

A dev-time script **in pitch3d** that runs PnLCalib on **one** frame of a clip and writes camlab's
`camera_manual.json` entry for that frame.

- It emits *the same file a human produces by dragging*, so `solve/hand.py` stays the one reader,
  the `REQUIRED = ("focal_px", "rotation", "position")` contract does not change, and no GPL code,
  weights or runtime enter camlab.
- The selection machinery already handles it correctly. `hand_candidates` returns *candidates*, not
  an answer, and `solve_carry.py:98-112` makes the seed's own pose compete against every anchor on
  paint — so a bad generated anchor loses on its own merits and the log says so.
- The fallback when it is wrong already exists and is good: the operator drags it.
- It closes what `bootstrap-progress.md` calls *"the whole remaining gap"* — **seven of the nine
  sample clips have no start camera** — and it does so without the height prior that makes
  `bootstrap_clip.plausible` reject a phone at 1.5 m.
- It is also the way out of the circularity named in `is-a-model-worth-training.md`: a good camera
  on a clip lets the pitch model be projected through it to label every marking pixel with its
  class, free and with no licence attached. Hand-placing cameras on diverse clips was named as the
  prerequisite for self-labelling. This automates the prerequisite.

### The measurement that decides it, and it is cheap

On `broadcast` — where camlab already knows the answer — produce a frame-0 camera from PnLCalib,
run `refit`, compare `across` against what the hand anchor achieves. Three outcomes, all useful:

- inside `refit`'s basin → the gap closes on the other seven clips;
- outside → we learn it from one clip instead of nine, and `#11`'s "score across frames, not one"
  is still next;
- near but not in → `refit._accept` refuses it rather than damaging anything, which is already the
  designed behaviour.

Do **not** judge this on `fan`: `bootstrap_clip.py fan --frame 0` already returns 1.0 px, so `fan`
is the clip that least needs help. `broadcast` plus one of the five that print *"no plausible camera
at all"* is the informative pair.

**Unknown, and it should be measured before it is relied on:** PnLCalib's weights are
SoccerNet-trained, i.e. broadcast-shaped. Whether they fire at all on a phone at head height is
untested on both sides. If they do not, this proposal helps the broadcast clips and not the class
`pitch-level-clips-2026-08-13.md` says is *"the main share of what this has to work on"*.

### One line to fix first

`pnlcalib_backend.py:323` resizes every frame to a fixed **540×960 regardless of aspect ratio**.
The `fan` clip is 1080×1920 portrait, so it reaches the network squashed **0.5× across and 0.28×
down**. Every number PnLCalib has produced on a portrait clip is under that handicap.

## 6. The rest of the list, ranked by what it would change

### 6.1 The pan term — focal evidence that owes nothing to the pitch model

**This is the most valuable item in this document and it needs no model, no licence and no GPU.**

camlab's second measured degeneracy is the focal trading against distance on a plane: 99 % of the
free solve's position variance along one 108 m direction, and *"sliding along it and re-refitting
gives 1.89 px at the optimum against 4.33 px three metres away, so the position is pinned to about
a metre."* One metre, from paint alone, is the ceiling of that instrument.

`fit_rigid_camera.py` adds a **second, independent residual block** that pins the focal without
consulting the pitch at all. From the pure-rotation identity, `K Rⱼ Rᵢᵀ K⁻¹` must reproduce the
*measured* image→image homography:

```python
def pan_maps(q, pairs):                       # fit_rigid_camera.py:220
    ...  k @ rot[b] @ rot[a].T @ ki
PAN_GAPS = (1, 10, 30, 59)                    # :79
PAN_GRID  = 45 points, 10 % inset             # :86-90
```

Three details are the whole point, and camlab has the first two already:

1. The measured maps come from SIFT + MAGSAC — camlab's `measure/pixel_motion.measure_pairs`
   produces exactly this and already runs on every clip.
2. `carry.py` uses that identity too, but only to **transport** the camera one frame. It never
   enters an objective, so its focal evidence is discarded after use.
3. **The long gaps are the addition.** `K R Rᵀ K⁻¹` is degenerate in `f` below a few degrees of
   turn, so gap 1 — the only one camlab computes — carries almost no focal information. Gaps of
   30 and 59 frames carry it. `fan` pans and zooms; the evidence is sitting in frames camlab
   already has on disk.

And the sparsity pattern says why it is orthogonal rather than more of the same
(`fit_rigid_camera.py:290-301`): **pan rows see the focal and two rotations and not the centre.**
The paint residual trades focal against distance; the pan residual constrains focal at fixed
distance. Adding it to `refit.objective` or as a term in `solve_shared_centre`'s 1-D search is the
one change that attacks the degeneracy rather than measuring it again.

One transferable trap with it: `x_scale="jac"` is load-bearing, *"the focal is ~4000 and a rotation
component is ~1, so on a common scale the optimiser cannot see the focal at all"*
(`fit_rigid_camera.py:303-305`).

Cost estimate, honestly: ~50 lines plus a bench. Unmeasured on camlab's clips — but it is the only
proposal in this document that could move `across` on a clip that already solves.

### 6.2 External ground truth. camlab has none

Its only check is its own detected paint. The mowing-stripe test is genuinely independent of the
markings and this repo is right to lean on it, but STATUS says the honest thing itself:
*"A check to run on a camera you already believe, never a way to find one."*

pitch3d has the third kind — an answer measured by somebody else:

| | |
|---|---|
| data | SoccerNet `calibration-2023`, openly downloadable via `scripts/get_soccernet_calibration.py` |
| harness | `scripts/run_calib_eval.py --dataset soccernet`, with a `--solver dlt\|camera` A/B |
| metric | `src/pitch3d/eval/calib_metrics.py` — error in **world metres** *and* **image pixels**, plus per-line accuracy at a pixel threshold |
| measured, 200 frames | completeness **0.745**, median reprojection **1.79 px / 0.236 m**, `line_acc@5px` **0.618** |

The metric file is honest about what it is not: it refuses to call itself `JaC@5`, because the
official metric scores full camera parameters with distortion, the circles and the left/right flip,
whereas this scores a planar homography over straight lines.

**Why this matters more to camlab than to pitch3d.** This repo has been wrong about its *own metric*
twice — the `match_px = 40` ceiling that deleted every sample without paint within it, and
`solve/ptz.py` converging precisely on the wrong objective. Both were caught by a human with a
ruler. Ground truth is the version of that human which runs in six seconds and does not get tired.

### 6.3 A synthetic oracle for the metric itself

`run_calib_eval.py --dataset synthetic --backend oracle` generates frames *with their true
homographies* and checks the harness returns ≈ 0; `--backend perturb` checks the error grows with
the perturbation. camlab has synthetic controls inside individual modules (`measure/lines.py`,
`measure/pixel_motion.py:251` — a pure 8° rotation at f = 2400 over a 34-point log grid) but
nothing that scores the **whole residual** against a known answer. That is the test that would have
caught the ceiling on the day it was written.

### 6.4 A labelled negative for the marking detector — #14's open half, for free

pitch3d swept `MIN_LEN_PX` against **broadcast frame f333, shot from inside the net**, which
contains no real pitch marking at all, so all 1080 of its LSD segments are known-false:

| `MIN_LEN` | fan f0 | fan f50 | bcast f67 | **NET f333 (all false)** |
|---|---|---|---|---|
| 30 | 16 | 14 | 16 | **136** |
| 40 | 10 | 11 | 10 | **52** |
| **60** | 11 | 11 | 8 | **3** |
| 80 | 9 | 6 | 7 | **0** |

80 reaches zero and is not worth it — it also deletes 25–31 % of the real markings on every ordinary
frame. That is **a precision curve with a real negative control and no labelling work**, which is
what `#14`'s precision half lacks; it is argued today from two segments on `fan` frame 8. Every clip
with a goalmouth close-up or a crowd shot contains such a frame.

### 6.5 Detector recall and precision measured directly against a known camera

`scripts/bench_markings_vs_camera.py`, all 60 calibrated frames of the broadcast clip:
**recall 97.8 %** (p10 94.7), **precision 100.0 %** — zero detections the camera cannot explain.
camlab infers the detector's contribution indirectly, from the gap between `worst spot` and `across`
(7.9× on `fan`). Direct is better and it separates the two subsystems by measurement rather than by
argument.

One trap comes with it, already paid for on this side: the first version read **precision 2.3 %
against recall 92 %**, an impossible pair, because it scored detections against `pitch_polylines`'
0.5 m samples that sit tens of pixels apart in the near field.

### 6.6 Cut detection. camlab has none at all

`adapters/models/shot_detect.py` — ORB(2000) + BF-Hamming(crossCheck) +
`findHomography(RANSAC, 3.0)`, constants measured on real footage.

camlab's `carry` takes the camera to the next frame through the image-to-image homography, and
`solve_selfheal.py` re-seeds a lost frame *from its nearest good neighbour on both sides*. Across a
cut both are wrong in a way no paint residual will name: the carry produces a plausible camera for
the wrong shot, and self-heal will reach across the cut to fetch a seed. pitch3d measured that the
broadcast clip contains one contiguous **2 s cut block (f272–330)** plus three short ones, where the
playing surface drops from 51 % to 31 % of frame. camlab's broadcast run is 60 frames and may simply
not have reached one.

### 6.7 Confidence — a retraction, and what is actually worth taking

The first draft of this section offered pitch3d's per-frame calibration confidence as something
camlab lacks. **`inherited-claims.md` already refutes it**, and pitch3d's own register agrees
(`landmines.md:48-52`):

> `FieldCalibration.confidence` — **anti-predictive**, Pearson **r = +0.699** against real paint
> error. The frames it trusts most are the worst ones. Measured three times, still exported.

So the field is not worth porting. **The instrument that found that out is.**
`scripts/bench_calib_confidence.py` (#105) asks a question camlab has never asked of its own
verdicts: *does this number correlate with the actual error?* camlab writes a per-frame good/bad
against the paint and nothing downstream can weight frames by it. The lesson pitch3d paid three
measurements for is that a confidence nobody has correlated is worse than none, because it is
believed.

One piece of the machinery around it *is* worth copying and is one line: the DOF normalisation
`dof = rows - 8`, where a zero-redundancy fit yields confidence 0 because it reproduces itself
perfectly. camlab's `MIN_SUPPORTING_MARKINGS` and `Residual.supported` are the same instinct
counted in markings rather than in rows.

### 6.8 Guards worth having, cheap

- **`_lines_agree`** (`pnlcalib_backend.py:205`) — fits points-only, measures the median
  point-on-line residual, and **disables the line constraints entirely** above
  `_LINE_FRAME_TOL_M = 3.0`. It exists because a mirrored world frame moves zero pixels on the lawn
  and only shows up as lines disagreeing with points. camlab carries the same `#118` negation
  across `seg()` by hand, with no runtime check that it still holds.
- **Refuse rather than emit.** `PlaneCameraFit.camera is None` unless
  `reprojection_px <= REALIZABLE_PX = 1.0`, and `CameraSource.{PLANE_FIT, STATIC_FALLBACK,
  PRESCRIBED}` + `is_measured` make a synthetic stand-in no longer byte-identical to a solve on
  disk. camlab inherited `REALIZABLE_PX` and its own register marks it **unverified** — it has
  never been re-derived for a phone clip. Worth deriving before it starts refusing good cameras.

### 6.9 Point-on-line rows inside the fit

pitch3d's DLT accepts `lᵀ·H·x = 0` rows from the line head alongside point correspondences, one row
each; `bench_line_constraints.py` measured p95 going **95.8 → 1.26 m at 4 keypoints**. camlab fits
to nearest-paint distance. Different objectives, not better and worse, and which wins on camlab's
clips is **unmeasured**. Noted because `refit.MIN_MATCHED = 4` is the gate that makes `g11710897`
unfittable, and line rows are the cheapest way to raise a frame's evidence count.

### 6.10 Where neither repo is ahead, and one where camlab is

- **Framing.** My first draft claimed pitch3d derives the crop and therefore cannot get the
  principal point out of step. **That is wrong.** pitch3d's `--crop auto` moved the homographies
  into a 1080×608 rect while `controller.py:709` was still told 1080×1920 — the defect behind the
  12 382 px figure in §4.4. camlab's failure is the mirror image: `ClipInfo.principal_point`
  derives `cy = −334` correctly and then four chain stages copy `cx, cy` from their input, so every
  shipped fan camera carries 304 anyway. **Both repos got the image space wrong in 2026-08; neither
  has a check that the space a homography was fitted in is the space it is used in.** That check is
  one line on either side and it is unwritten on both.
- **Focal from one homography.** Present on both sides — pitch3d's `_measure_focal` (96-point
  geomspace grid over (300, 20000) + golden-section on Zhang's orthonormality) and camlab's
  `focal_from_one_homography`. Nothing to port.
- **Lens distortion.** camlab measured it (0.37 px, random in direction, 42/58, not growing with
  radius) and ruled it out. pitch3d does not model it either and says so:
  *"our `CameraIntrinsics.distortion` is None on every solve we produce"*. Nothing to port.
- **The golden test.** `tests/test_golden_real_camera.py` is here, ported, pinned by the same real
  measurement on both sides. ADR-0013 §5 working as designed.
- **Per-frame focal — camlab is ahead.** pitch3d dropped it (*"0.6 % over 236 frames"*) and its
  rigid fit shares **one** focal across the clip. camlab's schema 2 writes a focal per frame, and
  measured that collapsing to one costs 65 % of the accuracy on a zooming clip. On this axis the
  port runs the other way, and pitch3d is the one that has to change.

## 7. One claim in STATUS.md that is stronger than its evidence

> **The pitch is exactly symmetric under a half-turn.** … Nothing in the markings can say which half
> is being looked at and **no solver ever will**.

True of *anonymous* markings, false of named ones. `FramebyFrameCalib` performs an **L/R plane
disambiguation** as part of its solve, and pitch3d's own metric file records that SoccerNet's
official metric carries the same left/right tactical-ambiguity flip — the field treats it as
something a calibrator is expected to resolve, not something nothing can.

It is not free and it is not always right. But the sentence as written closes a door that names
open. Suggested narrowing: *"nothing in the **geometry** of the markings can say which half"* —
which is what was actually measured (2.1 px on 307 samples either way) and stays true.

## 8. What this document does not claim

- **That PnLCalib's frame-0 camera is good enough to seed `refit`.** Unmeasured. §5 *is* the
  measurement and it has not been run on either side.
- **That PnLCalib fires at all on a pitch-level phone clip.** Its weights are broadcast-trained.
  Untested, and it is the clip class that matters most.
- **That pitch3d's camera is better than camlab's.** The 2026-08-12 exchange measured the opposite
  where it counts: 9.47 px against 4.17, and 2.06 m of displacement along pitch3d's own sight line.
- **That §6.1 works here.** The pan term is measured inside `fit_rigid_camera` on the broadcast
  clip and has never been run against camlab's objective. It is a proposal with a mechanism, not a
  result.
- **Anything about the seven clips camlab cannot start.** Nobody has run PnLCalib on them.
- **That the licence question is settled.** It is not. PnLCalib is GPL-2.0-only and its weights are
  research-only. Keeping the model out of camlab's process is what §5 is designed for, and even
  then, whether a camera derived from those weights is a derived work is a question nobody in
  either repo has answered.

## 9. If two things get done

**First, §6.1 — the pan residual over long gaps.** No model, no licence, no GPU, no new data;
`measure_pairs` already produces its input on every clip. It is the only proposal here that attacks
the focal/distance degeneracy instead of measuring it again, and it could move `across` on clips
that already solve.

**Second, §6.4 — the labelled negative frame.** One afternoon, no model, no licence. It turns
`#14`'s precision half from an argument about two segments into a curve, and `#11` is blocked on
`#14` by this repo's own finding — so it is also the shortest path to the thing §5 is trying to buy
with a model.

§5 itself is third: it is the direct answer to "who places the anchor", and it is the one that
brings a licence, a GPU and 265 MB of weights with it.
