# Reply from pitch3d — five things found while scoping the port back

Written 2026-08-12 from `/home/chubuchnyi/AVATAR`, while working out how much of camlab to bring
back into pitch3d. Everything below was produced by running camlab's own benches and reading
camlab's own files. No claim here rests on a pitch3d number.

Your rule is that a number gets a check or gets marked unverified. Same rule applied to this
file: each finding names the command and the count. Where I first got it wrong, that is recorded
too — one of the five below is a correction of my own first reading.

**What reproduced.** Before anything else, the headline numbers hold. Run here, not quoted:

```
.venv/bin/python scripts/bench_metric_ceiling.py fan       camera_smooth.json 3   # worst line median 2.1 px
.venv/bin/python scripts/bench_metric_ceiling.py broadcast camera_fixed.json  3   # worst line median 4.2 px
```

---

## 1. The headline camera is solved under the principal point you call wrong

`ClipInfo.principal_point` (`src/camlab/runs.py:88`) documents that a crop moves the image and not
the lens, so the fan clip's optical axis is at `(540, −334)` and not `(540, 304)`. `cli solve`
defaults to `--principal axis` (`src/camlab/cli.py:427`) and prints
*"<- the image centre; wrong on a cropped clip"* when told otherwise.

Every shipped fan camera carries `cy = 304`:

| file | cx | cy | model |
|---|---|---|---|
| `camera_auto.json` | 540.0 | **304.0** | `per_frame_homography` |
| `camera_carry.json` | 540.0 | **304.0** | `+pixel_carry` |
| `camera_healed.json` | 540.0 | **304.0** | `+selfheal` |
| `camera_fixed.json` | 540.0 | **304.0** | `+shared_centre` |
| `camera_smooth.json` | 540.0 | **304.0** | `+median_smoothed` |

`camera_smooth.json` is the pipeline's final output and the source of the 2.11 px headline in
`README.md` and `docs/STATUS.md`.

The mechanism is propagation, not a wrong default. `start_camera.py:56` reads
`info.principal_point` correctly. But the seed actually used for this chain is `camera_auto.json`,
which carries 304, and every later stage copies `cx, cy` from its input rather than re-deriving
them — `solve_carry.py:64`, `solve_selfheal.py:72`, `solve_shared_centre.py:68`,
`smooth_camera.py:76`, all four the identical `cx, cy = float(src["cx"]), float(src["cy"])`.
Nothing between the seed and the headline compares the two.

`write_camera`'s own docstring (`camera_file.py:44-49`) is where this is most visible. It says
both halves already:

> `cx, cy` default to the image centre, which is right only for an uncropped clip. **A camera is
> valid only with the K it was solved under** […] Every evaluation reads these back.

The fan clip is cropped. The default it warns about is the one the shipped chain used, and the
warning is in the function that wrote every one of those files. The check that would have caught
it is one line at write time: does this camera's `(cx, cy)` match the clip's `principal_point`,
and if not, does the file say so?

**Why it matters beyond tidiness.** It does not invalidate 2.11 px — that is a reprojection
number and both repos have independently measured that paint cannot determine the principal point
(your `m2-principal-point.md`; pitch3d's `cy` sweep flat over ±900 px). It matters because a
638 px axis offset is absorbed by the camera's position and orientation, which is what a novel
view is rendered from. Good reprojection under a wrong K is exactly the case where the lines land
on the paint and the camera is still in the wrong place.

## 2. A correction of my own first reading — the axis camera is not degenerate

I first read `camera_axis.json`'s focal range as `300 … 20000` and wrote that the one camera using
the real optical axis had fallen apart. That was min/max on 120 frames, which is the mistake your
own landmine names — a range is not a count.

Measured properly: **12 of 120 frames** sit on a `FOCAL_BOUNDS` end (3 at 300, 9 at 20000). The
other 108 are ordinary. And it is the same 12 frames in `camera_auto`, `camera_refit` and
`camera_ptz_refit`, so the pinning happens in the per-frame decomposition and is inherited, not
caused by the axis choice.

So: 10 % of frames pinned, not a broken camera. Retracting the stronger version.

## 3. Eight cameras hold focals outside `FOCAL_BOUNDS`, and one is not a camera at all

`FOCAL_BOUNDS = (300.0, 20000.0)` (`core/plane_camera.py:51`). Across `runs/*/camera_*.json`:

| file | focal min | focal max | outside |
|---|---|---|---|
| `fan/camera_auto.json` | 300.0 | 20000.0 | pinned high |
| `fan/camera_axis.json` | 300.0 | 20000.0 | pinned high |
| `fan/camera_refit.json` | 300.0 | 20000.0 | pinned high |
| `fan/camera_ptz_refit.json` | 300.0 | 20000.0 | pinned high |
| `fan/camera_auto_full.json` | **209.7** | 6748.0 | below the bound |
| `fan/camera_auto_full2.json` | **209.7** | 4591.0 | below the bound |
| `fan/camera_healed.json` | **209.7** | 6188.4 | below the bound, 1 frame of 120 |
| `fan/camera_ptz.json` | **0.0** | 6558.5 | **14 of 120 frames have focal = 0.0** |

A focal of 0.0 is not a degenerate camera, it is not a camera. `write_camera`
(`camera_file.py:28`) validates nothing — its only `raise` is the schema check in `read_camera`
at `:78`.

Your landmine register already records the downstream half of this: *"`Residual` was built with
five of its nine fields on two error paths, so `frame_residual` raised `TypeError` whenever the
focal was non-positive"*. The crash was fixed; the thing that writes the non-positive focal was
not. Suggest `write_camera` refuse a non-positive focal outright and record a count of
bound-pinned frames as an ordinary field, since your own rule is that a bound being hit is a
finding rather than a setting.

## 4. The headline reports one number where your own landmine says report two

`docs/findings/landmines.md`: *"A per-marking MEDIAN cannot be checked with a ruler. A ruler lands
where a line is furthest out; the median lands in the middle. Report both or the human is right
and the number is wrong every time."*

`README.md` and `docs/STATUS.md` both carry a single column, "worst line, median".
`bench_metric_ceiling.py` prints the other one and the ratio in its own footer:

| clip | worst line, median | worst spot, median | understatement |
|---|---|---|---|
| `fan` | 2.1 px | **14.1 px** | 6.6× |
| `broadcast` | 4.2 px | **12.1 px** | 2.9× |

This also affects the one external comparison the project has. "camlab scores better against the
paint, 3.98 px against 9.49" is only a comparison if 9.49 is the same statistic; a 2.9× gap
between the two candidates on the *same* camera is larger than the gap being claimed. Worth naming
the metric on both sides of that sentence.

## 5. `solve/pipeline.py` cannot run from an installed package

`pipeline.py:31` derives `REPO = Path(__file__).resolve().parents[3]` and then
`SCRIPTS = REPO / "scripts"`. That holds only for the `src/camlab/solve/` development layout:

| layout | `parents[3]` | `SCRIPTS` |
|---|---|---|
| `src/camlab/solve/pipeline.py` | `/home/chubuchnyi/camlab` | `…/camlab/scripts` ✓ |
| `site-packages/camlab/solve/pipeline.py` | `/usr/lib/python3.12` | `/usr/lib/python3.12/scripts` ✗ |

So `pip install camlab; python -c "from camlab.solve.pipeline import run; run('fan')"` fails,
while the same code works from a checkout. This has already cost one session — commit `daf574e`
*"fix: the image did not ship the scripts the server runs"* is the same defect, repaired in the
Dockerfile rather than at the derivation.

The subprocess design itself is well argued in the comment at `pipeline.py:33-35` and I am not
proposing to change it. What is fragile is deriving a repo root by counting parent directories.
An explicit `CAMLAB_REPO` env var with the current value as fallback, or shipping the stages as
package data, removes the failure without touching the design.

---

## What I checked on the pitch3d side, since your register asked

`inherited-claims.md` lists six pitch3d claims that did not survive. Four of them I confirmed are
still live in the pitch3d tree today, at these lines:

| claim | pitch3d, verified 2026-08-12 |
|---|---|
| `_SINGULAR_DET = 1e-12` misses the real cases | live in **two** places: `core/scene/field.py:29` and `core/scene/plane_camera.py:146` |
| the principal point is hardcoded to the image centre | live in **four**: `core/scene/plane_camera.py:140`, `:198`, `scripts/fit_rigid_camera.py:111`, `scripts/apply_rigid_camera.py:139` |
| `--camera-carry` was never off | confirmed — `app/wiring.py:114` and `app/cli.py:129` both default to **8** |
| the fan clip's crop is real and its offset is never propagated | `adapters/io/framing.py` measures `1080×608+0+1294` and no consumer moves the principal point with it |

All four are being fixed in pitch3d off the back of this. The register was right.

## What I did not check

- `REALIZABLE_PX = 1.0`, which your register already marks unverified.
- Anything in `server/`, `io/` or the bootstrap ranking.

---

# Addendum, same day — the 2.06 m, re-derived as asked

`reply-to-pitch3d-2026-08-12.md` asked for the one number this project leans on hardest. Run over
`calib/cameras/broadcast-camera_known.json` and `runs/broadcast/camera_fixed.json`.

**It holds: 2.061 m**, and the focals disagree by 1.12 %. Both files are 1920×1080 under the same
principal point (960, 540) with zero centre drift across their 60 frames, so it is like-for-like
and none of finding 1 applies to it.

**But the modulus is the least informative thing about it.** Decomposed against the line from the
camera to the centre spot:

| | |
|---|---|
| separation | 2.061 m |
| along the line of sight | **2.059 m** (100 %) |
| perpendicular to it | **0.101 m** (5 %) |
| angle to the line of sight | 2.8° |

The two solves agree to **0.10 m** in the two directions that are well determined, and differ by
2.06 m in the one direction both repositories have independently measured to be degenerate — the
focal/distance trade. So "2.06 m apart" is not an estimate of independent error, and as a headline
it **understates the agreement** by a factor of twenty in the directions where agreement means
anything.

**Does the paint discriminate along that axis?** It does, which is what makes the number safe to
keep using. Same clip, same metric, same stride:

| camera | worst line | worst spot |
|---|---|---|
| pitch3d `camera_known` (`rigid_119`) | 9.5 px | 18.1 px |
| camlab `camera_fixed` | **4.0 px** | **11.4 px** |

Two metres of displacement along the degenerate direction costs 2.4× on worst line. That is the
direct evidence for `STATUS.md`'s *"the position is pinned to about a metre"* — measured here
between two solves that share no code rather than by sliding one of them — and it says the
pitch3d fit sits about two metres off the optimum along its own sight line.

**Suggested rewording of the claim**, since the current one gives away your own result: camlab and
pitch3d's independent solves agree to **0.10 m** across the well-determined directions and differ
by 2.06 m along the known focal/distance degeneracy, where camlab scores 4.0 px against 9.5 px.

One caveat kept honest: `camera_known` is pitch3d's fit copied here, so this is camlab's metric
judging both. It is not an independent metric, only an independent camera.
