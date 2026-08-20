"""Same segments, true geometry: snap each detected segment onto the marking it lies on."""
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

TOL=25.0
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

def nearest(seg,tl):
    m=np.array([(seg[0]+seg[2])/2,(seg[1]+seg[3])/2]); best=1e9; hit=None
    for mid,a,b in tl:
        d=b-a; L=np.linalg.norm(d)
        if L<1e-6: continue
        u=float((m-a)@d/(L*L))
        if not (-0.15<=u<=1.15): continue
        n=np.array([-d[1],d[0]])/L
        off=abs(float(n@(m-a)))
        if off<best: best,hit=off,(a,b)
    return best,hit

print(f"  {'clip':<20} {'detected':>9} {'both fix':>9} {'ANGLE fix':>9} {'OFFSET fix':>10}")
A=[];B=[];Cc=[];D=[];ANG=[]
for c in sys.argv[1:]:
    info=ClipInfo.load(c); g=np.load(gt_path(c)); first=int(info.first_frame)
    fa=[];fb=[];fc=[];fd=[];ang=[]
    for i in range(0,min(info.n_frames,240),60):
        K,R,t,k=g["K"][first+i],g["R"][first+i],g["t"][first+i],g["k"][first+i]
        C=-R.T@t; rvec=cv2.Rodrigues(R)[0].ravel(); f=float(K[0,0])
        cx,cy=info.width/2.0,info.height/2.0
        d,s=frame_evidence_cached(info.frame_path(i))[:2]
        segs=detect_segments(d,s,method="hough")
        if len(segs)<4: continue
        tl=true_lines(K,R,t,k)
        snapped=[];ang_only=[];off_only=[]
        for sg in segs:
            off,hit=nearest(sg,tl)
            if hit is None or off>TOL: continue
            a,b=hit; dv=b-a; L=np.linalg.norm(dv); u=dv/L
            p1=np.array([sg[0],sg[1]]); p2=np.array([sg[2],sg[3]])
            q1=a+u*float((p1-a)@u); q2=a+u*float((p2-a)@u)
            snapped.append([q1[0],q1[1],q2[0],q2[1]])
            mid=0.5*(p1+p2); half=0.5*np.linalg.norm(p2-p1)
            # angle fixed, midpoint left where the detector put it
            ang_only.append([mid[0]-u[0]*half,mid[1]-u[1]*half,mid[0]+u[0]*half,mid[1]+u[1]*half])
            # offset fixed, the detector's own direction kept
            n=np.array([-u[1],u[0]]); sh=float(n@(mid-a))
            off_only.append([p1[0]-n[0]*sh,p1[1]-n[1]*sh,p2[0]-n[0]*sh,p2[1]-n[1]*sh])
            sv=p2-p1; sl=np.linalg.norm(sv)
            if sl>1e-6:
                cosang=abs(float((sv/sl)@u)); ang.append(np.degrees(np.arccos(min(1.0,cosang))))
        if len(snapped)<4: continue
        fa.append(refit_frame_lm(segs,f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
        fb.append(refit_frame_lm(np.asarray(snapped,float),f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
        fc.append(refit_frame_lm(np.asarray(ang_only,float),f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
        fd.append(refit_frame_lm(np.asarray(off_only,float),f,rvec,C,info.width,info.height,cx,cy,frame=i).focal_px/f)
    if not fa: continue
    A.append(np.median(fa)); B.append(np.median(fb)); Cc.append(np.median(fc)); D.append(np.median(fd)); ANG+=ang
    print(f"  {c:<20} {np.median(fa):9.4f} {np.median(fb):9.4f} {np.median(fc):9.4f} {np.median(fd):9.4f}")
print(f"\n  median focal, detected segments : {np.nanmedian(A):.4f}")
print(f"  median focal, SNAPPED to truth  : {np.nanmedian(B):.4f}")
print(f"  median focal, ANGLE fixed only  : {np.nanmedian(Cc):.4f}")
print(f"  median focal, OFFSET fixed only : {np.nanmedian(D):.4f}")
print(f"  angular error of detected lines : median {np.median(ANG):.3f} deg, p90 {np.percentile(ANG,90):.3f}")
