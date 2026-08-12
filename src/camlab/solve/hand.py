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

    def offer(source: str, edits: dict) -> None:
        for frame, entry in _aims(edits, seed_camera).items():
            out.setdefault(frame, []).append((source, entry))

    manual = Path(run_dir) / "camera_manual.json"
    if manual.exists():
        offer(manual.name, json.loads(manual.read_text()).get(seed_name, {}))

    if calib_dir is not None and clip_id is not None:
        legacy = next(Path(calib_dir).glob(f"{clip_id}-hand-aligned-*.json"), None)
        if legacy is not None:
            offer(legacy.name, json.loads(legacy.read_text()).get(seed_name, {}))
    return out


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
        keep[frame] = entry
    return keep


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
