"""The run directory — what a clip turns into on disk, and the contract between stages.

One directory per clip. Every stage writes one file and reads the ones before it, so re-solving
the camera never re-decodes the video and never re-runs a model. That is the difference between an
instrument and a batch job: spec §5.7.

    runs/<clip-id>/
      clip.json          w, h, fps, n_frames, the crop rect, sha256 of the source
      frames/000000.jpg  decoded through the crop, so pixel (0,0) here is pixel (0,0)
                         of the space the homographies live in
      camera_auto.json   the solve
      camera_manual.json hand edits, laid OVER camera_auto (M3) — never a rewrite of it

**The crop is part of the contract, not a detail.** pitch3d's `--crop auto` moves the homographies
into the crop rect while leaving `ClipRef.width/height` at the source size, and the camera fit is
then handed the wrong image size — a principal point placed 656 px outside an image 608 px tall
(`landmines.md`, measured 2026-08-10). Here `clip.json` records ONE image space, the frames on disk
are already in it, and `width`/`height` mean the size of those frames. There is no second answer to
the question.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


def runs_root() -> Path:
    """Where runs live. `CAMLAB_RUNS` in the container, `./runs` outside it."""
    import os

    return Path(os.environ.get("CAMLAB_RUNS", "runs")).resolve()


@dataclass(frozen=True)
class ClipInfo:
    """The one description of a clip's image space that every stage reads.

    Attributes:
        clip_id: Directory name under `runs/`.
        source: Absolute path of the mp4 this came from.
        source_sha256: First 16 hex chars of the file digest. Cheap insurance against the run
            silently being about a different video after someone re-encodes one in place.
        width, height: Size of the frames ON DISK — after the crop. This is the image space the
            homographies, the focal and the principal point all live in.
        fps: Frames per second of the source.
        n_frames: How many frames were extracted.
        first_frame: Index in the SOURCE of `frames/000000.jpg`.
        crop: `(w, h, x, y)` in source pixels, or None for the full frame.
        source_width, source_height: Size before the crop, kept only so the crop can be read back.
    """

    clip_id: str
    source: str
    source_sha256: str
    width: int
    height: int
    fps: float
    n_frames: int
    first_frame: int
    crop: tuple[int, int, int, int] | None
    source_width: int
    source_height: int

    @property
    def dir(self) -> Path:
        return runs_root() / self.clip_id

    def write(self) -> Path:
        d = self.dir
        d.mkdir(parents=True, exist_ok=True)
        p = d / "clip.json"
        p.write_text(json.dumps(asdict(self), indent=2))
        return p

    @staticmethod
    def load(clip_id: str) -> ClipInfo:
        blob = json.loads((runs_root() / clip_id / "clip.json").read_text())
        crop = blob.get("crop")
        return ClipInfo(**{**blob, "crop": tuple(crop) if crop else None})

    def frame_path(self, n: int) -> Path:
        return self.dir / "frames" / f"{n:06d}.jpg"

    @property
    def principal_point(self) -> tuple[float, float]:
        """The optical axis, in the coordinates of the frames on disk.

        **Not the centre of the cropped frame.** A crop moves the image relative to the lens; the
        optical axis stays where the lens put it, which is the centre of the SOURCE frame. Cutting
        `1080x608+0+1294` out of a 1080x1920 clip leaves the axis at `(540, -334)` — 638 px above
        the crop, further than the crop is tall.

        Measured 2026-08-10, and it is not a technicality. Sweeping `cy` through the image->image
        maps, which know nothing about the crop, puts the minimum at **-334.0** — the arithmetic
        value to the decimal — against **0.1005** at the crop centre we had assumed. A factor of
        2.4 in an instrument precise to 0.05. See `docs/findings/m2-principal-point.md`.

        Uncropped clips get the frame centre, which is the same statement with a zero offset.
        """
        if self.crop is None:
            return self.width / 2.0, self.height / 2.0
        _w, _h, x, y = self.crop
        return self.source_width / 2.0 - x, self.source_height / 2.0 - y


def list_runs() -> list[str]:
    root = runs_root()
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if (p / "clip.json").exists())


def sha256_head(path: Path, n_bytes: int = 8 << 20) -> str:
    """Digest of the first 8 MB. Enough to catch a swapped file, cheap on a 90 MB clip."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        h.update(f.read(n_bytes))
    return h.hexdigest()[:16]
