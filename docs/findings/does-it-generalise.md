# Does it work on a different clip, and a different part of the pitch?

Asked 2026-08-10. The honest starting position: camlab had exactly **one** clip, and every
threshold in it — the 0.65 on-paint fraction, the 8° family angle, Hough over LSD, the 40 px match
bound — was set from that clip. That is the disease this whole project has been recovering from:
numbers tuned to one artefact and quoted as general.

So it was tested rather than argued, on the strongest case available.

## The test

pitch3d's #119 rigid camera on the broadcast clip is **known good**: one focal, one optical centre,
1.4 px against the paint by pitch3d's own method, and pinned in camlab's own golden test — focal
4169.32 px, centre (−2.292, −70.134, 17.220) m. It is the closest thing this project has to a
correct answer.

Everything about that clip is different from the one camlab was built on: another stadium, a
broadcast gantry instead of a phone in the stands, 1920×1080 with no crop instead of a
1080×608 cut, a long lens on a tripod instead of a handheld zoom, and a different part of the pitch
in frame.

**If the metric does not call that camera good, the metric is wrong.**

| frame | segments | matched | missed | worst line | median | worst angle |
|---|---|---|---|---|---|---|
| 0 | 9 | 2 | 5 | 7.3 px | 4.7 | 0.62° |
| 10 | 9 | 3 | 4 | 6.1 px | 5.5 | 0.95° |
| 20 | 11 | 3 | 5 | 5.7 px | 4.9 | 0.75° |
| 30 | 8 | 3 | 5 | 3.1 px | 2.9 | 0.56° |
| 40 | 11 | 5 | 3 | **2.6 px** | 1.0 | 0.59° |
| 50 | 11 | 4 | 4 | **2.5 px** | 1.0 | 0.55° |

**Worst line, median over frames: 4.4 px.** The same metric reads 100+ px on the fan clip's shipped
camera — a separation of about 25×, on a clip it was never tuned on.

That is the validation that had been missing all along. The metric was shown to respond to injected
error; this shows it also calls a genuinely correct camera correct, which is the other half and the
harder one.

## Where it is honestly weaker

**It reads about 3× higher than pitch3d's 1.4 px.** Different quantity — worst *line* here against
an aggregate there — plus a different detector and a different correspondence. Not alarming, and
not identical; it should not be quoted as though the two numbers mean the same thing.

**Coverage falls: 2 to 5 markings matched of 7 to 8 projected, 3 to 5 misses per frame.** More of
the model pitch goes unmeasured here than on the fan clip. So the direct answer to "will it cope
with a different part of the pitch" is: *the measurement stays honest, but it measures less of it.*
A view containing few markings yields few correspondences, and the number then rests on a thin
base — which `n_matched` reports, and which is why it is reported.

**The discriminator being built for #14 needs at least four parallel markings of one family in
view** to have anything to test a projective spacing against. A frame showing mostly the centre
circle would not provide that, and there the discriminator simply abstains rather than guessing.

## What this does not answer

One more clip is two clips, not generality. Both are the same sport, the same broadcast era, green
grass, white paint, daylight or floodlight. Nothing here says anything about a snowy pitch, a worn
one, an artificial surface, or a stadium whose mowing pattern runs diagonally. The thresholds are
still set from one clip and merely *not contradicted* by a second.
