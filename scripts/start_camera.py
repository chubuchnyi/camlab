"""A plain, honest starting camera for a clip nobody has solved — something to drag from.

Not an estimate. A **default**, and it says so: a camera in the stands on the near touchline,
looking at the centre spot, with a focal that suits the frame width. Every number in it is a guess
from how football is filmed, not a measurement of this clip.

That is deliberately more useful than the automatic bootstrap right now. The bootstrap returns a
camera that fits the markings — genuinely, it is not broken — but 50 to 130 m from the true one,
because a pitch is exactly symmetric under a half-turn and its focal trades against its distance,
so many cameras fit (`findings/bootstrap-progress.md`). A wrong answer 100 m away is a worse place
to start dragging from than an admitted guess in the right neighbourhood.

Once one frame is right by eye, `solve_carry.py` follows the operator from there — measured at
about sixty frames per anchor — and `solve_selfheal.py` repairs what it loses.

Run:  .venv/bin/python scripts/start_camera.py <clip> [--y -75] [--z 20] [--fov 22]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.camera_file import write_camera  # noqa: E402
from camlab.core.angles import rodrigues_from_matrix, rotation_from_angles  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402


def look_at(pos: np.ndarray, target: np.ndarray) -> np.ndarray:
    f = np.asarray(target, float) - np.asarray(pos, float)
    f /= np.linalg.norm(f)
    return rodrigues_from_matrix(rotation_from_angles(
        float(np.degrees(np.arctan2(f[1], f[0]))), float(np.degrees(np.arcsin(f[2]))), 0.0))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--x", type=float, default=0.0, help="along the touchline, metres")
    ap.add_argument("--y", type=float, default=-75.0, help="back from the pitch, metres")
    ap.add_argument("--z", type=float, default=20.0, help="height, metres")
    ap.add_argument("--fov", type=float, default=22.0,
                    help="horizontal field of view in degrees. 22 is a moderate telephoto, which "
                         "is what most match footage is shot on; a wide establishing shot is 50+")
    ap.add_argument("--aim-x", type=float, default=0.0, help="where on the pitch it looks")
    ap.add_argument("--aim-y", type=float, default=0.0)
    ap.add_argument("--out", default="camera_start.json")
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    cx, cy = info.principal_point
    pos = np.array([args.x, args.y, args.z])
    rvec = look_at(pos, np.array([args.aim_x, args.aim_y, 0.0]))
    focal = (info.width / 2.0) / np.tan(np.radians(args.fov) / 2.0)

    n = info.n_frames
    out = write_camera(
        info.dir / args.out, model="hand_start_default", clip_id=info.clip_id,
        width=info.width, height=info.height, frames=np.arange(n),
        focal_px=np.full(n, focal), position=np.tile(pos, (n, 1)),
        rotation=np.tile(rvec, (n, 1)), cx=cx, cy=cy, degenerate=[False] * n,
        is_default=True, assumed_fov_deg=args.fov,
        notes=("A DEFAULT, not a solve. Nothing here was measured from this clip: a camera in the "
               "stands looking at the centre spot, with a focal from an assumed field of view. It "
               "exists to be dragged into place on one frame, after which solve_carry.py follows "
               "the operator and solve_selfheal.py repairs what it loses."),
    )
    print(f"== {args.clip}: {info.width}x{info.height}, {n} frames")
    print(f"   position {np.round(pos, 1)} looking at ({args.aim_x:g}, {args.aim_y:g}), "
          f"focal {focal:.0f} px for a {args.fov:g}deg horizontal field of view")
    print(f"   -> {out}   (a guess, clearly labelled as one)")


if __name__ == "__main__":
    main()
