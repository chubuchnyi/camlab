"""Score `findings/prediction-focal-deficit-2026-08-18.md` against a held-out match.

The prediction was committed (58004d4) BEFORE `ARG_CRO` was touched, and it names four quantities
with bands. This script reads them off a `bench_vs_worldpose.py --json` run and prints pass/fail per
band. It exists so the verdict is arithmetic rather than recollection: a band that is checked by
hand, after the numbers are visible, is not a band.

The coefficients and bands below are TRANSCRIBED FROM THE COMMITTED DOCUMENT and must not be
re-fitted here. If a band is wrong it is wrong in the document too, and the honest fix is a new
prediction against a match still held out — not an edit to this file.

    PYTHONPATH=src:. python scripts/check_prediction_focal.py out/worldpose/argcro.json

`--baseline` additionally re-states the working half so the two are read side by side.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

RUNS = Path.home() / "camlab/runs"

#: AVATAR's own list, `anchor_from_pnlcalib.KNOWN_HARD`, read here rather than imported so this
#: script does not need AVATAR on the path. One entry at the time of writing.
KNOWN_HARD = {"MOR_POR_181952"}


def comparable(clip: str, runs: Path = RUNS) -> bool:
    """Whether a clip counts, decided WITHOUT looking at its error.

    The working half's 18 came out of 23 by exactly two conditions: PnLCalib wrote an anchor, and
    AVATAR does not list the clip as known-hard. Both are settled before the chain runs, which is
    what makes them legitimate — a filter chosen after the errors are visible is not a filter, it is
    the result. Re-running this rule over the working half reproduces its 18 clips and every
    statistic in the finding to the printed digit, which is how it was checked.
    """
    return (runs / clip / "camera_manual.json").exists() and clip not in KNOWN_HARD


#: `position = SLOPE * (1 - focal_ratio) + INTERCEPT`, fitted on the 18 working-half clips.
SLOPE, INTERCEPT = 97.2, 1.44

#: Prediction 1/4: (low, high) for the median of each quantity.
FOCAL_BAND = (0.970, 0.988)
POSITION_BAND = (2.5, 5.0)
#: Prediction 2: residual sd of the transferred fit, in metres.
MAX_RESIDUAL_SD = 1.0
#: Prediction 3: the correlation must be at least this negative.
MAX_R = -0.85


def score(rows: list[dict]) -> dict:
    """The four predicted quantities, from whatever clips solved."""
    f = np.array([r["focal_ratio"] for r in rows], float)
    p = np.array([r["position_m"] for r in rows], float)
    resid = p - (SLOPE * (1.0 - f) + INTERCEPT)
    # r is undefined for <2 points and for a constant column; report nan rather than a crash, and
    # let the caller fail the band on nan.
    r = float(np.corrcoef(f, p)[0, 1]) if len(f) > 1 and f.std() and p.std() else float("nan")
    return {
        "n": len(rows),
        "focal_median": float(np.median(f)),
        "focal_mean": float(f.mean()),
        "focal_sd": float(f.std(ddof=1)) if len(f) > 1 else float("nan"),
        "focal_range": (float(f.min()), float(f.max())),
        "position_median": float(np.median(p)),
        "position_range": (float(p.min()), float(p.max())),
        "residual_sd": float(resid.std(ddof=1)) if len(resid) > 1 else float("nan"),
        "residual_mean": float(resid.mean()),
        "r": r,
    }


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("json", type=Path, help="output of bench_vs_worldpose.py --json")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="the working half's json, restated for comparison")
    args = ap.parse_args()

    every = [r for r in json.loads(args.json.read_text()) if r.get("focal_ratio")]
    rows = [r for r in every if comparable(r["clip"])]
    dropped = [r["clip"] for r in every if not comparable(r["clip"])]
    if not rows:
        raise SystemExit(f"no comparable clips in {args.json}")
    s = score(rows)

    print(f"HELD-OUT MATCH — {s['n']} clips solved and compared, "
          f"{len(dropped)} without an anchor\n")
    if dropped:
        print(f"  no anchor, excluded before any error was read: {', '.join(dropped)}\n")
    print(f"  focal ratio      median {s['focal_median']:.4f}  "
          f"mean {s['focal_mean']:.4f}  sd {s['focal_sd']:.4f}  "
          f"range {s['focal_range'][0]:.3f}–{s['focal_range'][1]:.3f}")
    print(f"  position error   median {s['position_median']:.2f} m  "
          f"range {s['position_range'][0]:.2f}–{s['position_range'][1]:.2f}")
    print(f"  fit residual     sd {s['residual_sd']:.2f} m  mean {s['residual_mean']:+.2f} m")
    print(f"  position vs focal  r = {s['r']:+.3f}\n")

    checks = [
        ("1  focal median in "
         f"[{FOCAL_BAND[0]:.3f}, {FOCAL_BAND[1]:.3f}]", s["focal_median"],
         FOCAL_BAND[0] <= s["focal_median"] <= FOCAL_BAND[1], True),
        (f"2  fit transfers, residual sd <= {MAX_RESIDUAL_SD:.1f} m", s["residual_sd"],
         s["residual_sd"] <= MAX_RESIDUAL_SD, True),
        (f"3  correlation r <= {MAX_R:.2f}", s["r"], s["r"] <= MAX_R, True),
        ("4  position median in "
         f"[{POSITION_BAND[0]:.1f}, {POSITION_BAND[1]:.1f}] m", s["position_median"],
         POSITION_BAND[0] <= s["position_median"] <= POSITION_BAND[1], False),
    ]
    for label, value, ok, load_bearing in checks:
        mark = "" if load_bearing else "   (outcome, not an independent test)"
        print(f"  {_verdict(ok):4}  {label:<44} got {value:+.4f}{mark}")

    load = [ok for _, _, ok, lb in checks if lb]
    print()
    if all(load):
        print("  All three load-bearing predictions hold. The focal deficit behaves as a constant")
        print("  of the method on a match that had no part in producing the number.")
    else:
        print("  REFUTED. At least one load-bearing prediction failed, and the committed document")
        print("  says what that means: the constant focal correction must not be shipped.")
        print("  Do not widen a band, drop a clip, or fit a second model to this match.")

    if args.baseline and args.baseline.exists():
        b = score([r for r in json.loads(args.baseline.read_text())
                if r.get("focal_ratio") and comparable(r["clip"])])
        print(f"\n  working half, restated: {b['n']} clips, focal median {b['focal_median']:.4f}, "
              f"position median {b['position_median']:.2f} m, r {b['r']:+.3f}")
    return 0 if all(load) else 1


if __name__ == "__main__":
    raise SystemExit(main())
