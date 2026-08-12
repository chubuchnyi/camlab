"""One place that turns a camera into a verdict, and refuses to when the evidence will not carry it.

Every measurement script here used to print its own summary — a median, a count of frames under
20 px — and each of them was a max over however many markings the frame happened to hold. A clip
that shows two markings scores a max over two, which is not a verdict, and it reads exactly like a
good one.

That is not hypothetical: `g15449383` was called solved on "40 of 40 frames under 20 px". It scores
**two** markings and 76 samples a frame where `fan` scores six and 165, and its worst spot is
twenty times its worst line. The number was right and it meant nothing.

So the summary is written once, carries what supports it, and says plainly when nothing does. Every
script that reports a camera goes through here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from camlab.measure.residual import MIN_SUPPORTING_MARKINGS, frame_residual

#: A camera whose frames mostly cannot be scored is not being judged, whatever number comes out.
#: Under this fraction of supported frames the verdict is withheld rather than qualified.
MIN_SUPPORTED_FRACTION = 0.5


@dataclass(frozen=True)
class Verdict:
    """What a camera is worth, and whether that is knowable from this clip.

    Attributes:
        worst_line_px, worst_spot_px: Medians over frames. **Both, always** — the first is the
            worst marking's own median and the second the worst sample on it, and they differ by
            5–9× on the clips here. Quoting one is how this project overstated its only external
            comparison threefold.
        worst_across_px: The worst sample measured ACROSS its marking. This is the one that is
            purely the camera. `worst_spot_px` is the distance to the nearest paint in any
            direction, and on `fan` 63 % of worst spots are dominated by the ALONG-line part —
            the far goal line splits 11.75 px along against 2.20 across. Along-line displacement
            of a line is not observable and not an error; it is the detected paint running out.
            So `worst_spot_px` is a joint reading of the camera and the detector, and this is the
            camera alone. Neither replaces the other: a large gap between them says the paint is
            being lost, which is a real defect in a different subsystem.
        markings: Median markings scored per frame. Read before either error.
        samples: Median scored samples per frame.
        n_frames, n_supported: How many frames were scored, and how many had enough markings.
        under_20: Frames under 20 px — **counted only over supported frames**, since on the rest
            a low number means the camera saw little rather than that it was right.
    """

    worst_line_px: float
    worst_spot_px: float
    worst_across_px: float
    markings: int
    samples: int
    n_frames: int
    n_supported: int
    under_20: int

    @property
    def supported(self) -> bool:
        return self.n_frames > 0 and self.n_supported >= MIN_SUPPORTED_FRACTION * self.n_frames

    def line(self) -> str:
        """One line, and it refuses rather than flatters when the evidence is thin."""
        if not self.n_frames:
            return "no frame could be scored at all"
        base = (f"across {self.worst_across_px:5.2f} px (the camera) · worst line "
                f"{self.worst_line_px:5.2f} · worst spot {self.worst_spot_px:5.2f} (camera+paint "
                f"gaps) · {self.markings} markings/frame · {self.samples} samples")
        if not self.supported:
            return (f"NO VERDICT — only {self.n_supported}/{self.n_frames} frames scored "
                    f"{MIN_SUPPORTING_MARKINGS}+ markings. ({base}, and both errors are a max over "
                    "too few markings to mean anything.)")
        return f"{base} · {self.under_20}/{self.n_supported} supported frames under 20 px"


def judge(clip_id: str, camera: dict, *, every: int = 1, frames=None) -> Verdict:
    """Score `camera` against the paint of `clip_id`. `camera` is a parsed camera file."""
    from camlab.runs import ClipInfo

    info = ClipInfo.load(clip_id)
    cx, cy = float(camera["cx"]), float(camera["cy"])
    idx = list(frames) if frames is not None else list(range(0, info.n_frames, max(1, every)))

    wl, ws, wa, mk, ns, sup, u20 = [], [], [], [], [], 0, 0
    for i in idx:
        if not camera["focal_px"][i] > 0:
            continue
        r = frame_residual(info.frame_path(i), camera["focal_px"][i], camera["rotation"][i],
                           camera["position"][i], frame=i, cx=cx, cy=cy)
        spot = max((v[2] for v in r.per_line.values() if v[1] >= 8), default=float("nan"))
        wl.append(r.worst_line_px)
        ws.append(spot)
        wa.append(r.worst_across_px)
        mk.append(r.n_markings)
        ns.append(r.n)
        if r.supported:
            sup += 1
            if r.worst_line_px < 20.0:
                u20 += 1
    if not wl:
        return Verdict(float("nan"), float("nan"), float("nan"), 0, 0, 0, 0, 0)
    return Verdict(float(np.nanmedian(wl)), float(np.nanmedian(ws)), float(np.nanmedian(wa)),
                   int(np.median(mk)), int(np.median(ns)), len(wl), sup, u20)


def judge_file(clip_id: str, camera_name: str, **kw) -> Verdict:
    """The same, from a camera file name in the clip's run directory."""
    import json

    from camlab.runs import ClipInfo

    path = Path(ClipInfo.load(clip_id).dir) / camera_name
    return judge(clip_id, json.loads(path.read_text()), **kw)
