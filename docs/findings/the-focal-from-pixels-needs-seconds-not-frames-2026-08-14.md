# The focal from the pixels alone: useless between neighbours, usable seconds apart

Asked whether OpenCV can get the camera's motion and focal quickly from neighbouring frames. The
motion, yes — the carry stage already does it. **The focal, no, and the reason is a number.**

`measure/pixel_motion.focals_from_homography` is the closed form from Shum and Szeliski: given the
image-to-image map between two views of a camera turning about a fixed centre, it returns the focal
of both. `cv2.detail.focalsFromHomography` is the same maths and is **unusable from Python** — its
C++ signature writes the four results through references, which the binding cannot do for immutable
Python numbers, so on OpenCV 5.0 it returns `None` whatever is passed. Fifteen lines to write.

## The implementation is exact, so the failure is the data

On synthetic pure rotations it is exact to 1e-6 at every focal and every angle tried, including
0.5°. That matters: without it the rest of this file would be a story about a bug.

## What it needs is DEGREES OF TURN, and that is what neighbours do not have

Noise applied to the correspondences, homography re-fitted the way `measure_pairs` does it, 25
trials, true focal 2896:

| turn | 0.1 px noise | 0.3 px | 1.0 px |
|---|---|---|---|
| **0.5°** | **20.2 %** | 58.9 % | 58.5 % |
| **3.0°** | 0.2 % | 2.9 % | 6.1 % |

Our measured maps sit at 0.14–0.95 px. Consecutive frames at 30 fps turn **0.06°**. That is the
top-left cell, and it is why the answer is noise.

## Measured on real footage, and the operator's question was the right one

`14604731`, 180 frames at 30 fps, solved focal 4875 px. Every pair scored against the solved camera:

| gap | seconds | pairs | turn | map resid | focal from pixels | solved | error | more than 50 % out |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.03 | 99 | 0.06° | 0.14 px | 147 | 4876 | **96.9 %** | **98/99** |
| 15 | 0.5 | 24 | 0.65° | 0.33 | 1795 | 4874 | 63.4 % | 15/24 |
| 30 | 1.0 | 13 | 1.37° | 0.62 | 3091 | 4875 | 36.8 % | 3/13 |
| 60 | **2.0** | 6 | 2.59° | 0.75 | 2987 | 4739 | **29.0 %** | **0/6** |
| 90 | 3.0 | 3 | 3.59° | 0.84 | 2567 | 3239 | 16.8 % | 0/3 |
| 120 | **4.0** | 2 | 4.66° | 0.95 | 3468 | 3839 | **10.8 %** | 0/2 |

Monotonic, and the catastrophic failures vanish entirely from two seconds on. At four seconds the
focal is within 11 % **with no pitch model involved at all** — no markings, no correspondence
naming, no half-turn ambiguity. That is a different kind of evidence from everything else in this
repo, and it is the half of #11 that has no chooser problem.

The cost is that the pairs run out: sampling this clip gives 99 neighbour pairs and 2 at four
seconds. On a full match that is not a constraint; on a 40-frame clip there is no four-second gap
to take.

## One number in this file was nearly wrong, and it is the repo's own landmine

The first run of the table above was on `fan`, which is 120 frames. At gap 60 **one pair survived**,
it read 67.5 % out, and I wrote it into a column headed "median". The register's first entry is
*"never compare medians without comparing sample counts"*. Re-run at the real geometry — 2.66° of
turn, 0.59 px of noise, 30 trials — a pure rotation gives **11.4 %**, and adding 50 cm of camera
translation only takes it to 21.5 %. So neither noise nor a handheld camera's drift explains 67.5 %:
one sample does.

## Where this leaves it

Not a calibration. A **prior**, and a cheap one — 0.03 ms a pair against 56–92 ms for the numerical
`rotation_only_residual_px` that fits the same two focals by optimisation. Worth having as:

- an independent check on the focal the pitch model derives, which currently has nothing to
  disagree with;
- a starting focal on a clip with no camera at all, where the bootstrap searches a range blind;
- a way to tell a zoom from a dolly over seconds, since it returns both focals separately.

Use pairs **seconds apart, not frames**, and count how many answered.
