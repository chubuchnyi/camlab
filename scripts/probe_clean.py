"""Does removing the junk segments remove the focal deficit? The causal test."""
import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.line_error import straight_markings
from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo
from camlab.solve.refit import refit_frame_lm

TOL = float(sys.argv[1])

def true_lines(K,R,t,k):
    rvec=cv2.Rodrigues(R)[0]; out=[]
    for mid,pts in straight_markings():
        P=np.asarray(pts,float)
        if P.shape[1]==2: P=np.column_stack([P,np.zeros(len(P))])
        cam=(R@P.T).T+t
        if (cam[:,2]<=1.0).any(): continue
        uv=cv2.projectPoints(P,rvec,t.reshape(3,1),K,np.asarray(k,float))[0].reshape(-1,2)
        out.append((mid,uv[0],uv[-1]))
    return out

def dist_to(seg, tl):
    """Smallest perpendicular distance of the segment's midpoint to any true marking's SPAN."""
    m=np.array([(seg[0]+seg[2])/2,(seg[1]+seg[3])/2]); best=1e9; who=None
    for mid,a,b in tl:
        d=b-a; L=np.linalg.norm(d)
        if L<1e-6: continue
        u=float((m-a)@d/(L*L))
        if not (-0.15 <= u <= 1.15):   # allow a little overhang, not the whole extension
            continue
        n=np.array([-d[1],d[0]])/L
        off=abs(float(n@(m-a)))
        if off<best: best,who=off,mid
    return best,who

print(f"  {'clip':<20} {'all segs':>9} {'clean':>7} {'kept':>6} {'focal all':>10} {'focal clean':>12}")
A=[];B=[]
for c in sys.argv[2:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    fa=[];fb=[];tot=0;kept=0
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        C=-R.T@t; rvec=cv2.Rodrigues(R)[0].ravel(); f=float(K[0,0])
        cx,cy=info.width/2.0,info.height/2.0
        d,s=frame_evidence_cached(info.frame_path(i))[:2]
        segs=detect_segments(d,s,method="hough")
        if len(segs)<4: continue
        keep=np.array([dist_to(sg,true_lines(K,R,t,k))[0]<=TOL for sg in segs])
        tot+=len(segs); kept+=int(keep.sum())
        fa.append(refit_frame_lm(segs,f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
        if keep.sum()>=4:
            fb.append(refit_frame_lm(segs[keep],f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
    if not fa: continue
    A.append(np.median(fa)); B.append(np.median(fb) if fb else np.nan)
    print(f"  {c:<20} {tot:9d} {kept:7d} {100*kept/max(tot,1):5.0f}% {np.median(fa):10.4f} "
          f"{(np.median(fb) if fb else float('nan')):12.4f}")
print(f"\n  median focal, ALL detected segments  : {np.nanmedian(A):.4f}")
print(f"  median focal, JUNK REMOVED (<={TOL:.0f}px): {np.nanmedian(B):.4f}")
