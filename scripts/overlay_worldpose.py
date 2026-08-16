#!/usr/bin/env python3
"""Draw the WorldPose ground truth on a frame, so a claim about it can be checked by eye.

Two modes, and the first exists because the second is not self-checking.

**`--players`** projects the dataset's own PLAYER positions through its own camera. No pitch
template, no paint detector, no camlab geometry — only the two halves of WorldPose against each
other. If the sticks stand on the players, the camera and the world frame are being read correctly,
and that conclusion does not depend on anything in this repo. It is the check to run first, because
every metre quoted against this dataset rests on a convention (`C = -Rᵀt`, Z up, origin at the pitch
centre) that the dataset does not document.

**`--cameras`** draws the ground truth in GREEN and a camlab solve in YELLOW on the same frame,
with both camera centres and focals printed on it. On `CRO_MOR_194948` frame 0 the two overlays sit
on top of each other and the cameras are **5.01 m apart** — which is the whole of
`findings/the-metric-cannot-see-depth-2026-08-16.md` in one picture. On `MOR_POR_181952` frame 7
they are nowhere near each other.

    PYTHONPATH=src python scripts/overlay_worldpose.py CRO_MOR_194948 0 --players --cameras
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.core.pitch import pitch_polylines  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402

CAMERAS = Path.home() / "AVATAR/WorldPose/cameras"
POSES = Path.home() / "AVATAR/WorldPose/poses"

#: Laws of the Game put nothing here; this is just a person-height stick to hang off the root, so
#: a reader can see whether the position is on the player rather than near him.
STICK_M = 1.75

GREEN, YELLOW, RED = (0, 220, 0), (0, 255, 255), (0, 0, 255)


def _caption(img, lines: list[str]) -> None:
    import cv2

    for i, s in enumerate(lines):
        y = 44 + i * 40
        cv2.putText(img, s, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (0, 0, 0), 5, cv2.LINE_AA)
        cv2.putText(img, s, (24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (255, 255, 255), 2,
                    cv2.LINE_AA)


def _draw_pitch(img, K, R, t, k, colour, thick: int) -> None:
    """The standard markings through one camera. Segments with an end behind it are dropped."""
    import cv2

    rvec = cv2.Rodrigues(np.asarray(R, float))[0]
    tv = np.asarray(t, float).reshape(3, 1)
    for poly in pitch_polylines(spacing=0.5):
        if len(poly) < 2:
            continue
        pts = np.column_stack([poly, np.zeros(len(poly))])
        uv = cv2.projectPoints(pts, rvec, tv, K, k)[0].reshape(-1, 2)
        # A point behind the camera projects to a mirrored position that is a perfectly plausible
        # pixel. Skipping the whole marking instead of the segment is what produced a "the camera
        # is still wrong" finding that the user caught by eye and that had to be withdrawn.
        ahead = ((np.asarray(R, float) @ pts.T).T + np.asarray(t, float))[:, 2] > 0.5
        for a, b, oa, ob in zip(uv[:-1], uv[1:], ahead[:-1], ahead[1:], strict=True):
            if oa and ob and np.abs(np.r_[a, b]).max() < 1e5:
                cv2.line(img, tuple(np.int32(a)), tuple(np.int32(b)), colour, thick, cv2.LINE_AA)


def players(clip_id: str, frame: int, out: Path, *, cameras: Path = CAMERAS,
            poses: Path = POSES) -> Path:
    import cv2

    info = ClipInfo.load(clip_id)
    img = cv2.imread(str(info.frame_path(frame)))
    cam = np.load(cameras / f"{clip_id}.npz")
    transl = np.load(poses / f"{clip_id}.npz")["transl"][:, frame, :]

    K, R, t, k = cam["K"][frame], cam["R"][frame], cam["t"][frame], cam["k"][frame].astype(float)
    rvec, tv = cv2.Rodrigues(R)[0], t.reshape(3, 1)
    n = 0
    for p in transl:
        if not np.isfinite(p).all():        # the dataset writes NaN for a player it cannot see
            continue
        stick = np.array([[p[0], p[1], 0.0], [p[0], p[1], STICK_M]])
        uv = cv2.projectPoints(stick, rvec, tv, K, k)[0].reshape(-1, 2)
        root = cv2.projectPoints(p.reshape(1, 3), rvec, tv, K, k)[0].reshape(2)
        cv2.line(img, tuple(np.int32(uv[0])), tuple(np.int32(uv[1])), RED, 3, cv2.LINE_AA)
        cv2.circle(img, tuple(np.int32(root)), 7, YELLOW, -1, cv2.LINE_AA)
        n += 1
    _caption(img, [f"{clip_id}  frame {frame}",
                   f"{n} WorldPose player positions through the WorldPose camera",
                   "no pitch template and no camlab geometry are involved"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out


def two_cameras(clip_id: str, frame: int, out: Path, *, camera: str = "camera_polished.json",
                cameras: Path = CAMERAS) -> Path:
    import cv2

    info = ClipInfo.load(clip_id)
    img = cv2.imread(str(info.frame_path(frame)))
    gt = np.load(cameras / f"{clip_id}.npz")
    ours = json.loads((info.dir / camera).read_text())

    _draw_pitch(img, gt["K"][frame], gt["R"][frame], gt["t"][frame],
                gt["k"][frame].astype(float), GREEN, 4)

    R_o = cv2.Rodrigues(np.asarray(ours["rotation"][frame], float))[0]
    C_o = np.asarray(ours["position"][frame], float)
    f = float(ours["focal_px"][frame])
    K_o = np.array([[f, 0, ours["cx"]], [0, f, ours["cy"]], [0, 0, 1.0]])
    _draw_pitch(img, K_o, R_o, -R_o @ C_o, np.zeros(5), YELLOW, 2)

    C_gt = -gt["R"][frame].T @ gt["t"][frame]
    f_gt = float(gt["K"][frame][0, 0])
    _caption(img, [
        f"{clip_id}  frame {frame}",
        f"GREEN = WorldPose ground truth   focal {f_gt:.0f} px   "
        f"camera ({C_gt[0]:.1f}, {C_gt[1]:.1f}, {C_gt[2]:.1f}) m",
        f"YELLOW = our {camera.replace('camera_', '').replace('.json', '')}   focal {f:.0f} px   "
        f"camera ({C_o[0]:.1f}, {C_o[1]:.1f}, {C_o[2]:.1f}) m",
        f"apart: {np.linalg.norm(C_o - C_gt):.2f} m   focal ratio {f / f_gt:.3f}x"])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip")
    ap.add_argument("frame", type=int, nargs="?", default=0)
    ap.add_argument("--players", action="store_true")
    ap.add_argument("--cameras-overlay", "--cameras", dest="both", action="store_true")
    ap.add_argument("--camera", default="camera_polished.json")
    ap.add_argument("--gt-dir", type=Path, default=CAMERAS)
    ap.add_argument("--out-dir", type=Path, default=Path("out/worldpose"))
    args = ap.parse_args()

    if not args.players and not args.both:
        args.players = args.both = True
    if args.players:
        p = players(args.clip, args.frame, args.out_dir / f"players_{args.clip}_{args.frame}.jpg",
                    cameras=args.gt_dir)
        print(f"-> {p}")
    if args.both:
        p = two_cameras(args.clip, args.frame,
                        args.out_dir / f"cameras_{args.clip}_{args.frame}.jpg",
                        camera=args.camera, cameras=args.gt_dir)
        print(f"-> {p}")


if __name__ == "__main__":
    main()
