# #17: straightness does not separate markings from mowing stripes. Length does.

The idea was reasonable and it is wrong. Real paint is straight to 0.37 px over 200 px
(`lens-distortion-is-not-the-error.md`), which looked like a tight, camera-free test for telling a
marking from a mowing stripe or a shadow edge. Measured against the solved camera on the fan clip —
a detected segment counts as a marking when a model marking lies along it — over 476 segments:

| | n | sag, median | p90 | span, median |
|---|---|---|---|---|
| markings | 237 | 0.21 px | 0.56 px | **239 px** |
| everything else | 239 | **0.14 px** | 0.37 px | **85 px** |

**The non-markings are straighter.** Mowing stripes and shadow edges are themselves straight, and
they are shorter, so they bow less. The test is not weak, it points the wrong way.

## What the same measurement handed over instead

Length separates them, and by a lot: 216 px against 86 px in the median, over 652 segments.

| cut | markings kept | others kept |
|---|---|---|
| 60 px (what shipped) | 100 % | 100 % |
| 100 px | 86 % | **39 %** |
| 150 px | 73 % | 27 % |
| 200 px | 56 % | 23 % |

The shipped `MIN_MERGED_PX = 60` filters nothing at all — everything the finder returns is longer
than that.

Refitting all 120 frames at each cut, judged by the paint:

| cut | segments/frame | refit median | frames under 20 px |
|---|---|---|---|
| 0 | 16.4 | 2.19 px | 81/120 |
| 80 | 12.7 | 2.18 px | 85/120 |
| **100** | **10.2** | **2.18 px** | **90/120** |
| 120 | 9.3 | 2.22 px | 89/120 |
| 150 | 8.2 | 2.57 px | 87/120 |
| 200 | 6.5 | 14.0 px | collapses |

**Nine more frames, and the median does not move**, which is the informative part: what the cut
removes was carrying none of the fit. `MIN_MERGED_PX` is now 100.

## The scope of this, checked afterwards and narrower than it was written

Asked whether any of it had been tried on another clip, the answer was no, and the check is worth
recording because of how it nearly went. Re-run across three clips:

| clip | markings | others | median sag, markings | median sag, others | reads as |
|---|---|---|---|---|---|
| `fan` | **208** | **88** | 0.20 px | 0.13 px | backwards |
| `broadcast` | 118 | **7** | 0.11 px | 0.32 px | forwards |
| `g15449383` | **3** | 19 | 0.09 px | 0.13 px | forwards |

The first reading of that table was "the finding flips on `broadcast`". It does not: **both
apparent reversals rest on 7 and 3 observations.** This project's own register says seven samples
agreeing on a binary outcome happens by chance about once in sixty, and it has now caught the same
mistake three times in one session.

So the honest scope: **this is measured on `fan` and untested anywhere else**, because no other
clip yields enough of both classes. The reason is itself informative — `broadcast`'s detector
returns almost no non-markings (7 across 30 frames; its turf is clean) and `g15449383` returns
almost no markings (3; the camera sees little pitch). A discriminator cannot be evaluated on a clip
that has nothing to discriminate.

The length separation is also weaker on `fan` now than the table above shows — 262 px against
226 px rather than 216 against 86 — because `MIN_MERGED_PX` was raised to 100 off the back of that
very measurement, and the cut has already removed what the separation was made of. Consistent, not
contradictory, and worth stating so the two numbers are not read as a disagreement.

## Two cautions

**This is the POST-merge length, and the distinction matters.** A cut on LSD's raw fragments at
60 px once left five frames with zero lines, having thrown away every piece of every real marking
before the merge could reassemble them. That is `LSD_MIN_LENGTH`, it stays at 12, and the two must
not be confused.

**It does not solve #14.** Thirty-nine per cent of the non-markings still get through, and 14 % of
real markings are lost. It is a cheap improvement to what the solver is fed, not a discriminator.
