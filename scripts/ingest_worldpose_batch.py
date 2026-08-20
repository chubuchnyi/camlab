"""Ingest more WorldPose clips and import their ground truth — **working half only**.

Four clips is not a sample. WorldPose covers 89, and the working half of the split in
`docs/held-out-clips.md` is 48 of them across four matches, so there are 44 more that may be looked
at without spending anything.

**This refuses to touch a held-out clip**, and that is the point of it existing rather than a shell
loop: the rule in the document is only worth having if something enforces it. Naming a held-out
clip is an error, not a warning — a warning is a thing people scroll past.

Reported per clip, because both matter and neither is obvious:

* the GT's own **focal, principal point, height and distortion** — the import prints these and they
  are the cheapest check that a clip is what it claims to be;
* whether the paint can score the GT camera **at all**. On `CRO_MOR_194338` it cannot: 18 frames of
  60 reach four markings, so that clip cannot take part in a paint-versus-truth comparison in
  either direction. That is the detector's limit, not the truth's, and a clip that fails it should
  be reported rather than quietly averaged in.

**The whole ingest-and-anchor is AVATAR's, called and not copied.** `new_clip_anchor.py` already
does every step between "here is an mp4" and "camlab has a first camera": it measures the crop,
**scans the clip for a frame worth solving** — PnLCalib returns 1 landmark on frame 0 of
`14604680` and 19 on frame 630, so picking a frame by convention is how two rounds were lost —
ingests through camlab's own venv, writes the start camera and puts the anchor in
`camera_manual.json`. Reimplementing any of that here would be a second copy to keep true.

So this script does only what AVATAR cannot know: which clips are in the WORKING half, and the
ground-truth import. It needs a camlab server up for the anchor to be scored against:

    PYTHONPATH=src .venv/bin/uvicorn camlab.server.app:app --port 8899

**A default seed alone does not solve these clips.** Measured on `CRO_MOR_182607`: the chain from
`camera_start.json` with no anchor reaches **0 of 60 frames with four markings, 22.76 px**. With one
PnLCalib anchor the same frame refits to 1.05 px on 9 markings. The anchor is not a convenience.

And the path has a `KNOWN_HARD` list of its own — `MOR_POR_181952` is on it, with the reason
measured rather than guessed — so some clips will be refused, and that is reported rather than
worked around.

    python scripts/ingest_worldpose_batch.py --per-match 4 --frames 240
    python scripts/ingest_worldpose_batch.py CRO_MOR_182607 --frames 240
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "scripts"))
sys.path.insert(0, str(HERE / "src"))

from worldpose_split import all_clips, half, match_of  # noqa: E402

VIDEO = Path.home() / "AVATAR/models/worldpose/WorldPose Dataset/compressed"
RUNS = HERE / "runs"

AVATAR = Path.home() / "AVATAR"
PNLCALIB_ENV = {
    "PNLCALIB_REPO": str(Path.home() / "repos/PnLCalib"),
    "PNLCALIB_WEIGHTS_KP": str(AVATAR / "models/pnlcalib/SV_kp"),
    "PNLCALIB_WEIGHTS_LINES": str(AVATAR / "models/pnlcalib/SV_lines"),
}


def ingested(clip: str) -> bool:
    return (RUNS / clip / "clip.json").exists()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("clips", nargs="*", default=None)
    ap.add_argument("--per-match", type=int, default=0,
                    help="take this many not-yet-ingested clips from each WORKING match")
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--video", default=str(VIDEO))
    ap.add_argument("--server", default="http://127.0.0.1:8899")
    ap.add_argument("--stride", type=int, default=0,
                    help="frame-probe stride for AVATAR's frame search; 0 leaves its default")
    ap.add_argument("--reingest", action="store_true",
                    help="re-decode a clip that is already ingested, e.g. for a longer window")
    args = ap.parse_args()

    want = list(args.clips or [])
    if args.per_match:
        by_match: dict[str, list[str]] = {}
        for c in all_clips():
            if half(c) == "work" and not ingested(c):
                by_match.setdefault(match_of(c), []).append(c)
        for m in sorted(by_match):
            want += by_match[m][:args.per_match]
    if not want:
        raise SystemExit("nothing to do: name clips or pass --per-match")

    held = [c for c in want if half(c) != "work"]
    if held:
        raise SystemExit(
            f"REFUSING: {', '.join(held)} are in the HELD-OUT half. Measuring on them spends a "
            f"match, which is a one-way door — see docs/held-out-clips.md. If that is genuinely "
            f"intended, add the match to SPENT_MATCHES in scripts/worldpose_split.py in the same "
            f"commit as the measurement.")

    env = {**dict(__import__("os").environ), "PYTHONPATH": str(HERE / "src")}
    print(f"{len(want)} clips, {args.frames} frames each, working half only\n")
    for c in want:
        video = Path(args.video) / f"{c}.mp4"
        if not video.exists():
            print(f"  {c:<20} NO VIDEO at {video}")
            continue
        cmd = [str(AVATAR / ".venv/bin/python"), str(AVATAR / "scripts/new_clip_anchor.py"),
               "--video", str(video), "--clip-id", c, "--frames", str(args.frames),
               "--server", args.server]
        if args.stride:
            cmd += ["--stride", str(args.stride)]
        got = subprocess.run(cmd, env={**env, **PNLCALIB_ENV}, capture_output=True, text=True,
                             cwd=str(AVATAR))
        lines = (got.stdout or got.stderr).strip().splitlines()
        keep = [ln for ln in lines
                if any(k in ln for k in ("best is frame", "after refit", "wrote anchor",
                                         "known not to solve", "worst line", "REFUS", "Traceback"))]
        print(f"  {c}")
        for ln in (keep or lines[-2:]):
            print(f"      {ln.strip()[:110]}")

        got = subprocess.run(
            [sys.executable, str(HERE / "scripts" / "import_worldpose_gt.py"), c, "--judge"],
            env=env, capture_output=True, text=True, cwd=str(HERE))
        for line in (got.stdout or got.stderr).strip().splitlines():
            print(f"      {line.strip()[:130]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
