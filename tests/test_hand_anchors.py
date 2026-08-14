"""The operator's own aim has to reach the solver — and the solver has to pick the right one.

Two defects, one after the other, both in the same week.

**The aim never arrived.** Every hand edit went to the run's `camera_manual.json`; `solve_carry.py`
read `calib/<clip>-hand-aligned-*.json`; and `solve/pipeline.py` passed `--no-hand` unconditionally,
so the "solve this clip" button discarded the anchor on every press. On `CRO_MOR_194948` frame 0
that is 24.17 px on 2 markings against 3.67 px on 10.

**The repair preferred the run's file, and that was worse.** `fan`'s `camera_manual.json` is
almost entirely the viewer's "position applies to the whole clip" tick-box — 117 of its 120 entries
carry a broadcast position with the solve's own rotation and focal — so preferring it put
`--anchor 0` on a **31.55 px** anchor where the curated file holds **5.30**, and frame 51 on
**102.01 px** against **2.17**.

The first round of these tests passed both defects: they used synthetic frames that did not overlap
between the two stores, so no choice was ever forced. Every test below forces one.
"""

from __future__ import annotations

import json

from camlab.solve.hand import hand_candidates

AIM = {"focal_px": 4300.0, "rotation": [1.8, 0.0, 0.0], "position": [0.5, -78.0, 20.5]}
OTHER_AIM = {"focal_px": 3900.0, "rotation": [1.6, 0.1, 0.0], "position": [2.0, -70.0, 19.0]}

#: A solve for a three-frame clip, to compare manual entries against.
SEED = {
    "focal_px": [5000.0, 5001.0, 5002.0],
    "rotation": [[1.7, 0.0, 0.0], [1.71, 0.0, 0.0], [1.72, 0.0, 0.0]],
    "position": [[0.0, -80.0, 20.0], [0.0, -80.0, 20.0], [0.0, -80.0, 20.0]],
}


def _write(path, blob):
    path.write_text(json.dumps(blob))


def _clip_scoped(i, shared_position):
    """What the viewer writes to a frame the operator did NOT aim, when the position is applied to
    the whole clip: the shared position, and that frame's own rotation and focal from the solve."""
    return {"focal_px": SEED["focal_px"][i], "rotation": list(SEED["rotation"][i]),
            "position": list(shared_position)}


def test_a_clip_scoped_position_write_is_not_an_aim(tmp_path):
    """`fan` in one test. Frame 1 was never aimed — it only carries the broadcast position — and
    offering it as an anchor is how a 5.30 px anchor became 31.55."""
    _write(tmp_path / "camera_manual.json", {"c.json": {
        "0": AIM,                              # actually aimed: rotation differs from the solve
        "1": _clip_scoped(1, [9.0, -60.0, 25.0]),
        "2": _clip_scoped(2, [9.0, -60.0, 25.0]),
    }})
    got = hand_candidates(tmp_path, "c.json", seed_camera=SEED)
    assert sorted(got) == ["0"], f"broadcast entries offered as aims: {sorted(got)}"


def test_without_the_solve_a_broadcast_cannot_be_told_from_an_aim(tmp_path):
    """Stated so the caller knows why `seed_camera` matters. Keeping them is the flattering
    direction — a bad anchor gets offered — which is exactly why the solver passes the seed."""
    _write(tmp_path / "camera_manual.json", {"c.json": {"1": _clip_scoped(1, [9.0, -60.0, 25.0])}})
    assert sorted(hand_candidates(tmp_path, "c.json")) == ["1"]


def test_both_stores_offer_the_same_frame_and_neither_wins_here(tmp_path):
    """The defect the first round of tests could not see, because its two stores never named the
    same frame. Which store an anchor came from says nothing about whether it is any good, so this
    returns both and the caller scores them against the paint."""
    calib = tmp_path / "calib"
    calib.mkdir()
    _write(calib / "fan-hand-aligned-2026-08-11.json", {"c.json": {"0": OTHER_AIM}})
    _write(tmp_path / "camera_manual.json", {"c.json": {"0": AIM}})

    got = hand_candidates(tmp_path, "c.json", seed_camera=SEED,
                          calib_dir=calib, clip_id="fan")
    assert sorted(got) == ["0"]
    sources = [src for src, _e in got["0"]]
    assert set(sources) == {"camera_manual.json", "fan-hand-aligned-2026-08-11.json"}, sources
    assert len(got["0"]) == 2, "one store silently won; that is the defect this test exists for"


def test_the_fan_shape_end_to_end(tmp_path):
    """Exactly what `runs/fan` holds: a manual file that is a broadcast over every frame, and a
    curated file with the real anchors. Only the curated ones may be offered."""
    calib = tmp_path / "calib"
    calib.mkdir()
    _write(calib / "fan-hand-aligned-2026-08-11.json", {"c.json": {"0": AIM, "2": OTHER_AIM}})
    _write(tmp_path / "camera_manual.json", {"c.json": {
        str(i): _clip_scoped(i, [9.0, -60.0, 25.0]) for i in range(3)}})

    got = hand_candidates(tmp_path, "c.json", seed_camera=SEED, calib_dir=calib, clip_id="fan")
    assert sorted(got) == ["0", "2"]
    for frame in got:
        assert [src for src, _e in got[frame]] == ["fan-hand-aligned-2026-08-11.json"]


def test_only_the_seeds_own_key_is_read_and_the_rest_are_reported(tmp_path):
    """The limitation, and the thing that makes it survivable.

    The entries are absolute world poses, so an aim made against one solve WOULD be a good anchor
    for another, and reading every key was tried. It is not safe: the broadcast test needs the solve
    the entries overlay, and for chain outputs the next run overwrites that file. Two reference-free
    substitutes were measured and both are refuted in `solve/hand.py` — a shared position marks a
    static phone, not a broadcast, and the store's mtime is about its newest edit anywhere.

    So the read stays narrow and the silence does not: twelve aims sat under another key on
    `g11710897` while the clip was called unsolvable, and nothing connected the two.
    """
    from camlab.solve.hand import aims_under_other_keys

    _write(tmp_path / "camera_manual.json", {"camera_start.json": {"0": AIM}})
    assert hand_candidates(tmp_path, "camera_smooth.json", seed_camera=SEED) == {}
    assert aims_under_other_keys(tmp_path, "camera_smooth.json") == {"camera_start.json": ["0"]}
    assert aims_under_other_keys(tmp_path, "camera_start.json") == {}, "the read key is not unread"


def test_an_entry_that_matches_the_solve_exactly_is_not_an_aim(tmp_path):
    """`g11710897` reported three anchors under `camera_start.json` and every one was this: the
    seed's own pose written back, differing only in the focal the viewer rounds on write. Nobody
    moved anything, and `solve_carry` already scores the seed's pose at every anchor, so keeping
    these adds no candidate and three phantom anchors."""
    echo = {"focal_px": round(SEED["focal_px"][1]),            # 5001.0 -> the viewer's rounding
            "rotation": list(SEED["rotation"][1]),
            "position": list(SEED["position"][1])}
    _write(tmp_path / "camera_manual.json", {"c.json": {"0": AIM, "1": echo}})
    assert sorted(hand_candidates(tmp_path, "c.json", seed_camera=SEED)) == ["0"]


def test_a_real_aim_is_not_mistaken_for_an_echo(tmp_path):
    """The filter must not eat the thing it sits next to. A focal moved by more than the write
    rounding, everything else untouched, is an operator zooming — and on a plane the focal is the
    parameter that trades against distance, so it is exactly what someone would aim alone."""
    zoomed = {"focal_px": SEED["focal_px"][1] + 2.0,
              "rotation": list(SEED["rotation"][1]),
              "position": list(SEED["position"][1])}
    _write(tmp_path / "camera_manual.json", {"c.json": {"1": zoomed}})
    assert sorted(hand_candidates(tmp_path, "c.json", seed_camera=SEED)) == ["1"]


def test_a_static_camera_aimed_frame_by_frame_is_not_a_broadcast(tmp_path):
    """`g11710897`, and the reason the obvious shortcut is wrong.

    All twelve of its aims sit at exactly (56, 25, 1.5): a phone held in one spot, where only the
    rotation is aimed. That is the same shape a position broadcast has — one position over many
    frames — so "shared position means broadcast" would delete the entire pitch-level case. What
    separates them is the rotation, which here is the operator's and there is the solve's.
    """
    fixed = [56.0, 25.0, 1.5]
    aims = {str(i): {"focal_px": 2100.0, "rotation": [0.40 + 0.01 * i, 2.09, -1.87],
                     "position": list(fixed)} for i in range(3)}
    _write(tmp_path / "camera_manual.json", {"c.json": aims})
    got = hand_candidates(tmp_path, "c.json", seed_camera=SEED)
    assert sorted(got) == ["0", "1", "2"], "a static camera's aims were taken for a broadcast"


def test_a_half_written_anchor_is_not_used(tmp_path):
    """It would be used silently, for the one frame the whole chain hangs off."""
    _write(tmp_path / "camera_manual.json", {"c.json": {
        "0": {"focal_px": 4300.0, "position": [0, 0, 20]},                      # no rotation
        "1": {"focal_px": 0.0, "rotation": [0, 0, 0], "position": [0, 0, 20]},  # not a lens
        "2": OTHER_AIM,
    }})
    assert sorted(hand_candidates(tmp_path, "c.json", seed_camera=SEED)) == ["2"]


def test_no_edits_anywhere_is_an_empty_answer(tmp_path):
    assert hand_candidates(tmp_path, "camera_auto.json") == {}


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
    the first stage read."""
    from camlab.solve.pipeline import OUTPUTS, SEED_SNAPSHOT

    assert "camera_smooth.json" in OUTPUTS, "the chain's last output must be recognised as one"
    assert "camera_start.json" not in OUTPUTS, "the default seed is not something the chain writes"
    assert SEED_SNAPSHOT not in OUTPUTS, "the snapshot would be overwritten by the run it records"


def test_the_manual_file_is_written_atomically(tmp_path):
    """It holds the one thing that cannot be recomputed. A plain `write_text` from four routes plus
    a background solve thread left `runs/g15449383/camera_manual.json` holding a complete JSON
    object followed by a stray `}` — two writers interleaving. Recoverable that time."""
    import threading

    from camlab.server.app import _write_manual

    path = tmp_path / "camera_manual.json"
    big = {"c.json": {str(i): dict(AIM) for i in range(200)}}
    small = {"c.json": {"0": dict(AIM)}}

    def hammer(blob, n):
        for _ in range(n):
            _write_manual(path, blob)

    threads = [threading.Thread(target=hammer, args=(big, 40)),
               threading.Thread(target=hammer, args=(small, 40))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Whatever won, it must be one of the two whole documents and never a splice of both.
    got = json.loads(path.read_text())
    assert got in (big, small), "a reader saw half of one write and half of another"
    assert not list(tmp_path.glob(".camera_manual.*")), "a temp file was left behind"


def test_the_pipeline_anchors_on_every_aimed_frame_not_one():
    """`run` took a single `anchor` and passed `--anchor 0`, while solve_carry.py has always
    accepted a comma list and assigned each frame to its nearest anchor. An operator who aimed
    twelve frames of g11710897 had eleven thrown away on every press of the solve button, and the
    register's own finding — each added anchor halves the drift the chain accumulates — was
    unreachable from the viewer."""
    import inspect

    from camlab.solve import pipeline

    src = inspect.getsource(pipeline.run)
    assert '"--anchor", str(anchor)' not in src, "back to a single anchor"
    assert '",".join' in src, "the anchor list is not being passed as a list"
    assert "anchors_for" in src, "nothing looks up what the operator aimed"


def test_the_chain_hands_back_its_last_output_not_a_hardcoded_name():
    """`out["camera"]` was the literal "camera_smooth.json" while the chain gained a fifth stage
    after it. A viewer opening the named file would have shown the camera from two stages back and
    called it the result."""
    from camlab.solve.pipeline import FINAL_CAMERA, OUTPUTS, STAGES

    last = [extra for _l, _s, extra in STAGES if "--out" in extra][-1]
    assert FINAL_CAMERA == last[last.index("--out") + 1]
    assert FINAL_CAMERA in OUTPUTS


def test_the_hand_key_survives_the_seed_snapshot():
    """Two changes made the same day, and together they lost the operator's work.

    pipeline.run copies a seed it is about to overwrite to camera_seed_used.json and reads the copy.
    The edits stay keyed to the ORIGINAL name, so looking them up under the copy's finds none — and
    solve_carry then quietly refitted every anchor from the seed's own pose. On g11710897 the anchor
    LIST was right and the anchors themselves were gone, and the clip scored 3 markings where the
    operator's aim scores 7.
    """
    import inspect

    from camlab.solve import pipeline

    src = inspect.getsource(pipeline.run)
    assert "--hand-key" in src, "the hand key is not passed at all"
    assert "hand_key = requested_seed" in src, (
        "the snapshot branch does not preserve the name the edits are keyed to"
    )


# ---------------------------------------------------------------------------------------------
# Stale stage outputs. A killed run leaves the PREVIOUS run's later stages on disk.
# ---------------------------------------------------------------------------------------------

STUB = '''import json, os, sys
from pathlib import Path
a = sys.argv[1:]
out = a[a.index("--out") + 1]
root = Path(os.environ["CAMLAB_RUNS"])
(root / a[0] / out).write_text(json.dumps({"wrote_by": Path(sys.argv[0]).name}))
print("wrote " + out)
'''

CLIP = {"clip_id": "c", "source": "x.mp4", "source_sha256": "0", "width": 100, "height": 100,
        "fps": 25.0, "n_frames": 3, "first_frame": 0, "crop": None,
        "source_width": 100, "source_height": 100}


def _fake_run(tmp_path, monkeypatch, *, fail_at=None):
    """A run directory and a scripts directory of stubs, wired the way `run` expects them."""
    from camlab.solve import pipeline

    root = tmp_path / "runs"
    (root / "c").mkdir(parents=True)
    (root / "c" / "clip.json").write_text(json.dumps(CLIP))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for _label, script, _extra in pipeline.STAGES:
        body = 'import sys; sys.exit(1)' if script == fail_at else STUB
        (scripts / script).write_text(body)
    monkeypatch.setenv("CAMLAB_RUNS", str(root))
    monkeypatch.setattr(pipeline, "SCRIPTS", scripts)
    monkeypatch.setattr(pipeline, "REPO", tmp_path)
    return root / "c"


def test_a_previous_runs_outputs_do_not_survive_into_this_one(tmp_path, monkeypatch):
    """`g11710897`, exactly. A run carried at 21:50 to the operator's anchor and was then killed;
    `camera_smooth.json` — the file FINAL_CAMERA names — was still the 15:37 file from the run
    before, at a focal 32 % out that scores three markings instead of seven. The directory read as a
    completed chain, and every conclusion drawn from it was about a camera three fixes out of date.
    """
    from camlab.solve.pipeline import FINAL_CAMERA, run

    clip_dir = _fake_run(tmp_path, monkeypatch)
    stale = clip_dir / FINAL_CAMERA
    stale.write_text(json.dumps({"focal_px": [2777.0] * 3, "wrote_by": "a run three fixes ago"}))

    got = run("c", anchor=0)

    assert got["ok"], got["stages"]
    assert json.loads(stale.read_text())["wrote_by"] != "a run three fixes ago"
    assert FINAL_CAMERA in got.get("cleared", []), "the removal was not reported to the caller"


def test_a_chain_that_dies_early_leaves_no_later_stage_behind(tmp_path, monkeypatch):
    """The failure that actually happened: the chain stops after `carry` and the previous run's
    `camera_smooth.json` is still sitting there. Absent is honest; stale is not, because every
    reader downstream takes FINAL_CAMERA on trust."""
    from camlab.solve.pipeline import FINAL_CAMERA, run

    clip_dir = _fake_run(tmp_path, monkeypatch, fail_at="solve_selfheal.py")
    (clip_dir / FINAL_CAMERA).write_text(json.dumps({"wrote_by": "the run before"}))

    got = run("c", anchor=0)

    assert not got["ok"], "the stub was supposed to fail at self-heal"
    assert (clip_dir / "camera_carry.json").exists(), "the stage that DID run must keep its output"
    assert not (clip_dir / FINAL_CAMERA).exists(), (
        "a stale final camera outlived the run that was supposed to replace it"
    )
