# "You can see the line the camera moves along" — and that line is the degeneracy

A human looked at the 3D view and said the camera's positions trace a visible line. They do, and it
is not a trajectory. It is the focal/distance degeneracy drawn in space.

| solve | variance along ONE direction | spread along it | scatter about it | angle to the line of sight |
|---|---|---|---|---|
| anchor-free (`camera_nohand`) | **99.0 %** | 108.3 m | 1.43 m | 24.7° |
| five-anchor (`camera_lm`) | 75.0 % | 21.4 m | 0.78 m | 13.0° |

The direction on `camera_lm` is `(0.072, 0.992, −0.106)` — essentially straight toward and away
from the pitch. Move the camera back, zoom in, and the image barely changes; on a plane, focal and
distance trade off almost exactly. Every frame's overlay could be nearly perfect while the camera
jumped 10.8 m between neighbours, which is why the fits were good and the trajectory was useless.

## The fix is one dimension wide

The camera is one point. So fit the line, slide along it, and at each stop refit every frame's
focal and rotation with the centre **held**. Keep the stop where the paint agrees best.

    t (m)   median worst line
    −6.00        18.74
    −4.50         6.17
    −3.00         4.33
    −1.50         2.52
     0.00         1.89   <-
    +1.50         2.36
    +3.00         3.49
    +6.00         6.55

**The degeneracy is not flat.** It only looked flat because nobody had searched along it. Three
metres either way costs more than a factor of two, so the position is pinned to about a metre:
`(3.11, −70.76, 22.15)`.

## What that buys

| | worst line, median | under 20 px | camera movement between frames |
|---|---|---|---|
| `camera_auto` | 38.4 px | 13/120 | — |
| `camera_carry` | 21.9 px | 59/120 | up to 11.5 m |
| `camera_lm` | 2.02 px | 104/120 | up to 10.8 m |
| **`camera_fixed`** | **1.88 px** | **106/120** | **0.00 m** |

Better on the paint *and* renderable. The trade that had held all session — accuracy against
physical plausibility, 21.9 px free versus 29.4 px held — was an artifact of holding the camera at
the **wrong** point. Held at the right one, there is no trade.

This is #10, answered. The 1.8× focal disagreement was two different points on this same line.

## What is still open

- **Fourteen frames remain above 20 px.** They are where the line detector finds little, not where
  the camera is wrong.
- **The line was fitted to a solve that had already used three hand-aligned anchors.** The
  anchor-free solve strings out over 108 m rather than 21, so its line is the same direction but a
  worse-conditioned fit. Whether the 1-D search finds the same point from that start is untested,
  and it is the thing to test next, because it decides whether any of this needs a human.
- **One clip.** The direction here is nearly the line of sight; on a broadcast camera further out
  it may not be, and the search span would need to follow the fitted direction rather than assume it.
