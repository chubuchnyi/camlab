# The paint scores a camera KNOWN to be correct anywhere from 5.6 to 30.0 px

Measured 2026-08-17 over 16 more WorldPose clips, working half only.

`the-metric-cannot-see-depth-2026-08-16.md` established that camlab's camera is 1.2–5.0 m from an
externally measured one and that the paint prefers it that way, on four clips. This adds sixteen,
and it does not test that claim — it measures the instrument the claim was made with.

**The ground-truth camera, scored by camlab's own `across`, over 20 clips from four matches:**

| clip | frames | zoom | anchor | **GT `across`** | markings |
|---|---|---|---|---|---|
| `MOR_POR_191625` | 240 | 1.15× | 1.07 px | **5.56** | 9 |
| `ENG_FRA_224710` | 208 | 1.11 | 1.23 | **6.32** | 8 |
| `CRO_MOR_184059` | 240 | 1.19 | 0.82 | **6.47** | 9 |
| `ENG_FRA_231054` | 240 | 1.20 | 1.20 | **6.96** | 7 |
| `CRO_MOR_182806` | 240 | 1.23 | 0.94 | **7.89** | 9 |
| `NET_ARG_224119` | 240 | 1.07 | 1.17 | **9.52** | 11 |
| `CRO_MOR_180400` | 240 | 1.04 | 0.97 | **10.00** | 10 |
| `NET_ARG_222226` | 240 | 1.17 | 1.40 | **10.17** | 6 |
| `MOR_POR_192030` | 240 | 1.19 | 2.49 | **11.07** | 7 |
| `CRO_MOR_182854` | 240 | 1.00 | 1.10 | **11.59** | 10 |
| `ENG_FRA_232115` | 240 | 1.16 | 0.93 | **12.77** | 10 |
| `NET_ARG_222749` | 240 | 1.17 | 2.58 | **13.06** | 9 |
| `MOR_POR_191519` | 240 | 1.09 | 2.88 | **14.22** | 8 |
| `CRO_MOR_183903` | 240 | 1.00 | 1.08 | **17.30** | 10 |
| `NET_ARG_223806` | 163 | 1.00 | 1.19 | **17.89** | 10 |
| `MOR_POR_193355` | 240 | 1.10 | 0.89 | **20.84** | 9 |
| `CRO_MOR_194948` | 120 | 1.06 | — | **30.01** | 10 |
| `ENG_FRA_224248` | 240 | 1.04 | 10.13 | no verdict, 0/240 frames reach 4 markings | |
| `ENG_FRA_221238` | 60 | — | — | no verdict, 0/60 | |
| `CRO_MOR_194338` | 60 | — | — | no verdict, 18/60 | |

**Median 11.33 px, range 5.56 to 30.01 — a factor of 5.4 on a camera that is right by
construction.** Three clips of twenty cannot be scored at all.

`CRO_MOR` is the sharpest version of it: six clips of ONE match, one camera on one mount — the
ground truth's own height is 18.59–18.66 m across all of them — scored at 6.47, 7.89, 10.00, 11.59,
17.30 and 30.01 px.

## What does NOT explain it

**Not the radial distortion.** That was the obvious candidate: WorldPose carries distortion moving a
projected marking by 17–37 px at the corners, camlab's model has none, and the import prints the
figure per clip. Correlation with `across` over the 16 verdict clips: **r = +0.33**. Within matches,
where distortion is nearly constant, `CRO_MOR` gives **r = −0.05** on five clips and `ENG_FRA`
+0.95 on three — and an r of 0.95 on three points is not a measurement. The hypothesis was written
down before the numbers and it is refuted by them.

**Not the marking count**, r = +0.34 — weak, and in the direction the definition already predicts,
since `across` is a max over the markings a frame scores and a camera seeing more of the pitch is
answering a harder question.

**Not the anchor.** Every anchor here refits to 0.82–2.88 px except the one clip that has no verdict
anyway, and the ground-truth camera does not come from the anchor at all.

**So the cause is not established.** What is established is the size: the paint's reading of a
correct camera moves by 5.4× between clips, and nothing measured here says why.

## Why it matters for the 1.2–5.0 m claim

That claim is a difference between two cameras, judged by a metric whose own spread on a known-good
camera is 5.6 to 30 px. It does not make the claim wrong — the claim was made in **metres**, from
the optical centres, and that comparison depends on neither the detector nor where in the frame the
markings fell.

It does mean the second half of that document — *"and the paint metric prefers it that way"* —
needs the same care. A metric that scores the correct camera at 30.01 px on `CRO_MOR_194948` and
6.47 px on `CRO_MOR_184059` has room to prefer the wrong camera on either.

**Compare in metres.** Pixels are for the detector's own regression tests.

## Two things this run also produced

**An offset window is now importable.** AVATAR's `new_clip_anchor.py` scans the video for a frame
PnLCalib can solve and ingests a window centred there, so `first_frame` is usually not 0 — on
`CRO_MOR_180400` it is 1320. `import_worldpose_gt.py` used to refuse any offset rather than risk an
off-by-N, which was right while nothing produced one. It now slices the GT at `first_frame + i`.
Checked both ways: the offset clip imports 240 frames and scores 10.00 px where it previously could
not be imported at all, and `CRO_MOR_194948` at `first_frame=0` still reads 30.01 px, unchanged.

**240 frames, not 60.** At 60 frames the window is two seconds and the camera barely moves;
`CRO_MOR_182806` zooms 1.23× over 240 frames and shows none of that over 60. Twelve of these clips
zoom by more than 7 %, which is the thing a per-clip focal cannot represent and a per-frame one can.

## Not yet done

camlab has not been solved on these sixteen. This measures the GROUND TRUTH against the paint, not
camlab against the ground truth. The next step is the chain on each and
`bench_vs_worldpose.py --camera camera_polished.json`, read in metres.
