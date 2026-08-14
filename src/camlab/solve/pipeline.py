"""The whole camera chain, as one call, so the viewer can run it.

Everything here already existed as a script. What it did not have was a single entry point that a
button could reach, which meant "upload a clip" stopped one step short of being useful: the frames
decoded, the clip appeared, and there was no way to get a camera without a shell.

The order is not arbitrary and every step earned its place by measurement:

    1. **anchors** — EVERY frame the human has aimed, not one. Each is worth about sixty frames of
       carry, and each one added halves the drift the chain accumulates between them.
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
    6. **polish** — go back over the frames the chain left worst and try their neighbours.

Progress is reported through a callback rather than printed, because the caller here is a browser.
"""

from __future__ import annotations

import json
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
    # Fifth, and after the median filter rather than before it, which is the whole point. Self-heal
    # already offers a neighbour's camera to a lost frame — but it runs on `camera_carry.json`, and
    # shared-centre then moves every frame onto one optical centre and smoothing moves every frame
    # again, so a frame that was fine when self-heal saw it can be the worst in the clip by the end.
    # An operator scrubbing `g14604660` found exactly that and fixed frames by hand.
    #
    # Measured 2026-08-13 09:0x, worst frame in the clip, before -> after. **Against a
    # `camera_smooth.json` that no longer exists**: the multi-anchor re-solve rewrote smooth on
    # every one of these clips six hours later, and because nothing invalidated the stage after
    # it, each `camera_polished.json` on disk stayed built from the older input. The gains below
    # were real when taken and have not been re-measured since.
    #     broadcast        7.03 -> 4.33     14 of 60 frames changed
    #     14604731        28.73 -> 22.74    10 of 180
    #     CRO_MOR_194948   6.80 -> 5.56      2 of 120
    #     wp_194948        6.41 -> 5.61      2 of 120
    #     fan              4.06 -> 3.21      1 of 120
    #     NET_ARG_225042  59.88 -> 57.63    10 of 60, and eight frames at 40-60 px went to 5-7
    # Medians barely move because only outliers are touched. Not one clip got worse: a candidate is
    # kept only if it beats what is there AND scores on no fewer markings.
    ("polish", "polish_camera.py", ["--from", "camera_smooth.json",
                                    "--out", "camera_polished.json"]),
]


#: Every camera file the chain writes, read off STAGES so this cannot drift from what it does.
OUTPUTS = frozenset(extra[extra.index("--out") + 1]
                    for _label, _script, extra in STAGES if "--out" in extra)

#: What the chain hands back — the last stage's output, read off STAGES so it cannot drift.
FINAL_CAMERA = next((extra[extra.index("--out") + 1]
                     for _l, _s, extra in reversed(STAGES) if "--out" in extra),
                    "camera_smooth.json")


def anchors_for(clip_id: str, seed: str, fallback: int = 0) -> list[int]:
    """Every frame the operator has actually aimed, as anchors — not just one.

    `run` took a single `anchor` and passed `--anchor 0`, while `solve_carry.py` has always
    accepted a comma list and assigned each frame to its NEAREST anchor. So an operator who aimed
    twelve frames of `g11710897` had eleven of them thrown away on every press of the solve button,
    and the register's own finding — that each added anchor halves the drift a chain accumulates —
    was unreachable from the viewer.

    Falls back to `fallback` when nothing has been aimed, which is the old behaviour.
    """
    from camlab.runs import ClipInfo
    from camlab.solve.hand import hand_candidates

    info = ClipInfo.load(clip_id)
    src = info.dir / seed
    base = json.loads(src.read_text()) if src.exists() else None
    got = hand_candidates(info.dir, seed, seed_camera=base,
                          calib_dir=REPO / "calib", clip_id=clip_id)
    frames = sorted(int(k) for k in got if 0 <= int(k) < info.n_frames)
    return frames or [fallback]


def unread_aims(clip_id: str, seed: str) -> dict[str, list[str]]:
    """Hand edits on disk that this seed will not read, so the caller can say so out loud.

    Only the key naming the seed is read, for the reasons in `solve/hand.py`. On `g11710897` that
    silence hid **twelve** aimed frames — the operator had been scrubbing `camera_smooth.json` when
    he aimed them — while the three the default seed did read were echoes of the seed itself, and
    the clip was called unsolvable for a day.
    """
    from camlab.runs import ClipInfo
    from camlab.solve.hand import aims_under_other_keys

    return aims_under_other_keys(ClipInfo.load(clip_id).dir, seed)


def run(clip_id: str, *, anchor: int | list[int] | None = None, seed: str = "camera_start.json",
        on_progress=None, timeout_s: int = 3600) -> dict:
    """Run every stage. Returns `{stage: last line of its output}` plus `ok` and `camera`.

    A stage that fails stops the chain and is reported — a half-solved clip whose later stages ran
    on a broken earlier one is worse than a clear failure, because it produces a camera file that
    looks like every other camera file.
    """
    # Default: every frame the operator aimed. An explicit `anchor` still wins, for a caller that
    # means one particular frame.
    if anchor is None:
        anchor = anchors_for(clip_id, seed)
    picks = [anchor] if isinstance(anchor, int) else list(anchor)
    out: dict = {"stages": {}, "ok": False, "camera": None, "seed": seed, "anchors": picks}
    # Say what is on disk and not being read. Not a warning about a hypothetical: this is the fact
    # that, left unsaid, kept twelve of `g11710897`'s aims out of every run for a day.
    other = unread_aims(clip_id, seed)
    if other:
        out["unread_aims"] = other
        listed = "; ".join(f"{k} ({len(v)} frames)" for k, v in sorted(other.items()))
        out["stages"]["aims"] = (
            f"hand edits exist that this seed does not read: {listed}. Seed from that file to "
            f"use them."
        )
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
    from camlab.runs import ClipInfo

    run_dir = ClipInfo.load(clip_id).dir
    hand_key = seed
    requested_seed = seed
    if not (run_dir / seed).exists():
        # Said here rather than left to a stage, which dies on it with a bare pathlib traceback and
        # no mention of the seed. This is reachable in one step: seed from a chain output, let the
        # run be killed after the clear, and the file the next run wants is gone.
        out["stages"]["seed"] = (
            f"there is no {seed} to seed from. If it is one this chain writes, a previous run "
            f"removed it; {SEED_SNAPSHOT} holds what that run started from."
        )
        return out
    if seed in OUTPUTS:
        src = run_dir / seed
        snap = run_dir / SEED_SNAPSHOT
        snap.write_text(src.read_text())
        out["seed"] = seed = SEED_SNAPSHOT
        hand_key = requested_seed
        out["stages"]["seed"] = (
            f"seeded from a copy of {src.name} kept as {SEED_SNAPSHOT}, because the chain "
            f"overwrites {src.name} itself"
        )

    # Clear every output this chain is about to write, BEFORE writing any of it.
    #
    # The failure path above only covers a stage that fails while this function is watching. A run
    # that is killed outright — a timeout on the caller's side, the harness, an operator closing the
    # tab — leaves the previous run's later outputs sitting next to this run's earlier ones, and
    # nothing on disk says which run each came from.
    #
    # That is not hypothetical. `g11710897` carried at 21:50 to focal 2100, the operator's own
    # anchor; `camera_smooth.json` — the file FINAL_CAMERA names, the one anything downstream reads
    # — was still the 15:37 file at focal 2777, the pre-fix seed that scores three markings instead
    # of seven. The run directory read as a completed chain and every conclusion drawn from it was
    # about a camera three fixes out of date.
    #
    # Deleting rather than stamping, because a missing file makes every reader fail loudly and a
    # stamp only helps the readers that check it.
    #
    # **Except the file this run is seeded from**, which is kept even though it is an output. The
    # first version deleted it, and that is a one-way door: seeding from `camera_smooth.json`
    # snapshotted it, deleted the original, and the run was then killed — after which nothing could
    # ever seed from that name again, because the file it names no longer exists. The snapshot makes
    # deleting it safe for THIS run and useless for the next one. The stage that owns it overwrites
    # it in due course anyway.
    stale = []
    for name in sorted(OUTPUTS - {requested_seed}):
        path = run_dir / name
        if path.exists():
            path.unlink()
            stale.append(name)
    if stale:
        out["cleared"] = stale
        out["stages"]["clear"] = (
            f"removed {len(stale)} output(s) from a previous run: {', '.join(stale)}"
        )

    for i, (label, script, extra) in enumerate(STAGES):
        args = [sys.executable, str(SCRIPTS / script), clip_id]
        if script == "solve_carry.py":
            args += ["--anchor", ",".join(str(a) for a in picks), "--seed", seed,
                     "--hand-key", hand_key]
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
    # The polish stage's output, when it ran. Named from STAGES rather than written out, so adding
    # or reordering a stage cannot leave this pointing at a file two stages back.
    out["camera"] = FINAL_CAMERA
    return out
