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

## What inside the evidence — not yet settled

One mechanism is measured and does **not** account for it. Detected lines sit slightly INWARD of the
true markings, median −0.168 px, mean −0.467 px over 240 matched segments. The direction is right —
pulling markings toward the centre makes the pitch look smaller and the focal short — but the size
is not: the displacement is flat with radius (−0.186 px inner, −0.164 px outer, r = −0.12), and a
near-uniform shift does not change scale. Sub-pixel line placement is not the generator.

The candidate still standing is **which marking a detected segment gets matched to**, and there is
now a number attached to it: **36 of 276 detected segments — 13 %, about one and a half per frame —
lie more than 25 px from ANY true marking.** They are not markings. Whatever they are, `line_errors`
still has to assign each of them to something, and a segment assigned to the wrong marking is not a
small error: it is a constraint pulling the camera toward a different, self-consistent, wrong scale.
That would be stable across clips for the same reason the pitch looks the same in every stadium —
which is the property the deficit has.

Measuring that is the next step and it is not done here. What can be said is that the evidence is
13 % junk by count, that the junk is not accounted for anywhere in the ladder above, and that it is
the only candidate left standing after the model, the objective, the template, the principal point,
the distortion and sub-pixel line placement have each been eliminated on the numbers.

## What this changes

**The constant correction stays a correction, not a fix.** It is worth what it measures — 3.69 m to
2.51 m on the working half, 2.67 m to 1.18 m on a held-out match — and it is now known to be
compensating for something in the evidence rather than for a missing model term. That is a reason to
keep looking, not a reason to withhold it.

**And the correction is not the freezing.** The control matters: re-fitting rotation and position
with the focal held at its OWN value, changing nothing else, moves the position error not at all —
3.69 m to 3.69 m, and 2.67 m to 2.67 m. The gain is the constant. `scripts/apply_focal_correction.py
--scale 1.0` is that control and it stays in the tree.
