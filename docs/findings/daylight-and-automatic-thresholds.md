# Daylight clips, and why one threshold cannot serve them

Researched 2026-08-10. Nine clips, two of which the paint stage was tuned on.

## It is a threshold problem, not a lighting problem

The tempting story is "the constants were set for floodlit evening football and daylight is
different". Half true, and the useful half is narrower. Measured on the ridge response *inside the
detected playing surface*:

| clip | surface | %> the fixed 16 | threshold needed for 0.5 % coverage |
|---|---|---|---|
| day amateur ✓ | 40.3 % | 3.4 % | 58 |
| 4K overhead ✓ | 100 % | 2.0 % | **20** |
| evening ✓ | 47.0 % | 3.0 % | 65 |
| evening ✓ | 49.5 % | 2.9 % | 68 |
| evening (tuned) ✓ | 29.9 % | 3.3 % | 63 |
| broadcast (tuned) ✓ | 55.5 % | 1.8 % | 78 |
| day stadium ✗ | 21.7 % | 4.6 % | 37 |
| day stadium ✗ | 73.8 % | **15.8 %** | 49 |
| day amateur ✗ | 46.4 % | **46.4 %** | **117** |

**Working clips let 1.8–4.6 % of the surface through. The failures let 15.8 % and 46.4 %.** And the
threshold that would equalise them ranges from **20 to 117** — a factor of six. `RIDGE_CONTRAST =
16` cannot be right for that spread, and no single number can.

Note also that one *daylight* clip works fine (3.4 %) and one *evening-lit* threshold value (20, the
4K overhead) is far below the tuned ones. So "daytime" is a correlate, not the cause. The cause is
that absolute brightness contrast depends on exposure, surface wear and mowing, and the constant
was calibrated against two clips' worth of it.

## What was ruled out by measurement

**`RIDGE_MIN_V = 95` is not the discriminator.** 68–100 % of turf passes it on working *and*
failing clips alike. The intuition that daylight grass is "too bright and gets through the gate"
is wrong — it gets through everywhere, and the ridge test is what is supposed to reject it.

## Three automatic schemes, measured

| clip | fixed 16 | percentile 99.4 | `cv2.adaptiveThreshold` |
|---|---|---|---|
| | lines / longest | lines / longest | lines / longest |
| day amateur ✓ | 32 / 1060 | 6 / 919 | 20 / 1074 |
| 4K overhead ✓ | 47 / 3285 | 17 / 2410 | 19 / **3712** |
| evening ✓ | 31 / 1029 | 9 / 1011 | 20 / 1049 |
| evening (tuned) ✓ | 21 / 593 | 9 / 669 | **28 / 876** |
| broadcast ✓ | 10 / 1356 | 9 / 1045 | **20** / 1353 |
| day stadium ✗ | 15 / 1708 | 1 / 927 | 9 / 1840 |
| day stadium ✗ | 106 / 1955 | 5 / 1787 | 65 / 1927 |
| day amateur ✗ | **1925** / 2640 | 1 / 64 | **1592** / 2614 |

**A fixed percentile fixes the runaway and breaks everything else.** 1925 lines becomes 1 on the
worst clip — but 32 becomes 6 and 47 becomes 17 on clips that were fine. It assumes markings are a
constant fraction of the frame, and they are not: a 4K camera above the halfway line sees the whole
pitch, a zoomed phone sees one penalty area.

**`cv2.adaptiveThreshold` is better than the fixed constant on most clips**, and better in the way
that matters: **longer** lines. 3285 → 3712, 593 → 876, and twice as many merged lines on the
broadcast clip at the same longest. It computes a threshold per neighbourhood, which is exactly
what "brighter than the grass around it" means, and it is exposure-independent by construction.

**It does not fix the extreme case**, and that is diagnostic: 1592 lines against the fixed
constant's 1925 is not a threshold failing, it is the **turf and surface stage** failing. On that
clip the mask is measuring grass texture across half the frame, and no thresholding of the ridge
map recovers from a surface that was never found.

## So: does OpenCV 5 help?

**Yes, but not where it was looked for.** LSD — the headline OpenCV 5 line detector — was measured
and is worse for this pipeline: half the paint coverage of Hough
(`measure/lines.py`'s docstring carries the table). The help is `adaptiveThreshold`, which is not a
new feature at all, and it helps because **this was never a line-detection problem**. It is a
thresholding problem, and OpenCV has had the right tool for it the whole time.

CLAHE is the other candidate worth trying for the same reason and has not been tested.

## What to do, in order

1. **Replace the fixed `RIDGE_CONTRAST` with `adaptiveThreshold` over the ridge map.** Measured
   better or equal on 6 of 9 clips and notably better on line length, which is what everything
   downstream consumes.
2. **Fix the surface stage before touching the extreme clips.** Two failures are the turf detector
   giving up, and a paint threshold cannot compensate for that.
3. **Then consider tuning the threshold to the objective directly** — choose whatever maximises the
   total length of long merged lines. That is self-tuning against exactly what is wanted, and a
   first attempt at it timed out: 22 candidate thresholds × 9 clips of Hough exceeded ten minutes.
   It needs a coarse-to-fine search, or scoring on a downscaled frame, before it is usable.
4. **A cheap pre-flight check exists and should be shipped**: paint pixels per megapixel. Working
   clips sit at 3 300–9 300, broken ones at 48 000–52 000. Above ~10 000 the paint stage has
   already failed and nothing downstream is worth running.

## What this does not claim

Nine clips, one frame each, one sport. The `%>16` figures are from frame 30 of each clip and were
not checked for stability across a clip. Everything above is a hypothesis about the *pipeline*,
tested at the level of "how many long lines come out" rather than "is the resulting camera right",
because on eight of the nine clips there is no camera to check against.
