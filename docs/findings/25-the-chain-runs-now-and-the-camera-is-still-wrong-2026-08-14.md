# #25: the chain runs end to end now, and needs wider ridge scales

> **Section 4 of this file is wrong and is kept with its correction at the end.** It claimed the
> camera was mis-solved; that was a bug in my overlay, caught by the operator's eye within minutes
> of my publishing it. The title has been changed to stop the claim spreading.

Two separate results, and conflating them would be the mistake.

## 1. It was never slow. It was deadlocked.

`g11710897` had been "an hour per run" since 2026-08-13, and four runs were abandoned to it. The
carry stage is **22 seconds**.

`verdict.judge` is the last thing `solve_carry` does and the only caller of `parallel.map_items`,
so when `default_workers()` went from 1 to 2 the hang landed at the end of **every solve**:

| | |
|---|---|
| fork, 2 workers | still hung at 3000 s — parent and both children in `futex_do_wait` |
| spawn, 2 workers | **22 s** |
| no pool at all | 23 s, and every reported number identical to the spawn run |

**The mechanism is not established.** The obvious candidate — forking after OpenCV has started its
threads, so a child inherits mutexes held by threads that do not exist in it — did not reproduce on
a synthetic probe: cv2 in the parent and cv2 in eight forked children completes fine. So the fix is
`spawn`, and what is written down is what was measured.

It cost two days because a hang and a slow stage are indistinguishable from outside — the more so
with `pipeline.run` buffering a stage's output until it exits (task #33).

## 2. The full chain, for the first time, and every stage earns its place

158 seconds, all five stages, on the operator's twelve anchors:

| stage | across | worst line | markings | under 20 px |
|---|---|---|---|---|
| carry | 20.41 px | 13.72 | 7 | 24/40 |
| self-heal | 17.58 | 12.92 | 7 | **36/40** |
| shared centre | 12.96 | 8.36 | 6 | 33/40 |
| smooth | 9.27 | 6.66 | 6 | 36/40 |
| polish | **9.16** | **6.66** | 6 | **36/40** |

## 3. The ridge scales DO need widening, and this branch said otherwise two days ago

On frame 39 the near touchline is **34–54 px** wide. `RIDGE_SCALES = (2, 4, 7)`:

| scales | segments | of those, on the foreground line |
|---|---|---|
| `(2, 4, 7)` — shipped | 7 | **0** |
| `(2, 4, 7, 14, 28)` | 10 | **5** |

All seven shipped-scale segments sit in the **43–50 % band** at the top of the playing surface —
the advertising hoarding and the grass/board junction — while the widest, most obvious line in the
picture contributes nothing at all.

Re-running the whole chain with the wider set:

| | `(2, 4, 7)` | `(2, 4, 7, 14, 28)` |
|---|---|---|
| across | 9.16 px | **4.34 px** |
| worst line | 6.66 | **3.09** |
| worst spot | 32.48 | **13.41** |
| under 20 px | 36/40 | **38/40** |

`worst spot` halving is the informative part: that statistic is the camera *plus* the detector's
holes, and the holes are what closed.

**This branch recorded the opposite on 2026-08-13** — "the ridge scales do not need widening,
refuted" — measured on frames 0 and 1, where the same line is far away and narrow. Both readings
are correct about their own frame. The real lesson is that on a pitch-level clip the painted width
varies by an order of magnitude *within a single frame*, so no fixed scale set serves it, and a
one-frame sweep will keep producing confident opposite answers. Left as a default plus a
`CAMLAB_RIDGE_SCALES` override until it is measured across the other clips.

## 4. And the camera is still wrong

The numbers above are not the test. Projecting the model through `camera_polished.json` and looking:

**the model's touchline lands on the advertising boards, and the broad white line filling the
foreground has no model line on it at all.** At 4.34 px.

So the metric is satisfied by the wrong correspondence. It is not measuring badly — every marking it
scores really is close to some paint — it is measuring against paint that belongs to a different
line. This is the missing input the anchor-automation note calls #2, *"which marking each one is"*,
and it is what blocks this clip, not the chain and not the detector's recall.

Two things follow:

- **`g11710897` is not solved, and no number in this file should be quoted as if it were.** Its
  honest status is: the chain completes, the evidence has improved, the pose is wrong.
- **#14's precision half is the blocker for #25**, which is worth stating because #14 was parked
  twice for want of data. The advertising hoarding is a non-marking that survives every filter
  measured so far, and here it is not a nuisance — it is what the solve is aligned to.


---

# Correction: section 4 was my rendering, not the camera

The operator looked at the overlay and said the yellow lay correctly, bar one piece. He was right
and section 4 above is withdrawn.

My overlay skipped any marking with an endpoint behind the camera:

    if np.any(q[:, 2] <= 1e-9): continue

A phone at 1.5 m standing beside the line has the near markings running *past* it — on frame 39 two
of them straddle the camera plane, one endpoint 54 m in front and the other **6.5 m behind**. Both
were dropped, and they are exactly the long lines crossing the foreground. So the broad white line
had no yellow on it because I did not draw it.

Clipping the segment at the camera plane before projecting puts them back: 7 markings drawn becomes
8, and the eighth runs the length of the foreground alongside the painted line, converging with it
at the right edge.

**What is actually true of this camera.** It is close and not exact: `across` 13.0 px on frame 39
against a 4.34 px median over the clip, and the visible error is an offset on the near line of well
under its own painted width (34–54 px). That is a camera to improve, not a camera that found the
wrong correspondence.

**What this cost.** Section 4 was committed, put in `STATUS.md`, and used to re-rank #14 above #25.
None of it was measured — it was one look at one picture I had drawn wrong, and I stated it as a
finding. The rule this repo already has ("the operator's eye is ground truth on a visual question")
exists for the case where my check and his disagree; here my check was the only one, and it was the
broken one.
