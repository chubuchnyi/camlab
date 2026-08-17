"""Is the frame-to-frame homography worth anything? — asked of the SHIPPED chain, on every clip.

A causal tracker measured it to be worth nothing on seven clips: carrying the previous camera
through the measured homography and carrying nothing at all gave the same `across` to within noise,
and on three clips no-motion was very slightly better. SIFT costs 75–185 ms a frame and about
11 s of a 24 s `carry` stage to achieve that.

That was a loop resembling `solve_carry`, not `solve_carry`, and it differed in four ways that
could each reverse it — it refit every frame with the position held where the chain frees it, it
was seeded from the chain's own polished answer rather than a hand anchor, it walked one direction
from one anchor rather than outward from several, and the carry should matter exactly where the
REFIT fails, which in those runs it rarely did.

So this asks the whole chain, both ways, over every clip, from one frozen copy of each:

    solve_carry ... --no-carry     vs     solve_carry ...

**Judged on `across` and the marking count, not on seconds.** Seconds are reported because if the
answer is "it buys nothing" then `measure_pairs` comes off the critical path and that is the point
— but a stage cannot be retired for being slow, only for being unnecessary.

`--snapshot` freezes each clip on first use, so both configurations and every later round read
identical bytes. That is not optional: a comparison over this repo's `runs/` once overlapped with
the operator's own solve and two rounds of the same code came out 219.4 s and 110.3 s apart.

    python scripts/bench_carry_necessity.py --snapshot /tmp/frozen --work /tmp/w
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
RUNS = HERE / "runs"

VERDICT = re.compile(
    r"across\s+([\d.]+) px.*?worst line\s+([\d.]+).*?worst spot\s+([\d.]+)")
FOCALS = re.compile(r"(\d+)/(\d+) frames with a focal, median ([\d.]+)")


def run(clip: str, work: Path, snapshot: Path, extra: list[str],
        seed: str | None = None) -> dict | None:
    cmd = [sys.executable, str(HERE / "scripts" / "bench_chain.py"), clip,
           "--work", str(work), "--snapshot", str(snapshot)]
    if seed:
        cmd += ["--seed", seed]
    cmd += extra
    got = subprocess.run(cmd, capture_output=True, text=True, cwd=str(HERE))
    if got.returncode != 0:
        return None
    out = got.stdout
    total = re.search(r"TOTAL\s+([\d.]+) s", out)
    # `startswith`, not `in`: the summary line names `camera_polished.json` and would win a
    # substring test, which is how this first reported `nan` for every clip.
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("polish")]
    v = VERDICT.search(lines[-1]) if lines else None
    f = FOCALS.search(out)
    return {
        "seconds": float(total.group(1)) if total else float("nan"),
        "across": float(v.group(1)) if v else float("nan"),
        "worst_line": float(v.group(2)) if v else float("nan"),
        "worst_spot": float(v.group(3)) if v else float("nan"),
        "frames": f"{f.group(1)}/{f.group(2)}" if f else "-",
        "focal": float(f.group(3)) if f else float("nan"),
        "verdict": "NO VERDICT" if "NO VERDICT" in out else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=None)
    ap.add_argument("--work", required=True)
    ap.add_argument("--snapshot", required=True)
    ap.add_argument("--seed", default=None,
                    help="seed camera for every clip. `bench_chain` otherwise picks the first that "
                         "exists, which on `fan` is `camera_boot.json` and yields NO VERDICT — the "
                         "clip's real chain starts from its 44 kB of hand anchors and reaches "
                         "1.82 px. Getting that wrong dropped the most carry-relevant clip in the "
                         "set, the one whose camera actually moves, out of the evidence.")
    args = ap.parse_args()

    clips = args.clips or sorted(
        p.name for p in RUNS.iterdir()
        if (p / "frames").is_dir() and any((p / "frames").glob("*.jpg")))
    work, snap = Path(args.work), Path(args.snapshot)

    print(f"{'clip':<26}{'':>10}{'across':>9}{'worst line':>12}{'worst spot':>12}"
          f"{'frames':>10}{'focal':>10}{'seconds':>9}")
    better = worse = same = novote = 0
    for clip in clips:
        # Interleaved per clip so machine load falls on both configurations, and from the same
        # frozen copy so neither can be reading a different clip from the other.
        with_carry = run(clip, work / "with", snap, [], args.seed)
        no_carry = run(clip, work / "without", snap, ["--first-stage-arg=--no-carry"], args.seed)
        if with_carry is None or no_carry is None:
            print(f"{clip:<26}  FAILED")
            continue
        for label, r in (("with carry", with_carry), ("NO carry", no_carry)):
            print(f"{clip if label == 'with carry' else '':<26}{label:>10}"
                  f"{r['across']:>9.2f}{r['worst_line']:>12.2f}{r['worst_spot']:>12.2f}"
                  f"{r['frames']:>10}{r['focal']:>10.1f}{r['seconds']:>9.1f}"
                  f"  {r['verdict']}")
        d = no_carry["across"] - with_carry["across"]
        # `nan - nan` is `nan`, and every comparison with it is False, so a clip with no verdict
        # on EITHER side used to fall into "unchanged" and be counted as agreement. Absence is not
        # agreement, and a summary that says otherwise is the kind of thing this repo retracts.
        if d != d:
            novote += 1
        elif d < -0.01:
            better += 1
        elif d > 0.01:
            worse += 1
        else:
            same += 1
        print(f"{'':<26}{'delta':>10}{d:>+9.2f}"
              f"{no_carry['worst_line'] - with_carry['worst_line']:>+12.2f}"
              f"{no_carry['worst_spot'] - with_carry['worst_spot']:>+12.2f}"
              f"{'':>10}{'':>10}{no_carry['seconds'] - with_carry['seconds']:>+9.1f}")

    total = better + worse + same + novote
    print(f"\nwithout the carry, by `across` (the camera alone): better on {better}, "
          f"WORSE on {worse}, unchanged on {same} — of {total - novote} clips that HAVE a verdict. "
          f"{novote} more score too few markings to say either way, on both sides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
