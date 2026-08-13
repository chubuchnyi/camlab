# The clips that actually matter are shot from pitch level, and nothing here is built for them

Branch `pitch-level-clips`, opened 2026-08-13 on the operator's word: a phone held at head height
beside an amateur pitch is **the main share of what this has to work on**, and every assumption in
the repo is broadcast-shaped.

## What such a frame is

`g11710897` frame 0, the operator's own anchor on it: position (56, 25, **1.5**) m. A phone at head
height, at the touchline. What that means for everything downstream, measured on that frame:

| | |
|---|---|
| model markings reaching the image | 7 |
| model markings reaching the **grass** | **1** |
| detected line segments | 6, longest 1083 px |
| painted-line width | median 4 px, **p90 32 px, max 33** |
| surface mask | 40 % of the image, and it runs to the top of the frame |

One marking is not a camera. Two lines fix a homography only with two more, and the frame does not
hold them. That is a property of the shot, not a failure of any detector, and it is the shape of the
problem this branch exists for.

## Three assumptions that break, each with its number

**The plausibility box is broadcast-shaped.** `bootstrap_clip.plausible` requires height 5–45 m and
ground distance 35–140 m. The operator's own camera on `g11710897` is at **1.5 m**, so the bootstrap
would reject the true camera outright — before any paint is consulted. On `broadcast` frame 0 that
box already throws away **89 %** of all hypotheses.

**The surface mask swallows the hedge and the trees.** They are the same hue as the pitch and
connected to it, so `_surface`'s biggest-component fill runs to the top of the frame. A camera-free
probe that reads "where does the grass stop" — which ought to separate a pitch-level camera from an
elevated one instantly — returns *0 % of the frame height* for `g11710897`, meaning grass everywhere,
on a picture with sky in the top third. It is also why the paint detector finds "markings" in the
tree canopy: the canopy is inside the playing surface as far as it knows.

**The ridge scales assume a broadcast lens.** `RIDGE_SCALES = (2, 4, 7)` brackets "the far touchline
at ~2 px to the goal area at ~14". Shot from the touchline the near part of a line is **32 px** wide.
Adding scales 12 and 20 grows the paint mask 44 % (23 806 → 34 238 px) and does not change the
marking count on this clip — so it is a real limit and not this clip's blocker.

## What such a frame does carry that a broadcast frame does not

None of this is used anywhere yet. Listed with what it would constrain, not as a plan:

- **The camera height is known to within a few centimetres.** A person holds a phone at 1.4–1.7 m.
  Broadcast height is a free parameter over a 40 m range; here it is nearly a measurement, and it
  attacks the focal/distance degeneracy directly.
- **The horizon is in shot.** On an elevated camera the pitch plane's vanishing line is off-frame and
  has to be inferred from two families of markings. Here it is visible as the line where the grass
  meets the boards, and every marking on the plane must vanish to it.
- **People are of known height and stand on the plane.** Two standing figures of equal height give
  the vanishing line by a construction that needs no markings at all.
- **Goal posts are 2.44 m by 7.32 m by law**, and at pitch level a goal fills enough of the frame to
  be measured rather than guessed at.
- **Mowing stripes are evenly spaced in metres** — already measured and already trusted on `fan`
  (11.00 m ± 2.3 % across a 1.61× zoom), and never yet used to find a camera.

## Where to start

The measurable first target is the surface mask, because three separate things depend on it and it
is currently wrong on exactly these clips: it decides which paint is scored, it is what the "paint
found in the trees" comes from, and it is what a horizon estimate would be built on.

Target: on `g11710897` and `g14604660`, the surface mask must stop at the boards. A camera-free
check exists and currently fails — "where does the grass stop" should read 40–60 % of frame height
on these clips and reads 0 %.
