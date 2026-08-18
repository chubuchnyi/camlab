import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo
from camlab.solve.refit import line_errors

clips = sys.argv[1:]
for c in clips:
    info = ClipInfo.load(c); g = np.load(gt_path(c)); first = int(info.first_frame)
    rows = []
    for i in range(0, min(info.n_frames, 240), 40):
        K, R, t = g["K"][first+i], g["R"][first+i], g["t"][first+i]
        C = -R.T @ t
        rvec = cv2.Rodrigues(R)[0].ravel()
        d, s = frame_evidence_cached(info.frame_path(i))[:2]
        segs = detect_segments(d, s, method="hough")
        errs = line_errors(segs, float(K[0,0]), rvec, C, info.width, info.height,
                           cx=float(K[0,2]), cy=float(K[1,2]))
        for e in errs:
            if not e.matched: continue
            mid = 0.5*(np.asarray(e.model_uv[0])+np.asarray(e.model_uv[1]))
            r = float(np.hypot(mid[0]-K[0,2], mid[1]-K[1,2]))
            rows.append((r, float(e.offset_px)))
    if not rows: print(f"  {c}: nothing matched"); continue
    a = np.array(rows)
    rr, oo = a[:,0], a[:,1]
    print(f"  {c:<20} n={len(a):4d}  signed offset med {np.median(oo):+6.2f} px  "
          f"|offset| med {np.median(np.abs(oo)):5.2f}  r(radius,offset)={np.corrcoef(rr,oo)[0,1]:+.3f}")
