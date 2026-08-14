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

## First result: the turf detector had locked onto the sky

Before any of the above could be worked on, the surface mask turned out to be wrong for a reason
nobody had guessed. `_turf` finds the frame's dominant bright saturated hue and calls that grass,
with **no bound on where the hue may be**. On `g11710897` at dusk the biggest bright saturated
region in the picture is the sky, so the peak came out at hue **108** — blue.

| | before | after |
|---|---|---|
| turf mask, top quarter of frame | **100 %** | 0 % |
| turf mask, bottom half | **2 %** | 68 % |
| markings scored on the operator's anchors | **1** | **7** |
| worst line on those anchors | 1.98–13.27 px | 22.5–31.1 px |

The error got **worse and became true**: one marking at 2 px is not a measurement, seven markings
at 25 px is. The fix bounds the peak search to `GRASS_HUE_RANGE = (25, 95)` — the hue is still
measured from the frame and the width around it is unchanged, it simply refuses to call something
grass that no grass is, and returns nothing at all when there is no green in the picture.

No other clip moved: `fan` 1.68, `broadcast` 2.56, `CRO_MOR_194948` 3.68, `NET_ARG_225042` 5.84,
`14604731` 1.24, `wp_194948` 3.41 — identical before and after, because their peaks were already
green.

## Where to start

The measurable first target is the surface mask, because three separate things depend on it and it
is currently wrong on exactly these clips: it decides which paint is scored, it is what the "paint
found in the trees" comes from, and it is what a horizon estimate would be built on.

Target: on `g11710897` and `g14604660`, the surface mask must stop at the boards. A camera-free
check exists and currently fails — "where does the grass stop" should read 40–60 % of frame height
on these clips and reads 0 %.


---

# Three of the branch's four items, resolved the same day

## The surface mask now stops at the boards — target met

Fixed by the sky repair rather than by anything aimed at it. The camera-free check I set as the
target reads:

| clip | top of grass, before | after |
|---|---|---|
| `g11710897` | 0 % of frame height | **42 %** |
| `g14604660` | 51 % | 51 % |
| `broadcast` | 38 % | 38 % |
| `fan` | 0 % | 0 % — correct, it is a crop with no sky in it |

## The ridge scales do not need widening — refuted

The measured fact stands: shot from the touchline the near part of a line is 32 px wide against a
largest scale of 7. The conclusion drawn from it does not. Projecting through the operator's own
anchor — the only camera on that clip that scores anything — and asking what each detected line
lies on:

| frame | scales | lines | on markings | junk |
|---|---|---|---|---|
| 0 | (2, 4, 7) shipped | 6 | **6** | **0** |
| 0 | (3, 6, 12, 24) | 13 | 6 | **7** |
| 1 | shipped | 5 | 3 | 2 |
| 1 | (3, 6, 12, 24) | 12 | 7 | 5 |

The shipped scales already find every marking on frame 0 and add no junk at all. Widening doubles
the junk for at best a wash. The detector copes with a line three times wider than its largest
scale, and the number that said otherwise was a fact about the paint, not about the detector.

*A caveat on how this was nearly got wrong:* the first run of this comparison projected through
`camera_smooth.json` and reported **zero** of the detected lines as markings on a frame where six
of them are. That clip has no trustworthy camera — its verdict is NO VERDICT — so "distance from a
line to a marking" could not be computed at all. The operator's anchor is the only camera there
that scores, and it is what the table above uses.

## What actually kept `g11710897` unsolvable

Not the detector, not the scales, not the surface. Scored frame by frame:

| | worst line | markings |
|---|---|---|
| the operator's anchor | 22.51 px | **7** |
| `camera_start.json`, and every stage after it | 16.61 → 9.39 px | **3** |

The seed sits at focal 2778 against the anchor's 2100 — 32 % out — and that difference is exactly
four markings pushed off the picture. Its 9.39 px is a max over three of them, the anchor's 22.51 a
max over seven, and **those are not the same statistic**.

The anchor chooser added that morning ranked them by the number alone and took the seed. So the
chain ran from a camera that had already thrown the pitch away, on every one of the operator's
twelve anchors. Fixed: markings first, error second.


---

# `g11710897` has a verdict for the first time

| | markings/frame | worst line | verdict |
|---|---|---|---|
| before | 3 | 8.47 px | **NO VERDICT** |
| after | **7** | 18.45 px | **4 of 8 supported frames under 20 px** |

**The number got worse and became real.** 8.47 px was a max over three markings and meant nothing;
18.45 over seven is a measurement, and one that can be improved. This is the carry stage alone —
self-heal, shared centre, smoothing and polish have not run on it yet.

Three defects had to be removed to get here, and all three were in code written the same day:

1. **The turf detector had locked onto the sky**, so the "playing surface" was the sky and 2 % of
   the grass. The operator's anchors went from 1 marking to 7 the moment the hue peak was bounded
   to hues grass can be.
2. **The anchor chooser ranked by the error alone**, so the operator's 22.51 px on 7 markings lost
   to the seed's 16.61 px on 3 — and the seed's focal is 32 % out, which is exactly what had pushed
   four markings off the picture. Ranks by markings first now.
3. **The seed snapshot lost the anchors.** The pipeline copies a seed it is about to overwrite to
   `camera_seed_used.json`; the edits stay keyed to the original name; the lookup found none and
   every anchor was quietly refitted from the seed's own pose. The anchor *list* printed correctly
   throughout, which is why it survived a whole run unnoticed.

## What is visibly next on this clip

The carry drifts between anchors: frame 20 comes out at focal 972 and frame 35 at 1709, against
2100 at the anchors either side. The markings hold at 7 throughout, so the drift is in the camera
and not in what can be measured — which is the situation the rest of the chain exists for, and it
has not run yet.


---

# What a run directory says it is, and what it is — 2026-08-14

Asked what I would carry into the working solution. Checking the state of `g11710897` to answer
honestly turned up two defects underneath the answer, and both had been shaping conclusions for a
day.

## The chain's declared result was three fixes out of date, on eight of nine clips

`camera_smooth.json` is what `FINAL_CAMERA` resolves to — the file anything downstream opens. On
`g11710897` it held focal **2777**, the pre-fix seed that scores three markings. The `camera_carry.json`
beside it, six hours newer, held **2100**: the operator's own anchor, scoring seven.

My own 3000 s timeout had killed that run after the carry stage, and nothing removed the stages
that no longer had an input. Checked across every run directory afterwards:

| | |
|---|---|
| clips holding a downstream output older than its input | **8 of 9** |
| clips where the stale file was `camera_polished.json`, the chain's declared result | **6** |
| how far behind | 5.9 – 6.7 hours |

The six polished files were written at 09:0x when polish was measured; the multi-anchor re-solve
rewrote `camera_smooth.json` under them at 15:1x. So the polish gains recorded in `pipeline.py`
were true when taken and describe nothing that is on disk now — they are dated in the source as of
this commit, not deleted, because they will be re-measured rather than guessed at.

`run()` now deletes every output it is about to write before writing any of them. A killed run
leaves gaps; gaps make readers fail loudly, and a stamp only helps the readers that check it.

## Three of the twelve anchors were the seed written back, and the twelve were not being read

The anchor list came back `[0, 2, 39]` where the run of 13 Aug had used twelve. The store holds
both, under two keys — and the operator had aimed while the viewer was showing each:

| key | entries | frame 0 holds |
|---|---|---|
| `camera_start.json` | 3 | focal 2778 at (0, −75, 20) — **the seed's own frame 0** |
| `camera_smooth.json` | 12 | focal 2100 at (56, 25, 1.5) — a phone at head height |

**An entry equal to the solve is not an aim,** and the separation is not close:

| | d_rot | d_pos | d_focal | |
|---|---|---|---|---|
| frame 0 | 2.47e-05 | 0.0000 | 0.0592 | nothing was moved |
| frame 2 | 2.01e-01 | 59.50 m | 571.94 | aimed |
| frame 39 | 2.74e-01 | 55.00 m | 0.0592 | aimed |

Four orders of magnitude between the viewer's write rounding and the smallest real aim, so the
tolerance is safe from both sides — 1e-4 rad is twenty times finer than the viewer's smallest
rotation step. Dropping these costs nothing, because `solve_carry` already scores the seed's own
pose as a candidate at every anchor; what they added was three phantom entries in the anchor list.

## Reading every key: implemented, then refuted

The entries are absolute world poses, so an aim made against one solve is a perfectly good anchor
for another. I implemented that and it is wrong, for a reason no amount of reasoning would have
produced:

- **The broadcast test needs the solve the entries overlay, and the next run overwrites that file.**
  `fan` went to **114 anchors on a 120-frame clip**, from five keys whose reference files have all
  been rewritten since the edits were made.
- **A shared position does not mark a broadcast.** All twelve of `g11710897`'s aims sit at exactly
  (56, 25, 1.5) — the phone does not move, and only the rotation was aimed. This filter looked
  obvious and would have deleted **exactly the pitch-level case this branch exists for**.
- **File mtimes cannot date an entry.** `camera_manual.json` is rewritten whole on every edit, so
  its timestamp is about the newest edit anywhere in it. The test called `g11710897`'s good
  reference stale and `fan`'s five overwritten ones current — the wrong answer on both.

So old edits cannot be classified after the fact. The read stays narrow; the **silence does not**.
`unread_aims()` reports what is on disk under other keys and `run()` prints it, because the failure
that actually happened was not a wrong choice — it was twelve aims sitting on disk while the clip
was called unsolvable, with nothing connecting the two.

The real repair is at write time: the viewer should record, in the entry, the pose it was aimed
away from. Then "was anything actually moved" is answerable forever without a file that moves.

## What this leaves

The operator's aims are split across two keys and **no seed reads both** — frames 2 and 39 are real
aims under `camera_start.json`, and the run now under way is seeded from `camera_smooth.json`, so
it is using twelve and reporting those two as unread. That is a real cost of the narrow read and
the reason the write-time stamp is worth doing.
