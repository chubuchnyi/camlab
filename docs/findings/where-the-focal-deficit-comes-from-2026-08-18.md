# The focal deficit is not the model, not the objective, and not the distortion

Measured 2026-08-18, after `the-focal-deficit-is-real-and-the-constant-is-not-2026-08-18.md` showed
that scaling the focal by a constant removes a third to a half of camlab's position error on five
matches, including one it was not fitted to. A 2 % systematic that reproduces across five stadiums
is not noise. This asks what generates it, and answers most of the question by elimination.

## The ladder

Each rung renders the pitch with WorldPose's own camera and asks what focal a fit wants. No clip is
solved; nothing depends on camlab's chain. The last two rows are camlab itself, for scale.

| what is fitted | focal ratio |
|---|---|
| camlab's model to perfect points, no distortion | **0.9990** |
| camlab's model to perfect points, with distortion | 1.0080 |
| camlab's model to perfect points, true principal point | 1.0089 |
| camlab's **line objective** to perfect lines, no distortion | **0.9993** |
| camlab's line objective to perfect lines, with distortion | **1.0088** |
| `refit_frame_lm` on REAL paint, **started at the truth** | **0.9853** |
| the shipped chain | 0.9808 |

Read down the first four rows: given evidence that is exactly right, camlab recovers the focal to
within a tenth of a per cent. **The pinhole model is not the cause. The principal point pinned to the
image centre is not the cause. The line objective is not the cause. The 105×68 template is not the
cause** — and that last one also follows from geometry, since scaling a plane and the camera's
distance to it by the same factor leaves the image identical, so a template scale error moves the
position and cannot move the focal.

## The distortion pushes the other way

This was the obvious suspect and it is refuted by its sign. WorldPose carries radial distortion, and
fitting a distortion-blind model to a distorted rendering wants a focal **1 % LONGER**, not shorter —
+0.80 % on points, +0.88 % on lines, consistently, on 27 clips.

So the distortion does not merely fail to explain the deficit; it is working against it. Whatever
pulls the focal down has to overcome that first, which makes the real pull about **2.4 %**, not 1.9.

Two corrections to how this repo has been quoting distortion. Its magnitude is **17–37 px at the
image corners** but only **2–3 px over the region where the pitch actually is**, and it is the
second number that matters for a fit that only ever sees pitch markings. And
`the-paint-metric-scores-a-correct-camera-5x-apart` reads the truth's paint score as 5.6–30 px; that
is `across`, the **worst** marking of a frame. The truth's *median* line offset against detected
segments is 1.5–3.1 px, which is a different and much better-behaved animal.

## What is left is the evidence

The sixth row is the finding. Put the solver exactly on the truth, hand it the real detected
segments, and it walks the focal **down 1.5 %** — while improving its own residual hugely: 96.28 px
to 1.37 on `ENG_FRA_231054`, 28.34 to 1.26 on `MOR_POR_191625`.

**The solver is not failing. It is succeeding, at a target that is displaced.** The truth is not
where camlab's evidence says the optimum is, and the gap is the deficit.

That relocates the whole question. The register has been treating the deficit as the focal/distance
degeneracy — but the degeneracy is only the reason a small error in the evidence turns into metres
of position. It is the amplifier, not the source. The source is upstream of the objective, in what
`detect_segments` hands it.

## Inside the evidence: it is where the lines are, not which ones or which way they point

Three more rungs, each holding the constraint set fixed and changing one thing. All start the solver
exactly on the truth, on the same real frames.

| the detected segments, but… | focal ratio |
|---|---|
| as detected | 0.9853 |
| junk removed — every segment >25 px from any true marking dropped | 0.9850 |
| **each segment rotated to its marking's true direction**, position kept | 0.9848 |
| **each segment shifted onto its marking's true line**, direction kept | **1.0119** |
| both | 1.0144 |

**It is the perpendicular offset, and only that.** Fixing every line's angle changes the focal by
five ten-thousandths. Fixing every line's offset moves it 2.7 % and lands where the distortion alone
says it should — 1.0119 against the 1.0088 the same fit gives on perfectly projected lines. Correct
the offsets and the deficit is not reduced, it is gone, and what remains is the distortion pushing
the other way.

Two hypotheses die here, and one of them was mine an hour earlier.

**Junk detections are innocent.** 36 of 276 detected segments — 13 %, about one and a half a frame —
lie more than 25 px from any true marking. Dropping all of them moves the focal from 0.9853 to
0.9850, and on four of the six clips the result is identical to the digit, which means `line_errors`
was already refusing to match them. The count was real and the inference from it was wrong.

**And the angular error is a red herring.** Detected lines are off by a median 0.233° (p90 1.267°),
which looked like enough to move a vanishing point. It is not: fixing it does nothing.

## The offset, measured in the units that show it

The reason this was missed is that I first measured the offset in **pixels**, got −0.168 px, and
concluded it was far too small to matter. That measurement was correct and the units were wrong. A
line running away from the camera is foreshortened, so a large sideways error on the grass is a
small one on the screen — and the fit reasons about the grass.

Back-projecting each detected segment onto the pitch with the truth's own camera, over 257 segments:

| | median offset toward the camera | median depth |
|---|---|---|
| near third | **+21.4 cm** | 66.8 m |
| middle third | −4.3 cm | 86.8 m |
| far third | −6.8 cm | 104.1 m |

`r(depth, offset) = −0.26`. The near markings are found about 21 cm nearer the camera than they are,
the far ones about 7 cm beyond — roughly a 28 cm swing across the pitch, which stretches the pitch in
depth and is exactly the kind of deformation a focal absorbs. In pixels the same thing is a fifth of
a pixel and invisible.

**That is the cause: `detect_segments` places markings with a depth-dependent lateral bias of tens of
centimetres on the ground.**

## Down one more layer: nothing is grossly misplaced

The chain from pixels to a line is: `ridge_map` scores paint, a threshold makes a mask, `thin`
reduces the mask to a one-pixel spine, a distance transform is built from the spine, and Hough reads
lines off that. Each hand-off was measured.

**The detected line sits on the spine exactly** — median difference 0.000 px over 155 segments. So
`detect_segments` adds nothing; whatever is wrong is already in the spine.

**And the spine sits on the ridge's own peak**, within half a pixel:

| clip | thin (far) markings | peak offset |
|---|---|---|
| `CRO_MOR_180400` | n=67 | +0.0 px |
| `MOR_POR_191625` | n=74 | +0.5 px |
| `ENG_FRA_231054` | n=53 | +0.5 px |
| `ARG_CRO_220954` | n=66 | +1.0 px |

**So there is no gross misplacement to find, and a mechanism I nearly published is wrong.** The
first clip measured was `ARG_CRO_220954`, whose spine sits a full pixel off the ridge peak with the
response actually NEGATIVE at the line — which is the signature of morphological thinning choosing a
side on an even-width structure, a real effect with a deterministic direction, and a tidy story. The
next three clips refute it. One clip in four is not a mechanism, and the register already carries
*"#17 was right — it measured on `fan`, the weakest of the six"* for exactly this.

## What the cause actually is, stated no more strongly than it was measured

**The deficit is sub-pixel error in where the spine falls, turned into tens of centimetres by
foreshortening.** Every step is individually accurate to a fraction of a pixel and the composition
is still worth 2.4 % of focal, because a line running toward the horizon converts a third of a pixel
into a quarter of a metre of grass.

That it is a *bias* and not noise is settled by the depth trend — +21 cm near against −7 cm far
would average away otherwise, and the focal deficit reproduces on five matches. **What makes the
sub-pixel error prefer a direction is not established.** Candidates, written here before measuring
so that testing them counts: the partial-volume effect as a stripe narrows below one pixel, with the
sub-pixel phase correlating with image position; asymmetric neighbours on the far side of the pitch,
where markings sit against boards and crowd rather than grass; and the threshold in
`over & (val >= RIDGE_MIN_V) & (surface > 0)` biting one edge of a stripe before the other.

The practical reading is that this is a precision limit rather than a mistake, which is why the
constant correction is worth keeping while the search continues.

## What this changes

**The constant correction stays a correction, not a fix.** It is worth what it measures — 3.69 m to
2.51 m on the working half, 2.76 m to 1.48 m on a held-out match — and it is now known to be
compensating for something in the evidence rather than for a missing model term. That is a reason to
keep looking, not a reason to withhold it.

**And the correction is not the freezing.** The control matters: re-fitting rotation and position
with the focal held at its OWN value, changing nothing else, moves the position error not at all —
3.69 m to 3.69 m, and 2.76 m to 2.76 m. The gain is the constant. `scripts/apply_focal_correction.py
--scale 1.0` is that control and it stays in the tree.
