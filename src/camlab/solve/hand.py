"""Where a human's own aim lives, and how the solver decides which one to believe.

Two stores exist and both are legitimate. The viewer writes every edit to the run's
`camera_manual.json`; `calib/<clip>-hand-aligned-*.json` holds curated anchors from earlier
sessions. Until 2026-08-12 the solver read only the second, and `solve/pipeline.py` passed
`--no-hand` anyway, so the viewer's "solve this clip" button discarded the operator's anchor on
every press without saying so. Measured on `CRO_MOR_194948` frame 0: **24.17 px on 2 markings**
against **3.67 px on 10**.

The first repair for that made it worse on `fan`, and both mistakes are worth keeping written down
because they are easy to make again.

**A store cannot have priority.** Preferring the run's file put `solve_carry.py fan --anchor 0` on a
31.55 px anchor where the curated file holds 5.30, and on frame 51 a **102.01 px** anchor against
2.17. Which store an anchor came from says nothing about whether it is a good one. So nothing here
ranks by source: both stores offer candidates and the caller picks the one that fits the paint,
which is the only thing that can settle it.

**A clip-scoped position write is not an aim.** The viewer's "position applies to the whole clip"
tick-box stamps an entry on *every* frame, carrying the shared position with that frame's own
rotation and focal — 117 of `fan`'s 120 entries are that, and only 3 are aims. The record shape is
identical to a hand alignment, so a loader that reads shape alone cannot tell them apart, and
`landmines.md` already records this exact write destroying a frame from 3.6 px to 41.1 px. It is
separable exactly rather than heuristically: in a broadcast entry the rotation and focal are
bit-identical to the solve underneath, because only the position was replaced.

**Edits are read only under the key naming the solve this run is seeded from — and that is a
limitation, not a design.** The store is keyed by solve name; the entries themselves are absolute
world poses, so an aim made against one solve would be a perfectly good anchor for another. Reading
every key is nonetheless not safe, and the reason is worth keeping because it cost a morning:

- the broadcast test above needs the solve the entries overlay, and for chain outputs that file is
  **overwritten by the next run**, so for old edits there is nothing left to compare against;
- **a shared position does not mark a broadcast.** Refuted on the clips this matters for: all 12 of
  `g11710897`'s aims sit at (56, 25, 1.5) because the phone does not move and only the rotation was
  aimed. Rejecting shared positions would delete exactly the pitch-level work;
- **file mtimes cannot date an entry.** `camera_manual.json` is rewritten whole on every edit, so
  its timestamp is about the newest edit anywhere in it. The test read "reference is stale" for
  `g11710897`, whose reference is fine, and "reference is current" for `fan`, whose five references
  have all been rewritten since.

So old edits cannot be classified after the fact, and the repair belongs at write time: the viewer
should record, in the entry, the pose it was aimed away from. Until then `aims_under_other_keys`
reports what is there without offering it, because the failure that actually happened was silence —
twelve aims on disk, a clip called unsolvable, and nothing connecting the two.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

#: Every key an anchor must carry to be usable as one. A partial entry is a bug upstream, not a
#: camera to fill in from defaults — and it would be used silently, for the frame the whole chain
#: hangs off.
REQUIRED = ("focal_px", "rotation", "position")


def hand_candidates(run_dir: Path, seed_name: str, seed_camera: dict | None = None,
                    calib_dir: Path | None = None,
                    clip_id: str | None = None) -> dict[str, list[tuple[str, dict]]]:
    """`{frame: [(source, entry), ...]}` — every hand aim offered for `seed_name`, from both stores.

    Deliberately not a single answer. Ranking by store is what broke `fan`; the caller has the
    frames and the paint and is the only one that can say which candidate is better.

    `seed_camera` is the solve these edits overlay. Given it, clip-scoped position writes are
    dropped exactly — they are the entries whose rotation and focal are bit-identical to it.
    Without it they cannot be told from aims and are all kept, which is the flattering direction
    and the reason to pass it.
    """
    out: dict[str, list[tuple[str, dict]]] = {}

    def offer(source: str, edits: dict, reference: dict | None) -> None:
        for frame, entry in _aims(edits, reference).items():
            out.setdefault(frame, []).append((source, entry))

    run_dir = Path(run_dir)
    manual = run_dir / "camera_manual.json"
    if manual.exists():
        offer(manual.name, json.loads(manual.read_text()).get(seed_name, {}), seed_camera)

    if calib_dir is not None and clip_id is not None:
        legacy = next(Path(calib_dir).glob(f"{clip_id}-hand-aligned-*.json"), None)
        if legacy is not None:
            offer(legacy.name, json.loads(legacy.read_text()).get(seed_name, {}), seed_camera)
    return out


def aims_under_other_keys(run_dir: Path, seed_name: str) -> dict[str, list[str]]:
    """`{key: [frame, ...]}` for hand edits aimed against some OTHER solve. Reported, not used.

    Nothing here can judge them — see the module docstring for the three discriminators that were
    measured and refuted — but leaving them silent is how twelve aims on `g11710897` stayed
    invisible while the clip was called unsolvable. A caller that prints this gives the operator the
    one fact they need: their work is on disk, under a name this run is not reading.
    """
    manual = Path(run_dir) / "camera_manual.json"
    if not manual.exists():
        return {}
    try:
        store = json.loads(manual.read_text())
    except ValueError:
        return {}
    return {k: sorted(v, key=int) for k, v in store.items()
            if k != seed_name and isinstance(v, dict) and v}


def _aims(edits: dict, seed_camera: dict | None) -> dict:
    """The entries that are somebody's aim, rather than a partial record or a position broadcast."""
    keep = {}
    for frame, entry in edits.items():
        if not isinstance(entry, dict) or not all(f in entry for f in REQUIRED):
            continue
        if not entry["focal_px"] > 0:
            continue
        if seed_camera is not None and _is_position_broadcast(entry, seed_camera, int(frame)):
            continue
        if seed_camera is not None and _is_echo(entry, seed_camera, int(frame)):
            continue
        keep[frame] = entry
    return keep


#: The viewer rounds when it writes, so an untouched entry comes back a fraction off the solve it
#: was copied from. Both tolerances are set from the measurement rather than guessed, on
#: `g11710897`'s three entries under `camera_start.json`:
#:
#:     frame  0   d_rot 2.47e-05   d_pos 0.0000   d_focal 0.0592     <- nothing was moved
#:     frame  2   d_rot 2.01e-01   d_pos 59.50     d_focal 571.94    <- aimed
#:     frame 39   d_rot 2.74e-01   d_pos 55.00     d_focal 0.0592    <- aimed
#:
#: Four orders of magnitude separate the rounding from the smallest real aim. 1e-4 rad is 0.0057
#: degrees — twenty times finer than the viewer's smallest rotation step, so a single minimum nudge
#: still reads as an aim.
ECHO_FOCAL_PX = 0.5
ECHO_ROT_RAD = 1e-4
ECHO_POS_M = 1e-4


def _is_echo(entry: dict, seed_camera: dict, i: int) -> bool:
    """Nothing was moved: every field matches the solve, to the precision the viewer writes at.

    Distinct from a position broadcast, where the position *did* change. This is the shape left by
    opening a frame and putting it back, and it is not an aim by anybody.

    Dropping it costs nothing, which is the point: `solve_carry` already scores the seed's own pose
    at every anchor, so an entry equal to that pose adds no candidate. What it does add is a
    frame to the anchor list — `g11710897` reported three anchors under `camera_start.json` and all
    three were this, while twelve real aims sat under another key and were not being read at all.
    """
    try:
        rot = np.asarray(seed_camera["rotation"][i], float)
        pos = np.asarray(seed_camera["position"][i], float)
        focal = float(seed_camera["focal_px"][i])
    except (KeyError, IndexError, TypeError, ValueError):
        return False
    return bool(
        np.allclose(np.asarray(entry["rotation"], float), rot, rtol=0, atol=ECHO_ROT_RAD)
        and np.allclose(np.asarray(entry["position"], float), pos, rtol=0, atol=ECHO_POS_M)
        and abs(float(entry["focal_px"]) - focal) <= ECHO_FOCAL_PX
    )


def _is_position_broadcast(entry: dict, seed_camera: dict, i: int) -> bool:
    """Only the position differs from the solve, so nobody aimed this frame.

    Exact equality, not a tolerance: the viewer copies these two fields through untouched, so a
    genuine aim that happened to reproduce the solve's rotation to the last bit does not occur.
    """
    try:
        rot = np.asarray(seed_camera["rotation"][i], float)
        focal = seed_camera["focal_px"][i]
    except (KeyError, IndexError, TypeError):
        return False
    return (np.array_equal(np.asarray(entry["rotation"], float), rot)
            and entry["focal_px"] == focal)
