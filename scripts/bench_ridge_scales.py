#!/usr/bin/env python3
"""Re-solve every clip under both ridge-scale sets and compare the verdicts.

`RIDGE_SCALES = (2, 4, 7)` brackets a broadcast lens. Two clips are measured to need more — the
near touchline on `g11710897` is 34–54 px wide, and the paint on `MOR_POR_181952` frame 7 is 7–14
px — but this branch has ALSO recorded, on 2026-08-13, that widening doubles the junk on
`g11710897` frames 0 and 1. Both readings are about single frames. This one is about whole clips
and the only test that decides anything here: the verdict against the paint.

Each clip is solved twice from the same seed, in the same process order, so the only difference is
the scale set. `runs/` is left holding whichever camera the LAST run wrote, which is deliberate —
the second run is the candidate default.

    PYTHONPATH=src python scripts/bench_ridge_scales.py --json out/ridge-ab.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.runs import ClipInfo, runs_root  # noqa: E402
from camlab.solve.pipeline import FINAL_CAMERA, anchors_for, run  # noqa: E402

SHIPPED = "2,4,7"
WIDE = "2,4,7,14,28"

#: `--derived` compares the shipped constant against the ladder each clip's own paint asks for
#: (`paint.scales_for_clip`), which is the point of #38: neither constant serves everything.
DERIVED = "derived"

#: Where a clip's chain starts. `camera_start.json` is the labelled default guess and is what a
#: clip has before anyone touches it; a clip without one has never been given a starting point and
#: there is nothing to re-solve.
SEED = "camera_start.json"


def verdict(clip_id: str) -> dict:
    from camlab.measure.verdict import judge_file

    info = ClipInfo.load(clip_id)
    p = info.dir / FINAL_CAMERA
    if not p.exists():
        return {"line": "no camera written", "supported": False}
    v = judge_file(clip_id, FINAL_CAMERA)
    return {"line": v.line(), "supported": bool(v.supported),
            "across": float(v.worst_across_px), "worst_line": float(v.worst_line_px),
            "markings": int(v.markings), "under_20": int(v.under_20),
            "n_supported": int(v.n_supported)}


def one(clip_id: str, scales: str, timeout_s: int) -> dict:
    if scales == DERIVED:
        from camlab.measure.paint import scales_for_clip

        info = ClipInfo.load(clip_id)
        scales = ",".join(str(x) for x in
                          scales_for_clip(info.frame_path(f) for f in range(info.n_frames)))
    r = run(clip_id, seed=SEED, timeout_s=timeout_s,
            env_extra={"CAMLAB_RIDGE_SCALES": scales})
    out = {"scales": scales, "ok": bool(r["ok"]), "seconds": r.get("seconds_total")}
    out.update(verdict(clip_id))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, default=Path("out/ridge-ab.json"))
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--clips", nargs="*")
    ap.add_argument("--derived", action="store_true",
                    help="compare the shipped constant against the per-clip ladder")
    args = ap.parse_args()

    clips = args.clips or sorted(
        d.name for d in runs_root().iterdir()
        if (d / "clip.json").exists() and (d / SEED).exists())

    rows = []
    for c in clips:
        try:
            anchors = anchors_for(c, SEED)
        except Exception as exc:                                  # noqa: BLE001
            print(f"{c:32} skipped: {str(exc)[:60]}", flush=True)
            continue
        print(f"\n=== {c}  (anchors {anchors}) ===", flush=True)
        row = {"clip": c, "anchors": anchors}
        rhs = DERIVED if args.derived else WIDE
        for tag, scales in (("shipped", SHIPPED), ("wide", rhs)):
            try:
                got = one(c, scales, args.timeout)
            except Exception as exc:                              # noqa: BLE001
                got = {"scales": scales, "ok": False, "line": f"crashed: {str(exc)[:80]}"}
            row[tag] = got
            print(f"  {tag:8} {scales:14} {got.get('line', '')[:110]}", flush=True)
        rows.append(row)
        # Written after EVERY clip, not at the end. This run takes an hour and the first attempt
        # was killed at 55 minutes with nothing on disk — an hour of solving thrown away because
        # the results were held in a list.
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=1))

    def cell(a: dict, b: dict, key: str, fmt: str = "{:.2f}") -> str:
        def one_(v):
            return "-" if v is None else fmt.format(v)
        return f"{one_(a.get(key)):>7} -> {one_(b.get(key)):<7}"

    print(f"\n{'clip':30} {'markings':>17} {'across px':>17} {'frames ok':>17}")
    for r in rows:
        a, b = r.get("shipped", {}), r.get("wide", {})
        print(f"{r['clip'][:30]:30} {cell(a, b, 'markings', '{:.0f}'):>17} "
              f"{cell(a, b, 'across'):>17} {cell(a, b, 'n_supported', '{:.0f}'):>17}")
    print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
