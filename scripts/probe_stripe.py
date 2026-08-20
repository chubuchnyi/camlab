"""Where does the detector sit inside the painted stripe, and where is the stripe's centre?"""
import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.line_error import straight_markings
from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo

R_MAX=18
def profile(img,m,n):
    ts=np.arange(-R_MAX,R_MAX+0.5,0.5)
    pts=m[None,:]+ts[:,None]*n[None,:]
    x=np.clip(pts[:,0],0,img.shape[1]-1); y=np.clip(pts[:,1],0,img.shape[0]-1)
    return ts, cv2.remap(img.astype(np.float32), x.astype(np.float32).reshape(-1,1),
                         y.astype(np.float32).reshape(-1,1), cv2.INTER_LINEAR).ravel()

rows=[]
for c in sys.argv[1:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        rvec=cv2.Rodrigues(R)[0]
        d,s=frame_evidence_cached(info.frame_path(i))[:2]
        segs=detect_segments(d,s,method="hough")
        tl=[]
        for mid,pts in straight_markings():
            P=np.asarray(pts,float)
            if P.shape[1]==2: P=np.column_stack([P,np.zeros(len(P))])
            cam=(R@P.T).T+t
            if (cam[:,2]<=1.0).any(): continue
            uv=cv2.projectPoints(P,rvec,t.reshape(3,1),K,np.asarray(k,float))[0].reshape(-1,2)
            tl.append((uv[0],uv[-1]))
        for sg in segs:
            m=np.array([(sg[0]+sg[2])/2,(sg[1]+sg[3])/2])
            v=np.array([sg[2]-sg[0],sg[3]-sg[1]]); L=np.linalg.norm(v)
            if L<1e-6: continue
            n=np.array([-v[1],v[0]])/L
            best=1e9; toff=None
            for a,b in tl:
                dv=b-a; LL=np.linalg.norm(dv)
                if LL<1e-6: continue
                u=float((m-a)@dv/(LL*LL))
                if not (-0.15<=u<=1.15): continue
                nn=np.array([-dv[1],dv[0]])/LL
                off=float(nn@(m-a))
                if abs(off)<abs(best): best=off; toff=-off*np.sign(float(nn@n)) if float(nn@n)!=0 else -off
            if toff is None or abs(best)>12: continue
            ts,prof=profile(d,m,n)          # d: distance to the nearest paint, 0 ON the paint
            on=prof<=0.75
            if not on.any(): continue
            idx=np.flatnonzero(on)
            # keep the run that contains the centre
            c0=np.argmin(np.abs(ts))
            if not on[c0]: continue
            lo=c0
            while lo>0 and on[lo-1]: lo-=1
            hi=c0
            while hi<len(on)-1 and on[hi+1]: hi+=1
            width=ts[hi]-ts[lo]; centre=0.5*(ts[hi]+ts[lo])
            if width<0.5 or width>16.0: continue
            rows.append((width, centre, toff))
a=np.array(rows)
print(f"  {len(a)} segments with a clean stripe profile")
print(f"  stripe width in the image : median {np.median(a[:,0]):.2f} px  range {np.percentile(a[:,0],5):.1f}-{np.percentile(a[:,0],95):.1f}")
print(f"  detector minus stripe centre : median {np.median(a[:,1]):+.3f} px")
print(f"  detector minus TRUE line     : median {np.median(a[:,2]):+.3f} px")
q=np.quantile(a[:,0],[0.5])
for lab,sel in (("thin (far) lines",a[:,0]<q[0]),("wide (near) lines",a[:,0]>=q[0])):
    v=a[sel]
    print(f"    {lab:<18} n={len(v):4d} width {np.median(v[:,0]):5.2f}px  "
          f"det-stripe {np.median(v[:,1]):+.3f}  det-true {np.median(v[:,2]):+.3f}")
print(f"  r(width, det-true) = {np.corrcoef(a[:,0],a[:,2])[0,1]:+.3f}")
