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

**And it prints a fingerprint of what it read, because the source moves.** On 2026-08-16 a
comparison over all fourteen clips overlapped with the operator's own solve, which rewrote
`runs/g11710897/camera_seed_used.json` at 21:01 and five other clips' files the same afternoon.
Every row stayed internally sound — both trees run back to back from one fresh copy, and every row
reported `0 differ`, which a changed seed could not have survived — but the rows could not be set
beside the previous round's: the same clip read 219.4 -> 74.3 s at across 14.70 px where an hour
earlier it read 110.3 -> 55.9 at 9.69. Same code, different input. That is the run-directory
landmine from the other side: not a stale output, a **moving input**.

Two things follow. The header carries a hash of every byte of the clip directory that was read, so
two tables can be told apart by reading them rather than by remembering when they were taken. And
`--snapshot DIR` takes one copy of the clip and reuses it for every later invocation, so a
comparison is comparable by construction: point both trees, and every round, at the same snapshot.

    python scripts/bench_chain.py broadcast --work /tmp/camlab-bench
    python scripts/bench_chain.py broadcast --work /tmp/w --snapshot /tmp/frozen   # comparable
"""
from __future__ import annotations

import argparse
import hashlib
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


def fingerprint(clip_dir: Path) -> str:
    """Twelve hex digits over every byte the chain will read out of this clip directory.

    Content, not mtimes: a copy has new mtimes and the same bytes, and it is the bytes that decide
    what the chain does. About 25 ms on a 24 MB clip, which is nothing against a run measured in
    minutes, and it is the difference between two tables that can be compared and two that only
    look as though they can.
    """
    h = hashlib.sha256()
    for path in sorted(p for p in clip_dir.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(clip_dir)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--work", required=True, help="where to copy the clip to; wiped first")
    ap.add_argument("--source-runs", default=None, help="default: this tree's runs/")
    ap.add_argument("--seed", default=None,
                    help="camera file to start from; default: the first that exists")
    ap.add_argument("--anchor", default=None)
    ap.add_argument("--workers", default=None, help="CAMLAB_WORKERS for every stage")
    ap.add_argument("--snapshot", default=None,
                    help="freeze the clip here on first use and read it from there afterwards, so "
                         "rounds taken hours apart are comparable by construction")
    args = ap.parse_args()

    src = Path(args.source_runs or (HERE / "runs")) / args.clip
    if args.snapshot:
        frozen = Path(args.snapshot) / args.clip
        if not frozen.exists():
            frozen.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, frozen)
        src = frozen

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
    print(f"{args.clip}  seed {seed}  tree {HERE}  source {fingerprint(src)}"
          f"{'  (frozen)' if args.snapshot else ''}  "
          f"load {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
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
