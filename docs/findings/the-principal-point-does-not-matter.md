# The principal point is not determined by pitch markings, and it does not matter

This clip is cropped off-centre from a 1080×1920 source, so its optical axis is geometrically at
`(540, −334)` — 638 px outside the frame. Four of the five original solves nonetheless used the
image centre, `(540, 304)`. That looked like a plain error, and a landmine and a task were filed
against it.

**It is not an error, because the difference is unmeasurable.** Each principal point solved in its
own K from its own seed, through the same chain — carry, then self-heal:

| | cy | worst line | worst spot | frames under 20 px | samples |
|---|---|---|---|---|---|
| `camera_auto_full3` | 304 | 2.11 px | 14.52 px | 120/120 | 165 |
| `ax2` | **−334** | **1.78 px** | 14.79 px | 117/120 | 164 |

638 px apart, and they land within noise of each other — one slightly better on the worst line, the
other on three more frames. The camera's other six parameters absorb the difference completely.

## What this does and does not change

**It does not repeal the consistency rule.** A camera is still only valid under the K it was solved
with, and scoring one against another's still measures a camera nobody solved — that landmine
stands, and it caused a real wrong result earlier in the session.

**It does repeal the worry.** There is no need to re-solve anything at the "true" axis, and a clip
whose crop is unknown is not thereby unsolvable.

## A caution about the obvious follow-up

Scanning cy while refitting from a camera solved at 304 is not a measurement of cy. It reads
1.57–1.83 px anywhere in 200–400 and 17–34 px outside, which looks like a sharp optimum at 304 and
is nothing of the kind: a local refit cannot travel from one K's solution to another's, so the scan
is measuring how far the refit reaches. Each principal point has to be solved independently, which
is what the table above does.
