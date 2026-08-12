"""Does a LOCAL paint threshold beat the fixed one, across every sample clip?

`docs/findings/daylight-and-automatic-thresholds.md` measured that `RIDGE_CONTRAST = 16` — an
ABSOLUTE brightness step set on two floodlit clips — needs to be anywhere from 20 to 117 to give
the same coverage across nine clips. Its recommendation #1 was to replace it with
`cv2.adaptiveThreshold` over the ridge map. That was never built, and the table behind it was a
throwaway with no script. This is the script, and it re-measures from scratch.

**What is compared.** Both schemes run the identical pipeline either side of one line in
`paint_masks` — same turf hue, same surface region, same ridge scales, same Hough, same merge.
Only "which ridge pixels count as paint" differs.

**What is reported, and why each.**

    px/Mpx     painted pixels per megapixel. The findings' cheap pre-flight signal: working clips
               sat at 3300-9300, broken ones at 48000-52000. It is resolution-free, so it compares
               a 4K overhead with a phone.
    lines      merged markings. Under about four, correspondence cannot start whatever the camera.
    longest    the longest merged marking, px. This is what the findings argued actually matters:
               `MIN_MERGED_PX = 100` throws away everything shorter, and the length filter is the
               only marking-vs-mowing-stripe signal that measured any good at all.

**What it does NOT claim.** One frame per clip, matching the findings' own methodology so the
numbers are comparable — and carrying the same caveat, that stability across a clip was never
checked. `--frames` samples more than one. This scores the PAINT stage, not a camera: on seven of
these nine clips there is no camera to check against, so "more long lines" is the whole verdict.

    PYTHONPATH=src .venv/bin/python scripts/bench_adaptive_threshold.py
    PYTHONPATH=src .venv/bin/python scripts/bench_adaptive_threshold.py --frames 30,60,90
    PYTHONPATH=src .venv/bin/python scripts/bench_adaptive_threshold.py --sweep-c 2,4,8,16
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from camlab.measure.lines import detect_segments, merge_collinear  # noqa: E402
from camlab.measure.paint import auto_contrast, paint_masks  # noqa: E402

#: The nine sample clips, with the label the findings gave each so the tables can be lined up.
#: `crop` is the framing the clip is actually solved through, where one has been measured.
VIDEO_DIR = Path("/home/chubuchnyi/AVATAR/samples/video")
CLIPS = [
    ("broadcast",   "Colombia-1-0-Congo-DR1080p.mp4",     "broadcast (tuned)", None),
    ("fan",         "14604731_1080_1920_30fps.mp4",       "evening (tuned)",
     (1080, 608, 0, 1294)),
    ("fan-raw",     "14604731_1080_1920_30fps.mp4",       "evening (tuned)",   None),
    ("day-amateur", "14604660_1080_1920_30fps.mp4",       "day amateur",       None),
    ("overhead-4k", "13386302_3840_2160_24fps.mp4",       "4K overhead",       None),
    ("evening-a",   "15449383-hd_1920_1080_60fps.mp4",    "evening",           None),
    ("evening-b",   "15449387-hd_1920_1080_60fps.mp4",    "evening",           None),
    ("day-stadium", "11710897-hd_1080_1920_60fps.mp4",    "day stadium",       None),
    ("day-stadium2", "14604680_1080_1920_30fps.mp4",      "day stadium",       None),
    ("day-amateur2", "15750079_2160_3840_60fps.mp4",      "day amateur",       None),
]


def read_frame(path: Path, index: int, crop) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    if crop is not None:
        w, h, x, y = crop
        frame = frame[y:y + h, x:x + w]
    return frame


def score(bgr: np.ndarray, *, mode: str = "fixed", c: int = 4) -> dict:
    """The three numbers, for one frame under one scheme.

    `mode` is "fixed" (the shipped constant), "adaptive" (local, needs `c`), or "auto"
    (self-tuned against total merged length, nothing set by hand).
    """
    t0 = time.perf_counter()
    chosen = None
    if mode == "auto":
        chosen = auto_contrast(bgr)[0]
        dist, surface = paint_masks(bgr, contrast=chosen)
    else:
        dist, surface = paint_masks(bgr, adaptive=(mode == "adaptive"), c=c)
    painted = int((dist == 0).sum())
    mpx = (bgr.shape[0] * bgr.shape[1]) / 1e6
    segs = detect_segments(dist, surface)
    merged = merge_collinear(segs) if len(segs) else np.zeros((0, 4))
    if len(merged):
        lengths = np.hypot(merged[:, 2] - merged[:, 0], merged[:, 3] - merged[:, 1])
        longest = float(lengths.max())
    else:
        longest = 0.0
    return {
        "px_per_mpx": painted / mpx,
        "lines": int(len(merged)),
        "longest": longest,
        "chosen": chosen,
        "secs": time.perf_counter() - t0,
    }


def median_of(rows: list[dict], key: str) -> float:
    return statistics.median([r[key] for r in rows]) if rows else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="30", help="comma-separated frame indices (default 30)")
    ap.add_argument("--sweep-c", default="", help="instead of the A/B, sweep ADAPTIVE_C values")
    ap.add_argument("--only", default="", help="comma-separated clip keys")
    args = ap.parse_args()

    frames = [int(x) for x in args.frames.split(",") if x.strip()]
    wanted = {x.strip() for x in args.only.split(",") if x.strip()}
    clips = [c for c in CLIPS if not wanted or c[0] in wanted]

    if args.sweep_c:
        cs = [int(x) for x in args.sweep_c.split(",")]
        print(f"ADAPTIVE_C sweep, frame(s) {frames}: lines / longest px\n")
        print(f"{'clip':<14} {'fixed 16':>14} " + " ".join(f"{'C=' + str(c):>14}" for c in cs))
        print("-" * (15 + 15 * (len(cs) + 1)))
        for key, name, _label, crop in clips:
            imgs = [f for f in (read_frame(VIDEO_DIR / name, i, crop) for i in frames)
                    if f is not None]
            if not imgs:
                print(f"{key:<14} {'unreadable':>14}")
                continue
            cells = []
            fx = [score(im, mode="fixed") for im in imgs]
            cells.append(f"{median_of(fx, 'lines'):.0f} / {median_of(fx, 'longest'):.0f}")
            for c in cs:
                ad = [score(im, mode="adaptive", c=c) for im in imgs]
                cells.append(f"{median_of(ad, 'lines'):.0f} / {median_of(ad, 'longest'):.0f}")
            print(f"{key:<14} " + " ".join(f"{s:>14}" for s in cells))
        return 0

    print(f"Three schemes, frame(s) {frames}. Medians where more than one frame.")
    print("fixed = RIDGE_CONTRAST 16 | adaptive = local, C=4 | auto = self-tuned, nothing set\n")
    head = (f"{'clip':<14} {'label':<18} {'resolution':>11} | "
            f"{'lines fix':>9} {'long fix':>8} | {'lines ad':>8} {'long ad':>8} | "
            f"{'T':>4} {'lines au':>8} {'long au':>8} | {'auto vs fixed':>13}")
    print(head)
    print("-" * len(head))

    wins = losses = ties = 0
    for key, name, label, crop in clips:
        path = VIDEO_DIR / name
        if not path.exists():
            print(f"{key:<14} {label:<18} {'MISSING':>11}")
            continue
        imgs = [f for f in (read_frame(path, i, crop) for i in frames) if f is not None]
        if not imgs:
            print(f"{key:<14} {label:<18} {'UNREADABLE':>11}")
            continue
        res = f"{imgs[0].shape[1]}x{imgs[0].shape[0]}"
        fx = [score(im, mode="fixed") for im in imgs]
        ad = [score(im, mode="adaptive", c=4) for im in imgs]
        au = [score(im, mode="auto") for im in imgs]

        gf, ga, gu = (median_of(fx, "longest"), median_of(ad, "longest"),
                      median_of(au, "longest"))
        chosen = statistics.median([r["chosen"] for r in au])
        # The objective the findings named: longer merged markings. Line COUNT is not it — the
        # runaway clip returns 1300+ of them and none is a marking.
        if gu > gf * 1.05:
            verdict = "better"
            wins += 1
        elif gu < gf * 0.95:
            verdict = "worse"
            losses += 1
        else:
            verdict = "same"
            ties += 1
        print(f"{key:<14} {label:<18} {res:>11} | "
              f"{median_of(fx, 'lines'):>9.0f} {gf:>8.0f} | "
              f"{median_of(ad, 'lines'):>8.0f} {ga:>8.0f} | "
              f"{chosen:>4.0f} {median_of(au, 'lines'):>8.0f} {gu:>8.0f} | {verdict:>13}")

    print(f"\nauto vs fixed, on longest marking: {wins} better, {ties} same, {losses} worse")
    print(f"auto costs {median_of(au, 'secs'):.1f}s/frame against {median_of(fx, 'secs'):.1f}s "
          "for the fixed threshold (last clip).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
