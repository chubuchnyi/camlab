# Which principal point a clip's chain actually runs at, and why a consumer must not derive it

Found while checking `automating-the-anchor-2026-08-13.md`, whose step 4 names this as the trap that
"has already cost both repos a week" — and then points at the wrong value. It is worth being exact,
because an anchor written under the wrong axis is systematically wrong in a way nothing downstream
reports.

## The rule

**Every stage of the chain runs at the `cx`, `cy` stored in the seed camera.** `solve_carry.py:69`
is `cx, cy = float(seed["cx"]), float(seed["cy"])`, and every later stage inherits it through the
file it reads. Nothing in the chain consults `ClipInfo.principal_point`.

So: **read `cx`/`cy` from the camera file. Never derive them.** `GET /api/run/{clip}/camera` is
right; `clip.json` is not, and the two disagree on cropped clips by the whole crop offset.

## Why it is not academic

`ClipInfo.principal_point` answers a different and physically correct question — where the lens's
axis sits in the *source* frame — and on the one cropped clip on disk it is 638 px from where that
clip's cameras were actually fitted:

| clip | frames | crop | `ClipInfo.principal_point` | the camera file's `cx,cy` |
|---|---|---|---|---|
| `fan` | 1080×608 | `[1080, 608, 0, 1294]` | (540, **−334**) | (540, **304**) |
| `broadcast` | 1920×1080 | none | (960, 540) | (960, 540) |
| `g11710897` | 1080×1920 | none | (540, 960) | (540, 960) |

`fan`'s camera file records `principal_point_offset_px: 638.0` beside its own `cy: 304.0`, so the
writer knows about the derived axis and is not using it.

Measured cost of getting it the wrong way round, on `fan` frame 0 — same camera, same segments, only
the axis swapped:

| scored at | model markings in frame | matched to a detected line |
|---|---|---|
| the camera's (540, 304) | 8 | **7** |
| the derived (540, −334) | 1 | **0** |

A whole 120-frame harvest run through the derived value returned **zero segments with every frame
reported "camera unsupported"**, which reads exactly like a clip with no markings in it rather than
like a wrong constant.

## The inconsistency inside camlab, stated plainly

`write_start_camera` (`server/app.py:449`) seeds a freshly ingested clip from
`ClipInfo.principal_point`. `fan` has **no `camera_start.json`** — its cameras predate that code and
carry the image centre instead. `fan` is also the only cropped clip on disk, so today nothing else
can show the disagreement.

The consequence is narrow and real: **re-ingesting `fan` and re-solving it would run the chain at
(540, −334), and every stored number for that clip would change.** Nothing warns about this, and the
two paths have never been reconciled.

This note does not decide which axis is right. The derived one is better physics; the stored one is
what every measurement in `STATUS.md` was taken under, and it scores 1.65 px. Settling it means
refitting `fan` from the derived axis and comparing on the paint — not editing a constant.

## For the anchor automation

`automating-the-anchor-2026-08-13.md` §3 says step 4 must take `cx, cy` "from
`GET /api/run/{clip}/camera` (or `clip.json`)" and gives `(540, −334)` on `fan` as the value to use,
"not `(540, 304)`". The first source is right and the second is not, and on `fan` they differ by
638 px — so an anchor computed under `clip.json` would be written into `camera_manual.json` under an
axis the solver does not use.

It would not be silent, which is the one piece of good news: `solve_carry` scores every candidate
anchor against the paint and prints the choice, so a systematically wrong anchor loses to the seed's
own pose and says so. That is the safety argument the document already makes, and it holds here.
