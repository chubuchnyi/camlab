"""`python -m camlab` — put a clip into a run directory and solve today's camera for it.

    python -m camlab ingest fan --video ~/AVATAR/samples/video/14604731_1080_1920_30fps.mp4 \
        --crop 1080 608 0 1294 --frames 120
    python -m camlab solve fan --scene ~/AVATAR/out/fan_auto/scene_fan_auto.json

`solve` is M1's control side: each frame's own camera, decomposed from its own free homography.
That scatter is the defect, drawn. M2 adds the model that replaces it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from camlab.camera_file import summarise, write_camera
from camlab.io.ingest import ingest
from camlab.io.pitch3d_scene import read_calibration, world_handedness
from camlab.runs import ClipInfo, list_runs
from camlab.solve.per_frame import per_frame_cameras


def _cmd_ingest(args) -> int:
    crop = tuple(args.crop) if args.crop else None
    info = ingest(Path(args.video).expanduser(), args.clip_id,
                  first=args.first, n_frames=args.frames, crop=crop)
    print(f"== {info.clip_id}")
    print(f"   source   {info.source}  ({info.source_width}x{info.source_height} @ {info.fps:g})")
    print(f"   crop     {info.crop or 'none'}")
    print(f"   frames   {info.n_frames} from #{info.first_frame}, written at "
          f"{info.width}x{info.height}")
    print(f"   -> {info.dir}")
    print("\n   NB every later stage reads width/height from clip.json. They are the size of the")
    print("   frames ON DISK, i.e. after the crop — the space the homographies live in.")
    return 0


def _cmd_solve(args) -> int:
    info = ClipInfo.load(args.clip_id)
    cal = read_calibration(Path(args.scene).expanduser())
    h, frames = cal["homographies"], cal["frames"]

    # Trim to what we actually decoded. A scene can be longer than the run, and silently fitting
    # through frames with no pixels behind them is how a solve ends up about a different clip.
    keep = (frames >= info.first_frame) & (frames < info.first_frame + info.n_frames)
    h, frames, conf = h[keep], frames[keep], cal["confidence"][keep]
    if not len(h):
        print(f"!! the scene covers frames {cal['frames'].min()}..{cal['frames'].max()}, "
              f"the run covers {info.first_frame}..{info.first_frame + info.n_frames - 1}")
        return 1

    hand = world_handedness(h, info.width, info.height)
    mirrored = hand < 0
    if mirrored.mean() > 0.5:
        # Majority vote, and the minority is reported rather than asserted away. pitch3d asserts
        # the whole clip agrees; on the fan clip two frames do not, and they turn out to be
        # rank-poor rather than differently framed.
        h = h @ np.diag([1.0, -1.0, 1.0])
        odd = np.flatnonzero(~mirrored)
    else:
        odd = np.flatnonzero(mirrored)

    cams = per_frame_cameras(h, frames, info.width, info.height)
    bad = np.flatnonzero(cams.degenerate)

    out = write_camera(
        info.dir / "camera_auto.json",
        model="per_frame_homography",
        clip_id=info.clip_id,
        width=info.width, height=info.height,
        frames=cams.frames, focal_px=cams.focal_px,
        position=cams.position, rotation=cams.rotation,
        zhang_residual=np.where(np.isfinite(cams.zhang_residual),
                                cams.zhang_residual, -1.0).round(9),
        degenerate=cams.degenerate.astype(bool).tolist(),
        source_scene=str(Path(args.scene).expanduser()),
        source_confidence=conf.round(4).tolist(),
        notes=("Each frame decomposed from its OWN free 8-DOF homography, at its own best focal. "
               "This is not one camera and is not meant to be — it is the control side of the "
               "A/B, and the spread of `position` is the ground swim, drawn."),
    )

    print(f"== {info.clip_id}: {len(cams)} frames at {info.width}x{info.height}")
    print(f"   {summarise({'model': 'per_frame_homography', 'position': cams.position.tolist(), 'focal_px': cams.focal_px.tolist()})}")  # noqa: E501
    if odd.size:
        print(f"   handedness minority (kept, marked): {odd.tolist()}")
    if bad.size:
        print(f"   rank-poor homographies (kept, marked): {bad.tolist()}")
    print(f"   -> {out}")
    return 0


def _cmd_list(_args) -> int:
    runs = list_runs()
    if not runs:
        print("no runs yet")
        return 0
    for r in runs:
        info = ClipInfo.load(r)
        cam = info.dir / "camera_auto.json"
        print(f"{r:<20} {info.n_frames:>4} frames  {info.width}x{info.height}  "
              f"{'camera_auto.json' if cam.exists() else '— not solved'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="camlab", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="decode a clip into a run directory, through a crop")
    p.add_argument("clip_id")
    p.add_argument("--video", required=True)
    p.add_argument("--first", type=int, default=0)
    p.add_argument("--frames", type=int, default=120)
    p.add_argument("--crop", type=int, nargs=4, metavar=("W", "H", "X", "Y"),
                   help="in SOURCE pixels; the frames are written already cropped")
    p.set_defaults(fn=_cmd_ingest)

    p = sub.add_parser("solve", help="today's camera: each frame from its own free homography")
    p.add_argument("clip_id")
    p.add_argument("--scene", required=True, help="a pitch3d scene.json to read homographies from")
    p.set_defaults(fn=_cmd_solve)

    p = sub.add_parser("list", help="what is in runs/")
    p.set_defaults(fn=_cmd_list)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
