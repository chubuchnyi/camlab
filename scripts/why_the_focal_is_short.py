"""Is camlab's 2 % focal deficit the radial distortion it does not model?

`the-focal-deficit-is-real-and-the-constant-is-not-2026-08-18.md` measured the deficit on five
matches and showed a constant correction removes a third to a half of the position error. A
systematic 2 % that reproduces across five stadiums is not noise, so something is generating it, and
this asks whether the generator is the distortion.

**The test needs no solving and no camlab camera at all**, which is what makes it decisive. Take
WorldPose's own camera, project the pitch through its own distortion — that is what the broadcast
frame actually shows — and then ask a PINHOLE model, given the true pose, what focal best explains
those pixels. If a distortion-blind fit systematically wants a shorter focal, and by about the
observed amount, the deficit is explained without any reference to camlab's solver.

The pinhole fit is closed form. With the pose held, a pinhole puts a world point at
`u = f·(x/z) + cx`, so stacking every visible sample's `a = (x/z, y/z)` against `b = (u−cx, v−cy)`
makes the focal a one-parameter least squares, `f* = Σab / Σa²`.

    PYTHONPATH=src:. python scripts/why_the_focal_is_short.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE / "src"))
sys.path.insert(0, str(HERE / "scripts"))

from bench_vs_worldpose import _pitch_samples, gt_path  # noqa: E402

from camlab.runs import ClipInfo  # noqa: E402


def pinhole_focal_for(K, R, t, k, w, h, pts) -> tuple[float, float] | None:
    """`(best pinhole focal, distortion shift in px)` for one frame, or None if too little is seen.

    The shift is the median distance between where a point lands with the true distortion and where
    the same point lands without it — the size of the effect being tested, in the units the register
    already quotes it in.
    """
    import cv2

    rvec = cv2.Rodrigues(R)[0]
    uv_d = cv2.projectPoints(pts, rvec, t.reshape(3, 1), K, np.asarray(k, float))[0].reshape(-1, 2)
    uv_p = cv2.projectPoints(pts, rvec, t.reshape(3, 1), K, np.zeros(5))[0].reshape(-1, 2)

    cam = (R @ pts.T).T + t
    seen = (cam[:, 2] > 1.0) & (uv_d[:, 0] >= 0) & (uv_d[:, 0] < w) \
        & (uv_d[:, 1] >= 0) & (uv_d[:, 1] < h)
    if seen.sum() < 50:
        return None

    cx, cy = K[0, 2], K[1, 2]
    a = np.concatenate([cam[seen, 0] / cam[seen, 2], cam[seen, 1] / cam[seen, 2]])
    b = np.concatenate([uv_d[seen, 0] - cx, uv_d[seen, 1] - cy])
    return float(a @ b / (a @ a)), float(np.median(np.linalg.norm(uv_d[seen] - uv_p[seen], axis=1)))


def camlab_model_focal(K, R, t, k, w, h, pts, *, centre_pp=True, distortion=True):
    """What focal camlab's MODEL wants for a frame the truth renders.

    This is the whole hypothesis in one function. camlab differs from WorldPose's camera in exactly
    two ways — it pins the principal point to the image centre, and it has no distortion term — so
    render the pitch with the truth's own camera and fit camlab's model to those pixels with the
    pose free. No detector, no paint, no noise: whatever bias comes out is the model's, and nothing
    else's. The flags let each difference be switched off on its own, which is how you find out
    which of the two is doing the work.
    """
    import cv2
    from scipy.optimize import least_squares

    rvec_t = cv2.Rodrigues(R)[0]
    dist = np.asarray(k, float) if distortion else np.zeros(5)
    uv = cv2.projectPoints(pts, rvec_t, t.reshape(3, 1), K, dist)[0].reshape(-1, 2)

    cam = (R @ pts.T).T + t
    seen = (cam[:, 2] > 1.0) & (uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h)
    if seen.sum() < 50:
        return None
    target, P = uv[seen], pts[seen]

    cx, cy = (w / 2.0, h / 2.0) if centre_pp else (K[0, 2], K[1, 2])
    f0 = float(K[0, 0])
    C0 = -R.T @ t
    p0 = np.concatenate([[f0], rvec_t.ravel(), C0.ravel()])

    def resid(p):
        Kp = np.array([[p[0], 0, cx], [0, p[0], cy], [0, 0, 1.0]])
        Rp = cv2.Rodrigues(p[1:4])[0]
        tp = -Rp @ p[4:7]
        q = cv2.projectPoints(P, p[1:4], tp.reshape(3, 1), Kp, np.zeros(5))[0].reshape(-1, 2)
        return (q - target).ravel()

    res = least_squares(resid, p0, x_scale=[100.0, .01, .01, .01, 1.0, 1.0, 1.0])
    return float(res.x[0]) / f0, float(np.linalg.norm(res.x[4:7] - C0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", type=Path, default=None,
                    help="a bench_vs_worldpose json, to correlate the prediction against")
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--model-fit", action="store_true",
                    help="fit camlab's model to the truth's own rendering, pose free")
    args = ap.parse_args()

    measured = {}
    if args.measured:
        for f in str(args.measured).split(","):
            measured.update({r["clip"]: r for r in json.loads(Path(f).read_text())
                             if r.get("focal_ratio")})

    pts = _pitch_samples()
    rows = []
    clips = sorted(measured) if measured else []
    if args.model_fit:
        print(f"{'clip':22} {'both':>9} {'no dist':>9} {'true pp':>9} {'measured':>10}")
    else:
        print(f"{'clip':22} {'predicted':>10} {'measured':>10} {'distortion':>11}")
    for c in clips:
        try:
            info = ClipInfo.load(c)
            d = np.load(gt_path(c))
        except Exception as exc:
            print(f"{c:22} skipped: {str(exc)[:50]}")
            continue
        first = int(info.first_frame)
        got = []
        for i in range(0, info.n_frames, max(1, args.every)):
            g = first + i
            out = pinhole_focal_for(d["K"][g], d["R"][g], d["t"][g], d["k"][g],
                                    info.width, info.height, pts)
            if out:
                got.append((out[0] / d["K"][g][0, 0], out[1]))
        if args.model_fit:
            variants = {}
            for label, kw in (("both", {}), ("no distortion", {"distortion": False}),
                              ("true pp", {"centre_pp": False})):
                v = [camlab_model_focal(d["K"][first + i], d["R"][first + i], d["t"][first + i],
                                        d["k"][first + i], info.width, info.height, pts, **kw)
                     for i in range(0, info.n_frames, max(1, args.every * 4))]
                v = [x for x in v if x]
                variants[label] = float(np.median([x[0] for x in v])) if v else float("nan")
            rows.append({"clip": c, "measured_ratio": measured[c]["focal_ratio"], **variants})
            print(f"{c:22} {variants['both']:9.4f} {variants['no distortion']:9.4f} "
                  f"{variants['true pp']:9.4f} {measured[c]['focal_ratio']:10.4f}")
            continue
        if not got:
            print(f"{c:22} nothing visible")
            continue
        pred = float(np.median([g[0] for g in got]))
        shift = float(np.median([g[1] for g in got]))
        row = {"clip": c, "predicted_ratio": pred, "distortion_px": shift,
               "measured_ratio": measured[c]["focal_ratio"]}
        rows.append(row)
        print(f"{c:22} {pred:10.4f} {row['measured_ratio']:10.4f} {shift:10.1f}p")

    if rows and args.model_fit:
        for label in ("both", "no distortion", "true pp"):
            v = np.array([r[label] for r in rows], float)
            v = v[np.isfinite(v)]
            print(f"  camlab's model, {label:<14}: median focal ratio {np.median(v):.4f}")
        m = np.array([r["measured_ratio"] for r in rows])
        print(f"  camlab's actual solve         : median focal ratio {np.median(m):.4f}")
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(rows, indent=1))
            print(f"\n-> {args.json}")
        return 0
    if rows:
        p = np.array([r["predicted_ratio"] for r in rows])
        m = np.array([r["measured_ratio"] for r in rows])
        print(f"\n  predicted by distortion alone : median {np.median(p):.4f}  "
              f"range {p.min():.4f}-{p.max():.4f}")
        print(f"  measured from camlab's solve  : median {np.median(m):.4f}  "
              f"range {m.min():.4f}-{m.max():.4f}")
        if len(rows) > 2:
            print(f"  correlation predicted vs measured: r = {np.corrcoef(p, m)[0, 1]:+.3f}")
        print(f"  the deficit distortion explains  : "
              f"{100 * (1 - np.median(p)):.2f} % of the {100 * (1 - np.median(m)):.2f} % observed")
    if args.json and rows:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=1))
        print(f"\n-> {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
