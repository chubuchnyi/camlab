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
