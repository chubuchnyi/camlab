"""Does the cached `measure_pairs` return the same homographies as the shipped one?

The descriptor cache moved from inside the call to the module, so the thing to prove is that a hit
is indistinguishable from a recomputation — on real frames, on every clip, and in **both shapes the
repo calls it in**:

* the whole clip at once, which is `solve_carry`, and which the old call-local cache already served
  correctly;
* one pair at a time, which is `solve_selfheal`, and which is where the old cache held two entries
  and died. If the module cache is wrong, this is the shape that shows it, because it is the shape
  where a hit actually happens.

Compared per pair: the homography **bit for bit**, the inlier count, and the median reprojection.

    python scripts/check_pixel_motion_equivalence.py --old /home/chubuchnyi/camlab
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

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
        "oldmotion", pkg_root / "camlab" / "measure" / "pixel_motion.py")
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "camlab.measure"
    sys.modules["oldmotion"] = mod
    spec.loader.exec_module(mod)
    sys.path[:] = saved
    for name in [m for m in sys.modules if m.startswith("camlab")]:
        del sys.modules[name]
    return mod


def same(a, b) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(sorted(a, key=lambda p: (p.i, p.j)),
                    sorted(b, key=lambda p: (p.i, p.j)), strict=True):
        if (x.i, x.j) != (y.i, y.j) or x.inliers != y.inliers or x.median_px != y.median_px:
            return False
        if not np.array_equal(x.h, y.h):
            return False
    return True


def pairwise(mod, paths: dict, gaps) -> list:
    """`solve_selfheal`'s shape: one call per pair, which is where a cache hit happens."""
    out = []
    frames = sorted(paths)
    for gap in gaps:
        for i in frames:
            j = i + gap
            if j in paths:
                out += mod.measure_pairs({i: paths[i], j: paths[j]}, gaps=(gap,))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="/home/chubuchnyi/camlab")
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--gaps", default="1,5,23")
    ap.add_argument("--clips", nargs="*", default=None)
    args = ap.parse_args()

    gaps = tuple(int(x) for x in args.gaps.split(","))
    old = load_old(Path(args.old))
    from camlab.measure import pixel_motion as new  # noqa: E402

    clips = args.clips or sorted(p.name for p in RUNS.iterdir()
                                 if (p / "frames").is_dir() and any((p / "frames").glob("*.jpg")))
    bad = 0
    for clip in clips:
        frames = sorted((RUNS / clip / "frames").glob("*.jpg"))[:args.frames]
        if len(frames) < 2:
            print(f"  {clip:<28} fewer than two frames, skipped")
            continue
        paths = dict(enumerate(frames))

        new.clear_descriptor_cache()
        o_whole = old.measure_pairs(paths, gaps=gaps)
        n_whole = new.measure_pairs(paths, gaps=gaps)
        o_pairs = pairwise(old, paths, gaps)
        n_pairs = pairwise(new, paths, gaps)          # every one of these is a cache hit now

        whole_ok = same(o_whole, n_whole)
        pairs_ok = same(o_pairs, n_pairs)
        # and the two shapes must agree with each other, which is what says the cache did not
        # change the answer depending on how the caller happened to batch its frames
        shape_ok = same(n_whole, n_pairs)
        ok = whole_ok and pairs_ok and shape_ok
        bad += 0 if ok else 1
        print(f"  {clip:<28} {len(n_whole):>3} pairs   "
              f"whole:{'=' if whole_ok else 'X'} pairwise:{'=' if pairs_ok else 'X'} "
              f"whole==pairwise:{'=' if shape_ok else 'X'}   "
              f"{'OK' if ok else '*** DIFFERS ***'}")

    print(f"\n{len(clips) - bad}/{len(clips)} clips identical")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
