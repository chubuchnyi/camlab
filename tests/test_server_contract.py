"""What the browser is promised, and the offline guarantee that lets it open at all."""

from __future__ import annotations

import hashlib
import re

import numpy as np
from fastapi.testclient import TestClient

from camlab.server.app import STATIC, app

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
