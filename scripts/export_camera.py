"""Export a solved camera to `calib/<clip>.npz`, the file pitch3d reads.

Run:  .venv/bin/python scripts/export_camera.py <clip> [--camera camera_smooth.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from camlab.io.export_npz import export_npz, export_npz_legacy  # noqa: E402
from camlab.runs import ClipInfo  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--camera", default="camera_smooth.json")
    ap.add_argument("--out", default=None)
    ap.add_argument("--legacy", action="store_true",
                    help="write the schema-1 shape pitch3d reads today: ONE focal, ONE centre. "
                         "Loses the zoom — 1.65 -> 4.56 px on fan, 4.04 -> 4.69 on CRO_MOR_194948")
    args = ap.parse_args()

    info = ClipInfo.load(args.clip)
    cam = json.loads((info.dir / args.camera).read_text())
    out = Path(args.out) if args.out else (
        Path(__file__).resolve().parent.parent / "calib" / f"{args.clip}.npz")
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.legacy:
        res = export_npz_legacy(cam, out)
        print(f"== {args.clip} / {args.camera} -> {res['path']}")
        print(f"   {res['frames']} frames, ONE focal {res['focal']:.0f}, ONE centre "
              f"(spread was {res['centre_spread_m']} m)")
        print(f"   schema 1, for pitch3d as it stands. The clip zooms {res['zoom_ratio']}x and "
              "that zoom is GONE from this file — quote the one-focal number, not the per-frame "
              "one, for anything built from it.")
        return

    res = export_npz(cam, out, clip_id=args.clip)
    print(f"== {args.clip} / {args.camera} -> {res['path']}")
    print(f"   {res['frames']} frames, focal {res['focal_px'][0]:.0f}..{res['focal_px'][1]:.0f} "
          f"(zoom {res['zoom_ratio']}x), centre spread {res['centre_spread_m']} m")
    print("   schema 2: focal_px and position are PER FRAME, every key present on every camera.")


if __name__ == "__main__":
    main()
