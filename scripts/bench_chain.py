"""The whole chain, timed per stage, against a COPY of the run directory.

Two rules this obeys that the repo learned the hard way.

**It never writes to the run directory it was pointed at.** Every stage rewrites camera files, and
`docs/STATUS.md`'s first paragraph is about eight of nine clips left holding a stale
`camera_polished.json`. A benchmark that overwrites the measurements it is being compared against
destroys the thing it is measuring. `--work` copies the clip somewhere else and points `CAMLAB_RUNS`
at the copy.

**It reports the camera it got, not only the seconds.** A stage that got faster and worse is not
faster. The `across` figure from `verdict`/`bench_metric_ceiling` is the check; this prints the
final camera's own worst-marking numbers so a regression cannot hide behind a wall-clock win.

    python scripts/bench_chain.py broadcast --work /tmp/camlab-bench
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))

from camlab.solve.pipeline import FINAL_CAMERA, STAGES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--work", required=True, help="where to copy the clip to; wiped first")
    ap.add_argument("--source-runs", default=None, help="default: this tree's runs/")
    ap.add_argument("--seed", default=None,
                    help="camera file to start from; default: the first that exists")
    ap.add_argument("--anchor", default=None)
    ap.add_argument("--workers", default=None, help="CAMLAB_WORKERS for every stage")
    args = ap.parse_args()

    src = Path(args.source_runs or (HERE / "runs")) / args.clip
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    (work / "runs").mkdir(parents=True)
    shutil.copytree(src, work / "runs" / args.clip)

    seed = args.seed
    if seed is None:
        for cand in ("camera_seed_used.json", "camera_start.json", "camera_boot.json",
                     "camera_auto.json", "camera_manual.json"):
            if (work / "runs" / args.clip / cand).exists():
                seed = cand
                break
    if seed is None:
        raise SystemExit(f"no seed camera in {src}; pass --seed")

    env = dict(os.environ, CAMLAB_RUNS=str(work / "runs"),
               PYTHONPATH=str(HERE / "src") + os.pathsep + os.environ.get("PYTHONPATH", ""))
    if args.workers:
        env["CAMLAB_WORKERS"] = args.workers

    load = os.getloadavg()
    print(f"{args.clip}  seed {seed}  tree {HERE}  load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
    if load[0] > 1.0:
        print("  *** the machine is busy; treat every row as an upper bound ***")

    total = 0.0
    prev = seed
    for label, script, extra in STAGES:
        cmd = [sys.executable, str(HERE / "scripts" / script), args.clip]
        if script == STAGES[0][1]:
            cmd += ["--seed", seed]
            if args.anchor:
                cmd += ["--anchor", args.anchor]
        cmd += extra
        t = time.perf_counter()
        got = subprocess.run(cmd, env=env, capture_output=True, text=True, cwd=str(HERE))
        took = time.perf_counter() - t
        total += took
        tail = (got.stdout or got.stderr).strip().splitlines()
        print(f"  {label:<16}{took:>8.1f} s   {tail[-1][:78] if tail else ''}")
        if got.returncode != 0:
            print(f"  *** {label} failed ***\n{(got.stderr or '')[-2000:]}")
            return 1
        prev = extra[extra.index("--out") + 1] if "--out" in extra else prev

    print(f"  {'TOTAL':<16}{total:>8.1f} s")

    final = work / "runs" / args.clip / FINAL_CAMERA
    if final.exists():
        cam = json.loads(final.read_text())
        focals = [f for f in (cam.get("focal_px") or []) if f and f > 0]
        print(f"  {FINAL_CAMERA}: {len(focals)}/{len(cam.get('focal_px') or [])} frames with a "
              f"focal, median {sorted(focals)[len(focals) // 2]:.1f} px" if focals else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
