# What stands between the other seven clips and a solved camera

The chain — carry, self-heal, shared centre, smooth — reaches 120 of 120 frames under 20 px on
`fan` and 59 of 60 on `broadcast`, with no human anchors. **Both were handed a starting camera by
pitch3d.** Every other clip has none, and `camlab solve` reads its homographies out of a pitch3d
`scene.json` that does not exist for them.

So: what actually blocks each clip, measured. `scripts/survey_clips.py`.

| clip | size | paint % | lines/frame | bootstrap | samples |
|---|---|---|---|---|---|
| `fan` ✓solved | 1080×608 | 86.1 | 12 | 10.7 px | 66 |
| `broadcast` ✓solved | 1920×1080 | 53.8 | 9 | 102.9 px | 181 |
| 11710897 | 1080×1920 | 39.4 | 7 | 269.1 px | 82 |
| 13386302 | 3840×2160 | **98.9** | 6 | 18.0 px | 478 |
| 14604660 | 1080×1920 | 47.2 | 6 | 8.8 px | 215 |
| 14604680 | 1080×1920 | 28.8 | 12 | 11.6 px | 96 |
| 14604731 | 1080×1920 | 28.5 | 16 | 17.8 px | 31 |
| 15449383 | 1920×1080 | 19.3 | 5 | 1.9 px | 125 |
| 15449387 | 1920×1080 | 69.9 | **64** | 15.0 px | 332 |
| 15750079 | 2160×3840 | 41.0 | **1967** | 3.3 px | 159 |

## The first two rows are controls, and they fail

`fan` and `broadcast` are solved to 2.1 px and 4.0 px. The bootstrap — 4000 random cameras scored
by the line objective, best one handed to the least-squares refit — returns **10.7 px on 66 samples**
and **102.9 px on 181**. It does not find the answer on the two clips where the answer is known.

So no row of that table can be believed. A 1.9 px on 125 samples means nothing when the method
scores 10.7 px on a clip that is actually solved.

**It is not a compute problem.** On `fan` frame 8, 4000, 20 000 and 60 000 random cameras return the
*identical* wrong answer: 17.3 px, 22 scored samples, focal 8045 against a truth near 4000. The
search is converging, and converging to the wrong place.

The reason is in the objective it is searching. `refit.objective` is `worst matched offset +
MISS_PX × misses`, and a camera that puts almost none of the pitch in frame has almost nothing to
miss — so pointing at a corner and fitting four lines beats framing the pitch and fitting twelve.
Adding a floor on how much of the model lands in the picture at all helps and does not solve it:

    fan frame 8, truth 2.1 px on 307 samples
      no floor       10.2 px,  91 samples, focal 10987
      15 % in frame   7.7 px, 297 samples, focal  4027
      30 % in frame  14.5 px, 490 samples, focal  1699

The 15 % floor drags the focal from 10 987 to 4027 and the coverage from 91 to 297, both onto the
right order — and still lands at 7.7 px, which is not a seed worth chaining from.

## So the one thing missing is a first camera, and random search is not it

What would be, in increasing cost:

1. **Combinatorial correspondence.** The pitch is known geometry. With 6–16 detected lines and about
   twenty model markings, enumerate plausible assignments — the two world-parallel families are
   already separated by `world_family`, and `_assign_in_order` already exploits the fact that
   parallel markings appear in the image in the same order as in the world — solve a homography for
   each, keep the best. This is the classical route and most of its machinery is already here.
2. **Vanishing points.** Built, in `solve/vanishing.py`, and measured unusable on a long lens:
   0.25 px of endpoint noise becomes ±25 % of focal. Might be fine on the wider clips.
3. **A keypoint model.** PnLCalib is exactly what produced the two seeds we do have.

## Two smaller things the same survey exposed

**The paint mask is not calibrated per clip.** It keeps 19.3 % of pixels on one clip and **98.9 %**
on another. At 98.9 % it has stopped separating anything — that is the known daylight failure, where
turf and paint sit at the same brightness. Any clip in that state needs a different threshold, not a
better camera.

**The line finder returns between 5 and 1967 markings a frame.** 1967 is not a pitch; it is the
finder running on noise. A per-clip sanity bound belongs in front of the solver, because a frame
with 1967 lines will find a correspondence for anything.

## And a small operational one

`runs/` is a docker volume on the GPU box. Looking at a new clip in the viewer means shipping its
frames — about 24 MB for sixty at 1920×1080. Cheap, but it is a step, and nothing does it
automatically.
