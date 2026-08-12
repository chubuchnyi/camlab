# The paint threshold can tune itself — and the obvious way to do it is wrong twice

Measured 2026-08-12, on all nine sample clips. Supersedes the "what to do, in order" list in
[`daylight-and-automatic-thresholds.md`](daylight-and-automatic-thresholds.md): its
recommendation #1 was measured and **does not hold**, and its recommendation #3 does, but only
with a constraint it did not mention.

```bash
PYTHONPATH=src .venv/bin/python scripts/bench_adaptive_threshold.py
PYTHONPATH=src .venv/bin/python scripts/bench_adaptive_threshold.py --sweep-c 8,16,24,32
```

## Recommendation #1 was wrong: `adaptiveThreshold` is another hand-set constant

The earlier finding proposed replacing `RIDGE_CONTRAST = 16` with `cv2.adaptiveThreshold`, on a
table that had no script behind it. Built and re-measured: it swaps an absolute constant for a
relative one, `ADAPTIVE_C`, and the best value of that is **also different for every clip**.

Swept over three frames per clip, `lines / longest px`:

| clip | fixed 16 | C=8 | C=16 | C=24 | C=32 |
|---|---|---|---|---|---|
| broadcast | 13 / 1160 | 11 / 1031 | 9 / 1025 | 13 / 1033 | 10 / 1030 |
| evening-a | 2 / 927 | 1 / **167** | 1 / 1099 | 1 / **1236** | 1 / 1230 |
| evening-b | 45 / **1911** | 42 / 854 | 2 / 404 | 3 / 1691 | 2 / 1708 |
| day-stadium | 4 / 259 | 6 / **542** | 1 / 130 | 1 / 243 | 1 / 197 |

`day-stadium` wants C=8, `evening-a` wants C=24, `evening-b` wants the fixed threshold. Adjacent
values swing the answer by up to 7× on the same clip. This is the disease being treated, relocated.

**Retraction of a number in the superseded file.** Its table claims the broadcast clip goes from
10 merged lines to 20 under `adaptiveThreshold` at the same longest. Re-measured, broadcast does
not move at all — 6 / 1356 either way at frame 30, and 13 / 1160 vs 9…13 / ~1030 over three
frames. The parameters behind that table were never recorded and the script did not survive, so
the disagreement cannot be traced further than this.

## Recommendation #3 works, and the first version of it was gameable

The right shape is to search for the threshold that maximises what the chain actually consumes:
**total length of merged markings**. No constant, one answer per clip. `auto_contrast` does this
coarse-to-fine over 12…110 — a range that brackets the 20…117 the nine clips were measured to
need — paying for the ridge map once instead of once per candidate, which is what made the earlier
attempt time out.

**First version, objective alone, ran to the bottom of its range on 4 of 10 rows.** The search
picked `T = 6` — the floor of what it could reach — on `day-amateur`, `day-stadium2`, `evening-b`
and `day-amateur2`, because total length is maximised by admitting everything: lowering the
threshold lets turf texture merge into long spurious lines. `day-amateur` reported **389 merged
"markings" on a pitch that has 17**, and scored *better* on longest for it. A bound being hit is a
finding, and this one said the objective was wrong.

**Fixed by constraining, not by re-tuning.** Maximise merged length *subject to* the paint stage
not having given up — painted pixels per megapixel at or below 10 000, this repo's own pre-flight
signal (working clips 3 300–9 300, failed ones 48 000–52 000). One line, no new constant:
`PAINT_CEILING_PX_PER_MPX`. The pinning stopped on all four rows: `day-amateur` moved T 6 → 24 and
389 lines → 8.

## All nine clips, one frame each

`fixed` is the shipped constant, `adaptive` is `cv2.adaptiveThreshold` at C=4, `auto` is the
constrained self-tuning search. `T` is what `auto` chose.

| clip | label | resolution | lines fix | long fix | lines ad | long ad | T | lines auto | long auto | auto vs fixed |
|---|---|---|---|---|---|---|---|---|---|---|
| broadcast | broadcast (tuned) | 1920×1080 | 6 | 1356 | 6 | 1356 | 48 | 8 | 1350 | same |
| fan | evening (tuned) | 1080×608 | 9 | 842 | 9 | 893 | 54 | 9 | **895** | better |
| fan-raw | evening (tuned) | 1080×1920 | 15 | 593 | 11 | 562 | 54 | 12 | **972** | better |
| day-amateur | day amateur | 1080×1920 | 7 | 731 | 41 | 1025 | 24 | 8 | **976** | better |
| overhead-4k | 4K overhead | 3840×2160 | 1 | 115 | 9 | 378 | 24 | 4 | 152 | better |
| evening-a | evening | 1920×1080 | 1 | 927 | 0 | 0 | 24 | 1 | **1078** | better |
| evening-b | evening | 1920×1080 | 45 | 1911 | 100 | 1980 | 54 | 2 | 1740 | worse |
| day-stadium | day stadium | 1080×1920 | 6 | 259 | 4 | 1077 | 12 | 6 | **1078** | better |
| day-stadium2 | day stadium | 1080×1920 | 15 | 1029 | 13 | 988 | 18 | 19 | 1010 | same |
| day-amateur2 | day amateur | 2160×3840 | 1309 | 2640 | 1400 | 2702 | 84 | 2 | 116 | worse |

**6 better, 2 same, 2 worse — and the headline is not that score.**

**Both "worse" rows are clips whose fixed-threshold result was already inside the failure band.**
`evening-b` runs at 48 202 painted px/Mpx under the fixed constant and `day-amateur2` at 52 304,
against 3 300–9 300 on every clip that works. Their 45 and 1 309 "markings" were turf texture
scoring well on a length metric that cannot tell the difference. `auto` refuses to operate there
and returns little. That is the correct behaviour and it is a **loss of confidence, not of
capability**: it converts two confident-and-wrong clips into two honestly-empty ones.

Counted by whether a clip yields usable evidence — four or more merged markings, long enough to
matter — the fixed threshold gives **6 usable and 2 false**, `auto` gives **6 usable and 0 false**,
and it lengthens `day-stadium` by 4.2× (259 → 1078 px) at no cost on either tuned clip.

**It does not rescue the broken clips**, and the superseded file's recommendation #2 stands
unchanged: `overhead-4k` (4 lines, longest 152 px) and `evening-a` (1 line) fail in the surface
stage, and no threshold over the ridge map recovers from a surface that was never found.

## The threshold is a clip property, not a frame property

Asked because the superseded file admitted it had never checked, and one frame is what both its
table and the one above rest on. `auto_contrast` run on five frames of four clips:

| clip | f10 | f30 | f50 | f70 | f90 | median | spread |
|---|---|---|---|---|---|---|---|
| broadcast | 36 | 48 | 36 | 24 | **6** | 36 | 6…48 |
| fan | 48 | 54 | 12 | 12 | 30 | 30 | 12…54 |
| day-stadium | 6 | 12 | 12 | 18 | 12 | 12 | 6…18 |
| evening-a | 36 | 24 | 36 | 18 | 24 | 24 | 18…36 |

**The pick moves 6…48 on the tripod broadcast clip, whose lighting does not change.** The objective
is flat enough that a single frame does not determine the winner. Two consequences:

1. **A per-frame threshold must not be used in the chain.** It would make the paint stage jitter
   underneath a per-frame camera solve, and the jitter would be search noise, not exposure.
2. **Every single-frame number above — mine and the superseded file's — is one draw from that
   spread.** The A/B table should be read as an ordering, not as values.

`auto_contrast_for_clip(frames)` is the usable entry point: the median over sampled frames, with
the spread and a `settled` flag returned rather than hidden, so a caller can see when the clip's
own frames do not agree.

## Cost, which is the open problem

| | fixed | auto |
|---|---|---|
| 1080p clip | 0.1 s/frame | 0.5 s/frame |
| 2160×3840 clip | 88 s/frame | **270 s/frame** |

The search evaluates ~10 thresholds and each pays a `distanceTransform` + Hough + merge; only the
ridge map is shared. At 4K that is four and a half minutes for one frame, and the per-clip median
wants several. The superseded file's suggestion — score on a downscaled frame — is untried and is
the obvious next move, with the caveat that `MIN_MERGED_PX` and the Hough parameters are in pixels
and do not survive a rescale unchanged.

## What this does not claim

Nine clips, one sport. The main table is one frame per clip, and the section above says what that
is worth. Nothing here scores a **camera**: on seven of these nine clips there is none to score
against, so "more long markings" is the whole verdict, and a longer line is only evidence that the
paint stage found more paint — not that a solve will follow.
