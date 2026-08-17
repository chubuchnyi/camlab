# Asked of the shipped chain, the carry does NOT come out unnecessary — and the judge is suspect

Measured 2026-08-17. This is the follow-up
`the-carry-buys-nothing-when-every-frame-is-refitted-2026-08-17.md` said had to be run, and it
does not confirm it. **The stage stays.**

## What was asked

A causal tracker measured the frame-to-frame homography to be worth nothing on seven clips. That
was a loop resembling `solve_carry`, not `solve_carry`, and the doc listed four ways it differed
that could each reverse the result. So `solve_carry` gained `--no-carry` — measure no motion at
all, let every frame refit from its neighbour's camera — and the **whole chain** was run both ways
over every clip in `runs/`, from one frozen copy of each, interleaved.

`scripts/bench_carry_necessity.py`, and `bench_chain.py --snapshot` so both configurations and
every later round read identical bytes.

## What came back

Ten clips of fourteen produce a verdict. On those:

| clip | with carry | no carry | Δ `across` |
|---|---|---|---|
| `g11710897` | 14.70 | **13.26** | −1.44 |
| `NET_ARG_225042` | 6.32 | **5.34** | −0.98 |
| `broadcast` | 4.27 | **4.07** | −0.20 |
| `CRO_MOR_194948` | 4.05 | **3.90** | −0.15 |
| `14604731_1080_1920_30fps` | 1.34 | **1.25** | −0.09 |
| `14604731_..._Copy` | 1.29 | **1.26** | −0.03 |
| `g14604660` | 1.80 | 1.81 | +0.01 |
| `wp_194948` | 3.85 | 3.92 | +0.07 |
| **`fan`** | **1.40** | 1.81 | **+0.41** |
| **`ENG_FRA_232015`** | **2.60** | 3.25 | **+0.65** |

Six better, two a wash, **two clearly worse**. Four more score too few markings on both sides to
say anything either way; that is absence, not agreement, and the summary line says so since it
first counted `nan` as "unchanged".

Time: the chain is 2.5 to 52 s faster a clip without it.

**And the two the carry wins are the two where the camera moves.** `fan` is a phone held at head
height through a **1.61x zoom**; `ENG_FRA_232015` is the longest clip in the set at 180 frames. The
six it loses are tripods and short clips. That is not a stage failing to justify itself — it is a
motion model earning its keep exactly where there is motion, and being harmless where there is not.

**`fan` was nearly left out of this table, and leaving it out would have inverted the conclusion.**
`bench_chain` picks the first seed that exists, which on `fan` is `camera_boot.json`, and from
there the clip scores too few markings for a verdict. Its hand edits are keyed to
`camera_auto.json` — `camera_manual.json` is not a camera at all but a map from seed NAME to frame
to edit, so passing it as a seed is a `KeyError` and not a subtle mistake. Run from the seed its
anchors belong to, the most carry-relevant clip in the repo says the carry matters.

## The signal that is not in the `across` column

The focal moves, and on two clips it moves a great deal:

| clip | focal with carry | focal no carry | |
|---|---|---|---|
| `fan` | 3001.8 | **2300.3** | **−23 %** |
| `g11710897` | 2592.7 | 2277.4 | −12 % |
| `CRO_MOR_194948` | 5962.7 | 5872.7 | −1.5 % |
| `ENG_FRA_232015` | 3868.7 | 3815.3 | −1.4 % |
| the rest | | | under 1.5 % |

On `fan` from its real seed the focal is 4581.3 with the carry and 4884.6 without, 6.6 % apart on a
clip that DOES have a verdict — and there the carry is also the better camera by 0.41 px, so for
once the two signals agree. (The 23 % above is from the `camera_boot` run, which has no verdict:
`across` cannot see it at all.) This is the focal /
distance degeneracy this repo has measured twice and written down twice: the paint is nearly flat
along it, so a refit freed from the carry can slide down it and the metric will not object. **The
carry is constraining something the paint cannot reward**, which is the shape of a stage that looks
useless to the only instrument pointed at it.

## And the instrument itself is now under suspicion

Everything above is judged by `across` — the paint. On 2026-08-16 this repo acquired its first
externally measured camera, and
`findings/the-metric-cannot-see-depth-2026-08-16.md` reports that **the camera is 1.2–5.0 m from
where it was and the paint metric prefers it that way.**

If the paint metric can prefer a displaced camera, then "`across` improved when the carry was
removed" is not "the camera got better". On six clips it may mean the camera slid further down the
degeneracy and the metric applauded. That is not a rhetorical worry — the focal column above is
what sliding down it looks like.

**So this sweep cannot conclude, and the reason is not the sweep.** It needs the second judge.

## What to run next

`scripts/bench_vs_worldpose.py` against the no-carry cameras, on the clips WorldPose covers, and
the comparison read in metres rather than pixels. Until then:

* `--no-carry` stays a control flag, documented as one, and is not a mode to solve in.
* `measure_pairs` and SIFT stay on the critical path.
* The causal-tracker finding is **bounded to that loop** and does not transfer.

The claim that would have followed — SIFT off the critical path, a causal frame at 36 ms with no
motion at all — is not available, and the honest reason is that it was measured against a judge the
repo had just found to be biased in exactly the direction the change moves the camera.
