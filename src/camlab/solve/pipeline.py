"""The whole camera chain, as one call, so the viewer can run it.

Everything here already existed as a script. What it did not have was a single entry point that a
button could reach, which meant "upload a clip" stopped one step short of being useful: the frames
decoded, the clip appeared, and there was no way to get a camera without a shell.

The order is not arbitrary and every step earned its place by measurement:

    1. **anchor** — a hand-aligned frame if the human has made one, else frame 0 refitted from the
       default. One hand anchor is measured at about sixty frames' worth.
    2. **carry** — take that camera to the next frame through the image-to-image homography, then
       refit. Copying instead of carrying loses the track in three frames, because the operator
       zooms (`carrying-the-camera-works.md`).
    3. **self-heal** — find the frames the chain lost and re-seed each from its nearest good
       neighbour on both sides, trying a plain copy as well as a carry, keeping whichever the paint
       prefers. 97 -> 120 of 120 on the fan clip.
    4. **shared centre** — the camera is one point; slide along the line the free solve strung
       itself out on and keep the best. Better on the paint AND renderable
       (`the-camera-moves-along-a-line-and-that-is-the-bug.md`).
    5. **smooth** — median-filter each parameter, keeping only the frames the paint agrees with.

Progress is reported through a callback rather than printed, because the caller here is a browser.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "scripts"

#: Each stage as (label, script, extra args). Run as subprocesses rather than imported: the scripts
#: are the thing that has been measured, and a second import-shaped path through the same logic is
#: how two versions of "the pipeline" start to disagree.
STAGES = [
    ("carry", "solve_carry.py", ["--no-hand", "--free-position", "--out", "camera_carry.json"]),
    ("self-heal", "solve_selfheal.py", ["--from", "camera_carry.json",
                                        "--out", "camera_healed.json"]),
    ("shared centre", "solve_shared_centre.py", ["--from", "camera_healed.json",
                                                 "--out", "camera_fixed.json"]),
    ("smooth", "smooth_camera.py", ["--from", "camera_fixed.json",
                                    "--out", "camera_smooth.json"]),
]


def run(clip_id: str, *, anchor: int = 0, seed: str = "camera_start.json",
        on_progress=None, timeout_s: int = 3600) -> dict:
    """Run every stage. Returns `{stage: last line of its output}` plus `ok` and `camera`.

    A stage that fails stops the chain and is reported — a half-solved clip whose later stages ran
    on a broken earlier one is worse than a clear failure, because it produces a camera file that
    looks like every other camera file.
    """
    out: dict = {"stages": {}, "ok": False, "camera": None}
    for i, (label, script, extra) in enumerate(STAGES):
        args = [sys.executable, str(SCRIPTS / script), clip_id]
        if script == "solve_carry.py":
            args += ["--anchor", str(anchor), "--seed", seed]
        args += extra
        if on_progress:
            on_progress(i, len(STAGES), label, "running")
        try:
            p = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                               timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired:
            out["stages"][label] = f"timed out after {timeout_s}s"
            if on_progress:
                on_progress(i, len(STAGES), label, "timed out")
            return out
        tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()]
        out["stages"][label] = tail[-1] if tail else (p.stderr or "").strip()[-300:]
        if p.returncode != 0:
            out["stages"][label] = f"failed: {(p.stderr or '').strip()[-300:]}"
            if on_progress:
                on_progress(i, len(STAGES), label, "failed")
            return out
        if on_progress:
            on_progress(i + 1, len(STAGES), label, "done")
    out["ok"] = True
    out["camera"] = "camera_smooth.json"
    return out
