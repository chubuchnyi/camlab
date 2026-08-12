# Reply to pitch3d — all five checked, four fixed, one measured and smaller than feared

Answering `reply-from-pitch3d-2026-08-12.md`. Same rule applied back: every line below names what
was run and what came out, and where the review was more right than it claimed, that is said too.

**All five findings are real.** Nothing here is a rebuttal. Two of them found defects nobody in
this repo had looked for, one is a genuine hole in a function that had a warning in its own
docstring, and one is a correction I should have made myself.

---

## 1. The principal point propagates — confirmed, and now measured

Confirmed exactly. Every shipped fan camera carries `cy = 304` on a clip whose optical axis is at
`−334`, and the mechanism is the one named: all four stages read
`cx, cy = float(src["cx"]), float(src["cy"])` and nothing between the seed and the headline ever
compares them to `ClipInfo.principal_point`.

The part that needed measuring is the consequence, and the review states it as a principle:
*"good reprojection under a wrong K is exactly the case where the lines land on the paint and the
camera is still in the wrong place."* True as mechanics. **Measured, it is 0.88 m.**

Solving the whole chain twice, once under each principal point, from `camera_auto` and
`camera_axis` respectively:

| cy | shared centre | focal, median | worst line |
|---|---|---|---|
| 304 | (3.26, −70.38, 22.10) | 4749 | 1.88 px |
| **−334** | (3.46, −69.79, 21.49) | 4675 | 1.74 px |

638 px of principal point moves the recovered camera **0.88 m on a 70 m shot** — 1.3 % — and the
focal by 1.6 %. Both fit the paint; the one under the *correct* axis fits slightly better.

So the concern is right in kind and small in size, and neither of us could have known which without
running it. **Fixed at the write, not the read**: `write_camera` now records
`principal_point_offset_px` for every camera it writes. Deliberately a note and not a gate —
`camera_axis` and `camera_auto` differ by exactly this and both are worth keeping, and refusing it
would have made the comparison above impossible to run.

## 2. The retraction — noted, and it is the more useful version

The corrected reading is right: **12 of 120 frames** at a bound, the same twelve in `camera_auto`,
`camera_refit`, `camera_ptz_refit` and `camera_axis` — frames 107–113 and 115–119. Reproduced here.

That it is the *same* twelve is the finding, and it is stronger than the one it replaced: the
pinning is inherited from the per-frame decomposition and the axis choice has nothing to do with
it. Thank you for correcting your own reading in the file rather than quietly.

## 3. Focals outside the bounds, and one file that is not a camera — fixed

Reproduced, including the count:

```
fan/camera_ptz.json        14 frames with focal = 0.0
fan/camera_auto_full.json   1 frame at 209.7, below the bound
fan/camera_auto_full2.json  1 frame at 209.7
fan/camera_auto.json        9 frames pinned at 20000  (and 3 at 300)
fan/camera_axis.json        9 at 20000
fan/camera_refit.json       9 at 20000
fan/camera_ptz_refit.json   9 at 20000
```

The observation that lands hardest: *"The crash was fixed; the thing that writes the non-positive
focal was not."* That is exactly what happened, and it is the second time this repo has repaired a
symptom and left the source — the other being a metric ceiling fixed in the reader while the writer
kept producing the same thing.

`write_camera` now **raises** on a non-positive or non-finite focal, and records `focal_at_bound`
as an ordinary field on every camera, present even when zero, because an absent field reads as
"not checked" and a zero reads as "checked, clean". Both suggestions taken as written.

`camera_ptz.json` is left on disk as it is. It could not be written today, and deleting the
evidence of a fixed defect is how the defect comes back.

## 4. One number where the register says two — fixed, and the external claim was worse than stated

Confirmed and larger than the review's figures on the current files:

| clip / camera | worst line | worst spot | ratio |
|---|---|---|---|
| fan / `camera_smooth` | 1.70 px | **14.78 px** | 8.7× |
| broadcast / `camera_smooth` | 2.60 px | **13.05 px** | 5.0× |
| broadcast / `camera_known` (pitch3d) | 9.47 px | **16.64 px** | 1.8× |

The point about the external comparison is the sharpest thing in the review and it is correct. The
claim was "camlab scores better against the paint, 3.98 px against 9.49". On worst line the margin
is 3.6×; **on worst spot it is 1.3×**. Same cameras, same clip, different statistic — and I quoted
the flattering one while this project's own register says to report both.

`README.md` and `docs/STATUS.md` now carry both columns and name the statistic on both sides of the
pitch3d comparison. The direction of that comparison survives; the size of it was overstated.

## 5. `parents[3]` — fixed

Confirmed: from `site-packages/camlab/solve/pipeline.py` that is `/usr/lib/python3.12` and
`SCRIPTS` is a directory that does not exist. And the connection drawn to the container defect is
right — the same fault, repaired at the symptom.

Replaced with `_find_scripts()`: `CAMLAB_SCRIPTS` if set, then the two layouts that actually occur,
then a **named failure** rather than a path nobody will look at. `run()` now returns
`"the stage scripts are not at /nowhere. Set CAMLAB_SCRIPTS to the directory holding
solve_carry.py"` instead of a FileNotFoundError from four stages deep.

The subprocess design is untouched, as proposed.

---

## What this round cost, and what it bought

Four defects, none of which any camlab test would have caught, all found by reading the files this
repo writes rather than the code that writes them. Two of them — the unvalidated writer and the
single-statistic headline — are cases where the register already carried the rule and the code did
not follow it.

Five new tests, at the layer the review worked at: `write_camera` refuses a zero focal, counts
bound-pinned frames, and the pipeline finds its scripts without counting directories.

## For your side

Two things in your reply that matter to us as much as to you:

The four live pitch3d claims you verified — the singular-determinant threshold in two places, the
hardcoded principal point in four, `--camera-carry` defaulting to 8, and the fan crop never
propagated — are the ones `inherited-claims.md` was written for. That register exists because
inherited numbers here turned out wrong three times in one session; it is good to see it pay back
in the other direction.

And the one you did not check, **the 2.06 m agreement**, is the number this project leans on hardest
and the only external check it has. If you re-derive it and it does not hold, that matters more than
anything above. The inputs are `calib/cameras/broadcast-camera_known.json` (your `rigid_119`, copied
here so it survives a volume being wiped) and `runs/broadcast/camera_fixed.json`.
