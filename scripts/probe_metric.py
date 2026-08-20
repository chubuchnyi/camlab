"""How far, in METRES on the pitch, is a detected line from the marking it belongs to?"""
import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
from bench_vs_worldpose import gt_path

from camlab.measure.line_error import straight_markings
from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo


def ground(uv,K,R,t):
    """Back-project an image point onto the pitch plane z=0 with the true camera."""
    Kinv=np.linalg.inv(K); C=-R.T@t
    d=R.T@(Kinv@np.array([uv[0],uv[1],1.0]))
    if abs(d[2])<1e-9: return None
    s=-C[2]/d[2]
    return (C+s*d)[:2] if s>0 else None

rows=[]
for c in sys.argv[1:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        C=-R.T@t
        d,s=frame_evidence_cached(info.frame_path(i))[:2]
        segs=detect_segments(d,s,method="hough")
        for sg in segs:
            m=np.array([(sg[0]+sg[2])/2,(sg[1]+sg[3])/2])
            P=ground(m,K,R,t)
            if P is None: continue
            best=1e9;info2=None
            for mid,pts in straight_markings():
                A=np.asarray(pts,float)[:,:2]
                a,b=A[0],A[-1]; dv=b-a; L=np.linalg.norm(dv)
                if L<1e-6: continue
                u=float((P-a)@dv/(L*L))
                if not (-0.05<=u<=1.05): continue
                n=np.array([-dv[1],dv[0]])/L
                off=float(n@(P-a))
                if abs(off)<abs(best): best=off; info2=(a,b,n)
            if info2 is None or abs(best)>2.0: continue
            a,b,n=info2
            depth=float(np.linalg.norm(P-C[:2]))
            # sign the metric offset TOWARD the camera (negative = detector sits nearer than truth)
            toward=float(n@((C[:2]-P)/max(np.linalg.norm(C[:2]-P),1e-9)))
            rows.append((depth, best*np.sign(toward) if toward!=0 else best))
a=np.array(rows)
print(f"  {len(a)} detected segments placed on the pitch by the TRUE camera")
print(f"  metric offset toward the camera: median {np.median(a[:,1])*100:+.1f} cm  mean {a[:,1].mean()*100:+.1f} cm")
q=np.quantile(a[:,0],[0.33,0.66])
for lab,sel in (("near third",a[:,0]<q[0]),("middle",(a[:,0]>=q[0])&(a[:,0]<q[1])),("far third",a[:,0]>=q[1])):
    v=a[sel][:,1]
    print(f"    {lab:<12} n={len(v):4d}  median {np.median(v)*100:+6.1f} cm   depth {np.median(a[sel][:,0]):5.1f} m")
print(f"  r(depth, offset) = {np.corrcoef(a[:,0],a[:,1])[0,1]:+.3f}")
