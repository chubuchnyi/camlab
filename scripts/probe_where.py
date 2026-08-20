import sys

import numpy as np

sys.path.insert(0,'src'); sys.path.insert(0,'scripts')
import cv2
from bench_vs_worldpose import gt_path

from camlab.measure.line_error import straight_markings
from camlab.measure.lines import detect_segments
from camlab.measure.residual import frame_evidence_cached
from camlab.runs import ClipInfo


def true_lines(K,R,t,k,w,h):
    rvec=cv2.Rodrigues(R)[0]; out=[]
    for _id,pts in straight_markings():
        P=np.asarray(pts,float)
        if P.shape[1]==2: P=np.column_stack([P,np.zeros(len(P))])
        cam=(R@P.T).T+t
        if (cam[:,2]<=1.0).any(): continue
        uv=cv2.projectPoints(P,rvec,t.reshape(3,1),K,np.asarray(k,float))[0].reshape(-1,2)
        out.append(uv)
    return out

rows=[]
TOT=[0,0]
for c in sys.argv[1:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        d,s=frame_evidence_cached(info.frame_path(i))[:2]
        segs=detect_segments(d,s,method="hough")
        tl=true_lines(K,R,t,k,info.width,info.height)
        if not len(segs) or not tl: continue
        cx,cy=info.width/2.0,info.height/2.0
        for sg in segs:
            m=np.array([(sg[0]+sg[2])/2,(sg[1]+sg[3])/2])
            best=None
            for uv in tl:
                a,b=uv[0],uv[-1]; dvec=b-a; L=np.linalg.norm(dvec)
                if L<1e-6: continue
                n=np.array([-dvec[1],dvec[0]])/L
                off=float(n@(m-a))
                if best is None or abs(off)<abs(best[0]): best=(off,n)
            TOT[0]+=1
            if best is None or abs(best[0])>25: continue
            TOT[1]+=1
            off,n=best
            rad=m-np.array([cx,cy]); rn=np.linalg.norm(rad)
            if rn<1e-6: continue
            # sign the offset along the outward radial direction
            rows.append((rn, off*float(n@(rad/rn))))
a=np.array(rows)
print(f"  {TOT[1]}/{TOT[0]} detected segments ({100*TOT[1]/max(TOT[0],1):.0f} %) lie within 25 px of a true marking")
print(f"  {len(a)} detected segments matched to a true marking within 25 px")
print("  radial displacement of the DETECTED line vs the TRUE one:")
print(f"    median {np.median(a[:,1]):+.3f} px   mean {a[:,1].mean():+.3f} px")
print(f"    inner half of the image {np.median(a[a[:,0]<np.median(a[:,0])][:,1]):+.3f} px")
print(f"    outer half              {np.median(a[a[:,0]>=np.median(a[:,0])][:,1]):+.3f} px")
print(f"    r(radius, displacement) = {np.corrcoef(a[:,0],a[:,1])[0,1]:+.3f}")
