# 18 clips against the truth: 0.98–6.43 m out, and the focal explains 94 % of it

Measured 2026-08-17, working half only. `the-metric-cannot-see-depth-2026-08-16.md` said camlab's
camera is **1.2–5.0 m** from an externally measured one, on four clips. This is eighteen, solved the
same way, and it does not just confirm that — it says what the metres are made of.

## The comparison

Every clip ingested at 240 frames, anchored by AVATAR's PnLCalib, solved by the shipped chain, and
compared to WorldPose in metres, degrees and pixels.

| | median | range |
|---|---|---|
| **position** | **3.69 m** | 0.98 – 6.43 |
| rotation | 0.635° | 0.129 – 0.869 |
| focal ratio (ours ÷ truth) | **0.979×** | 0.944 – 1.005 |
| reprojection of the pitch | 6.5 px | 3.6 – 10.7 |

Eighteen of twenty-three solved. The five that did not are exactly the four with no PnLCalib anchor
and the one AVATAR's own `KNOWN_HARD` refuses — `MOR_POR_181952`. **Every clip that got an anchor
got a camera; every clip that did not, did not.** Their rotation errors are 6.7–51°, which is not a
degraded camera but a different one.

## What the metres are

**The focal is short on 16 of 18 clips, by a median of 2.1 %.** And:

    position error  vs  focal ratio      r = -0.97
    position error  vs  reprojection     r = -0.19

The first number is the whole finding. A correlation of −0.97 over eighteen clips is not a hint that
the focal/distance degeneracy is involved; it is the degeneracy, drawn against an external ruler.
camlab lands with a slightly short focal and a correspondingly near camera, and the ratio of the two
is fixed by the geometry — which is precisely what `m2-paint-alone-cannot-pin-the-position.md`
derived from the plane and what `the-camera-moves-along-a-line-and-that-is-the-bug.md` saw as a line
in the free solve's positions. Neither could see which point on the line was right. This can, and
the answer is: not the one the paint picks, by about 3.7 m and 2 %.

The second number is why nobody noticed. **Being 3.7 m from the truth moves the pitch in the image
by 6.5 px.** The correlation between how far the camera is and how wrong the picture looks is
−0.19 — nothing. A camera metres away reprojects the pitch to within ten pixels, so no image-space
metric, however careful, can charge it.

## What this does and does not settle

**It confirms the 1.2–5.0 m claim and widens it to 0.98–6.43 m** on four times the clips, from four
matches rather than four clips. The direction is consistent: short focal, near camera.

**It does not say the paint metric is broken.** `across` answers "does this camera put the markings
on the paint" and it answers it correctly — camlab scores 1.9–3.3 px where the ground-truth camera
scores 5.6–20.8 px on the same frames, and that ordering is real. The paint is a fine instrument for
the question it asks. It simply cannot ask this one, and the reprojection column is the proof: the
two cameras differ by metres and agree in the image.

**It does not fix anything.** Nothing here proposes a change. What it provides is a ruler: any
future claim about camera position can now be checked in metres on eighteen clips, and the
[[held-out]] half of the matches is still untouched for the claim that eventually matters.

## The bug I nearly published

The first run of this table reported camlab **42.07° and 4275 px** from the truth on
`CRO_MOR_180400` — a clip the paint scores at 2.54 px. That is impossible, which is what made it
findable.

`import_worldpose_gt.py` had refused any clip whose window does not start at source frame 0, on the
grounds that "silently off-by-N is the whole failure mode here". AVATAR's `new_clip_anchor.py`
scans the video for a frame PnLCalib can solve and ingests a window centred there, so offsets are
now normal — `CRO_MOR_180400` starts at 1320. I taught the import to slice the GT at `first + i`
and **did not teach the comparison the same thing**, so it read camlab's frame `i` against the
truth's frame `i`.

The tell was that the error tracked the offset exactly: every clip starting at 0 came out
0.31–0.87°, every clip that did not came out 5.7–59.5°, rising with the offset. Fixed, and checked
in both directions — the offset clip goes 42.07° → 0.858°, and the six clips at offset 0 do not move
by a digit, including the two the original finding quotes.

Half a fix is worse than none: it turns a refusal into a wrong number.
