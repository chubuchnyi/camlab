"""A WARM `frame_residual` — the half that changes when the camera does.

The performance day measured a cold score: 463 ms, of which decode and `paint_masks` were 456,
*"the camera-dependent remainder is 7 ms"*, and it went on to spend the day on the 456. That was
the right call for a chain that scores each frame once. It is the wrong number for everything else
this repo does, because the paint cache means every search loop — a bootstrap ranking thousands of
cameras against one anchor, an LM refit issuing about a hundred objective evaluations, the polish
pass, every ICP round — pays the camera-dependent half over and over and the paint half once.

So this measures the warm score: paint already cached, camera moving. Reported per call, split
into the walk along each marking's normal and everything else.

    python scripts/bench_residual_warm.py fan broadcast --repeat 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"

from camlab.measure import residual as R  # noqa: E402


def camera_for(clip: str):
    """`(file, frame, kwargs)` for the clip's solved camera, on its first usable frame."""
    for name in ("camera_polished.json", "camera_smooth.json", "camera_carry.json"):
        path = RUNS / clip / name
        if not path.exists():
            continue
        got = json.loads(path.read_text())
        focals, positions = got.get("focal_px") or [], got.get("position") or []
        rotations, frames = got.get("rotation") or [], got.get("frames") or []
        for i, f in enumerate(focals):
            if f and f > 0:
                return name, int(frames[i]), dict(
                    focal=float(f), rvec=rotations[i], centre=positions[i],
                    frame=int(frames[i]), cx=got.get("cx"), cy=got.get("cy"))
    return None, None, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="+")
    ap.add_argument("--repeat", type=int, default=30)
    args = ap.parse_args()

    load = os.getloadavg()
    print(f"load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; treat every row as an upper bound ***")

    for clip in args.clips:
        name, idx, kw = camera_for(clip)
        if kw is None:
            print(f"{clip}: no solved camera in runs/, skipped")
            continue
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        path = frames[min(idx, len(frames) - 1)]

        R.clear_evidence_cache()
        t = time.perf_counter()
        R.frame_residual(path, **kw)
        cold = time.perf_counter() - t

        warm = 1e9
        for k in range(args.repeat):
            # nudge the camera so nothing downstream can be memoised on its value
            kw2 = dict(kw, focal=kw["focal"] * (1.0 + 1e-6 * k))
            t = time.perf_counter()
            got = R.frame_residual(path, **kw2)
            warm = min(warm, time.perf_counter() - t)

        # the walk on its own, at the sizes the real call uses
        dist, surface, spine, tree, w, h, scale = R.frame_evidence_cached(path)
        rng = np.random.default_rng(0)
        n = max(1, got.n)
        ys, xs = np.nonzero(surface > 0)
        take = rng.choice(len(xs), size=min(n, len(xs)), replace=False)
        sub = np.column_stack([xs[take], ys[take]]).astype(float)
        ang = rng.uniform(0, 2 * np.pi, len(sub))
        normal = np.column_stack([np.cos(ang), np.sin(ang)])
        walk = 1e9
        for _ in range(args.repeat):
            t = time.perf_counter()
            R._across_on_normal(sub, normal, dist, 40.0)
            walk = min(walk, time.perf_counter() - t)

        print(f"\n{clip}  {w}x{h}  {name} frame {idx}  {got.n} samples, "
              f"{len(got.per_line)} markings")
        print(f"  cold score (paint + camera)   {cold * 1e3:>8.1f} ms")
        print(f"  warm score (camera only)      {warm * 1e3:>8.1f} ms")
        print(f"    of which the normal walk    {walk * 1e3:>8.1f} ms   "
              f"{100 * walk / warm:.0f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
