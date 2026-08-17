# Half the ground truth is being kept back, and this says which half and why

This is a standing rule, not a measurement. It applies from 2026-08-17 to every claim made against
the WorldPose ground truth.

## The split

WorldPose ships ground truth for **89 clips from eight matches**. Four matches are the working half
and four are held out:

| | matches | clips |
|---|---|---|
| **working half** — free to measure on | `CRO_MOR`, `ENG_FRA`, `MOR_POR`, `NET_ARG` | 48 |
| **held out** — do not measure on | `ARG_CRO`, `ARG_FRA`, `BRA_KOR`, `FRA_MOR` | 41 |

`scripts/worldpose_split.py` is the source of truth; the table above is a copy and copies drift.

```bash
python scripts/worldpose_split.py                 # the whole split, with the clip names
python scripts/worldpose_split.py --list work     # for a bench to iterate over
python scripts/worldpose_split.py --check ARG_FRA_181108
```

## Why

`findings/the-metric-cannot-see-depth-2026-08-16.md` is this repo's first comparison against an
externally measured camera, and it says the camera is **1.2–5.0 m out and the paint metric prefers
it that way**. That is a large claim, and it was drawn on four clips — `CRO_MOR_194948`,
`ENG_FRA_232015`, `MOR_POR_181952`, `NET_ARG_225042`. Those four cannot check it: a claim cannot be
tested against the evidence that produced it.

Nothing about that is a criticism of the finding. It is the ordinary situation, and it is the one
this repo keeps meeting. `docs/findings/landmines.md` records roughly thirty retracted conclusions
and the recurring shape is a number that was right about the clips it was measured on:

* *"`on_paint` beats length, 0.839 against 0.720"* — a single-clip answer that inverted over six.
* *"#17 was right — it measured on `fan`, the weakest of the six."*
* *"A filter designed on one frame works on that frame"* — `fan` 40, 2.6 m to 10.3 m.
* *"The straightness finding flips on `broadcast`"* — both reversals rested on 7 and 3 observations.

Every one of those was caught after publication, by re-measuring. A held-out half catches the same
thing before, and costs nothing but patience.

## Split by MATCH, not by clip

Clips within a match share a stadium, a lighting rig, a broadcast setup and — on the evidence of
their near-identical optical centres and fixed camera heights — the same camera on the same mount.
A per-clip split puts `CRO_MOR_194948` in one half and `CRO_MOR_193322` in the other and calls them
independent. They are not. Most of what one can teach you the other already did, and a held-out
half that leaks that way will agree with whatever the working half suggested — which is worse than
having no held-out half at all, because it looks like confirmation.

The first version of `worldpose_split.py` split per clip, by a hash of the clip name. It is worth
recording that the wrong answer was the attractive one: balanced, stateless, elegant, and measuring
the wrong thing.

## And the rule is not a hash

A hash over the four untouched matches sent one of them to the working half and produced 60 clips
against 29 — not a half, and it buys nothing, because the boundary that matters is already there.
A match either has been measured on or has not:

* **measured on → working half, permanently.** The whole match, not just the clip: a clip does not
  tell you less about its neighbour for having been measured second.
* **not yet → held out**, until someone measures on it and says so.

So the split is a consequence of what has been used rather than of an arbitrary function, it comes
out four matches against four, and a match arriving later starts held out, which is the safe default
rather than a coin toss.

## How the held-out half gets used

**Looking is a one-way door.** Once a held-out match has been used to choose between two options —
a threshold, a stage, a model — it is spent, and it moves to `SPENT_MATCHES` in the same commit as
the measurement that spent it, so the two cannot drift apart.

The sequence that makes it worth anything:

1. Do the work on the working half. Tune, sweep, argue, retract, whatever it takes.
2. **Write the claim down first** — the number, the direction, and what would refute it. A
   prediction made after seeing the answer is not a prediction.
3. Run it once on the held-out half.
4. **Report what came back.** If it fails, it is reported as failed. Re-tuning against the held-out
   half and reporting the second attempt is how a held-out set becomes a second training set, and
   the only defence against it is that step 2 is already written down and dated.

Four matches will not survive many rounds of this. That is the point: it makes each look expensive,
which is the only thing that makes them get spent on claims worth checking.

## What is already spent

`CRO_MOR`, `ENG_FRA`, `MOR_POR` and `NET_ARG` were spent before this file existed, by
`the-metric-cannot-see-depth-2026-08-16.md`. Everything that document concludes stands on the
working half and has **not** been checked against the held-out one.

The first claim worth spending a match on is that document's own: **the camera is 1.2–5.0 m out and
the paint prefers it that way.** It is written down, it is falsifiable, and it is not yet confirmed
on a clip that had no part in producing it.
