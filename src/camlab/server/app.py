"""The camlab HTTP surface.

Deliberately small and deliberately offline. Two rules it keeps from `poseannot`, both of which
were learned the expensive way there:

* **No CDN.** three.js is vendored under `static/vendor/` with its checksums (spec §7.3). The
  target box runs the container behind a link that resets every ~250 MB and is reached only over
  ssh; a page that fetches its renderer at load time is a page that does not open.
* **The browser never posts a matrix.** When editing arrives (M3) the client sends a gesture or a
  few scalars and the server derives the transform. A raw 3x3 from the client can express things
  that are not a camera, and then "one camera" stops being a guarantee and becomes a hope.

Run:

    uvicorn camlab.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from camlab import __version__
from camlab.core.pitch import pitch_polylines, pitch_upright_polylines
from camlab.core.units import FieldDimensions

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="camlab", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/pitch")
def pitch() -> dict:
    """The pitch, in world metres: Z-up, right-handed, origin on the centre spot.

    Regenerated from the Laws-of-the-Game constants in `core/pitch.py`, not stored in any run —
    the markings are the one thing in this project that is known exactly, and a solved camera is
    judged by whether it lands them on the paint.

    `markings` are on the plane and come back as (x, y). `uprights` — the two goal frames and the
    four corner flagposts — are the only geometry with height, which makes them the instrument for
    checking the focal: a wrong focal puts the crossbar in the right place on the ground and the
    wrong place in the air.

    Single-point "polylines" (the centre spot and the two penalty spots) are kept as length-1
    lists rather than dropped; the viewer draws them as dots.
    """
    dims = FieldDimensions()
    return {
        "dimensions": {"length": dims.length, "width": dims.width},
        "markings": [np.asarray(p, dtype=float).round(4).tolist() for p in pitch_polylines()],
        "uprights": [
            np.asarray(p, dtype=float).round(4).tolist() for p in pitch_upright_polylines()
        ],
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
