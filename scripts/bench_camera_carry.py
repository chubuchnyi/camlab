"""Does moving the camera before refining it make a good seed last longer than three frames?

The measured problem (`findings/the-search-fails-not-the-model.md`): `refit_frame` is a local
search that cannot reach a good camera from the per-frame solve's seed, and seeding each frame by
COPYING the previous frame's camera is worth about three frames before it loses the track — the
operator pans and zooms, and a copy has not moved.

This compares three ways of walking away from one known-good anchor:

    auto     the per-frame solve, untouched
    copy     seed frame j with frame j−1's camera, then refit
    carry    seed frame j by taking frame j−1's camera through the measured image→image
             homography (solve/carry.py), then refit

Judged with the paint metric, which involves no line detector and so cannot be gamed by the thing
the refit is optimising.

Run:  .venv/bin/python scripts/bench_camera_carry.py [clip] [anchor-frame] [n-frames]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402

from camlab.measure.lines import detect_segments  # noqa: E402
from camlab.measure.paint import paint_masks  # noqa: E402
from camlab.measure.pixel_motion import measure_pairs  # noqa: E402
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402
from camlab.solve.carry import carry  # noqa: E402
from camlab.solve.refit import refit_frame  # noqa: E402


def main() -> None:
    clip_id = sys.argv[1] if len(sys.argv) > 1 else "fan"
    anchor = int(sys.argv[2]) if len(sys.argv) > 2 else 28
    span = int(sys.argv[3]) if len(sys.argv) > 3 else 24

    info = ClipInfo.load(clip_id)
    auto = json.loads((info.dir / "camera_auto.json").read_text())
    cx, cy = float(auto["cx"]), float(auto["cy"])
    hand = json.loads(
        (Path(__file__).resolve().parent.parent / "calib"
         / f"{clip_id}-hand-aligned-2026-08-11.json").read_text()
    )["camera_auto.json"][str(anchor)]

    frames = list(range(anchor, min(anchor + span + 1, len(auto["frames"]))))
    print(f"{clip_id}: anchor {anchor}, walking to {frames[-1]}, K = ({cx:.0f}, {cy:.0f})")

    # Consecutive-frame homographies, from the pixels only. No pitch, no markings, no focal.
    pairs = measure_pairs({f: info.frame_path(f) for f in frames}, gaps=(1,))
    h_of = {(p.i, p.j): p for p in pairs}
    print(f"   {len(pairs)} of {len(frames) - 1} consecutive pairs measured, "
          f"median reprojection {np.median([p.median_px for p in pairs]):.2f} px\n")

    seg_cache: dict[int, np.ndarray] = {}

    def segs(n):
        if n not in seg_cache:
            d, s = paint_masks(cv2.imread(str(info.frame_path(n))))
            seg_cache[n] = detect_segments(d, s, method="hough")
        return seg_cache[n]

    def score(n, f, rv, c):
        return frame_residual(info.frame_path(n), f, rv, c, frame=n, cx=cx, cy=cy).worst_line_px

    state = {m: (hand["focal_px"], np.asarray(hand["rotation"], float),
                 np.asarray(hand["position"], float)) for m in ("copy", "carry")}
    rows = []
    print(f'{"frame":>5} {"auto":>8} {"copy":>8} {"carry":>8}   {"f_carry":>7} {"disagree":>8}')
    for n in frames[1:]:
        out = {}
        for mode in ("copy", "carry"):
            f0, rv0, c0 = state[mode]
            note = ""
            if mode == "carry":
                p = h_of.get((n - 1, n))
                moved = carry(f0, rv0, c0, p.h, cx, cy) if p is not None else None
                if moved is not None:
                    f0, rv0, c0 = moved.focal_px, moved.rotation, moved.position
                    note = f"{moved.focal_px:7.0f} {moved.focal_disagreement:8.3f}"
                else:
                    note = f'{"—":>7} {"no pair":>8}'
            r = refit_frame(segs(n), f0, rv0, c0, info.width, info.height, cx, cy)
            state[mode] = (r.focal_px, r.rotation, r.position)
            out[mode] = score(n, r.focal_px, r.rotation, r.position)
            if mode == "carry":
                out["note"] = note
        a = score(n, auto["focal_px"][n], auto["rotation"][n], auto["position"][n])
        rows.append((a, out["copy"], out["carry"]))
        print(f'{n:5d} {a:8.1f} {out["copy"]:8.1f} {out["carry"]:8.1f}   {out["note"]}')

    m = np.array(rows, float)
    print(f"\nmedian worst line   auto {np.nanmedian(m[:, 0]):6.1f}   "
          f"copy {np.nanmedian(m[:, 1]):6.1f}   carry {np.nanmedian(m[:, 2]):6.1f} px")
    for k, name in ((1, "copy"), (2, "carry")):
        better = int(np.sum(m[:, k] < m[:, 0]))
        print(f"   {name:5s} beats auto on {better} of {len(m)} frames")
    print(f"   carry beats copy on {int(np.sum(m[:, 2] < m[:, 1]))} of {len(m)}")
    # How far the anchor carries: frames held under 20 px before the first one that is not.
    for k, name in ((1, "copy"), (2, "carry")):
        held = 0
        for v in m[:, k]:
            if not (v < 20.0):
                break
            held += 1
        print(f"   {name:5s} held under 20 px for {held} frames after the anchor")


if __name__ == "__main__":
    main()
