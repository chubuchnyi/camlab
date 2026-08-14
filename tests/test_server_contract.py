"""What the browser is promised, and the offline guarantee that lets it open at all."""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pytest
from fastapi.testclient import TestClient

from camlab.runs import runs_root
from camlab.server.app import STATIC, app

#: These go through the server at real run data — an ingested clip with frames, a
#: camera and a manual layer. `runs/` is not committed (it is measurements, not source),
#: so in a fresh checkout, which is what CI is, there is nothing for them to run against.
#: They used to FAIL there rather than skip: 4 failed, 135 passed on an empty runs dir.
#: Skipping is honest; a green CI here does not mean these were exercised.
needs_fan = pytest.mark.skipif(not (runs_root() / "fan").exists(),
                              reason="needs the ingested `fan` run; runs/ is not committed")

client = TestClient(app)


def test_the_page_never_reaches_the_network():
    """No CDN, anywhere in the served front end.

    The box runs this container behind a link that resets every ~250 MB and is reached only over
    ssh (spec §7.5). pitch3d's viewer import-maps three.js off jsdelivr, so it simply does not
    open without internet — that is the defect this repo does not inherit, and a test is the only
    thing that keeps it from creeping back in one `<script src=…>` at a time.
    """
    # The SVG namespace is an XML IDENTIFIER, not an address: createElementNS never fetches it,
    # and a page using it works with the network unplugged. Allowed by exact string, not by a
    # pattern — "anything on w3.org" would also allow a stylesheet, which would be a real fetch.
    ALLOWED = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xhtml"}
    offenders = []
    for f in STATIC.rglob("*"):
        if f.suffix.lower() not in {".html", ".js", ".css"} or "vendor" in f.parts:
            continue
        for m in re.finditer(r"https?://[^\s\"'()]+", f.read_text(encoding="utf-8")):
            if m.group(0) in ALLOWED:
                continue
            offenders.append(f"{f.relative_to(STATIC)}: {m.group(0)}")
    assert not offenders, "front end reaches the network:\n" + "\n".join(offenders)


def test_the_vendored_renderer_is_the_one_we_pinned():
    """Checksums, not just presence: a silently swapped three.js is a silently changed viewer."""
    sums = STATIC / "vendor" / "SHA256SUMS"
    assert sums.exists(), "vendor/SHA256SUMS is missing — the pin is the point"
    for line in sums.read_text().split("\n"):
        if not line.strip():
            continue
        want, name = line.split()
        got = hashlib.sha256((STATIC / "vendor" / name).read_bytes()).hexdigest()
        assert got == want, f"{name} is not the vendored build"


def test_the_vendored_patches_are_still_applied():
    """The half a checksum cannot do.

    `SHA256SUMS` fails when a vendored file changes unexpectedly. It passes happily when a
    re-vendor **removes** a change we made on purpose — the sum gets updated as part of the
    re-vendor and nothing says the behaviour went with it. Each patch in `vendor/PATCHES.md` is
    asserted here by the thing it exists to provide.
    """
    vendor = STATIC / "vendor"
    assert (vendor / "PATCHES.md").exists(), "vendor/PATCHES.md is what says these are deliberate"

    tc = (vendor / "TransformControls.js").read_text(encoding="utf-8")
    assert "defineProperty( 'rotationSpeed', 1 )" in tc, (
        "the rotationSpeed knob is gone from TransformControls.js — upstream has no way to slow "
        "a rotation drag, only rotationSnap, and aiming at 70 m needs a tenth of a degree"
    )
    assert "this.rotationSpeed * 20" in tc, "rotationSpeed is defined but no longer multiplies in"
    view = (STATIC / "pitch_view.js").read_text(encoding="utf-8")
    assert "gizmo.rotationSpeed" in view, "nothing sets it, so the patch buys nothing"


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_pitch_is_the_laws_of_the_game_in_metres():
    """The markings are the one thing known exactly, so they are asserted against the Laws.

    A solved camera is judged by whether it lands these on the paint — if the pitch itself drifts,
    every calibration number in this repo silently moves with it.
    """
    d = client.get("/api/pitch").json()
    assert d["dimensions"] == {"length": 105.0, "width": 68.0}

    flat = np.concatenate([np.asarray(p, float) for p in d["markings"]])
    assert flat.shape[1] == 2, "markings are on the plane; height lives in `uprights`"
    assert flat[:, 0].min() == -52.5 and flat[:, 0].max() == 52.5   # touchline to touchline
    assert flat[:, 1].min() == -34.0 and flat[:, 1].max() == 34.0   # goal line to goal line

    spots = [p for p in d["markings"] if len(p) == 1]
    assert len(spots) == 3, "centre spot + two penalty spots, kept rather than dropped"
    assert [0.0, 0.0] in [s[0] for s in spots], "origin is the centre spot"

    up = [np.asarray(p, float) for p in d["uprights"]]
    assert len(up) == 6, "two goal frames + four corner flagposts"
    assert max(float(a[:, 2].max()) for a in up) == 2.44, "goal crossbar height, Law 1"
    assert min(float(a[:, 2].min()) for a in up) == 0.0


def test_the_residual_endpoint_is_actually_reachable():
    """A regression test for a deploy, not for a function.

    The image once shipped without the `[cv]` extra: it started, served the viewer, and returned
    500 from the one endpoint that answers "is this camera right?". Everything looked fine until
    someone asked the question. If cv2 is missing here, this fails at import and says so.
    """
    import importlib.util

    assert importlib.util.find_spec("cv2") is not None, (
        "opencv is missing — install with the `[cv]` extra. camlab's ground truth is the paint in "
        "the frame, and finding it is a cv2 pipeline."
    )


def test_the_whole_clip_checkbox_is_wired_to_something():
    """It was not, and a human found out by ticking it and watching nothing happen.

    `pushManual()` ran only from an edit field's `onchange`, so "position applies to the whole clip"
    armed a mode that took effect on the next keystroke in a coordinate — which is indistinguishable
    from a dead control. The server side was correct the whole time, which is why this is a page
    test: the bug was that nothing ever called the working endpoint.
    """
    page = (STATIC / "index.html").read_text()
    assert 'id="e-clip"' in page
    assert re.search(r'\$\("e-clip"\)\.onchange\s*=', page), (
        "ticking the box must do something by itself, not arm a mode for a later keystroke"
    )


@needs_fan
def test_a_clip_scoped_edit_moves_every_frame_and_keeps_their_own_aim():
    """Position is shared across a clip; orientation and focal are not.

    Copying one frame's aim to all of them would be a different camera, not an edit — the operator
    panned. So a clip-scoped write must set one position everywhere and leave each frame's own
    rotation and focal alone.
    """
    import json

    from camlab.runs import ClipInfo

    info = ClipInfo.load("fan")
    path = info.dir / "camera_manual.json"
    before = path.read_text() if path.exists() else None
    try:
        c = TestClient(app)
        cur = c.get("/api/run/fan/manual/28?which=camera_auto.json").json()
        body = {"which": "camera_auto.json", "scope": "clip",
                **{k: cur[k] for k in ("x", "y", "z", "yaw", "elev", "roll", "focal_px")}}
        r = c.post("/api/run/fan/manual/28", json=body)
        assert r.status_code == 200 and r.json()["scope"] == "clip"

        edits = json.loads(path.read_text())["camera_auto.json"]
        n_frames = len(c.get("/api/run/fan/camera").json()["frames"])
        assert len(edits) == n_frames, "clip scope means every frame, not just this one"

        pos = [e["position"] for e in edits.values()]
        assert all(p == pos[0] for p in pos), "one position for the whole clip"

        focals = {round(e["focal_px"]) for e in edits.values()}
        assert len(focals) > 1, "each frame keeps its own focal — the operator zoomed"
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before)


def test_the_copy_from_frame_control_is_wired_and_cannot_go_clip_wide():
    """Copying a neighbour is how a lost frame gets fixed quickly; it must stay one frame.

    "Copy frame 70 onto frame 66" is an instruction about one frame. Honouring the clip-wide
    checkbox while doing it would write 120 positions, which is exactly how a hand-aligned frame
    was destroyed once already.
    """
    page = (STATIC / "index.html").read_text()
    assert 'id="e-copyfrom"' in page and 'id="e-copy"' in page
    handler = re.search(r'\$\("e-copy"\)\.onclick[\s\S]*?\n\};', page)
    assert handler, "the copy button must have a handler, not just markup"
    body = handler.group(0)
    assert 'e-clip"' in body and "checked = false" in body, (
        "the copy must clear the clip-wide box for the write and put it back"
    )
    assert "nFrames" in body, "and it must reject a frame number outside the clip"




@needs_fan
def test_the_upload_route_rejects_what_is_not_a_video():
    """The upload exists so a clip nobody has tuned anything for can be tried.

    It hands what arrives to ffmpeg and executes nothing, but the extension check is still the
    cheap first gate, and a route that accepts anything and fails deep inside a decoder reports
    the wrong thing to the person who used it.
    """
    c = TestClient(app)
    r = c.post("/api/upload", files={"video": ("notes.txt", b"not a video", "text/plain")},
               data={"clip_id": "should_not_exist"})
    assert r.status_code == 400 and "expected one of" in r.json()["detail"]

    from camlab.runs import list_runs
    r = c.post("/api/upload", files={"video": ("x.mp4", b"\x00" * 32, "video/mp4")},
               data={"clip_id": sorted(list_runs())[0]})
    assert r.status_code == 409, "an existing clip must not be silently overwritten"


def test_the_page_lists_unsolved_clips_instead_of_hiding_them():
    """An uploaded clip has no camera yet. That is the open problem, not a reason to hide it."""
    page = (STATIC / "index.html").read_text()
    assert 'id="u-file"' in page and 'id="u-go"' in page
    assert "async function listClips" in page
    assert "no camera" in page, "an unsolved clip must be listed and labelled"
    assert re.search(r'listClips\([^)]*\)', page), "the clip selector must go through listClips"


def test_a_clip_counts_as_solved_when_it_has_any_camera():
    """It used to check for `camera_auto.json` by name.

    broadcast has four cameras — known, carry, healed, fixed — and not one of them is called auto,
    so it reported itself unsolved and the page refused to open the better-solved of the two clips
    in the repo.
    """
    c = TestClient(app)
    runs = {r["clip_id"]: r for r in c.get("/api/runs").json()}
    for cid, r in runs.items():
        from camlab.runs import ClipInfo
        has = bool(list(ClipInfo.load(cid).dir.glob("camera_*.json")))
        assert r["solved"] == has, f"{cid}: solved={r['solved']} but cameras present={has}"


@needs_fan
def test_the_flip_turns_every_frame_and_leaves_the_solve_alone():
    """The pitch is exactly symmetric under a half-turn, so this is the one question about the
    camera that no measurement can answer and a person can. It must therefore be one click, apply
    to the whole clip — the answer cannot differ between frames — and be undoable like any edit."""
    from camlab.runs import ClipInfo

    info = ClipInfo.load("fan")
    path = info.dir / "camera_manual.json"
    before = path.read_text() if path.exists() else None
    try:
        c = TestClient(app)
        base = c.get("/api/run/fan/camera?which=camera_auto.json").json()
        r = c.post("/api/run/fan/flip?which=camera_auto.json")
        assert r.status_code == 200
        assert r.json()["flipped_frames"] == len(base["frames"])

        after = c.get("/api/run/fan/camera?which=camera_auto.json").json()
        for i in (0, 5, len(base["frames"]) - 1):
            bx, by, bz = base["position"][i]
            ax, ay, az = after["position"][i]
            assert (ax, ay, az) == pytest.approx((-bx, -by, bz)), f"frame {i} not mirrored"
            assert after["focal_px"][i] == pytest.approx(base["focal_px"][i]), "focal must not move"

        page = (STATIC / "index.html").read_text()
        assert 'id="e-flip"' in page and re.search(r'\$\("e-flip"\)\.onclick', page)
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before)


def test_an_uploaded_clip_arrives_with_a_camera_and_a_way_to_solve_it():
    """Upload used to stop one step short of useful.

    The frames decoded, the clip appeared in the list, and there was no camera — so it could not be
    opened, the edit fields had nothing to show, and the only way to a solve was a shell. A clip
    now arrives with a labelled default and a button that runs the whole chain.
    """
    page = (STATIC / "index.html").read_text()
    assert 'id="s-go"' in page and 'id="s-anchor"' in page
    assert re.search(r'\$\("s-go"\)\.onclick', page), "the solve button needs a handler"
    assert "setInterval" in page, (
        "the solve takes minutes, so the page must poll rather than hold a request open"
    )

    from camlab.server.app import write_start_camera
    assert callable(write_start_camera)

    c = TestClient(app)
    r = c.get("/api/run/fan/solve")
    assert r.status_code == 200 and "state" in r.json(), "status must answer before any solve runs"


@needs_fan
def test_the_default_camera_is_labelled_as_a_guess():
    """It is a guess and every consumer has to be able to tell. A default that reads like a solve
    is how an unmeasured number ends up quoted as a result."""
    import json

    from camlab.runs import ClipInfo

    for cid in ("fan",):
        p = ClipInfo.load(cid).dir / "camera_start.json"
        if not p.exists():
            continue
        d = json.loads(p.read_text())
        assert d.get("is_default") is True
        assert d["model"] == "hand_start_default"


def test_the_image_ships_the_scripts_the_server_runs():
    """The server runs the solve stages as subprocesses, so they have to be IN the image.

    They were not: the first end-to-end solve from the browser failed with "can't open file
    '/app/scripts/solve_carry.py'". The container had the library and not the thing that drives it,
    and nothing local could have caught that — the scripts are right there on a dev box.
    """
    from camlab.solve.pipeline import SCRIPTS, STAGES

    docker = (SCRIPTS.parent / "docker" / "Dockerfile").read_text()
    assert "COPY scripts/" in docker, "the image must carry the scripts the server shells out to"
    for _label, script, _extra in STAGES:
        assert (SCRIPTS / script).exists(), f"{script} is named by the pipeline and missing"


def test_nothing_in_window_b_changes_height_when_the_numbers_change():
    """The photograph jumped on every scrub, and this is why.

    `#bstage` sits in a flex column with `margin: auto 0`, so it re-centres in whatever height the
    rows below leave it. The readouts used to live in `#btools`, which wraps: a full readout made
    the toolbar three lines and an empty one made it one. Both rows are now fixed height with no
    wrap, and anything too long scrolls sideways rather than pushing the picture around.
    """
    css = (STATIC / "style.css").read_text()
    page = (STATIC / "index.html").read_text()

    assert 'id="breadout"' in page, "the numbers need their own row"
    tools = re.search(r"#btools \{[^}]*\}", css).group(0)
    assert "flex-wrap: nowrap" in tools, "the toolbar must not wrap"
    assert re.search(r"height:\s*\d+px", tools), "and must have a fixed height"
    readout = re.search(r"#breadout \{[^}]*\}", css).group(0)
    assert re.search(r"height:\s*\d+px", readout), "so must the readout row"
    assert "nowrap" in readout


def test_the_panes_can_be_resized():
    """A fixed 34vw for the photograph was a guess, and which pane needs the space depends on what
    is being looked at."""
    page = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()
    assert 'id="split-b"' in page and 'id="split-p"' in page
    assert "onpointerdown" in page, "the dividers need a drag handler"
    assert "setProperty" in page, "which writes the width back to the CSS variable that owns it"
    assert 'new Event("resize")' in page, "and tells the renderer to re-read its container"
    assert ".split" in css and "col-resize" in css


def test_the_scrubber_does_not_colour_frames_by_a_stale_flag():
    """`degenerate` belongs to the ORIGINAL per-frame solve, and every camera since copies the list
    through from its seed. A frame flagged there stayed pink for the rest of the pipeline's life,
    including after the chain had brought it to 2 px — a strip reporting a property of a solve
    nobody is looking at."""
    page = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()
    build = re.search(r"function buildStrip[\s\S]*?\n\}", page).group(0)
    assert "cam.degenerate" not in build, "the strip must not colour by the seed's degenerate flag"
    assert "#strip i.bad" not in css, "and the colour it used must be gone with it"


def test_the_camera_can_be_dragged_and_it_writes_through_the_normal_edit_path():
    """The last piece of #7. Two things it must not do.

    It must not attach the gizmo to the camera BODY: `drawCamera` clears and rebuilds that on every
    frame, and three.js does not complain when a gizmo ends up attached to a deleted object — it
    just stops working. And it must not invent a second write path: a drag goes through the same
    manual endpoint a typed number does, or the two eventually disagree about what the camera is.
    """
    view = (STATIC / "pitch_view.js").read_text()
    page = (STATIC / "index.html").read_text()

    assert "TransformControls" in view and "dragProxy" in view
    assert "gizmo.attach(dragProxy)" in view, "attach to the proxy, never to the rebuilt body"
    assert "getHelper()" in view, (
        "three r170's TransformControls is a Controls, not an Object3D; adding it to the scene is "
        "a silent no-op"
    )
    assert "dragging-changed" in view and "orbit.enabled" in view, (
        "orbit and drag both claim the pointer and must not both act"
    )

    assert 'id="e-drag"' in page and "setDragMode" in page
    drag = re.search(r"onDragEnd:[\s\S]*?\},", page).group(0)
    assert "pushManual()" in drag, "a drag must be written by the same path a typed number is"


def test_the_camera_can_be_turned_and_nudged_without_ever_posting_a_matrix():
    """Rotation is allowed; posting a matrix is not.

    The objection to a rotate gizmo was that a hand could produce something that is not a rotation.
    A quaternion IS one — the risk was only in sending a raw 3x3, which the server has refused
    since the start. So the gizmo derives the three ANGLES the server speaks and sends those, with
    roll read in the level basis rather than as `right.z`, which is the roll only when the camera
    is already level. Verified against the server to 1e-16 degrees on six frames.
    """
    view = (STATIC / "pitch_view.js").read_text()
    page = (STATIC / "index.html").read_text()

    st = re.search(r"function proxyState\(\)[\s\S]*?\n  \}", view).group(0)
    assert "crossVectors" in st and "atan2" in st, "roll must be read in the level basis"
    assert "matrix" not in st.lower(), "the browser sends scalars, never a transform"
    assert 'id="e-mode"' in page and 'value="rotate"' in page

    # The arrows scrub frames normally, so the mode has to take them and say where scrubbing went.
    assert "NUDGE" in page and "function nudge" in page
    assert "pushManual()" in re.search(r"function nudge[\s\S]*?\n\}", page).group(0), (
        "a keyboard nudge is the same edit as a typed number"
    )
    assert 'id="e-keys"' in page, "a mode that repurposes the arrow keys must say so on screen"
    assert "adjusting()) return;" in page, "and the frame stepper must yield while it is on"


def test_a_clip_opens_on_a_camera_it_actually_has():
    """`broadcast` has never had a `camera_auto.json` — its cameras are known, carry, healed,
    fixed, smooth — and both the API default and the page's fallback asked for that name, so
    selecting the clip 404'd and the viewer showed nothing."""
    from camlab.runs import ClipInfo, list_runs

    c = TestClient(app)
    for cid in list_runs():
        have = {p.name for p in ClipInfo.load(cid).dir.glob("camera_*.json")
                if "manual" not in p.name}
        if not have:
            continue
        r = c.get(f"/api/run/{cid}/camera")
        assert r.status_code == 200, f"{cid} does not open without an explicit camera"
        assert r.json()["which"] in have, f"{cid} opened on a camera it does not have"

    page = (STATIC / "index.html").read_text()
    assert 'camera_auto.json"' not in re.search(r"function camWhich[\s\S]*?\}", page).group(0), (
        "no hardcoded camera name in the page's fallback"
    )


def test_the_camera_list_is_rebuilt_per_clip_not_per_count():
    """It rebuilt only when the NUMBER of cameras changed, so two clips with the same count would
    leave the previous one's names in the list — and picking one asks a clip for a file it has
    not got."""
    page = (STATIC / "index.html").read_text()
    assert "camsel\").dataset.of" in page, "the list must be keyed on the camera NAMES"
    assert "options.length !== cam.available.length" not in page


def test_long_jobs_show_progress_and_lock_the_controls():
    """A long job leaves the page looking idle otherwise, and every control it does not own is a
    way to start a second job on top of the first — uploading while a solve runs would have both
    writing camera files for the same clip."""
    page = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()

    assert 'id="busy"' in page and "function setBusy" in page
    assert "LOCKABLE" in page and "el.disabled = busy" in page
    for owned in ("u-go", "s-go", "clip", "camsel", "scrub"):
        assert f'"{owned}"' in re.search(r"const LOCKABLE = \[[\s\S]*?\];", page).group(0), (
            f"{owned} can start or disturb a job and must be locked"
        )
    assert "indeterminate" in page and "indeterminate" in css, (
        "an upload cannot report a fraction, so the bar must be able to say 'working' without one"
    )
    assert ":disabled" in css, "a locked page must look locked, not frozen"


def test_the_panel_is_tabbed_and_nothing_was_lost_in_the_move():
    """Eight sections in one column put the camera numbers — the thing being worked on — below the
    fold behind the layer toggles. Three tabs now, and this asserts every control survived: a
    restructure that silently drops a checkbox is a feature that quietly stops existing."""
    page = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()

    tabs = re.findall(r'data-tab="([a-z-]+)"', page)
    assert set(tabs) == {"t-camera", "t-clip", "t-view"}
    for pane in ("t-camera", "t-clip", "t-view"):
        assert f'id="{pane}"' in page, f"{pane} has a button but no pane"

    # Every control the app depends on, wherever it now lives.
    for cid in ("clip", "camsel", "u-file", "u-go", "s-go", "s-anchor",
                "L-turf", "L-markings", "L-goals", "L-camera", "L-trajectory", "L-frameplane",
                "planeauto", "planed", "e-x", "e-y", "e-z", "e-yaw", "e-elev", "e-roll", "e-focal",
                "e-clip", "e-copy", "e-copyfrom", "e-flip", "e-reset", "e-resetall",
                "e-drag", "e-mode", "e-keys", "c-resid", "c-residspot", "c-flag",
                "solveinfo", "reset", "busy"):
        assert f'id="{cid}"' in page, f"{cid} did not survive the restructure"

    assert "localStorage" in page, "the open tab must survive a reload"
    assert ".tab-pane { overflow-y: auto" in css, (
        "each pane scrolls on its own, or a long one pushes the tab strip out of reach"
    )


def test_write_camera_refuses_a_camera_that_is_not_one():
    """`runs/fan/camera_ptz.json` holds fourteen frames with a focal of 0.0. That is not a
    degenerate camera, it is not a camera, and the function that wrote it validated nothing —
    found by a reviewer reading the files rather than the code."""
    import numpy as np
    import pytest as _pytest

    from camlab.camera_file import write_camera

    n = 3
    kw = dict(model="t", clip_id="nosuchclip", width=100, height=100,
              frames=np.arange(n), position=np.zeros((n, 3)), rotation=np.zeros((n, 3)))
    tmp = STATIC.parent / "_probe_camera.json"
    try:
        with _pytest.raises(ValueError, match="not a camera"):
            write_camera(tmp, focal_px=np.array([1000.0, 0.0, 1000.0]), **kw)
        with _pytest.raises(ValueError, match="NaN or inf"):
            write_camera(tmp, focal_px=np.array([1000.0, np.nan, 1000.0]), **kw)

        # A bound that the data reaches is a finding, and it is counted rather than left to notice.
        write_camera(tmp, focal_px=np.array([300.0, 1000.0, 20000.0]), **kw)
        import json
        assert json.loads(tmp.read_text())["focal_at_bound"] == 2
    finally:
        tmp.unlink(missing_ok=True)


def test_the_pipeline_finds_its_scripts_without_counting_parent_directories():
    """`parents[3]` holds only for the src layout; from site-packages it is /usr/lib/python3.12.
    The same defect already cost a session as a container built without scripts/."""
    from camlab.solve.pipeline import SCRIPTS, _find_scripts

    assert (SCRIPTS / "solve_carry.py").exists()
    import os
    old = os.environ.get("CAMLAB_SCRIPTS")
    try:
        os.environ["CAMLAB_SCRIPTS"] = "/nowhere-at-all"
        assert str(_find_scripts()) == "/nowhere-at-all", "an explicit override must win"
    finally:
        if old is None:
            os.environ.pop("CAMLAB_SCRIPTS", None)
        else:
            os.environ["CAMLAB_SCRIPTS"] = old


def test_refine_refuses_a_frame_with_no_camera_rather_than_fitting_noise():
    """The auto-fit button is a REFINEMENT of an aim, not a solver. Handed a frame the solve could
    not use — `focal_px == 0`, kept and marked rather than dropped (R-6) — it has nothing to start
    from, and starting from a default would silently answer a question nobody asked."""
    runs = [r["clip_id"] for r in client.get("/api/runs").json()]
    if not runs:
        pytest.skip("no ingested clip in this checkout")
    clip = runs[0]
    cam = client.get(f"/api/run/{clip}/camera").json()
    dead = [i for i, f in enumerate(cam["focal_px"]) if not f > 0]
    if not dead:
        pytest.skip(f"{clip} has no frame without a camera")
    r = client.post(f"/api/run/{clip}/refine/{dead[0]}", json={"which": cam["which"]})
    assert r.status_code == 400
    assert "aim one first" in r.json()["detail"]


def test_refine_is_out_of_range_safe():
    runs = [r["clip_id"] for r in client.get("/api/runs").json()]
    if not runs:
        pytest.skip("no ingested clip in this checkout")
    clip = runs[0]
    cam = client.get(f"/api/run/{clip}/camera").json()
    past_end = len(cam["frames"]) + 5
    r = client.post(f"/api/run/{clip}/refine/{past_end}", json={"which": cam["which"]})
    assert r.status_code == 404
