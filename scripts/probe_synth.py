import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.line_error import straight_markings
from camlab.runs import ClipInfo
from camlab.solve.refit import refit_frame_lm


def synth(K,R,t,k,w,h,use_dist):
    rvec=cv2.Rodrigues(R)[0]; dist=np.asarray(k,float) if use_dist else np.zeros(5)
    out=[]
    for _id,pts in straight_markings():
        P=np.asarray(pts,float)
        if P.shape[1]==2: P=np.column_stack([P,np.zeros(len(P))])
        cam=(R@P.T).T+t
        if (cam[:,2]<=1.0).any(): continue
        uv=cv2.projectPoints(P,rvec,t.reshape(3,1),K,dist)[0].reshape(-1,2)
        # keep a marking only if both ends are inside the frame, so nothing is clipped
        if (uv[:,0]<0).any() or (uv[:,0]>=w).any() or (uv[:,1]<0).any() or (uv[:,1]>=h).any():
            continue
        out.append([uv[0,0],uv[0,1],uv[-1,0],uv[-1,1]])
    return np.asarray(out,float)

print(f"  {'clip':<20} {'no distortion':>14} {'with distortion':>16} {'n lines':>8}")
A=[];B=[]
for c in sys.argv[1:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    ra=[];rb=[];nn=[]
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        C=-R.T@t; rvec=cv2.Rodrigues(R)[0].ravel(); f=float(K[0,0])
        cx,cy=info.width/2.0,info.height/2.0
        for use,acc in ((False,ra),(True,rb)):
            segs=synth(K,R,t,k,info.width,info.height,use)
            if len(segs)<4: continue
            if not use: nn.append(len(segs))
            out=refit_frame_lm(segs,f,rvec,C,info.width,info.height,cx,cy,frame=i)
            acc.append(out.focal_px/f)
    if not ra: continue
    A.append(np.median(ra)); B.append(np.median(rb) if rb else np.nan)
    print(f"  {c:<20} {np.median(ra):14.4f} {(np.median(rb) if rb else float('nan')):16.4f} {int(np.median(nn)):8d}")
print(f"\n  median, perfect lines no distortion : {np.nanmedian(A):.4f}")
print(f"  median, perfect lines WITH distortion: {np.nanmedian(B):.4f}")
