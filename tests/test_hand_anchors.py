"""The operator's own aim has to reach the solver.

It did not, for as long as the viewer has had an edit panel. Every hand edit went to the run's
`camera_manual.json`; `solve_carry.py` read `calib/<clip>-hand-aligned-*.json`; and
`solve/pipeline.py` passed `--no-hand` unconditionally, so the "solve this clip" button discarded
the anchor on every run. Nothing in the output said so — the chain still reported every frame
carrying a camera and a plausible focal range.

Measured on `CRO_MOR_194948` frame 0: refitting the anchor from the seed's default pose gives
**24.17 px on 2 markings**, from the operator's pose **3.67 px on 10**.
"""

from __future__ import annotations

import json

from camlab.solve.hand import hand_anchors

ANCHOR = {"focal_px": 4300.0, "rotation": [1.8, 0.0, 0.0], "position": [0.5, -78.0, 20.5]}


def _write(path, blob):
    path.write_text(json.dumps(blob))


def test_the_viewers_own_file_is_what_the_solver_reads(tmp_path):
    _write(tmp_path / "camera_manual.json", {"camera_smooth.json": {"0": ANCHOR}})
    hand, where = hand_anchors(tmp_path, "camera_smooth.json")
    assert list(hand) == ["0"]
    assert where == "camera_manual.json"


def test_edits_are_keyed_by_the_solve_they_overlay(tmp_path):
    """An anchor aimed against one solve is not an anchor for another: same frame, different
    camera underneath, and the seven numbers mean different things."""
    _write(tmp_path / "camera_manual.json", {"camera_start.json": {"0": ANCHOR}})
    assert hand_anchors(tmp_path, "camera_smooth.json") == ({}, None)


def test_the_legacy_calib_store_still_works_when_the_run_has_no_edits(tmp_path):
    calib = tmp_path / "calib"
    calib.mkdir()
    _write(calib / "fan-hand-aligned-2026-08-11.json", {"camera_auto.json": {"8": ANCHOR}})
    hand, where = hand_anchors(tmp_path, "camera_auto.json", calib_dir=calib, clip_id="fan")
    assert list(hand) == ["8"]
    assert where == "fan-hand-aligned-2026-08-11.json"


def test_the_run_wins_over_the_legacy_store(tmp_path):
    """Two stores is how the defect happened. When both hold something, the one the human just
    looked at is the one that counts."""
    calib = tmp_path / "calib"
    calib.mkdir()
    _write(calib / "fan-hand-aligned-2026-08-11.json",
           {"camera_auto.json": {"8": dict(ANCHOR, focal_px=9999.0)}})
    _write(tmp_path / "camera_manual.json", {"camera_auto.json": {"0": ANCHOR}})
    hand, where = hand_anchors(tmp_path, "camera_auto.json", calib_dir=calib, clip_id="fan")
    assert list(hand) == ["0"]
    assert where == "camera_manual.json"


def test_a_half_written_anchor_is_not_used(tmp_path):
    """It would be used silently, for the one frame the whole chain hangs off."""
    _write(tmp_path / "camera_manual.json", {"c.json": {
        "0": {"focal_px": 4300.0, "position": [0, 0, 20]},                      # no rotation
        "1": {"focal_px": 0.0, "rotation": [0, 0, 0], "position": [0, 0, 20]},  # not a lens
        "2": ANCHOR,
    }})
    hand, _ = hand_anchors(tmp_path, "c.json")
    assert list(hand) == ["2"]


def test_no_edits_anywhere_is_reported_as_none_not_as_an_empty_success(tmp_path):
    assert hand_anchors(tmp_path, "camera_auto.json") == ({}, None)


def test_the_pipeline_does_not_force_the_anchor_away():
    """The single line that made all of the above moot: `--no-hand` was hardcoded into the stage
    the viewer's solve button runs."""
    from camlab.solve.pipeline import STAGES

    carry = [s for s in STAGES if s[0] == "carry"]
    assert carry, "the carry stage vanished; this test is checking the wrong thing"
    assert "--no-hand" not in carry[0][2], (
        "--no-hand is back in the pipeline: the viewer's solve button is discarding the "
        "operator's own anchor on every run"
    )


def test_the_chain_knows_which_files_it_overwrites():
    """The viewer sends whichever camera is selected as the seed, and four of the names it can send
    are files this chain writes. Seeding from `camera_smooth.json` had the last stage overwrite what
    the first stage read — a second press compounds on the first with no way back, and the manual
    layer, which is keyed by file name, ends up over a different solve than it was aimed against."""
    from camlab.solve.pipeline import OUTPUTS, SEED_SNAPSHOT

    assert "camera_smooth.json" in OUTPUTS, "the chain's last output must be recognised as one"
    assert "camera_start.json" not in OUTPUTS, "the default seed is not something the chain writes"
    assert SEED_SNAPSHOT not in OUTPUTS, "the snapshot would be overwritten by the run it records"
