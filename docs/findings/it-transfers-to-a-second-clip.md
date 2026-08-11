# The second clip, and a camera fitted two metres from one nobody in this repo fitted

Everything so far was measured on `fan`: a cropped 1080×608 phone clip of a floodlit night match.
`broadcast` is a different thing — 1920×1080, uncropped, a professional camera, a different match.
Its seed is `camera_known.json`, pitch3d's `rigid_119` solve: one position, one focal for all sixty
frames.

## What the chain did to it

| | worst line, median | under 20 px | camera movement |
|---|---|---|---|
| `camera_known` (pitch3d) | 9.49 px | 41/60 | 0 (rigid by construction) |
| + carry | 5.45 px | **60/60** | up to 3.4 m |
| + self-heal | 5.45 px | 60/60 | nothing left to fix |
| **+ shared centre** | **3.98 px** | 59/60 | **0.00 m** |

The seed's failure is instructive: frames 0–15 score 125–130 px while frames 20–45 score 2.3–5.6.
A rigid camera cannot follow an operator who pans, so it fits the middle of the clip and abandons
the start. The carry follows it and every frame comes under 20 px.

The self-heal pass found nothing to do, which is the right answer on a clip where nothing was lost,
and said so instead of churning.

## The line is there too

`camera_carry`'s positions on this clip put **97.0 %** of their variance along one direction, over
10.0 m, with 0.31 m of scatter about it — the same degeneracy as on `fan`, at a different scale
(there it was 99 % over 108 m). The 1-D search found its minimum at t = +2.06 m, inside the window
rather than at its edge.

## The part that is an outside check

`solve_shared_centre` landed on:

    position  (−2.19, −68.16, 16.64) m      focal median 4216 px

pitch3d's golden camera, fitted from PnLCalib keypoints by a completely different route and pinned
in a mutation-checked test, is:

    position  (−2.29, −70.13, 17.22) m      focal 4169.32 px

**2.06 m apart on a 70 m shot; the focal agrees to 1.1 %.** Two methods that share no code, no
detector and no objective, on the same footage. And camlab's scores better against the paint —
3.98 px against 9.49.

This is the first external check any number in this repo has had. Every other comparison so far has
been camlab against camlab, or camlab against a human's eye.

## What does not work yet, stated plainly

Three more sample clips were ingested (`test_11710897`, `test_14604660`, `test_15449383`). The
detector is fine on all three — 6 to 11.5 merged lines a frame, comparable to `fan`. **The chain
still cannot run on them, because it improves a seed and cannot create one.** `camlab solve` reads
homographies out of a pitch3d `scene.json`, and there is no such file for these.

A crude bootstrap does look possible: 4000 random cameras — position sampled around the pitch,
aimed at a random point on it, focal from a wide range — scored by the line objective, best one
handed to `refit_frame_lm`, gives 2.3 px on one clip and 9.5 px on another for frame 0.

**Do not read that as solved.** The 2.3 px is over 103 scored samples where a normal frame has
160–300, and this repo's own rule is that a median without its sample count is worthless: a camera
that has run away projects almost everything off-surface and posts a flattering number on the
handful of survivors. There is no ground truth on these clips and nobody has looked at them. It is
a promising direction and nothing more until an eye has judged one.
