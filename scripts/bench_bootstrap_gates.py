"""Where the bootstrap loses the answer — the funnel, gate by gate, and the truth's own fate.

`bootstrap_clip.py` prints "no plausible camera at all on the anchor frame" and stops. That is one
sentence for seven separate ways to fail, and guessing between them has already cost a day: the arc
gate was measured, blamed, loosened, and the loosening made two clips return confidently wrong
cameras where they had returned none (`findings/11-is-blocked-by-14-2026-08-12.md`).

So this counts the population at every gate, and — where the clip is solved and a truth exists —
puts the **true camera** through the same gates. A gate that rejects the truth is a defect. A gate
that rejects everything while passing the truth is doing its job on a frame whose pool is empty.

    PYTHONPATH=src .venv/bin/python scripts/bench_bootstrap_gates.py fan 0 40 80
    PYTHONPATH=src .venv/bin/python scripts/bench_bootstrap_gates.py broadcast 0 10 30
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402
from scipy.spatial import cKDTree  # noqa: E402

from camlab.core.angles import rodrigues_from_matrix  # noqa: E402
from camlab.measure.ellipse import arc_paint_distance  # noqa: E402
from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import centreline_pixels, paint_masks  # noqa: E402
from camlab.measure.residual import frame_residual, world_to_image  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.bootstrap import hypotheses  # noqa: E402
from camlab.solve.refit import refit_frame_lm  # noqa: E402

#: The same numbers `bootstrap_clip.py` uses. Duplicated deliberately rather than imported: that
#: script is a CLI whose main() would run, and a probe that silently drifts from the thing it
#: probes is worse than one that states its assumptions.
MAX_MISSING = 0.05
MIN_ARC_SAMPLES = 8
MAX_ARC_PX = 6.0
MIN_SAMPLES = 100
FOCAL_RANGE = (900.0, 12000.0)
HEIGHT_RANGE = (5.0, 45.0)
GROUND_RANGE = (35.0, 140.0)


def plausible(focal, position) -> bool:
    d = float(np.hypot(position[0], position[1]))
    return (FOCAL_RANGE[0] < focal < FOCAL_RANGE[1]
            and HEIGHT_RANGE[0] < position[2] < HEIGHT_RANGE[1]
            and GROUND_RANGE[0] < d < GROUND_RANGE[1])


def gates(info, frame, focal, rvec, pos, cx, cy, tree):
    """`(verdict, detail)` — the first gate that rejects this camera, or `("kept", …)`."""
    if not plausible(focal, np.asarray(pos, float)):
        return "not a football camera", f"focal {focal:.0f}, height {pos[2]:.1f}"
    r = frame_residual(info.frame_path(frame), focal, rvec, pos, frame=frame, cx=cx, cy=cy)
    if not np.isfinite(r.median_px):
        return "nothing scored", "no marking landed on the surface"
    miss = r.n_unmatched / max(r.n, 1)
    if miss > MAX_MISSING:
        return "miss gate", f"{miss:.1%} of samples have no paint within 40 px"
    h = world_to_image(focal, rvec, pos, info.width, info.height, cx=cx, cy=cy)
    ad, an = arc_paint_distance(h, tree, info.width, info.height)
    if an < MIN_ARC_SAMPLES:
        return "arc gate", f"only {an:.0f} arc samples in frame"
    if not (np.isfinite(ad) and ad <= MAX_ARC_PX):
        return "arc gate", f"arcs {ad:.1f} px off the paint"
    if r.n < MIN_SAMPLES:
        return "coverage floor", f"{r.n} samples"
    return "kept", f"median {r.median_px:.2f} px, {r.n} samples"


def main() -> None:
    clip_id = sys.argv[1] if len(sys.argv) > 1 else "fan"
    frames = [int(a) for a in sys.argv[2:]] or [0]
    info = ClipInfo.load(clip_id)

    truth = None
    for name in ("camera_smooth.json", "camera_fixed.json"):
        if (info.dir / name).exists():
            truth = json.loads((info.dir / name).read_text())
            print(f"truth from {name}")
            break
    if truth is None:
        print("no solved camera on disk — the funnel only, no verdict on the truth")

    seed = json.loads((info.dir / "camera_start.json").read_text()) if truth is None else truth
    cx, cy = float(seed["cx"]), float(seed["cy"])

    for a in frames:
        bgr = cv2.imread(str(info.frame_path(a)))
        dist, surface = paint_masks(bgr)
        segs = detect_segments(dist, surface, method="hough")
        tree = cKDTree(centreline_pixels(dist))
        print(f"\n== {clip_id} frame {a}: {len(segs)} segments, K = ({cx:.0f}, {cy:.0f})")

        if truth is not None and truth["focal_px"][a] > 0:
            v, why = gates(info, a, truth["focal_px"][a], truth["rotation"][a],
                           truth["position"][a], cx, cy, tree)
            mark = "PASSES" if v == "kept" else f"REJECTED by the {v}"
            print(f"   the TRUE camera: {mark} — {why}")

        # The closest candidate to the truth is tracked separately, because the funnel alone cannot
        # say whether the gates are wrong or the pool is empty. If the nearest thing the generator
        # produced is 12 m out, no gate is at fault; if it is 3 m out and rejected, one is.
        want = np.asarray(truth["position"][a], float) if truth is not None else None
        counts: dict[str, int] = {}
        best = (np.inf, None)
        n_gen = 0
        for h in hypotheses(segs, info.width, info.height, cx, cy, max_hypotheses=60000):
            n_gen += 1
            if not plausible(h.focal_px, np.asarray(h.position, float)):
                counts["not a football camera"] = counts.get("not a football camera", 0) + 1
                continue
            rv = rodrigues_from_matrix(h.rotation)
            r = refit_frame_lm(segs, h.focal_px, rv, h.position, info.width, info.height, cx, cy)
            v, why = gates(info, a, r.focal_px, r.rotation, r.position, cx, cy, tree)
            counts[v] = counts.get(v, 0) + 1
            if want is not None:
                d = float(np.linalg.norm(np.asarray(r.position, float) - want))
                if d < best[0]:
                    best = (d, (v, why, float(r.focal_px)))

        print(f"   {n_gen} hypotheses generated. Where they end up:")
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"      {k:24s} {v:6d}  {v / max(n_gen, 1):5.1%}")
        if best[1] is not None:
            v, why, f = best[1]
            tf = truth["focal_px"][a]
            print(f"   closest to the truth: {best[0]:.1f} m, focal {f:.0f} against {tf:.0f} "
                  f"({(f - tf) / tf:+.0%}) — {'kept' if v == 'kept' else 'REJECTED by the ' + v}"
                  f", {why}")
        if not counts.get("kept"):
            print("      NOTHING SURVIVES — and the line above says which gate to argue with.")


if __name__ == "__main__":
    main()
