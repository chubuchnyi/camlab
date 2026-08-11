# Is it worth fine-tuning a model for this?

Asked 2026-08-11. Answered by measuring which half of the problem is actually failing, because
"detection" and "correspondence" want completely different answers.

## The measurement that decides it

Broadcast clip, camera **known to be right** (#119, 1.4 px). For every pitch marking the camera
projects into frame but the pipeline fails to match, ask a simple question: **is there paint under
where the camera says the line is?**

| | |
|---|---|
| matched | 20 |
| **missed, with paint plainly under them** | **9** (63–100 % of their length) |
| missed, with no paint | 2 |

**82 % of the failures are correspondence, not detection.** The paint is there. The detector found
it. The matcher lost it.

And the reason turned out to be one line of arithmetic:

```
marking  3: projects 2423 px, best candidate angle 0.7 deg, offset 0.2 px, overlap 24 %
            -> REJECTED, overlap 24 % < 25 %
marking  1: projects 11115 px (a touchline running far beyond the frame)
            -> no detected segment can ever cover 25 % of that
```

An offset of **0.2 px** discarded by one percentage point, and long lines structurally unmatchable
because overlap is measured against the full projected length rather than the part inside the
frame. Filed as task #16.

## So: a model?

**Not yet, and the measurement says why.**

**A segmentation model would fix 2 of 11 misses.** That is the share that is genuinely a detection
failure. Everything else is ours.

**A model with LINE CLASSES would fix all 11** — with names, correspondence stops being a search
and becomes a lookup. That is the real prize, and it is the thing no classical method here has
produced: our detector says "a painted line", never "the goal line".

But three things stand between here and that, and two of them are not technical.

**1. The labels are licence-blocked.** Per-pixel line classes for football exist essentially only
in SoccerNet, whose own FAQ restricts it to research; the models trained on it (PnLCalib, TVCalib,
the SoccerNet baseline) inherit that, and PnLCalib is additionally GPL-2.0-only. The one MIT
alternative, soccersegcal, emits six regions rather than line classes — the wrong output. Training
our own needs labels we do not have the right to use.

**2. We cannot yet evaluate one.** The metric had a fundamental flaw found two days ago and still
carries the overlap bug above. Choosing or training a model against a measurement we do not trust
is exactly the mistake this project spent a week undoing at the solver level — `solve/ptz.py` was
converged, precisely, on the wrong objective.

**3. The cheap wins are not spent.** `adaptiveThreshold` measured better on 6 of 9 clips for the
cost of one function call. The turf stage collapses on two clips and has not been looked at. The
overlap bug is arithmetic. None of that is a week of work, and all of it changes what a model would
have to beat.

## What would change the answer

**Self-labelling.** Where a camera is trustworthy, projecting the pitch model through it labels
every marking pixel with its class, for free and with no licence attached. The broadcast clip's 60
frames are already that. It is the only route to line-class labels this project can legally own.

The catch is circular and worth stating plainly: it works where we already have a good camera, and
the clips that most need a model — daylight amateur, where the paint stage collapses entirely — are
exactly the ones where no camera can be solved to generate labels from. Breaking that circle needs
either hand-placed cameras on a few diverse clips (task #7 now makes that possible) or a
bootstrapping loop, and both are real projects rather than an afternoon.

**The free upgrade nobody has taken.** PnLCalib already computes a dense per-pixel line map and
discards it: `pnlcalib_backend.py:124` slices `heatmaps_l[:, :-1]`, cutting the 24th channel, and
keeps 23 channels that are two Gaussian blobs per segment end. Returning it costs one array slice.
That is line-class evidence for zero training — for anyone who can live with the licence.

## The recommendation

1. Fix the overlap length (#16). It is arithmetic and it is currently costing 82 % of matches.
2. Re-measure everything: the ranking and the 4.4 px reference were both computed with those misses
   in them.
3. Swap the fixed ridge threshold for `adaptiveThreshold`, and look at the turf stage.
4. **Then** ask this question again, against a metric that works and a pipeline whose known bugs
   are out. If names are still the bottleneck at that point — and they may well be — the answer is
   a model, and the honest path to it is self-labelling from cameras we placed by hand.

Training now would be optimising against a broken ruler to fix a problem that is 82 % our own
arithmetic.
