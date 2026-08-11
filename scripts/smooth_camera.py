"""Smooth each camera parameter along the clip, and keep only the frames where it helps.

An operator pans and zooms smoothly; a solve does not. Each of focal, yaw, elevation and roll
should be a smooth curve in the frame index, and where it is not, the wobble is the solver's rather
than the camera's.

**Why this is not just a low-pass.** Measured in the parent project: an iterative moving average on
yaw removed 90 % of the jitter and flattened 100°-plus real turns with it. A filter cannot tell a
solver's wobble from an operator's whip pan by looking at the signal alone. So two guards, and
neither is optional:

    a MEDIAN filter, not a mean — it deletes isolated spikes and leaves a ramp exactly where it is,
    which is the difference between removing a bad frame and removing a pan;

    and every smoothed frame is scored against the PAINT and kept only if it improves. The filter
    proposes; the photograph decides.

Roll is worth smoothing hardest: a phone in a hand stays within a couple of degrees of level for a
whole clip, so almost all of its variation is solver noise. Focal is worth smoothing least — a zoom
is real, fast, and the thing the carry exists to follow.

Run:  .venv/bin/python scripts/smooth_camera.py [clip] [--from camera_auto_full3.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.camera_file import write_camera  # noqa: E402
from camlab.core.angles import (  # noqa: E402
    angles_from_rotation,
    matrix_from_rodrigues,
    rodrigues_from_matrix,
    rotation_from_angles,
)
from camlab.measure.residual import frame_residual  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402


def median_filter(x: np.ndarray, k: int) -> np.ndarray:
    """Odd-length running median, edges held rather than shrunk.

    Reflecting or zero-padding the ends invents motion that was never filmed; holding the first and
    last value invents none.
    """
    if k < 3:
        return x.copy()
    k |= 1
    half = k // 2
    pad = np.concatenate([np.full(half, x[0]), x, np.full(half, x[-1])])
    return np.array([np.median(pad[i:i + k]) for i in range(len(x))])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", nargs="?", default="fan")
    ap.add_argument("--from", dest="src", default="camera_auto_full3.json")
    ap.add_argument("--out", default="camera_smooth.json")
    ap.add_argument("--k-focal", type=int, default=5)
    ap.add_argument("--k-yaw", type=int, default=5)
    ap.add_argument("--k-elev", type=int, default=5)
    ap.add_argument("--k-roll", type=int, default=15)
    args = ap.parse_args()

    t0 = time.time()
    info = ClipInfo.load(args.clip)
    src = json.loads((info.dir / args.src).read_text())
    cx, cy = float(src["cx"]), float(src["cy"])
    n = len(src["frames"])
    pos = np.asarray(src["position"], float)
    focal = np.asarray(src["focal_px"], float)
    rvec = np.asarray(src["rotation"], float)

    ang = np.array([angles_from_rotation(matrix_from_rodrigues(r)) for r in rvec])
    yaw, elev, roll = ang[:, 0], ang[:, 1], ang[:, 2]
    # Unwrap yaw before filtering. A pan through the +/-180 seam is a 360 degree jump in the
    # numbers and nothing at all in the world; a median over that seam invents a camera that spun.
    yaw_u = np.degrees(np.unwrap(np.radians(yaw)))

    prop = {
        "focal": median_filter(focal, args.k_focal),
        "yaw": median_filter(yaw_u, args.k_yaw),
        "elev": median_filter(elev, args.k_elev),
        "roll": median_filter(roll, args.k_roll),
    }

    def score(i, f, rv):
        r = frame_residual(info.frame_path(i), f, rv, pos[i], frame=i, cx=cx, cy=cy)
        spot = max((v[2] for v in r.per_line.values() if v[1] >= 8), default=float("nan"))
        return r.worst_line_px, float(spot), r.n

    w0 = np.empty(n)
    sp0 = np.empty(n)
    ns0 = np.empty(n, int)
    for i in range(n):
        w0[i], sp0[i], ns0[i] = score(i, focal[i], rvec[i])

    print(f"== {args.clip}: {n} frames from {args.src}")
    print("   how much each parameter moves frame to frame, before -> after the median filter:")
    for k, before in (("focal", focal), ("yaw", yaw_u), ("elev", elev), ("roll", roll)):
        d0 = float(np.median(np.abs(np.diff(before))))
        d1 = float(np.median(np.abs(np.diff(prop[k]))))
        print(f"      {k:6s} {d0:8.3f} -> {d1:8.3f}   "
              f"(range {np.ptp(before):.1f})")

    w, sp, ns = w0.copy(), sp0.copy(), ns0.copy()
    out_f, out_r = focal.copy(), rvec.copy()
    taken = 0
    floor = 0.7 * float(np.median(ns0))
    for i in range(n):
        f = prop["focal"][i]
        rv = rodrigues_from_matrix(rotation_from_angles(prop["yaw"][i], prop["elev"][i],
                                                        prop["roll"][i]))
        nw, nsp, nn = score(i, f, rv)
        if not np.isfinite(nw) or nn < floor:
            continue
        # Better on BOTH numbers, not one. A smoothed frame that improves the middle of a marking
        # while swinging its ends further out has not been improved, and the middle is the number
        # that would have hidden it.
        if nw <= w[i] and (not np.isfinite(nsp) or nsp <= sp[i]):
            out_f[i], out_r[i] = f, rv
            w[i], sp[i], ns[i] = nw, nsp, nn
            taken += 1

    write_camera(
        info.dir / args.out, model=f"{src['model']}+median_smoothed", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.asarray(src["frames"], int),
        focal_px=out_f, position=pos, rotation=out_r, cx=cx, cy=cy,
        degenerate=src.get("degenerate", [False] * n),
        smoothed_from=args.src,
        kernels={"focal": args.k_focal, "yaw": args.k_yaw, "elev": args.k_elev,
                 "roll": args.k_roll},
        notes=("Each parameter median-filtered along the clip, then applied frame by frame ONLY "
               "where the paint agreed. A median leaves a ramp where it is and deletes spikes, "
               "which is what separates a solver's wobble from an operator's pan; a mean does not, "
               "and flattening a real 100-degree turn is a measured way to lose."),
    )
    print(f"\n== wrote {args.out} in {time.time() - t0:.0f}s")
    print(f"   smoothed frames accepted  {taken} of {n}")
    print(f"   worst line, median  {np.nanmedian(w0):6.2f} px  ->  {np.nanmedian(w):6.2f} px")
    print(f"   worst spot, median  {np.nanmedian(sp0):6.2f} px  ->  {np.nanmedian(sp):6.2f} px")
    print(f"   frames under 20 px  {int(np.nansum(w0 < 20)):6d}     ->  "
          f"{int(np.nansum(w < 20)):6d}   of {n}")


if __name__ == "__main__":
    main()
