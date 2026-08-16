"""Does the faster paint stage return the same evidence as the shipped one?

Not "does it look right" and not "do the tests pass" — the same arrays, on real frames, on every
clip in `runs/`. The two implementations are imported side by side out of two working trees, so
this compares running code against running code rather than a rewrite against its own docstring.

What is checked, per frame:

* the **centreline** — `argwhere(dist == 0)`, which is what `frame_evidence` keeps and the k-d tree
  is built over. This is the evidence. Anything else is bookkeeping.
* the **distance map** itself, which `residual._across_on_normal` walks along each marking's normal.
* the **surface** mask, which decides what is on the pitch.
* the **turf** mask and the **thresholded ridge**, so a disagreement can be located rather than
  just reported.

    python scripts/check_paint_equivalence.py --old /home/chubuchnyi/camlab --frames 3
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"


def load_old(root: Path):
    """`camlab.measure.paint` from another working tree, under a name of its own."""
    pkg_root = root / "src"
    saved = list(sys.path)
    sys.path.insert(0, str(pkg_root))
    for name in [m for m in sys.modules if m.startswith("camlab")]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "oldpaint", pkg_root / "camlab" / "measure" / "paint.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oldpaint"] = mod
    spec.loader.exec_module(mod)
    sys.path[:] = saved
    for name in [m for m in sys.modules if m.startswith("camlab")]:
        del sys.modules[name]
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="/home/chubuchnyi/camlab",
                    help="working tree holding the implementation to compare against")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--clips", nargs="*", default=None)
    ap.add_argument("--scales", default=None, help="CAMLAB_RIDGE_SCALES for both sides")
    args = ap.parse_args()

    if args.scales:
        import os
        os.environ["CAMLAB_RIDGE_SCALES"] = args.scales

    old = load_old(Path(args.old))
    from camlab.measure import paint as new  # noqa: E402

    assert tuple(old.RIDGE_SCALES) == tuple(new.RIDGE_SCALES), \
        f"the two trees disagree on the scales: {old.RIDGE_SCALES} vs {new.RIDGE_SCALES}"
    print(f"old {Path(args.old)}   scales {new.RIDGE_SCALES}")

    clips = args.clips or sorted(p.name for p in RUNS.iterdir()
                                 if (p / "frames").is_dir() and any((p / "frames").glob("*.jpg")))
    bad = 0
    for clip in clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        step = max(1, len(frames) // args.frames)
        rows = []
        for path in frames[::step][:args.frames]:
            bgr = cv2.imread(str(path))
            hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

            t_old = np.asarray(old._turf(hsv)) > 0
            t_new = np.asarray(new._turf(hsv)) > 0
            r_old, v_old, s_old = old.ridge_map(bgr)
            r_new, v_new, s_new = new.ridge_map(bgr)
            d_old, sf_old = old.paint_masks(bgr)
            d_new, sf_new = new.paint_masks(bgr)

            rows.append((
                path.name,
                np.array_equal(t_old, t_new),
                np.array_equal(np.asarray(v_old, np.int32), np.asarray(v_new, np.int32)),
                np.array_equal(s_old > 0, s_new > 0),
                np.array_equal(r_old >= new.RIDGE_CONTRAST, r_new >= new.RIDGE_CONTRAST),
                np.array_equal(d_old, d_new),
                np.array_equal(np.argwhere(d_old == 0), np.argwhere(d_new == 0)),
                np.array_equal(sf_old > 0, sf_new > 0),
            ))

        names = ("turf", "val", "surface(rm)", "ridge>=16", "dist", "centreline", "surface(pm)")
        ok = all(all(r[1:]) for r in rows)
        bad += 0 if ok else 1
        flags = " ".join(f"{n}:{'=' if all(r[i + 1] for r in rows) else 'X'}"
                         for i, n in enumerate(names))
        print(f"  {clip:<28} {len(rows)} frames  {flags}   {'OK' if ok else '*** DIFFERS ***'}")

    print(f"\n{len(clips) - bad}/{len(clips)} clips identical")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
