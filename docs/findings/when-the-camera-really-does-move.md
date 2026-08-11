# Telling a camera that moves from a camera that only appears to

**Asked, not to be solved now:** the camera will not always sit at one point — it can genuinely
travel along a line. How would that case be detected, and how should the solver handle it?

Recorded because the answer contains a trap that would otherwise be found the expensive way.

## The trap

`camera_fixed` was built on the finding that the positions strung along a line are an *artifact*:
focal and distance trade off on a plane, so many (position, focal) pairs fit the same image. A
camera that really is moving along a line produces **the same picture in the 3D view**. The two
cases are visually identical, and the current pipeline would collapse a real dolly move to a single
point and call it a success — the paint error would even look fine, because a wrong position is
absorbed by the focal.

Worse: on a **pure plane**, translation and rotation are not distinguishable at all. A plane under
a translating camera still induces a homography. Every measurement this repo makes about the pitch
markings is a measurement on one plane, so no amount of marking accuracy can separate the cases.

## Three tests that would, in increasing cost

**1. The shape of the 1-D scan.** `solve_shared_centre.py` already slides along the fitted line and
scores each stop. On this clip the curve has a sharp minimum — 1.89 px at the optimum against
4.33 px three metres away. Run the same scan **per block of frames** rather than once for the clip:

- one shared minimum for every block → the camera is at one point,
- each block's minimum at a *different* t, drifting monotonically with frame number → the camera
  is moving along the line, and that drift **is** the motion,
- no minimum at all, flat → the degeneracy is genuinely unresolved and neither answer is supported.

Cheapest by far, needs nothing new, and it reuses a search that already exists.

**2. `carry`'s focal disagreement.** `solve/carry.py` solves the focal twice, once from each image
axis, and returns how far apart they came out. A pure rotation makes them agree — measured 0.001 on
this clip. A translation breaks the identity `H = K_j Rⱼ Rᵢᵀ K_i⁻¹` that the two estimates rest on,
so they separate. Already computed on every carried frame and currently only logged.

**3. Parallax between the pitch and everything else.** The decisive one, and the only one that works
when the motion is small. Split the SIFT features `measure_pairs` finds into those on the playing
surface (the `surface` mask from `paint_masks` already says which) and those off it — stands, goal
frames, floodlights, the crowd. Fit a homography to each set separately.

- Camera rotating about a point: **both** homographies agree, whatever the depth.
- Camera translating: they disagree, by an amount that grows with the depth difference. That
  disagreement is the parallax, and it is the only signal that carries real 3D information.

This is also the only one of the three that could recover *how far* the camera moved in metres
rather than in units of the fitted line.

## What the solver should then do

Nothing in the current chain needs replacing — `carry` already propagates a per-frame camera and
`refit_frame_lm` already fits one. What changes is the last step: instead of collapsing to a single
centre, fit a **line segment** — two endpoints and a per-frame position along it — which is three
extra parameters for the clip rather than three per frame. That keeps the trajectory smooth and
renderable while allowing the motion, and it degrades gracefully to the fixed case when the fitted
travel comes out at zero.

Do not simply free the position again. That was measured this session: a free per-frame centre
scores *better* on the paint (21.9 px against 29.4 held) by exploiting the degeneracy, and produces
a camera that jumps 10.8 m between neighbouring frames. Better numbers, unusable output.
