# #12: the mowing stripes check the camera, and they never touch the markings

Every other number in this repo comes from the painted lines, so every one of them shares whatever
the line finder gets wrong. The turf is independent: a mower cuts in passes of constant width, so
on a striped pitch the stripes are evenly spaced **in metres**. Rectify a frame through the camera
and they become a periodic signal — and if the camera is right, that period does not move while the
operator zooms.

## It holds

fan, solved camera (`camera_auto_full3`, 2.11 px), 40 frames:

| | |
|---|---|
| striped on | 19 of 40 frames |
| stripe width | **11.00 m**, spread 0.25 m — **2.3 %** |
| focal over those frames | 2801 → 4502, a **1.61×** zoom |
| focal-to-period correlation | **−0.19** |

The operator zooms by 61 % and the measured stripe width does not move. A wrong focal track would
show up here immediately, because the period is what the focal error stretches.

## Breaking the camera breaks it, in the way the geometry predicts

| camera | paint error | striped | period |
|---|---|---|---|
| solved | 2.0 px | 9/9 | 11.00 m, spread 0.25 |
| moved 5 m **along** the stripes | 25.3 px | 9/9 | 11.00 m — unchanged, and correctly so |
| moved 15 m sideways | 23.1 px | 0/9 | none |
| focal ×0.85 | 36.5 px | 0/9 | none |
| focal ×1.25 | 38.8 px | 7/9 | **8.75 m**, and 11.00 / 8.75 = 1.257 against the 1.25 applied |

The 5 m case is the one worth reading twice: sliding the camera along the stripe direction does not
change the spacing across them, so the check is blind to it — correctly. A test that claimed to
catch that would be claiming information it does not have.

## Not every pitch is striped, and two different things look the same

Broadcast comes back striped on 3 frames of 20. That is its turf, not a failure.

But the fan clip through its *untouched* solve (38.4 px) comes back striped on 9 of 40 — while the
same turf through the solved camera is 19 of 40. **Stripes are only periodic once rectified
correctly**, so a wrong camera hides them. "Not striped" and "the camera is wrong" produce the same
output, and this cannot tell them apart. It is a check to run on a camera you already believe, not
a way to find one.

## What it is good for

- **Confirming a focal track on independent evidence.** Sensitivity is a few per cent, and nothing
  about it touches the paint, the line finder, or the correspondence.
- **Not for finding a camera.** You need one to rectify at all.
- **Not for #14 either.** It says a detected line sitting at a multiple of 11 m from its neighbours
  is a stripe boundary — but only on striped pitches, and only once the camera is known, which is
  the wrong way round for feeding the solver.
