"""Video in, frames on disk, in ONE image space.

Decode is the only place the crop is applied, so every later stage — the solver, the viewer, the
frame plane, window B — is looking at the same pixels the homographies were fitted to. pitch3d
applies its crop at decode too, but keeps the uncropped size on the clip record, and the camera fit
reads that one; the result is a principal point placed outside the image. Here there is one number.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from camlab.runs import ClipInfo, runs_root, sha256_head


def apply_crop(img: np.ndarray, crop: tuple[int, int, int, int] | None) -> np.ndarray:
    """Cut `(w, h, x, y)` out of a frame. Clamped to the frame rather than raising.

    A rect measured on one segment of a clip whose framing moved can overhang a later frame, and a
    black bar is a better failure than a dead run.
    """
    if crop is None:
        return img
    h_img, w_img = img.shape[:2]
    w, h, x, y = (int(v) for v in crop)
    x = max(0, min(x, max(w_img - 1, 0)))
    y = max(0, min(y, max(h_img - 1, 0)))
    w = max(1, min(w, w_img - x))
    h = max(1, min(h, h_img - y))
    return img[y:y + h, x:x + w]


def ingest(
    source: Path,
    clip_id: str,
    *,
    first: int = 0,
    n_frames: int = 120,
    crop: tuple[int, int, int, int] | None = None,
    jpeg_quality: int = 92,
) -> ClipInfo:
    """Decode `n_frames` from `source` into `runs/<clip_id>/frames/`, through `crop`.

    Sequential read with an explicit seek to `first` only. Seeking per frame on a long-GOP h264
    file is both slow and, on some builds, silently off by a frame or two — and a frame index that
    is quietly wrong is the kind of defect that shows up much later as a camera that does not fit.
    """
    import cv2

    source = Path(source).resolve()
    if not source.exists():
        raise FileNotFoundError(source)

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {source}")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if first:
            cap.set(cv2.CAP_PROP_POS_FRAMES, first)

        out_dir = runs_root() / clip_id / "frames"
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.jpg"):
            old.unlink()

        written = 0
        shape: tuple[int, int] | None = None
        for i in range(n_frames):
            ok, frame = cap.read()
            if not ok:
                break
            cropped = apply_crop(frame, crop)
            if shape is None:
                shape = (cropped.shape[1], cropped.shape[0])
            cv2.imwrite(str(out_dir / f"{i:06d}.jpg"), cropped,
                        [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
            written = i + 1
    finally:
        cap.release()

    if not written or shape is None:
        raise RuntimeError(f"decoded 0 frames from {source} at first={first}")

    info = ClipInfo(
        clip_id=clip_id,
        source=str(source),
        source_sha256=sha256_head(source),
        width=shape[0], height=shape[1],
        fps=fps,
        n_frames=written,
        first_frame=first,
        crop=tuple(crop) if crop else None,
        source_width=src_w, source_height=src_h,
    )
    info.write()
    return info
