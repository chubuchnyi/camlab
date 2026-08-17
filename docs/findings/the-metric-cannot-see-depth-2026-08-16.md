# The camera is 1.2–5.0 m from where it was, and the paint metric prefers it that way

Measured 2026-08-16 against the WorldPose ground truth. **This is the first time a camlab camera has
been compared to an externally measured one.** Everything before this was judged against the paint,
which is what the clip itself can tell you, and against the user's eye.

Reproduce:

```bash
PYTHONPATH=src python scripts/import_worldpose_gt.py --all --judge
PYTHONPATH=src:. python scripts/bench_vs_worldpose.py --camera camera_polished.json
PYTHONPATH=src python scripts/overlay_worldpose.py CRO_MOR_194948 0   # and MOR_POR_181952 7
```

**Check the ground truth before checking anything measured against it.** The world frame is not
documented by the dataset, so `overlay_worldpose.py --players` projects WorldPose's own *player*
positions through WorldPose's own camera: no pitch template, no paint detector, no camlab geometry.
On `CRO_MOR_194948` frame 0 all six visible players get a stick standing on them. That verifies the
convention this whole document rests on, and it does so without using anything in this repo.

---

> **Every number below is from the working half, and the held-out half has not seen any of it.**
> WorldPose covers 89 clips from eight matches; this document used four clips from four matches,
> which spends those matches. The other four — `ARG_CRO`, `ARG_FRA`, `BRA_KOR`, `FRA_MOR`, 41 clips
> — are kept back, and `docs/held-out-clips.md` says why and how they may be spent. **The claim
> that the camera is 1.2-5.0 m out and the paint prefers it that way is written down and not yet
> confirmed on a clip that had no part in producing it.**


## 1. What the ground truth is, and why it was not being used

WorldPose ships 89 broadcast clips of the 2022 World Cup with **per-frame `K`, `R`, `t` and radial
distortion** — 1299 frames each, the full 26 s at 50 fps. Four of them are already ingested here and
were ingested without anyone noticing what they were, because the clip id **is** the WorldPose id:

| in `runs/` | frames held | ground truth |
|---|---|---|
| `CRO_MOR_194948` | 120 | yes |
| `ENG_FRA_232015` | 180 | yes |
| `MOR_POR_181952` | 60 | yes |
| `NET_ARG_225042` | 60 | yes |

All four were ingested with `first_frame: 0`, so frame *n* here is GT entry *n*. Nothing had to be
re-aligned.

The world frame is not documented by the dataset. It is asserted here by measurement: `C = -Rᵀt`
comes out at **(−0.02, −88.15, 18.63) m** on `CRO_MOR_194948` — a camera on the halfway line, 88 m
back, 18.6 m up. That is camlab's own convention, origin at the pitch centre, X along the length,
Z up, and no transform is needed.

Two facts fall out of the GT before any comparison:

* **The camera centre does not move.** Height is constant to the printed precision over every clip
  (18.63 m for all 120 frames of `CRO_MOR_194948`). These are pan/tilt/zoom heads on fixed mounts,
  which is what the shared-centre stage assumes. That assumption is now measured, not hoped.
* **The focal does move.** 5720 → 6066 px over 120 frames on `CRO_MOR_194948`. A one-focal-per-clip
  camera cannot represent that, which is the reason this repo exists.

## 2. Where our camera actually is

`camera_polished.json` against the GT, medians over every frame:

| clip | position | rotation | focal ours/GT | reprojection median | p90 |
|---|---|---|---|---|---|
| `NET_ARG_225042` | **1.17 m** | 0.311° | 0.999× | 6.4 px | 11.3 px |
| `ENG_FRA_232015` | **3.82 m** | 0.782° | 0.981× | 9.5 px | 21.3 px |
| `CRO_MOR_194948` | **5.01 m** | 0.869° | 0.974× | 6.6 px | 18.2 px |
| `MOR_POR_181952` | **16.24 m** | 7.690° | 1.551× | 332 px | 557 px |

Reprojection is the distance between where the two cameras put the same pitch point, over the points
the GT puts inside the image. It is the number that matters for a novel view: position and rotation
trade against each other, and neither alone says whether the picture is right.

## 3. The error is along the line of sight, and almost nowhere else

Decomposing our displacement against the GT's own viewing axis, at the middle frame:

| clip | total | along the view axis | across it | focal ours/GT |
|---|---|---|---|---|
| `CRO_MOR_194948` | 5.01 m | **+4.96 m** | 0.68 m | 0.971× |
| `ENG_FRA_232015` | 3.82 m | **+3.73 m** | 0.86 m | 0.982× |
| `NET_ARG_225042` | 1.17 m | **+1.16 m** | 0.19 m | 0.999× |

Positive is toward the pitch. Our camera sits **closer than the real one, with a proportionally
narrower focal**, which leaves the picture nearly unchanged. 86 %, 98 % and 99 % of the displacement
is along the one direction a planar target cannot constrain.

This is the degeneracy the repo already names — "focal trades against distance on a plane" — and
this is the first measurement of what it costs: **up to 5 m on an 88 m shot, at 2.6 % of focal.**

The ratio is not a clean similarity (a pure scale about the camera would need a much larger depth
than these clips have), so some of it is absorbed by the 0.3–0.9° of rotation. The direction is the
established part; the exact mechanism is not, and is not claimed here.

## 4. The paint metric prefers the wrong camera

Distance from a projected marking to the nearest painted pixel, `CRO_MOR_194948`, median over 12
frames sampled across the clip:

| camera | distance to the paint |
|---|---|
| ground truth, distortion applied | 3.06 px |
| ground truth, distortion dropped | 3.28 px |
| **our pinhole solve** | **1.33 px** |

Through camlab's own `measure/verdict.py`, the same ordering, larger because that statistic is a max
over markings rather than a median over points:

| clip | our `camera_polished` | the ground truth |
|---|---|---|
| `CRO_MOR_194948` | **3.88 px** | 30.01 px |
| `ENG_FRA_232015` | **2.93 px** | 9.24 px |
| `NET_ARG_225042` | **5.73 px** | 6.36 px |
| `MOR_POR_181952` | no verdict, 2 markings | no verdict, 3 markings |

**Our camera beats the true camera on our own metric, on every clip that scores at all.** The metric
is not lying about what it measures — the markings genuinely land closer. It is that fitting the
paint tighter and being where the camera was are different objectives, and past ~3 px they point in
different directions. A camera 5 m out of position scores 3.88 px; the camera that was actually
there scores 30.01.

So `across` is a floor, not a certificate. It can still catch a badly wrong camera. It cannot rank
two cameras that both sit near the paint, and it was being used to do exactly that.

## 5. What the 30 px is, and what it is not

`worst_across_px` for the GT on `CRO_MOR_194948` is 30.01 px, and that is **not** the GT being wrong.
Two separate causes, both measured:

**Distortion, which camlab's camera model does not have.** On frame 0, over the pitch points that
land in the image:

| radius from the optical axis | 0–200 | 200–400 | 400–600 | 600–800 | 800–1100 px |
|---|---|---|---|---|---|
| median shift the distortion adds | 0.07 | 0.61 | 2.80 | 7.68 | **15.32 px** |

Median 2.84 px over the whole visible pitch, worst 31.94 px in a corner. `worst_across_px` is a max
over markings, so it reports whichever marking is nearest the edge — and that is where the whole 30
px lives. Dropping distortion costs only 0.22 px at the median (§4) and up to 32 px in a corner.

**The template.** Refitting the pitch rectangle to the GT gives 105×69 for `CRO_MOR_194948`
(2.61 px against 2.91 for 105×68), 105×68 exactly for `ENG_FRA_232015` (1.50 px), 106×68 for
`NET_ARG_225042` (2.03 vs 2.11). So the shipped 105×68 is right to within a metre and is **not** an
explanation for anything above; the GT's own residual against it is 1.5–2.9 px.

## 6. `MOR_POR_181952` is not nearly-solved, it is wrong

16.24 m, 7.69°, **focal 1.551×**, 332 px of reprojection. It has been carried as a clip that scores
"no verdict" for want of markings — 2 per frame — and read as thin evidence about a roughly right
camera. It is not: the focal is off by half.

Its GT camera is 11.79 m up and its focal is 3180–3194 px. That is now available as a starting
point, and it is the first clip where an anchor can be checked instead of aimed.

## 7. What this changes

* **89 clips with a measured camera** are on disk (`~/AVATAR/models/worldpose/WorldPose Dataset/
  compressed/*.mp4`, 24 GB; GT in `~/AVATAR/WorldPose/cameras/*.npz`). Four are ingested. The
  remaining 85 are a validation set for the whole chain, on the exact problem, at no cost.
* **`across` cannot be the acceptance test on its own.** It is now known to prefer a camera 5 m out.
  Anything tuned to minimise it — the polish stage, the LM refit's `_accept`, the ridge scales — was
  tuned against a target that rewards absorbing distortion into camera position.
* **Distortion is not ruled out.** `docs/STATUS.md` inherited "lens distortion — RULED OUT" from a
  single clip measured at 0.37 px. On these four the GT carries 27–34 px of it in the corners. The
  earlier measurement is not contradicted — it was a different lens — but the conclusion does not
  generalise and must not be quoted as if it did.

## 8. What was NOT established

* Whether fitting distortion would move our camera toward the GT rather than just lowering the
  residual. Not tried.
* Whether the 1.2–5.0 m matters to the eye in a novel view. Nothing has been rendered from a GT
  camera yet. That is the test that decides how much of this is worth acting on.
* Anything about the other 85 clips. Four is what is ingested; the numbers here are four clips wide.
