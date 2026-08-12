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

import os
import subprocess
import sys
from pathlib import Path


def _find_scripts() -> Path:
    """Where the stage scripts live.

    Counting parent directories was the previous answer and it holds only for the development
    layout: from `site-packages/camlab/solve/pipeline.py`, `parents[3]` is `/usr/lib/python3.12`
    and `SCRIPTS` is a directory that does not exist. The same defect has already cost one session
    in a different shape — the container was built without `scripts/` and the viewer's solve button
    failed with "can't open file /app/scripts/solve_carry.py".

    So: an explicit override first, then the two layouts that actually occur, then a clear failure
    rather than a path nobody will look at.
    """
    env = os.environ.get("CAMLAB_SCRIPTS")
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    for base in (here.parents[3], here.parents[2], Path.cwd()):
        cand = base / "scripts"
        if (cand / "solve_carry.py").exists():
            return cand
    # Nothing found. Return the development guess so the error names a path a human recognises.
    return here.parents[3] / "scripts"


SCRIPTS = _find_scripts()
REPO = SCRIPTS.parent

#: Each stage as (label, script, extra args). Run as subprocesses rather than imported: the scripts
#: are the thing that has been measured, and a second import-shaped path through the same logic is
#: how two versions of "the pipeline" start to disagree.
#: Where the run's own starting point is kept when the seed is a file the chain overwrites. One
#: fixed name rather than a timestamp: what matters is that the last run's input survives its
#: output, not that every run's does.
SEED_SNAPSHOT = "camera_seed_used.json"

STAGES = [
    # NOT `--no-hand`. It was hardcoded here, so the viewer's "solve this clip" button threw away
    # the operator's own anchor on every run — the one input the chain most depends on.
    ("carry", "solve_carry.py", ["--free-position", "--out", "camera_carry.json"]),
    ("self-heal", "solve_selfheal.py", ["--from", "camera_carry.json",
                                        "--out", "camera_healed.json"]),
    ("shared centre", "solve_shared_centre.py", ["--from", "camera_healed.json",
                                                 "--out", "camera_fixed.json"]),
    ("smooth", "smooth_camera.py", ["--from", "camera_fixed.json",
                                    "--out", "camera_smooth.json"]),
]


#: Every camera file the chain writes, read off STAGES so this cannot drift from what it does.
OUTPUTS = frozenset(extra[extra.index("--out") + 1]
                    for _label, _script, extra in STAGES if "--out" in extra)


def run(clip_id: str, *, anchor: int = 0, seed: str = "camera_start.json",
        on_progress=None, timeout_s: int = 3600) -> dict:
    """Run every stage. Returns `{stage: last line of its output}` plus `ok` and `camera`.

    A stage that fails stops the chain and is reported — a half-solved clip whose later stages ran
    on a broken earlier one is worse than a clear failure, because it produces a camera file that
    looks like every other camera file.
    """
    out: dict = {"stages": {}, "ok": False, "camera": None, "seed": seed}
    if not (SCRIPTS / "solve_carry.py").exists():
        out["stages"]["setup"] = (
            f"the stage scripts are not at {SCRIPTS}. Set CAMLAB_SCRIPTS to the directory holding "
            "solve_carry.py, or install from a checkout."
        )
        return out
    # The viewer sends whichever camera is selected as the seed, and four of the names it can send
    # are files this chain WRITES. Seeding from `camera_smooth.json` means the last stage overwrites
    # what the first stage read: a second press compounds on the first with no way back, and the
    # manual layer — which is keyed by file name — ends up laid over a different solve than the one
    # it was aimed against. That happened on `CRO_MOR_194948` before anyone noticed.
    #
    # Not refused, because re-solving from a refined camera is a real thing to want. Snapshotted:
    # the run reads a copy, so whatever it overwrites, what it STARTED from is still on disk.
    if seed in OUTPUTS:
        from camlab.runs import ClipInfo

        info = ClipInfo.load(clip_id)
        src = info.dir / seed
        if src.exists():
            snap = info.dir / SEED_SNAPSHOT
            snap.write_text(src.read_text())
            out["seed"] = seed = SEED_SNAPSHOT
            out["stages"]["seed"] = (
                f"seeded from a copy of {src.name} kept as {SEED_SNAPSHOT}, because the chain "
                f"overwrites {src.name} itself"
            )

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
