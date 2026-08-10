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

from camlab.camera_file import read_camera, summarise, write_camera
from camlab.io.ingest import ingest
from camlab.io.pitch3d_scene import read_calibration, world_handedness
from camlab.runs import ClipInfo, list_runs
from camlab.solve.per_frame import PerFrameCameras, per_frame_cameras
from camlab.solve.ptz import fit_ptz


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

    if args.principal == "axis":
        cx, cy = info.principal_point
    else:
        cx, cy = info.width / 2.0, info.height / 2.0
    cams = per_frame_cameras(h, frames, info.width, info.height, cx=cx, cy=cy)
    bad = np.flatnonzero(cams.degenerate)

    out = write_camera(
        info.dir / (args.out or "camera_auto.json"),
        model="per_frame_homography",
        clip_id=info.clip_id,
        width=info.width, height=info.height,
        frames=cams.frames, focal_px=cams.focal_px,
        position=cams.position, rotation=cams.rotation, cx=cx, cy=cy,
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
    print(f"   principal point: ({cx:.1f}, {cy:.1f})" +
          ("  <- the clip's true optical axis" if args.principal == "axis"
           else "  <- the image centre; wrong on a cropped clip"))
    print(f"   {summarise({'model': 'per_frame_homography', 'position': cams.position.tolist(), 'focal_px': cams.focal_px.tolist()})}")  # noqa: E501
    if odd.size:
        print(f"   handedness minority (kept, marked): {odd.tolist()}")
    if bad.size:
        print(f"   rank-poor homographies (kept, marked): {bad.tolist()}")
    print(f"   -> {out}")
    return 0


def _build_evidence(info, frames):
    """Paint per frame. The expensive step, and it is camera-independent, so it is done once."""
    import time

    from camlab.measure.paint import frame_evidence

    ev, t0 = {}, time.time()
    for n, f in enumerate(frames):
        e = frame_evidence(info.frame_path(int(f)), int(f))
        if e is not None:
            ev[int(f)] = e
        if n % 20 == 0:
            print(f"      paint {n}/{len(frames)} ...", flush=True)
    print(f"   paint evidence: {len(ev)}/{len(frames)} frames in {time.time() - t0:.0f}s")
    return ev


def _cmd_fit(args) -> int:
    """M2: one position for the clip, per-frame orientation and focal, fitted to the paint."""
    import time

    from camlab.measure.residual import frame_residual

    info = ClipInfo.load(args.clip_id)
    auto = read_camera(info.dir / "camera_auto.json")
    seed = PerFrameCameras(
        frames=np.asarray(auto["frames"], dtype=int),
        focal_px=np.asarray(auto["focal_px"], dtype=float),
        position=np.asarray(auto["position"], dtype=float),
        rotation=np.asarray(auto["rotation"], dtype=float),
        zhang_residual=np.asarray(auto.get("zhang_residual", []), dtype=float),
        degenerate=np.asarray(auto.get("degenerate", []), dtype=bool),
    )
    print(f"== {info.clip_id}: fitting one camera to {len(seed)} frames at "
          f"{info.width}x{info.height}")

    ev = _build_evidence(info, seed.frames)
    t0 = time.time()
    fit = fit_ptz(seed, ev, rounds=args.rounds)
    print(f"   solved in {time.time() - t0:.0f}s over {len(fit.fit_frames)} anchor frames")

    live = fit.focal_px > 0
    out = write_camera(
        info.dir / "camera_ptz.json",
        model="ptz",
        clip_id=info.clip_id, width=info.width, height=info.height,
        frames=fit.frames, focal_px=fit.focal_px,
        # One position, written out T times. The format is per-frame because the FREE model needs
        # it to be; a model that shares the position says so by repeating itself, which keeps every
        # reader — the viewer, the residual, a filter — identical for both.
        position=np.repeat(fit.centre[None], len(fit), axis=0),
        rotation=fit.rotation,
        degenerate=(~live).tolist(),
        anchor_frames=fit.fit_frames.tolist(),
        centre_seed=fit.centre_seed.round(4).tolist(),
        stage1_paint_px=round(fit.stage1_px, 3),
        notes=("ONE optical centre for the whole clip, per-frame rotation and focal, fitted "
               "directly to the painted lines. The control side is camera_auto.json."),
    )

    print(f"   centre {np.round(fit.centre, 2).tolist()} m "
          f"(seed {np.round(fit.centre_seed, 2).tolist()}, moved "
          f"{np.linalg.norm(fit.centre - fit.centre_seed):.2f} m)")
    if live.any():
        print(f"   focal  {fit.focal_px[live].min():.0f}-{fit.focal_px[live].max():.0f} px "
              f"(x{fit.focal_px[live].max() / fit.focal_px[live].min():.2f})  "
              f"{int(live.sum())}/{len(fit)} frames solved")
    print(f"   anchor-frame paint residual: {fit.stage1_px:.2f} px")
    print(f"   -> {out}")

    # --- the A/B, on the same frames, both scored the same way -------------------------------
    probe = [int(f) for f in np.asarray(fit.fit_frames)[::max(1, len(fit.fit_frames) // 8)]][:8]
    print(f"\n   paint residual, free (per-frame) vs ptz (one position), on {len(probe)} frames:")
    print(f"   {'frame':>6} {'free px':>9} {'n':>6} | {'ptz px':>9} {'n':>6}")
    fa, fb = [], []
    for f in probe:
        i = int(np.flatnonzero(fit.frames == f)[0])
        a = frame_residual(info.frame_path(f), seed.focal_px[i], seed.rotation[i],
                           seed.position[i], frame=f)
        b = frame_residual(info.frame_path(f), fit.focal_px[i], fit.rotation[i],
                           fit.centre, frame=f)
        fa.append(a)
        fb.append(b)
        print(f"   {f:6d} {a.median_px:9.2f} {a.n:6d} | {b.median_px:9.2f} {b.n:6d}")
    ma = np.nanmedian([r.median_px for r in fa])
    mb = np.nanmedian([r.median_px for r in fb])
    na = sum(r.n for r in fa)
    nb = sum(r.n for r in fb)
    print(f"   {'median':>6} {ma:9.2f} {na:6d} | {mb:9.2f} {nb:6d}")
    if nb < 0.6 * na:
        print("\n   NO VERDICT: ptz scored on far fewer samples. Those markings did not improve,")
        print("   they left the frame. Compare coverage before believing any median.")
    else:
        d = mb - ma
        print(f"\n   one position costs {abs(d):.2f} px "
              f"({'BETTER' if d < 0 else 'worse'} than 8 free DOF per frame), "
              f"and removes {len(fit)} positions in favour of 1.")
    return 0


def _cmd_markings(args) -> int:
    """Draw the CV-detected markings over every frame. No camera anywhere in this.

    The point is isolation. Every other picture in camlab shows a camera's opinion of the pitch;
    this one shows only what the frame itself says is painted, so the detector can be judged
    without a camera to blame or to hide behind. A human scrubbing this can see directly what the
    metric is being fed — which is how the mowing-stripe boundary was caught being measured
    against in the first place.
    """
    import time

    import cv2

    from camlab.measure.lines import detect_segments, on_paint_fraction
    from camlab.measure.paint import paint_masks

    info = ClipInfo.load(args.clip_id)
    out_path = Path(args.out) if args.out else info.dir / "markings.mp4"
    writer = cv2.VideoWriter(str(out_path), cv2.VideoWriter_fourcc(*"mp4v"),
                             info.fps, (info.width, info.height))
    if not writer.isOpened():
        print(f"!! cannot open {out_path} for writing")
        return 1

    t0, counts, empties = time.time(), [], []
    for n in range(info.n_frames):
        bgr = cv2.imread(str(info.frame_path(n)))
        if bgr is None:
            break
        dist, surface = paint_masks(bgr)
        segs = detect_segments(dist, surface, method=args.method)
        counts.append(len(segs))
        if not len(segs):
            empties.append(n)

        vis = bgr.copy()
        # The paint mask itself, dim: it shows what the line finder was given, so a frame with no
        # segments can be told apart from a frame with no paint.
        vis[(dist == 0) & (surface > 0)] = (0, 200, 255)
        for s in segs:
            frac = on_paint_fraction(s, dist)
            # Green where the segment sits on paint along its whole length, amber where it only
            # partly does. Amber is where a shadow edge or a net gets in, and it is drawn rather
            # than filtered so the eye can see how close the threshold is running.
            col = (80, 255, 80) if frac > 0.85 else (60, 200, 255)
            cv2.line(vis, (int(s[0]), int(s[1])), (int(s[2]), int(s[3])), col, 2, cv2.LINE_AA)
        cv2.putText(vis, f"{n:4d}  {len(segs)} lines", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(vis, f"{n:4d}  {len(segs)} lines", (10, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        writer.write(vis)
        if n % 25 == 0:
            print(f"      {n}/{info.n_frames} ...", flush=True)
    writer.release()

    c = np.asarray(counts)
    print(f"== {info.clip_id}: {len(counts)} frames in {time.time() - t0:.0f}s "
          f"({1000 * (time.time() - t0) / max(len(counts), 1):.0f} ms/frame, {args.method})")
    print(f"   lines per frame: median {np.median(c):.0f}, min {c.min()}, max {c.max()}")
    print(f"   frames with NO line: {len(empties)}" + (f" {empties[:12]}" if empties else ""))
    print(f"   -> {out_path}")
    print("\n   No camera is involved. What you see is what the metric is fed; if a mowing stripe")
    print("   or a net is drawn here, it is evidence as far as everything downstream is concerned.")
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
    p.add_argument("--principal", choices=["axis", "centre"], default="axis",
                   help="'axis' uses the clip's real optical axis, which on a cropped clip is NOT "
                        "the middle of the frames on disk; 'centre' reproduces the old behaviour")
    p.add_argument("--out", help="output name (default camera_auto.json)")
    p.set_defaults(fn=_cmd_solve)

    p = sub.add_parser("fit", help="M2: ONE position for the clip, fitted to the paint")
    p.add_argument("clip_id")
    p.add_argument("--rounds", type=int, default=4, help="ICP rounds for the shared position")
    p.set_defaults(fn=_cmd_fit)

    p = sub.add_parser("markings", help="draw the CV-detected markings over every frame")
    p.add_argument("clip_id")
    p.add_argument("--out", help="mp4 path (default: the run's markings.mp4)")
    p.add_argument("--method", choices=["lsd", "hough"], default="lsd")
    p.set_defaults(fn=_cmd_markings)

    p = sub.add_parser("list", help="what is in runs/")
    p.set_defaults(fn=_cmd_list)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
