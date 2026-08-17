# The carry buys nothing when every frame is refitted — and flow cannot replace SIFT

> **Corrected the same day — the second half does NOT transfer to the shipped chain.** Asked of
> `solve_carry` itself with `--no-carry`, over every clip, the answer is six clips better, two a
> wash and **two clearly worse** — `ENG_FRA_232015` +0.65 px and `fan` +0.41, which are the two
> clips where the camera MOVES. And the focal moves 6.6 % on `fan`, up to 23 % on a clip `across`
> cannot judge at all — the focal/distance degeneracy, which the carry constrains and the paint
> cannot reward. Worse, the judge is the paint, which this repo has since measured to PREFER a camera
> 1.2-5.0 m out of place. **The stage stays.** See
> `the-carry-does-not-survive-the-shipped-chain-2026-08-17.md`.
>
> The FIRST half stands and is unaffected: optical flow cannot replace SIFT, and it fails on
> accumulation exactly as this document predicted it had to be tested for.

Measured 2026-08-17, from a question about real time and answered by a control nobody had run.

Two results, and the second is the one that matters:

1. **Optical flow cannot replace SIFT.** It agrees per pair to 0.018–0.360 px and **fails on
   accumulation**, which is what the per-pair table could never have said. On `fan` it scores
   90 frames of 119 against SIFT's 119, and its p90 is 26.53 px against 2.26.
2. **Neither of them buys anything.** On seven clips, in a loop that refits every frame against its
   own paint, carrying the previous camera through the measured homography and **carrying nothing
   at all** give the same answer to within noise — and SIFT costs 75–185 ms a frame.

## What was run

`scripts/track_causal.py` is `solve_carry` with one anchor, one direction and nothing downstream:

    seed the anchor from the chain's own answer -> for every frame after it:
        measure the motion from the frame before      (SIFT, flow, or NOTHING)
        carry the previous camera through it
        refit against this frame's own paint

The same loop with three motion sources, so a difference is the motion's and nothing else's. Scored
with `frame_residual`'s `worst_across_px` — the camera alone — against the shipped
`camera_polished.json` on the same frames.

## 1. Flow tracks a pair and loses a clip

`findings/making-it-fast-again-2026-08-16.md` §10 measured flow agreeing with SIFT to a median of
0.018–0.360 px over the whole frame at 15–36× the speed, and said in as many words that the test
was not that table: *"`solve_carry` ACCUMULATES these maps over up to sixty frames, and the worst
pair disagrees by 2–7.8 px."*

It does accumulate, and flow does not survive it. On `fan` — a phone from the stands through a
1.61× zoom, the clip whose camera actually moves:

| `fan`, 119 frames | frames scored | median | p90 | worst | under 20 px |
|---|---|---|---|---|---|
| no motion | 119 | 1.84 | 2.23 | 20.42 | 118/119 |
| **flow** | **90** | 2.06 | **26.53** | 37.65 | **69/90** |
| SIFT | 119 | 1.83 | 2.26 | 34.98 | 117/119 |

Twenty-nine frames stopped scoring at all — the camera drifted until no marking held eight samples
— and the p90 went from 2.26 px to 26.53. Flow produced a homography for every pair; they were
simply wrong enough, often enough, to walk the camera off the pitch.

**A median of 0.018 px and a tail of 7.8 px is exactly the shape where agreement per pair says
nothing.** The tail is what a chain integrates.

## 2. And the motion buys nothing anyway

The control — carry NOTHING, let the refit start from the previous frame's camera — was run
because flow and SIFT came out identical on `broadcast` to two decimal places, which is not what
two different instruments usually do.

| clip | no motion, median / p90 | SIFT, median / p90 | under 20 px |
|---|---|---|---|
| `broadcast` | 3.04 / 5.74 | 3.04 / 5.36 | 59/59 both |
| `fan` | 1.84 / 2.23 | 1.83 / 2.26 | **118** vs 117 of 119 |
| `CRO_MOR_194948` | 4.10 / 5.62 | 4.09 / 5.60 | 119/119 both |
| `g14604660` | 2.03 / 2.36 | 2.03 / 2.59 | 39/39 both |
| `ENG_FRA_232015` | 3.47 / 13.83 | 3.27 / 14.30 | **179/179** vs 177/179 |
| `wp_194948` | 4.07 / 5.09 | 4.08 / 5.08 | 119/119 both |
| `g11710897` | 17.34 / 25.19 | 17.46 / 26.90 | **28** vs 24 of 39 |

Seven clips, and on none of them does the measured homography improve the camera. On three it is
very slightly worse. SIFT costs **75–185 ms a frame** to achieve that.

The mechanism is not mysterious once stated: consecutive frames at 30 fps turn by **0.06 degrees**,
which this repo measured itself, and the refit that follows fits the camera to the frame's own
paint. The carry is putting the seed in a basin the seed was already in.

## What this does NOT say

**It does not say `measure_pairs` should be deleted.** Four things differ between this loop and the
shipped `solve_carry`, and each could reverse the result:

* This refits **every** frame with `free_position=False`. The chain runs `solve_carry` with
  `--free-position`, and the comment at the carry says the position was HELD for a measured reason:
  the free solve *"wandered 2.9 / 4.7 / 2.1 m per axis with a single-frame step of 11.5 m"*.
* This is seeded from the chain's own polished answer at frame 0 — a good camera. `solve_carry` is
  seeded from a hand anchor or a bootstrap, which is not.
* This goes one direction from one anchor. `solve_carry` walks outward from several, in both
  directions, and its whole design is about drift over the longest chain a frame sits on.
* The carry should matter exactly where the **refit fails** — a frame with few markings, a player
  across a line — and in these runs the refit rarely failed. `solve_selfheal` exists for those
  frames and was not in this loop.

**And it does not say the chain is redundant.** The tracker is worse than the chain on every clip:
`broadcast` 3.04 against 2.81, `ENG_FRA_232015` 3.47 against 2.96. Four non-causal stages buy that,
and a live stream cannot have them.

## The test that would settle it

Run the shipped chain with the carry disabled — `solve_carry` with an identity homography, or with
`measure_pairs` returning nothing — over every clip, and compare `across` and the marking count.
That is the same shape as #17's re-solve sweep and it is the only thing that can retire a stage
this repo's cameras all descend from. If it holds there, SIFT is 11 s of a 24 s `carry` stage and
75–185 ms of every causal frame, bought for nothing.

## Real time, with what is now known

A causal frame on `broadcast` is decode + paint + segments + refit, and the motion is optional:

| | full resolution | paint at 0.5 |
|---|---|---|
| paint + refit | 57–65 ms | 36 ms |
| + flow at 0.5 | +20 ms | +20 ms |
| + SIFT | +179 ms | +179 ms |

Against a 40 ms budget: **paint at half resolution and no motion at all is 36 ms and inside it.**
Half resolution costs 1.97 px of median accuracy on `broadcast` (3.04 → 4.78), which is a real
price and a separate decision from this one.
