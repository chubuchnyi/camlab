#!/usr/bin/env python3
"""Score a camlab solve against the WorldPose ground truth, in metres, degrees and pixels.

The paint metric (`measure/verdict.py`) answers "does this camera put the markings on the paint",
which is the only question available on a clip with no external answer — and it is blind to the
whole family of errors that move the camera and the focal together along a plane's depth ambiguity.
This asks the other question: is the camera WHERE the camera was.

Three numbers, and the third is the one that matters for a novel view:

* **position** — metres between the two camera centres.
* **rotation** — the angle of `R_ours R_gtᵀ`, in degrees.
* **reprojection** — the median pixel distance between where the two cameras put the same pitch
  points. Position and rotation trade against each other (a camera 2 m back with 3% more focal
  looks nearly identical), so neither alone says whether the picture is right; this does.

Reprojection is measured over the pitch points the GROUND TRUTH puts inside the image, distortion
included on the GT side, because that is where the real camera was actually looking.

    PYTHONPATH=src python scripts/bench_vs_worldpose.py --camera camera_polished.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.runs import ClipInfo, runs_root  # noqa: E402
from scripts.import_worldpose_gt import CAMERAS, gt_path  # noqa: E402  (same dir on sys.path)

#: Pitch points to compare over. Spread across a box a little larger than the pitch, so a camera
#: aimed past a touchline is still compared on what it actually sees.
SAMPLE_BOX = ((-70.0, -50.0), (70.0, 50.0))
N_SAMPLE = 20000


def _pitch_samples(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lo, hi = SAMPLE_BOX
    xy = rng.uniform(lo, hi, size=(N_SAMPLE, 2))
    return np.column_stack([xy, np.zeros(len(xy))])


def compare_frame(K_gt, R_gt, t_gt, k_gt, focal, rvec, pos, cx, cy, w, h, pts) -> dict | None:
    """One frame. Returns None when the GT camera sees too little of the pitch to compare on."""
    import cv2

    R_ours, _ = cv2.Rodrigues(np.asarray(rvec, float))
    C_ours = np.asarray(pos, float)
    C_gt = -R_gt.T @ t_gt

    uv_gt = cv2.projectPoints(pts, cv2.Rodrigues(R_gt)[0], t_gt.reshape(3, 1),
                              K_gt, np.asarray(k_gt, float))[0].reshape(-1, 2)
    front = ((R_gt @ pts.T).T + t_gt)[:, 2] > 1.0
    seen = front & (uv_gt[:, 0] >= 0) & (uv_gt[:, 0] < w) & (uv_gt[:, 1] >= 0) & (uv_gt[:, 1] < h)
    if seen.sum() < 50:
        return None

    K_ours = np.array([[focal, 0, cx], [0, focal, cy], [0, 0, 1.0]])
    t_ours = -R_ours @ C_ours
    uv_ours = cv2.projectPoints(pts[seen], cv2.Rodrigues(R_ours)[0], t_ours.reshape(3, 1),
                                K_ours, np.zeros(5))[0].reshape(-1, 2)
    d = np.linalg.norm(uv_ours - uv_gt[seen], axis=1)

    ang = float(np.degrees(np.arccos(np.clip((np.trace(R_ours @ R_gt.T) - 1) / 2, -1, 1))))
    return {
        "position_m": float(np.linalg.norm(C_ours - C_gt)),
        "rotation_deg": ang,
        "focal_ratio": float(focal / K_gt[0, 0]),
        "reproj_median_px": float(np.median(d)),
        "reproj_p90_px": float(np.percentile(d, 90)),
        "n": int(seen.sum()),
    }


def compare(clip_id: str, camera_name: str, *, cameras: Path = CAMERAS, every: int = 1) -> dict:
    info = ClipInfo.load(clip_id)
    cam = json.loads((info.dir / camera_name).read_text())
    d = np.load(gt_path(clip_id, cameras))
    pts = _pitch_samples()

    # The GT index is the SOURCE frame number and a run may start partway into the video, so
    # camlab's frame `i` must be read from GT row `first + i`. Getting this wrong is silent and
    # enormous: it reported camlab as 42 deg and 4275 px from the truth on `CRO_MOR_180400`, on a
    # camera the paint scores at 2.54 px. The tell was that the error tracked `first_frame`
    # exactly — 0.31-0.87 deg on every clip that starts at 0, and 5.7-59.5 deg on every clip that
    # does not, rising with the offset.
    first = int(info.first_frame)
    if first + info.n_frames > len(d["K"]):
        raise ValueError(f"{clip_id}: run holds source frames {first}..{first + info.n_frames - 1}, "
                         f"GT has {len(d['K'])}")

    rows = []
    for i in range(0, info.n_frames, max(1, every)):
        f = float(cam["focal_px"][i])
        if not f > 0:
            continue
        g = first + i
        got = compare_frame(d["K"][g], d["R"][g], d["t"][g], d["k"][g], f,
                            cam["rotation"][i], cam["position"][i],
                            float(cam["cx"]), float(cam["cy"]), info.width, info.height, pts)
        if got is not None:
            rows.append(got)
    if not rows:
        return {"clip": clip_id, "camera": camera_name, "n_frames": 0}

    def med(key):
        return float(np.median([r[key] for r in rows]))

    return {
        "clip": clip_id, "camera": camera_name, "n_frames": len(rows),
        "position_m": med("position_m"), "rotation_deg": med("rotation_deg"),
        "focal_ratio": med("focal_ratio"),
        "reproj_median_px": med("reproj_median_px"), "reproj_p90_px": med("reproj_p90_px"),
        "worst_frame_reproj_px": float(max(r["reproj_median_px"] for r in rows)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*")
    ap.add_argument("--camera", default="camera_polished.json")
    ap.add_argument("--cameras", type=Path, default=CAMERAS)
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    clips = args.clips or sorted(
        d.name for d in runs_root().iterdir()
        if (d / "clip.json").exists() and gt_path(d.name, args.cameras).exists()
        and (d / args.camera).exists())

    print(f"{'clip':22} {'frames':>6} {'position':>10} {'rotation':>10} {'focal':>8} "
          f"{'reproj med':>11} {'reproj p90':>11} {'worst frame':>12}")
    rows = []
    for c in clips:
        try:
            r = compare(c, args.camera, cameras=args.cameras, every=args.every)
        except Exception as exc:                                   # noqa: BLE001
            print(f"{c:22} skipped: {str(exc)[:70]}")
            continue
        rows.append(r)
        if not r["n_frames"]:
            print(f"{c:22} nothing comparable")
            continue
        print(f"{c:22} {r['n_frames']:6d} {r['position_m']:9.2f}m {r['rotation_deg']:9.3f}° "
              f"{r['focal_ratio']:7.3f}x {r['reproj_median_px']:10.1f}p "
              f"{r['reproj_p90_px']:10.1f}p {r['worst_frame_reproj_px']:11.1f}p", flush=True)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=1))
        print(f"\n-> {args.json}")


if __name__ == "__main__":
    main()
