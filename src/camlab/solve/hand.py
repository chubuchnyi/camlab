"""Where a human's own aim lives, and the one place the solver looks for it.

Until 2026-08-12 there were two stores of hand-aligned anchors and neither knew about the other.
The viewer wrote every edit — typed number, gizmo drag, keyboard nudge, auto-fit — to the run's
`camera_manual.json`; `solve_carry.py` read `calib/<clip>-hand-aligned-*.json`; and
`solve/pipeline.py` passed `--no-hand` unconditionally, so the viewer's "solve this clip" button
threw the operator's anchor away on every run without saying so.

Nothing about the result looked wrong. The chain still reported every frame carrying a camera and a
plausible focal range. What it actually did, measured on `CRO_MOR_194948` frame 0:

| the anchor was refitted from | worst line | markings | a verdict? |
|---|---|---|---|
| the seed's own default pose (what ran) | **24.17 px** | 2 | no |
| the operator's hand pose | 7.06 px | 10 | yes |
| the operator's hand pose, position free | **3.67 px** | 10 | yes |

and `camera_carry.json` came out carrying `anchors_hand_aligned: []`, with `rotation[0]`
bit-identical to the shipped default.
"""

from __future__ import annotations

import json
from pathlib import Path

#: Every key an anchor must carry to be usable as one. A partial entry is a bug upstream, not a
#: camera to fill in from defaults.
REQUIRED = ("focal_px", "rotation", "position")


def hand_anchors(run_dir: Path, seed_name: str, calib_dir: Path | None = None,
                 clip_id: str | None = None) -> tuple[dict, str | None]:
    """Hand-aligned anchors for `seed_name`, and the name of the file they came from.

    The run's own `camera_manual.json` wins, because that is what the viewer writes and what a
    human just looked at. `calib/<clip>-hand-aligned-*.json` is read only when that is empty, so
    the anchors recorded there for `fan` keep working.

    Returns `({}, None)` when there are none — which callers should say out loud rather than
    proceed quietly, since a missing anchor is invisible in the output.
    """
    manual = Path(run_dir) / "camera_manual.json"
    if manual.exists():
        found = _usable(json.loads(manual.read_text()).get(seed_name, {}))
        if found:
            return found, manual.name

    if calib_dir is not None and clip_id is not None:
        legacy = next(Path(calib_dir).glob(f"{clip_id}-hand-aligned-*.json"), None)
        if legacy is not None:
            found = _usable(json.loads(legacy.read_text()).get(seed_name, {}))
            if found:
                return found, legacy.name
    return {}, None


def _usable(edits: dict) -> dict:
    """Drop entries that are not a camera.

    The viewer writes complete entries, but the file is hand-editable and a half-written anchor
    would be worse than none: it would be used, silently, for the frame the whole chain hangs off.
    """
    return {k: v for k, v in edits.items()
            if isinstance(v, dict) and all(f in v for f in REQUIRED) and v["focal_px"] > 0}
