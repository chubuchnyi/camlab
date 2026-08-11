# #13: the cross-ratio is camera-free, selective on paper, and weak on the pitch

Parallel markings appear in the image in the same order as in the world, and the **cross-ratio** of
any four of them is unchanged by projection. That makes it the one test of marking geometry that
needs no camera at all — which is exactly what #14 wants, since local appearance provably cannot
separate a marking from a mowing stripe.

## On paper it is selective

A pitch's straight markings form two parallel families, ten and seven lines. Every four of them
give a cross-ratio, and after removing the degenerate quads there are **29 admissible values** in
the useful range 1–10:

    1.000 1.003 1.007 1.010 1.018 1.025 1.036 1.048 1.055 1.058 1.070 1.096 1.132 1.153 1.161
    1.164 1.172 1.186 1.216 1.229 1.275 1.343 1.407 1.417 1.421 1.495 1.534 1.681 1.799

| tolerance | fraction of 1–10 the test accepts |
|---|---|
| 0.050 | 8.7 % |
| 0.020 | 6.0 % |
| 0.010 | 4.0 % |
| 0.005 | 2.6 % |

A value drawn uniformly from that range would pass a 0.05 test less than one time in eleven.

## On the pitch it is not

Measured on the fan clip, quads of detected lines within one image family, with a quad counted as
real when every one of its four lines has a model marking lying along it under the solved camera:

| | n | distance to the nearest admissible cross-ratio | passes at 0.05 |
|---|---|---|---|
| all four are markings | 102 | median **0.0029** | 81 % |
| at least one impostor | 1379 | median 0.0123 | **70 %** |

Real quads sit four times closer, and **seven impostor quads in ten pass anyway**. Nothing is drawn
uniformly: fifteen of the 29 admissible values are below 1.2, and so are most observed quads,
because four nearly-equally-spaced lines give ~1.33 and four closely-spaced ones give ~1.0. Both
distributions pile up in the same narrow band, and a test whose admissible set is dense exactly
where the data lives is not a test.

## What to take from it

**Not a per-quad filter.** Ranking or thresholding individual quads by cross-ratio will discard 19 %
of real markings to remove 30 % of impostors, which is a bad trade at any threshold on this curve.

**The information is already being used, better.** `line_error._assign_in_order` requires the whole
family to map to the model in order, all lines at once, and that constraint is strictly stronger
than any four-line invariant: it is the same information plus the ordering plus the requirement
that one assignment explain everything. Extracting it a quad at a time throws away the part that
does the work.

**So #14 does not get its discriminator from here either.** Straightness pointed the wrong way
(`straightness-is-not-the-discriminator-length-is.md`); the cross-ratio points the right way and
too weakly. Length remains the only thing that has helped, and it is a filter, not a discriminator.
