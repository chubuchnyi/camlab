# Automating the anchor — AVATAR drives, camlab stays a tool

**2026-08-13.** Constraints set by the brief, in order of priority:

1. **The implementation lives in AVATAR.** It takes camlab as a tool.
2. **camlab may be changed only slightly, and only where genuinely necessary.**
3. No human in the loop for the first camera.
4. Take the best of each side.

The result of designing against those constraints is stronger than expected: **the loop closes
with zero changes to camlab.** Everything the automation needs is already on camlab's public
surface. This document records what that surface is, what AVATAR builds against it, and the one
change that might later become necessary — with the condition that would make it so.

Companion to `reply-from-pitch3d-2026-08-13-the-first-camera.md`, which establishes *why* the first
camera is hard here.

---

## 1. What actually has to be supplied — and it is not a camera

The failure on five of six anchors is **abstention, not a wrong answer**: they print *"no plausible
camera at all"*. Where the bootstrap does answer, it answers well — `bootstrap_clip.py fan
--frame 0` returns 1.0 px over three probe frames on 298 samples, 3.11 m from the truth, focal
1.7 % off, and reports the half-turn twin correctly.

So the missing input is not a better search. It is **evidence and names**:

| # | missing | today |
|---|---|---|
| 1 | which detected segments are markings at all | `#14`'s open precision half — two of nine on `fan` f8 lie along the grass/hoarding join |
| 2 | which marking each one is | the chooser; the pool's best lands 113 m out on the far side |
| 3 | which half of the pitch is in view | the half-turn — STATUS says choosing *"needs something off the pitch, or an eye"* |

All three are **discrete**. None is a number. That is why something other than more geometry can
supply them.

## 2. camlab's surface is already sufficient — the full loop, unmodified

Everything below exists today. Nothing in this section is a proposal.

| step | camlab gives it as | note |
|---|---|---|
| get the frame | `GET /api/run/{clip}/frame/{n}` | what the labeller looks at |
| **get the detected segments** | `GET /api/run/{clip}/lines/{n}` | **camlab's own**, so labels land on exactly the evidence its solver will use |
| write the anchor | `POST /api/run/{clip}/manual/{n}`, or write `runs/<clip>/camera_manual.json` directly | the store `solve/hand.py` already reads |
| run the chain | `POST /api/run/{clip}/solve?anchor=N&seed=…` → `solve/pipeline.run` | carry → self-heal → shared centre → smooth |
| read the verdict | `GET /api/run/{clip}/residual/{n}`, or `measure.verdict.judge_file(clip, camera)` | machine-readable, per frame |
| take the result | `scripts/export_camera.py` → `calib/<clip>.npz` **schema 2** | focal *and* position per frame |

Two of these matter more than the rest.

**`GET …/lines/{n}` is the reason the whole design is cheap.** The labeller does not have to
re-detect anything or agree with camlab about what a segment is. It labels camlab's own numbered
segments, so a returned label maps one-to-one onto the line the solver will actually use.

**`camera_manual.json` needs no new code to accept a machine's anchor.** `solve/hand.py` is
explicit that source carries no authority:

> **A store cannot have priority.** … Which store an anchor came from says nothing about whether it
> is a good one. So nothing here ranks by source: both stores offer candidates and the caller picks
> the one that fits the paint, which is the only thing that can settle it.

An anchor written by AVATAR is therefore judged the same way a human's is —
`solve_carry.py:98-112` scores every candidate including the seed's own pose, and `:116-119`
already prints when none of them won. **A wrong automatic anchor loses on the paint and says so.**
That is the entire safety argument, and it is machinery that already shipped.

## 3. What AVATAR builds

All new code, all on the AVATAR side. camlab is called, never edited.

```
AVATAR
  ├─ 1. surface mask            SAM-class, Apache-2.0        → out/anchor/<clip>/surface.png
  ├─ 2. frame + segments        GET …/frame/{n}, GET …/lines/{n}
  ├─ 3. labels                  Claude API, ONE frame, cached → out/anchor/<clip>/labels_f0.json
  ├─ 4. named correspondences → homography → focal → pose
  │        (calibration.solve_homography + plane_camera._measure_focal/_decompose)
  ├─ 5. POST …/manual/{0}        the anchor
  ├─ 6. POST …/solve             camlab runs its own chain, untouched
  └─ 7. read calib/<clip>.npz    schema 2 → scene.json
```

Steps 1, 3 and 4 are the new work; 2, 5, 6 and 7 are HTTP calls.

**Why this split is the right one, and not merely the one the brief asked for.** camlab's identity
is *"No GPU, no neural network, no ML runtime… nothing trained, nothing downloaded, no checkpoint
to lose."* AVATAR already carries torch, a GPU box, PnLCalib and network access. Putting the model
work in AVATAR is what **lets camlab keep that property** — camlab stays weightless precisely
because AVATAR absorbs the weight. That is the best-of-each split done properly rather than
politely.

### The trap in step 4, and it has already cost both repos a week

camlab's anchor contract is `REQUIRED = ("focal_px", "rotation", "position")` — Rodrigues
**world→camera**, and the camera **centre** in world metres, not the `t` of `X_c = R X_w + t`. And
the focal and pose are only meaningful under the principal point they were solved with.

AVATAR's `plane_camera` hardcodes `cx, cy = width / 2.0, height / 2.0` (`:198`), while camlab
derives `ClipInfo.principal_point` from the crop — `(540, −334)` on `fan`, not `(540, 304)`. An
anchor computed under AVATAR's assumption and written into camlab's store would be systematically
wrong, in the exact way both registers already record. **So step 4 must take `cx, cy` from
`GET /api/run/{clip}/camera` (or `clip.json`) rather than assume them**, which is a small change to
AVATAR's own code — parameterising `_measure_focal` and `_decompose` on the principal point.

## 4. What supplies the names — two producers, both in AVATAR

Both write the same artefact and both compete on camlab's paint. There is no arbitration to build.

| | producer | gives | licence / hardware |
|---|---|---|---|
| **A** | a VLM labelling **one** frame, cached | names + family + left/right | API call, no weights |
| **B** | PnLCalib on one frame | a full camera directly | **GPL-2.0-only**, GPU, 265 MB |

B already exists in AVATAR and needs no new integration beyond the anchor writer. A is the new
thing and is the higher-value one, for three reasons: no licence, no weights, and it is not
broadcast-trained, so it is the only one with a chance on the pitch-level clips that
`pitch-level-clips-2026-08-13.md` calls *"the main share of what this has to work on"*.

### On a VLM specifically

**What it must never be asked for: numbers.** No coordinates, no focal, no position. The output
must be discrete and small or it is unverifiable and does not belong in the loop.

**What it is uniquely suited to is all three missing things, and all three are discrete:**

1. **"Is segment 7 a painted marking, or the edge of the advertising hoarding?"** A distinction
   obvious to an eye and invisible to every classical feature this repo has measured — straightness
   points the *wrong* way (0.13 px against 0.20), cross-ratio passes 70 % of impostor quads, and
   length actively *prefers* the 567 px hoarding join.
2. **"Which marking is segment 3?"** — with a deliberately **coarse** vocabulary: touchline /
   goal line / halfway line / penalty-box long edge / penalty-box short edge / goal-box edge / not a
   marking. It does not need the exact instance. `_homography_from_lines` needs **four**
   correspondences, two per family; getting the *type* and the *family* right is enough, and it is
   far more reliable than asking for "Big rect. left top".
3. **"Is the camera looking at the left half or the right half?"** — the half-turn. STATUS says the
   choice *"needs something off the pitch, or an eye"*. A VLM **is** an eye, and this is a binary
   question about stands, hoardings, goal position and direction of play. Cheapest question in the
   system, and it answers the one thing camlab says no solver ever will.

**Why this does not violate camlab's philosophy.** `measure/paint.py:13-15`: *"A keypoint
detector's output is another model's opinion. A painted line is in the pixels."* A VLM's output is
also an opinion — and that is acceptable **because it enters at the exact slot a human's opinion
already occupies**. A hand anchor is a cached opinion in a file, judged by the paint. A label file
is the same object with a different author. The governing rule needs no amendment.

**Cost and reproducibility.** One call per clip, ever, cached in `out/anchor/<clip>/labels_f0.json`
and committed. After that the clip solves offline forever — a stronger reproducibility position
than a 265 MB checkpoint, not a weaker one.

## 5. On SAM — it fixes precision, not naming, and it stays out of camlab

Segmentation gives class-agnostic masks. It does **not** name lines, so it does not touch the
chooser. What it fixes is `#14`'s precision half, structurally:

- the two false segments on `fan` f8 *"both lie along the join between the grass and the advertising
  hoarding."* With a surface mask **that join is the mask boundary** — so "discard segments on the
  boundary" becomes a geometric test rather than one more refuted heuristic.
- it fixes the recorded turf failure the right way round. The hardcoded `s > 70` drops the
  **sunlit** half of `g15449383` — *"the rejected pixels are brighter than the accepted ones"* — and
  sweeping it 70 → 15 improved not one measured number. A threshold does not have to classify every
  pixel. It has to find **one** confident seed point, and segmentation grows the rest.
- `pitch-level-clips-2026-08-13.md` states its target in exactly these terms: *"the surface mask
  must stop at the boards… should read 40–60 % of frame height on these clips and reads 0 %."*

For the anchor path this lives entirely in AVATAR: AVATAR uses the mask to decide which of camlab's
returned segments to hand the labeller, and camlab never sees it.

## 6. The one camlab change that might become necessary — and the test for it

Everything above is zero-change. One thing is not, and it is worth stating precisely rather than
pre-emptively doing:

**If — and only if — the mask turns out to improve camlab's *own* residual and refit** on the
clips where its turf stage collapses (`g15449383`'s sunlit half, the pitch-level clips), then
camlab needs to be able to read it. The minimal form is an **optional `runs/<clip>/surface.png`
that, when present, replaces the HSV turf test** — roughly ten lines in `measure/paint.py`, no new
dependency, since reading a PNG is not an ML runtime and the file-with-a-schema contract is what
ADR-0013 §4 already prescribes.

**The test that decides it:** solve `g15449383` with and without the mask and compare `across` and
the markings count. It currently scores 4.47 px on **2 markings** with 21 % of frames having no
paint across — which STATUS already refuses to call a verdict. If the mask moves the markings count
and not just the pixels, the change is necessary. If it does not, it is not, and camlab stays
untouched.

Two things explicitly **not** proposed, because AVATAR can do them on its own side:

- **No label filter inside `solve/bootstrap.hypotheses`.** AVATAR does not constrain camlab's
  enumeration; it computes the homography from named correspondences directly — it already has a
  normalised DLT with point and point-on-line rows — and hands camlab a finished anchor. camlab's
  bootstrap is **bypassed, not modified**, and still competes as an independent candidate.
- **No third store in `hand_candidates`.** AVATAR writes into the existing `camera_manual.json`.
  The file does not know whether a browser or a script wrote it, and `_is_position_broadcast` will
  not mistake a genuine machine aim for a clip-scoped position write, because the rotation and
  focal will not be bit-identical to the seed.

## 7. The first experiment — it measures the labeller before anything trusts it, and needs no labelling

camlab already has two clips whose cameras it believes, which is enough to score a labeller with
**zero manual work**:

1. take `broadcast` frame 0, its known camera, and its segments from `GET …/lines/0`;
2. project the pitch model through the known camera — that assigns the true class to every detected
   segment. (This is `is-a-model-worth-training.md`'s self-labelling idea run backwards: instead of
   making training data, it makes an answer key.);
3. ask the VLM to label the same numbered segments in the same image;
4. count.

**The bar is stateable in advance and it is low:** four correct correspondences, two per family,
with the families correct. Get that on `broadcast` and `fan` and the method works. Get the
left/right call right on both and the half-turn is closed. One API call, no code in camlab, and a
negative result costs an afternoon.

Run it on `fan` f8 as well — the frame where two of nine segments are the hoarding join — because
that is where the answer changes `#14` and not only `#11`.

## 8. Sequencing

1. **The §7 measurement.** No code in camlab, almost none in AVATAR. Decides everything after it.
2. **The anchor writer in AVATAR** — names → homography → focal → pose → `POST …/manual/0`, under
   camlab's principal point, not AVATAR's.
3. **Drive the chain end to end** — `POST …/solve`, read `judge_file`, take `calib/<clip>.npz`.
4. **Surface mask in AVATAR**, for choosing which segments to label.
5. **§6's camlab change** only if its own test says so.
6. **The pan residual** (`reply-from-pitch3d-…-the-first-camera.md` §6.1) — unrelated to the anchor
   and still the largest free accuracy win: focal evidence owing nothing to the pitch model, from
   `measure_pairs` output camlab already computes. This one *is* a camlab change and it is the one
   most worth arguing for on its merits later.

## 9. What crosses each way, so this is a combination and not a takeover

| AVATAR → camlab | camlab → AVATAR |
|---|---|
| a first camera, as an ordinary anchor | **the camera solve itself** — AVATAR should consume `calib/<clip>.npz` and stop fitting |
| (later, on merit) the pan residual over long gaps | schema 2: a focal **per frame**, worth 65 % of the accuracy on a zooming clip |
| the labelled-negative frame method for detector precision | self-heal, shared centre, smoothing |
| cut detection | the paint metric reported as three statistics, not one |
| the SoccerNet GT harness | `write_camera` refusing a non-positive focal |

## 10. What this does not claim

- **That a VLM can label pitch lines well enough.** Unmeasured. §7 is the measurement, designed so
  a negative result is cheap and unambiguous.
- **That segmentation stops at the boards on a pitch-level clip.** That is an open branch's stated
  target, not a result.
- **That PnLCalib fires at all below broadcast height.** Its weights are broadcast-trained.
- **That any of this improves a clip that already solves.** It does not. It is about the seven that
  cannot start. The item that improves a solved clip is §8.6.
- **That the licence question around producer B is settled.** It is not; that is why it is the
  fallback and why it stays out of camlab's process.
