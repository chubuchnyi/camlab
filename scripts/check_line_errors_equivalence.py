"""Does the faster `line_errors` return the same lines, offsets and angles as the shipped one?

`line_errors` is what says a camera is right at the level of correspondence — which marking matched
which detected segment, and by how much it missed. It is the thing an LM refit minimises, so a
change to it that moved any number by a float would change every solved camera in the repo.

Same shape as `check_paint_equivalence.py`: both implementations imported out of two working trees
and run against each other on real frames, real detected segments and the clip's own solved camera,
including a swept camera so the comparison covers cameras that are WRONG as well as the one that
is right — a refit spends almost all of its evaluations away from the optimum.

    python scripts/check_line_errors_equivalence.py --old /home/chubuchnyi/camlab
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
RUNS = HERE / "runs"


def load_old(root: Path):
    pkg_root = root / "src"
    saved = list(sys.path)
    sys.path.insert(0, str(pkg_root))
    for name in [m for m in sys.modules if m.startswith("camlab")]:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        "oldline", pkg_root / "camlab" / "measure" / "line_error.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["oldline"] = mod
    spec.loader.exec_module(mod)
    sys.path[:] = saved
    for name in [m for m in sys.modules if m.startswith("camlab")]:
        del sys.modules[name]
    return mod


def cameras_for(clip: str):
    for name in ("camera_polished.json", "camera_smooth.json", "camera_carry.json"):
        path = RUNS / clip / name
        if path.exists():
            return name, json.loads(path.read_text())
    return None, None


def compare(a, b) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=True):
        dx, dy = asdict(x), asdict(y)
        if set(dx) != set(dy):
            return False
        for k in dx:
            u, v = dx[k], dy[k]
            if isinstance(u, np.ndarray) or isinstance(v, np.ndarray):
                if not np.array_equal(np.asarray(u), np.asarray(v)):
                    return False
            elif u != v and not (u != u and v != v):     # NaN == NaN, for this purpose
                return False
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="/home/chubuchnyi/camlab")
    ap.add_argument("--frames", type=int, default=3)
    ap.add_argument("--clips", nargs="*", default=None)
    args = ap.parse_args()

    old = load_old(Path(args.old))
    from camlab.measure import line_error as new  # noqa: E402
    from camlab.measure.lines import detect_segments, merge_collinear
    from camlab.measure.paint import paint_masks

    clips = args.clips or sorted(p.name for p in RUNS.iterdir()
                                 if (p / "frames").is_dir() and any((p / "frames").glob("*.jpg")))
    bad = 0
    for clip in clips:
        name, cam = cameras_for(clip)
        if cam is None:
            print(f"  {clip:<28} no solved camera, skipped")
            continue
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))
        step = max(1, len(frames) // args.frames)
        checked = ok = seen = 0
        for i in range(0, len(frames), step):
            if seen >= args.frames:
                break
            focals = cam.get("focal_px") or []
            if i >= len(focals) or not focals[i] or focals[i] <= 0:
                continue
            bgr = cv2.imread(str(frames[i]))
            dist, surface = paint_masks(bgr)
            segs = merge_collinear(detect_segments(dist, surface))
            h, w = bgr.shape[:2]
            base = dict(segments=segs, rvec=cam["rotation"][i], centre=cam["position"][i],
                        width=w, height=h, cx=cam.get("cx"), cy=cam.get("cy"))
            seen += 1
            # the solved camera, and four deliberately wrong ones — a refit spends almost all of
            # its evaluations off the optimum, so that is where agreement has to hold too
            for scale in (1.0, 0.85, 1.2, 1.0, 1.0):
                kw = dict(base)
                kw["focal"] = float(focals[i]) * scale
                if scale == 1.0 and checked % 2:
                    kw["centre"] = list(np.asarray(cam["position"][i]) + np.array([1.5, -2.0, 0.4]))
                checked += 1
                if compare(old.line_errors(**kw), new.line_errors(**kw)):
                    ok += 1
        flag = "OK" if ok == checked and checked else ("*** DIFFERS ***" if checked else "no data")
        bad += 0 if flag == "OK" else 1
        print(f"  {clip:<28} {ok}/{checked} camera+frame combinations identical   {flag}")

    print(f"\n{len(clips) - bad}/{len(clips)} clips identical")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
