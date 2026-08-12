"""Check a solved camera against the mowing stripes — the one test that does not use the markings.

Every other number in this repo comes from the painted lines, so every one of them shares whatever
the line finder gets wrong. The turf is independent evidence: a mower cuts in passes of constant
width, so on a striped pitch the stripes are evenly spaced **in metres**. Rectify the frame through
the camera and they become a periodic signal, and if the camera is right that period does not move
while the operator zooms.

Measured on the fan clip: over twelve frames the focal moves 1.18x and the period stays
11.00–11.25 m — 2.3 % — with a focal-to-period correlation of −0.10. Deliberately breaking the
camera breaks the period in the way the geometry predicts:

    the solved camera            period 11.00 m, spread 0.25 m, striped on 9 of 9 frames
    moved 5 m along the stripes  period 11.00 m — invisible, and correctly so: sliding along a
                                 stripe does not change the spacing across it
    moved 15 m sideways          no period at all
    focal x0.85                  no period at all
    focal x1.25                  period 8.75 m, and 11.00 / 8.75 = 1.257 against the 1.25 applied

**Not every pitch is striped**, and saying so is half the job. The broadcast clip returns a period
on one frame in ten and no period on the rest, which is the correct answer for that turf rather
than a failure. A clip that comes back unstriped is simply not checkable this way.

Run:  .venv/bin/python scripts/check_stripes.py <clip> [--camera camera_fixed.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2  # noqa: E402

from camlab.measure.residual import world_to_image  # noqa: E402
from camlab.measure.stripes import measure  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--camera", default="camera_auto.json")
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--axis", type=float, default=None,
                    help="stripe direction in world degrees; omitted means try 0/45/90/135 and "
                         "keep the strongest, which can flip between frames on a weak pitch")
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    cam = json.loads((info.dir / args.camera).read_text())
    cx, cy = float(cam["cx"]), float(cam["cy"])
    axes = None if args.axis is None else (args.axis,)

    rows = []
    for n in range(0, info.n_frames, args.every):
        if not cam["focal_px"][n] > 0:
            continue
        h = world_to_image(cam["focal_px"][n], cam["rotation"][n], cam["position"][n],
                           info.width, info.height, cx=cx, cy=cy)
        s = measure(cv2.imread(str(info.frame_path(n))), h, axes=axes)
        rows.append((n, float(cam["focal_px"][n]), s))

    striped = [r for r in rows if r[2].period_m]
    print(f"== {args.clip} / {args.camera}: {len(rows)} frames checked")
    if len(striped) < max(3, len(rows) // 4):
        print(f"   striped on {len(striped)} of {len(rows)} frames. TWO things look like this and "
              "they are not the same:")
        print("     the pitch is not striped — broadcast comes back 3 of 20 and that is simply "
              "its turf;")
        print("     or the CAMERA is wrong, because stripes are only periodic once rectified "
              "correctly. The fan clip, same turf, is 19 of 40 through its solved camera and 9 of "
              "40 through the untouched one.")
        print("   So this is not a verdict on the pitch until the camera is known good.")
        return

    f = np.array([r[1] for r in striped])
    p = np.array([r[2].period_m for r in striped])
    ax = np.array([r[2].axis_deg for r in striped])
    corr = float(np.corrcoef(f, p)[0, 1]) if len(f) > 2 and np.ptp(f) > 1e-6 else float("nan")
    print(f"   striped on {len(striped)} of {len(rows)} frames, axis "
          f"{sorted({float(a) for a in ax})}")
    print(f"   stripe width   {np.median(p):.2f} m, spread {np.ptp(p):.2f} m "
          f"({np.ptp(p) / np.median(p):.1%})")
    print(f"   focal over those frames {f.min():.0f}..{f.max():.0f}  ({f.max() / f.min():.2f}x)")
    print(f"   focal-to-period correlation {corr:+.2f}")
    # The verdict, and it is about the FOCAL TRACK rather than any single camera: a period that
    # holds while the focal moves is a focal track that is right in its ratios.
    if np.ptp(f) / f.mean() < 0.05:
        print("   the focal barely moves over these frames, so this says little — the check needs "
              "a zoom to bite")
    elif abs(corr) < 0.5 and np.ptp(p) / np.median(p) < 0.06:
        print("   VERDICT: the period holds while the focal moves, so the focal track is right "
              "to within a few per cent, on evidence that never touches the markings")
    else:
        print("   VERDICT: the period tracks the focal, which is what a WRONG focal track looks "
              "like — the rectified world is being stretched frame to frame")


if __name__ == "__main__":
    main()
