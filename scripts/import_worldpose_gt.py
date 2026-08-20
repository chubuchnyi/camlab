#!/usr/bin/env python3
"""Write the WorldPose ground-truth camera into a run directory, in camlab's own format.

WorldPose ships per-frame `K`, `R`, `t`, `k` for 89 broadcast clips. The cameras live in
`~/AVATAR/WorldPose/cameras/<clip>.npz` (`--cameras`) and the **video is somewhere else entirely**,
under `~/AVATAR/models/worldpose/WorldPose Dataset/compressed/<clip>.mp4` — searching the first
directory for video finds none and has already produced the wrong conclusion once. A clip ingested
from that video with `first_frame: 0` has a measured camera for every frame it holds: the first
external answer this project can be scored against, rather than judged by eye.

Two conversions, and both are the ones that go wrong:

* WorldPose stores `t` of `X_c = R X_w + t`; camlab stores the camera CENTRE, `C = -Rᵀt`. Mixing
  them puts the camera under the pitch.
* The GT carries radial distortion; **camlab's camera model has none**, and that is not a rounding
  difference. Measured on `CRO_MOR_194948` frame 0, over the pitch points that land in the image:

      radius from the optical axis      0-200   200-400   400-600   600-800   800-1100  px
      median shift the distortion adds   0.07      0.61      2.80      7.68      15.32   px

  Median 2.84 px over the whole visible pitch, worst 31.94 px in a corner. A pinhole camera written
  from this GT therefore reprojects the middle of the frame exactly and the corners by up to 32 px,
  and any residual measured against it inherits that. It is a floor on how well camlab's camera
  model can fit a real broadcast lens at the edges, not an error in a solve. The number is printed
  per clip on every import rather than read off this table.

The world frame is NOT documented by the dataset and is asserted here by measurement: `C` comes out
at (-0.02, -88.15, 18.63) m on `CRO_MOR_194948` — a camera on the halfway line, 88 m back and 18.6 m
up — which is camlab's own convention (origin at the pitch centre, X along the length, Z up).

    PYTHONPATH=src python scripts/import_worldpose_gt.py CRO_MOR_194948
    PYTHONPATH=src python scripts/import_worldpose_gt.py --all --judge
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.camera_file import write_camera  # noqa: E402
from camlab.runs import ClipInfo, runs_root  # noqa: E402

CAMERAS = Path.home() / "AVATAR/WorldPose/cameras"

#: Written under its own name, never over a solve. The chain's outputs are cleared and rewritten by
#: every run (`solve/pipeline.py`); this file must survive that, because it is the reference.
GT_CAMERA = "camera_worldpose_gt.json"


def gt_path(clip_id: str, root: Path = CAMERAS) -> Path:
    return root / f"{clip_id}.npz"


def distortion_shift_px(K, R, t, k, n: int = 4000, seed: int = 0) -> float:
    """The largest pixel move `k` causes, over points spread across the image. Pure diagnostics."""
    import cv2

    rng = np.random.default_rng(seed)
    rvec, _ = cv2.Rodrigues(np.asarray(R, float))
    # Points on the pitch plane, in front of the camera, is what actually gets projected.
    xy = rng.uniform([-60.0, -40.0], [60.0, 40.0], size=(n, 2))
    pts = np.column_stack([xy, np.zeros(len(xy))])
    cam = (np.asarray(R, float) @ pts.T).T + np.asarray(t, float)
    pts = pts[cam[:, 2] > 1.0]
    if not len(pts):
        return float("nan")
    a = cv2.projectPoints(pts, rvec, np.asarray(t, float).reshape(3, 1), K, np.zeros(5))[0]
    b = cv2.projectPoints(pts, rvec, np.asarray(t, float).reshape(3, 1), K, np.asarray(k, float))[0]
    inside = ((b[:, 0, 0] >= 0) & (b[:, 0, 0] < 2 * K[0, 2]) &
              (b[:, 0, 1] >= 0) & (b[:, 0, 1] < 2 * K[1, 2]))
    if not inside.any():
        return float("nan")
    return float(np.linalg.norm((a - b).reshape(-1, 2)[inside], axis=1).max())


def import_one(clip_id: str, *, cameras: Path = CAMERAS, report_distortion: bool = False) -> dict:
    """Write `GT_CAMERA` into the run, and return what was written."""
    import cv2

    npz = gt_path(clip_id, cameras)
    if not npz.exists():
        raise FileNotFoundError(f"no WorldPose ground truth for {clip_id}: {npz}")
    info = ClipInfo.load(clip_id)
    d = np.load(npz)
    # The GT index is the SOURCE frame number, so a run that starts partway into the video reads
    # its own frame `i` from GT row `first_frame + i`. This used to REFUSE any offset clip rather
    # than guess, which was right while nothing produced one — and AVATAR's `new_clip_anchor.py`
    # now does, because it scans the video for a frame PnLCalib can actually solve and ingests a
    # window centred there. On `CRO_MOR_180400` that frame is 1320, and frame 0 gives an anchor
    # that does not survive its own refit. Refusing the offset would mean choosing between a
    # solvable clip and a checkable one.
    first = int(info.first_frame)
    n = int(info.n_frames)
    if first + n > len(d["K"]):
        raise ValueError(f"{clip_id}: run holds frames {first}..{first + n - 1} of the source, "
                         f"GT only has {len(d['K'])}")

    sl = slice(first, first + n)
    K, R, t, k = d["K"][sl], d["R"][sl], d["t"][sl], d["k"][sl]
    rot = np.stack([cv2.Rodrigues(np.ascontiguousarray(r))[0].ravel() for r in R])
    pos = np.einsum("nji,nj->ni", R, -t)              # C = -Rᵀ t, per frame

    cx, cy = float(np.median(K[:, 0, 2])), float(np.median(K[:, 1, 2]))
    spread = float(max(np.ptp(K[:, 0, 2]), np.ptp(K[:, 1, 2])))
    fx, fy = K[:, 0, 0], K[:, 1, 1]

    shift = distortion_shift_px(K[0], R[0], t[0], k[0]) if report_distortion else None
    notes = (f"WorldPose ground truth, {npz.name}. cx/cy vary by {spread:.2f} px over the clip "
             f"and the median is written; fx/fy differ by at most "
             f"{float(np.abs(fx - fy).max()):.3f} px."
             + (f" Radial distortion moves a projected marking by up to {shift:.2f} px, and is "
                "dropped — camlab's camera model has none." if shift is not None else ""))
    write_camera(
        info.dir / GT_CAMERA, model="worldpose-gt", clip_id=clip_id,
        width=info.width, height=info.height, frames=np.arange(n),
        focal_px=fx, position=pos, rotation=rot, cx=cx, cy=cy, notes=notes,
        distortion_k=np.asarray(k, float).round(6).tolist(),
    )
    return {"clip": clip_id, "frames": n, "first_frame": first,
            "focal": (float(fx.min()), float(fx.max())),
            "cx": cx, "cy": cy, "cxcy_spread_px": spread,
            "height_m": (float(pos[:, 2].min()), float(pos[:, 2].max())),
            "distortion_px": shift}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--all", action="store_true", help="every run that has ground truth")
    ap.add_argument("--cameras", type=Path, default=CAMERAS)
    ap.add_argument("--judge", action="store_true", help="score the GT against the clip's paint")
    args = ap.parse_args()

    clips = args.clips
    if args.all or not clips:
        clips = sorted(d.name for d in runs_root().iterdir()
                       if (d / "clip.json").exists() and gt_path(d.name, args.cameras).exists())
    if not clips:
        print("no run has WorldPose ground truth")
        return

    for c in clips:
        try:
            got = import_one(c, cameras=args.cameras, report_distortion=True)
        except Exception as exc:                                   # noqa: BLE001
            print(f"{c:20} skipped: {exc}")
            continue
        print(f"{c:20} {got['frames']:4d} frames · focal "
              f"{got['focal'][0]:.0f}-{got['focal'][1]:.0f}"
              f" px · principal ({got['cx']:.1f}, {got['cy']:.1f}) ±{got['cxcy_spread_px']:.1f}"
              f" · height {got['height_m'][0]:.2f}-{got['height_m'][1]:.2f} m"
              f" · distortion {got['distortion_px']:.2f} px", flush=True)
        if args.judge:
            from camlab.measure.verdict import judge_file
            print(f"{'':20} GT vs paint: {judge_file(c, GT_CAMERA).line()}", flush=True)


if __name__ == "__main__":
    main()
