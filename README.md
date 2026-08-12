# camlab

**One question: where was the camera, where was it pointed, and what was the focal, on each frame.**

A clip goes in. A camera comes out — visible in 3D, editable by hand, and checkable by eye against
the video: project the pitch model through it and the lines must land on the paint.

Everything else — poses, physics, rendering, the generative tail — stays in `pitch3d`.

**Read [`docs/STATUS.md`](docs/STATUS.md) first.** It is what is true right now, and this file is
only the way in.

## Where it stands

| clip | worst line, median | frames under 20 px | camera movement between frames |
|---|---|---|---|
| `fan` — 1080×608, a phone from the stands, floodlit night | **2.11 px** | **120/120** | 0.00 m |
| `broadcast` — 1920×1080, professional | **3.98 px** | 59/60 | 0.00 m |

On `broadcast`, camlab's camera lands **2.06 m** from pitch3d's, which was fitted from PnLCalib
keypoints by a completely different route, with the focals agreeing to 1.1 % — and camlab scores
better against the paint, 3.98 px against 9.49. That is the only external check this project has;
everything else is camlab against camlab or camlab against an eye.

`fan` used one hand-aligned frame as its anchor. With no human at all the same chain reaches
7.75 px and 100 of 120 frames. The whole difference is the seed, and getting one automatically is
the main thing still open — see **#11** in `docs/STATUS.md`.

## Use it

Everything below is also a button in the viewer.

```bash
# upload an mp4 in the UI, or:
python -m camlab ingest myclip --video /path/to/clip.mp4 --frames 60

# a labelled default camera to drag from — stands, looking at the centre spot, 22 deg of horizontal
# field of view. Nothing in it is measured; the file says is_default: true.
.venv/bin/python scripts/start_camera.py myclip

# align ONE frame by eye in the viewer, then:
.venv/bin/python scripts/solve_carry.py        myclip --anchor 12 --seed camera_start.json \
                                                      --free-position --out camera_carry.json
.venv/bin/python scripts/solve_selfheal.py     myclip --from camera_carry.json  --out camera_healed.json
.venv/bin/python scripts/solve_shared_centre.py myclip --from camera_healed.json --out camera_fixed.json
.venv/bin/python scripts/smooth_camera.py      myclip --from camera_fixed.json  --out camera_smooth.json
```

Judging a camera:

```bash
.venv/bin/python scripts/bench_metric_ceiling.py myclip camera_smooth.json 3   # against the paint
.venv/bin/python scripts/check_stripes.py        myclip --camera camera_smooth.json
```

The second one is the check that never touches the markings: mowing stripes are evenly spaced in
metres, so through a right camera their period holds while the operator zooms. On `fan` it holds at
11.00 m ± 2.3 % across a 1.61× zoom.

## What it needs, and what it does not

**No GPU. No neural network. No ML runtime of any kind.** Every stage is classical computer vision
and numerical optimisation: SIFT features and a MAGSAC homography for frame-to-frame motion, a
distance transform and Hough or LSD for the markings, `scipy.optimize` for the fit, a k-d tree for
the paint residual. Nothing is trained, nothing is downloaded, and there is no checkpoint to lose.
The whole install is numpy, scipy, opencv-headless and FastAPI.

Measured on a laptop CPU — 11th-gen i7-11850H, no GPU in the machine:

| | |
|---|---|
| full chain, 60 frames at 1920×1080 | **155 s** |
| per-frame work (paint, lines, refit, score) | **340 ms** |
| peak memory, per-frame work | 180 MB |
| peak memory, full chain | 1.1 GB |
| install size | 482 MB |
| a 60-frame run on disk | ~24 MB of JPEG |

**One core is the whole requirement.** The work is single-threaded and does not benefit from more:
342 ms a frame on one thread, 324 ms on sixteen — five per cent, which is noise. Several stages are
embarrassingly parallel across frames and simply are not parallelised, so more cores *could* help,
but that is work nobody has done rather than a property of the method.

The GPU box in `scripts/deploy.sh` is used because it is a machine that is always on and reachable,
not because anything here needs it. This runs on a laptop.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,cv]"
.venv/bin/python -m pytest                                   # 89 tests, ~6 s
.venv/bin/uvicorn camlab.server.app:app --port 8000          # -> http://localhost:8000
```

```bash
docker build -f docker/Dockerfile -t camlab:m0 .
docker run --rm -p 8000:8000 -v "$PWD/runs:/runs" camlab:m0
```

## On the GPU box

```bash
bash scripts/deploy.sh          # pack HEAD -> ship -> build in WSL -> run detached -> tunnel
bash scripts/tunnel.sh          # just the tunnel, when it drops. --watch keeps it up.
```

`deploy.sh` ships **HEAD, not the working tree**. Deploy after committing, and check what the box
actually serves rather than trusting a green deploy — a control was once deployed before it was
committed and reported missing by the person looking at it.

**Access is an ssh tunnel, not an open port.** WSL's localhost forwarding does not reach the
container, so the alternative is `netsh interface portproxy` plus a firewall rule. The tunnel needs
neither, exposes nothing to the LAN, and survives the thing a portproxy does not: the WSL IP is
dynamic and changes when the VM restarts.

**The WSL VM sleeps when nothing is attached**, taking dockerd with it — every probe wakes it, it
answers, and it sleeps again, so the box reads alive from a shell and dead from a browser.
`tunnel.sh` holds a `wsl.exe` process open to prevent that.

## Two rules it keeps

**No CDN.** three.js is vendored under `src/camlab/server/static/vendor/` with checksums, and a
test fails if any served file reaches the network. The box runs behind a link that resets every
~250 MB and is reached only over ssh; a page that fetches its renderer at load time does not open.

**The browser never posts a matrix.** It posts a gesture or a few scalars and the server derives the
transform. This survived adding a rotation gizmo: the gizmo derives the three angles the server
speaks — with roll read in the level basis, verified against the server to 1e-16 degrees — and
sends those.

## What can be trusted here

**camlab's ground truth is the video, not pitch3d's outputs**, and not its own earlier conclusions.
This thread has retracted a great deal of its own work on measurement: a metric that could not
report an error larger than 40 px, an overlap test that discarded exact matches, a "not radial"
argument computed about the wrong centre, a pincushion signature that was seven samples of noise, a
boundary hit reported as an optimum twice, and three separate ideas for telling markings from
mowing stripes that measurement refuted.

The register of traps is [`docs/findings/landmines.md`](docs/findings/landmines.md) and it is the
one place they go. What was inherited from upstream and whether it has been checked is
[`docs/inherited-claims.md`](docs/inherited-claims.md).

## Layout

```
src/camlab/
  core/      pure numpy: pitch model, camera types, plane->camera recovery, projection
  measure/   the paint in the frame, and how far a camera is from it — the ground truth
             lines, line_error, residual, ellipse (the arcs), stripes (the turf), pixel_motion
  solve/     carry, refit (Nelder-Mead and Levenberg-Marquardt), bootstrap, per_frame, pipeline
  io/        video in, frames and clip.json out; reading an upstream scene
  server/    FastAPI + a vendored three.js viewer, no CDN, no build step
scripts/     every stage as a CLI, and the benches the findings cite
docs/
  STATUS.md            what is true right now — start here
  PROBLEM.md           the problem stated for someone who has not seen this repo
  findings/            measurements made here, including the refutations
  findings/landmines.md  traps that have already cost time
  archive/             superseded, kept for the record
tests/     against real captured data wherever possible, not against fakes
```

## Relationship to pitch3d

camlab is **self-contained**: it installs, tests, runs and deploys without pitch3d present. What
came from there is a **copy**, not a dependency — the camera contract itself had to change here,
since `CameraTrack` holds one intrinsic for a whole clip and a zoom is not representable in it.
Each copied file carries a header saying where it came from. Do not hand-sync them back.

`tests/test_golden_real_camera.py` pins the copy against the same real measurement pitch3d pins:
focal 4169.32 px, one optical centre for 60 frames at (−2.29, −70.13, 17.22) m.
