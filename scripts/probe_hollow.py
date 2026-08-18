"""Does the ridge response hollow out on wide (near) markings?"""
import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2

from camlab.measure.lines import detect_segments
from camlab.measure.paint import RIDGE_SCALES, ridge_map
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo

print(f"  RIDGE_SCALES = {RIDGE_SCALES}")
info=ClipInfo.load(sys.argv[1])
prof_by_w={}
for i in range(0,min(info.n_frames,240),40):
    bgr=cv2.imread(str(info.frame_path(i)))
    ridge,val,surface=ridge_map(bgr)
    d,s=frame_evidence_cached(info.frame_path(i))[:2]
    segs=detect_segments(d,s,method="hough")
    R=np.asarray(ridge,np.float32)
    for sg in segs:
        m=np.array([(sg[0]+sg[2])/2,(sg[1]+sg[3])/2])
        v=np.array([sg[2]-sg[0],sg[3]-sg[1]]); L=np.linalg.norm(v)
        if L<1e-6: continue
        n=np.array([-v[1],v[0]])/L
        ts=np.arange(-9,9.5,0.5)
        pts=m[None,:]+ts[:,None]*n[None,:]
        x=np.clip(pts[:,0],0,R.shape[1]-1).astype(np.float32).reshape(-1,1)
        y=np.clip(pts[:,1],0,R.shape[0]-1).astype(np.float32).reshape(-1,1)
        p=cv2.remap(R,x,y,cv2.INTER_LINEAR).ravel()
        if p.max()<=0: continue
        p=p/p.max()
        # width of the response at half maximum
        on=p>=0.5; idx=np.flatnonzero(on)
        if not len(idx): continue
        w=ts[idx[-1]]-ts[idx[0]]
        key="wide (near)" if w>=4.0 else "thin (far)"
        prof_by_w.setdefault(key,[]).append(p)
for k,v in sorted(prof_by_w.items()):
    a=np.array(v); mp=a.mean(axis=0); ts=np.arange(-9,9.5,0.5)
    c=mp[np.argmin(np.abs(ts))]
    peak=mp.max(); at=ts[np.argmax(mp)]
    print(f"  {k:<12} n={len(v):4d}  response at the centre {c:.3f}  peak {peak:.3f} at {at:+.1f} px  "
          f"dip = {100*(1-c/peak):.1f} %")
