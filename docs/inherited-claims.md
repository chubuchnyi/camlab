# What camlab inherited from pitch3d, and whether any of it has been checked

**Operating rule: camlab's ground truth is the video, not pitch3d's outputs.**

Every number that arrives here from pitch3d is a claim until camlab measures it against pixels.
That is not scepticism as a posture — it is what the last two days measured. In one session, on
this one thread:

| inherited claim | what it turned out to be |
|---|---|
| the fan clip's camera reprojects at **12 382 px** | measured in the wrong image space. `--crop auto` moved the homographies into a 1080×608 rect while the fit was handed 1080×1920, putting the principal point 656 px outside an image 608 px tall. Correct-space value: 18 313 px |
| `--camera-carry` was off in every scene ("unset means off") | wrong. The default is **8** at all three layers (`cli.py:690`, `cli.py:129`, `wiring.py:114`). The remedy the brief called untried had been on the whole time |
| "for handheld footage a novel view does not exist" | rested on an analogy, not a measurement — WorldPose has no phone clips. [M-1](findings/m1-fixed-centre.md) refuted it: fixing the camera position costs 0.90–1.23× |
| `FieldCalibration.confidence` | **anti-predictive**, Pearson r = +0.699 against real paint error. The frames it trusts most are the worst ones. Measured three times, still exported |
| `_SINGULAR_DET = 1e-12` catches degenerate homographies | misses the real cases by six orders of magnitude. Fan frames 115/117 sit at 1.0e-6 and 5.3e-8 |
| `--calibrator keypoints` runs the keypoint backend | without `--calibrator-backend` it constructs a stub that raises `NotImplementedError` |

And two of my own from the same session, so this is not a one-sided list: my first M-1 probe
returned a confident **wrong** verdict off a fit whose focal had run away to 87 px on a 1080 px
image, because it compared medians without comparing sample counts. And the frame plane hanging
above the grass, which the user asked about as a camera error, was a hardcoded 40 m default of
mine.

---

## The register

**Verified here** means a camlab test fails if it stops being true.

| what | status | how |
|---|---|---|
| `core/` — the 7 copied geometry modules | **verified** | `tests/test_golden_real_camera.py` loads the committed 7 kB npz and reproduces focal 4169.32 px, reprojection ~0, one optical centre for 60 frames at (−2.29, −70.13, 17.22) m |
| the pitch model constants | **verified** | `tests/test_server_contract.py` asserts them against the Laws of the Game: 105×68, crossbar 2.44 m, three spots, ±52.5 / ±34 |
| the OpenCV↔world conventions on the path to the viewer | **verified** | `tests/test_per_frame_solve.py` builds a homography from a camera with a known answer and checks the same camera comes back — focal, centre, rotation, a per-frame zoom with no position drift |
| the panel's angles and fov | **verified** | cross-checked against an independent Python computation over frames 0/30/60/90/116 |
| **the homographies M1 draws** | **unverified as a solve** | they come straight from a pitch3d `scene.json`. What *has* been checked is different and better: they sit **8.0 px** from the actual painted lines (M-1, and 1.7 px on the tripod clip). That is a check against pixels, not against pitch3d |
| `REALIZABLE_PX = 1.0` | **unverified** | an inherited threshold. Nothing observed sits near it, so it has never had to be right — but it has also never been re-derived for a phone clip |
| `FOCAL_BOUNDS = (300, 20000)` | **unverified, and it binds** | frame 116 pins at 20000 and one M-1 fit pinned at 300. A bound that is being hit is doing work, and this one was chosen for broadcast lenses |
| the fan clip zooms **1.66×** | **partially corroborated** | the brief measured it as p95/p05 of metres-per-pixel. camlab's per-frame focal independently gives ~1.9× over f0–108. Same order, different estimator, neither re-derived from the other |
| **the principal point is at the image centre** | **unverified, and it discards a measurement** | camlab assumes `cx, cy = W/2, H/2` in `solve/per_frame.py` and writes it into every `camera_auto.json` — inherited from `fit_rigid_camera.kmat()`, which hardcodes it and never fits it. But **PnLCalib returns a `principal_point`** and pitch3d's `calibration.py:645` consumes it, so the assumption overwrites a real measurement. Found 2026-08-10 by the agent working pitch3d's render thread, and it lands on camlab because camlab copied the assumption. Consequence worth testing before anything fancier: a displaced principal point produces exactly the 6.2 → 15.7 px centre-to-edge residual growth that pitch3d's #140 attributes to lens distortion, at **2** free parameters against a distortion model's 2–5. **Test cx/cy before reaching for distortion**, or a distortion fit will absorb the error and hide its cause |
| "a moving average on yaw removes 90 % of the jitter and flattens real 100° turns" | **unverified here** | inherited from a different subsystem (HMR pose), a different quantity (body yaw), and a different clip. It may well be true of camera filters too — it is a good hypothesis and a bad law. Task #8 **re-measures it** rather than citing it |

## What follows, mechanically

1. **A number from pitch3d gets a camlab test or gets marked unverified where it is cited.** No
   third option, and no quoting one in a commit message as if it were established here.
2. **Verification is against the video.** The paint residual, the overlay in window B, the goal
   frame landing on the goal. Not against another number pitch3d produced.
3. **A bound that is being hit is a finding, not a setting.** `FOCAL_BOUNDS` and `REALIZABLE_PX`
   both need re-deriving for phone clips; until then, report when they bind.
4. **This file gets a row whenever something moves from unverified to verified, or is refuted.**
   It is the honest answer to "how much of this can I trust?", and the answer today is: the
   geometry, yes; the calibration it is fed, only to 8 px against paint; the thresholds, not yet.
