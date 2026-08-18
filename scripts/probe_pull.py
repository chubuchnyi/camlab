import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo
from camlab.solve.refit import objective, refit_frame_lm

print(f"  {'clip':<20} {'start=truth':>11} {'after refit':>12} {'obj before':>11} {'obj after':>10}")
tot=[]
for c in sys.argv[1:]:
    info = ClipInfo.load(c); g = np.load(gt_path(c)); first = int(info.first_frame)
    got=[]
    for i in range(0, min(info.n_frames,240), 60):
        K,R,t = g["K"][first+i], g["R"][first+i], g["t"][first+i]
        C = -R.T @ t; rvec = cv2.Rodrigues(R)[0].ravel(); f = float(K[0,0])
        d,s = frame_evidence_cached(info.frame_path(i))[:2]
        segs = detect_segments(d,s,method="hough")
        cx,cy = info.width/2.0, info.height/2.0
        ob = objective(segs,f,rvec,C,info.width,info.height,cx,cy)
        out = refit_frame_lm(segs,f,rvec,C,info.width,info.height,cx,cy,frame=i)
        oa = objective(segs,out.focal_px,out.rotation,out.position,info.width,info.height,cx,cy)
        got.append((out.focal_px/f, ob, oa))
    if not got: continue
    a=np.array(got); tot.append(np.median(a[:,0]))
    print(f"  {c:<20} {1.0:11.4f} {np.median(a[:,0]):12.4f} {np.median(a[:,1]):10.2f}p {np.median(a[:,2]):9.2f}p")
print(f"\n  median focal after refitting FROM THE TRUTH: {np.median(tot):.4f}")
