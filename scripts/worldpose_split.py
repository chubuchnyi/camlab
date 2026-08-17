"""Which WorldPose clips may be measured on, and which are being kept back.

WorldPose ships ground truth for **89 broadcast clips from eight matches**, and this repo has
ingested four clips from four of those matches. Every number in
`findings/the-metric-cannot-see-depth-2026-08-16.md` was drawn on them, so they are spent: a claim
cannot be checked against the evidence that produced it.

So the eight matches are split in half. Four are where the work happens. **The other four are not
looked at until a claim is written down**, and looking at one is a one-way door — once a match has
been used to choose between two options it has joined the working half, whatever this file says.

Why bother: this repo's register lists about thirty retracted conclusions, and the recurring shape
is a number that was right about the clips it was measured on. *"Length separates on every clip
(0.713–0.975)"* and *"#17 was right — it measured on `fan`, the weakest of the six"* are the same
lesson twice. A held-out half is the cheapest instrument that catches that before publication.

**Split by MATCH, not by clip.** Clips within a match share a stadium, a lighting rig, a broadcast
setup and — on the evidence of their near-identical optical centres — the same camera on the same
mount. A per-clip split puts `CRO_MOR_194948` in one half and `CRO_MOR_193322` in the other and
calls them independent. They are not: most of what one can teach you, the other already did, and a
held-out half that leaks like that confirms whatever the working half suggested. The first version
of this file split per clip, by a hash, and it is worth recording that the wrong answer was the
attractive one — balanced, stateless, elegant, and measuring the wrong thing.

**And the rule is not a hash either.** A hash over the four untouched matches sent one of them to
the working half and produced 60 clips against 29, which is not a half and buys nothing: the
boundary that matters is already there. A match either HAS been measured on or has not. So the rule
is that list, and nothing else:

* measured on -> working half, permanently;
* not yet -> held out, until someone measures on it and adds it here.

That makes the split a consequence of what has been used rather than of an arbitrary function, it
comes out four matches against four here, and a new match arriving later starts held out — which is
the safe default rather than a coin toss.

    python scripts/worldpose_split.py                 # the whole split
    python scripts/worldpose_split.py --check CRO_MOR_194948 ARG_FRA_181108
    python scripts/worldpose_split.py --list work     # for a bench to iterate over
"""
from __future__ import annotations

import argparse
from pathlib import Path

CAMERAS = Path.home() / "AVATAR/WorldPose/cameras"

#: The matches this repo has already measured on, and therefore cannot check itself against. The
#: four clips are `CRO_MOR_194948`, `ENG_FRA_232015`, `MOR_POR_181952` and `NET_ARG_225042`; the
#: whole of each MATCH is spent with them, because a clip does not tell you less about its
#: neighbour for having been measured second.
#:
#: **Adding a name here is how a match leaves the held-out half, and it is a one-way door.** It
#: should be added in the same commit as the measurement that spent it, so the two cannot drift.
SPENT_MATCHES = ("CRO_MOR", "ENG_FRA", "MOR_POR", "NET_ARG")


def match_of(clip_id: str) -> str:
    """`ARG_CRO_220954` -> `ARG_CRO`. The two team codes; the rest is a kick-off timestamp."""
    return "_".join(clip_id.split("_")[:2])


def half(clip_id: str) -> str:
    """`"work"` or `"held out"`. Depends on the clip's MATCH and on nothing else."""
    return "work" if match_of(clip_id) in SPENT_MATCHES else "held out"


def all_clips(cameras: Path = CAMERAS) -> list[str]:
    return sorted(p.stem for p in cameras.glob("*.npz"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", default=None,
                    help="name clips and print which half each is in, without listing the rest")
    ap.add_argument("--cameras", default=str(CAMERAS))
    ap.add_argument("--list", choices=("work", "held out"), default=None)
    args = ap.parse_args()

    if args.check:
        for c in args.check:
            print(f"  {c:<26}{match_of(c):<10}{half(c)}")
        return 0

    clips = all_clips(Path(args.cameras))
    if not clips:
        raise SystemExit(f"no ground truth under {args.cameras}")
    work = [c for c in clips if half(c) == "work"]
    held = [c for c in clips if half(c) == "held out"]

    if args.list:
        for c in (work if args.list == "work" else held):
            print(c)
        return 0

    wm = sorted({match_of(c) for c in work})
    hm = sorted({match_of(c) for c in held})
    print(f"{len(clips)} clips with WorldPose ground truth, from {len(wm) + len(hm)} matches\n")
    print(f"WORKING HALF — {len(work)} clips, {len(wm)} matches: {', '.join(wm)}")
    for c in work:
        print(f"  {c}")
    print(f"\nHELD OUT — {len(held)} clips, {len(hm)} matches: {', '.join(hm)}")
    print("Do not measure on these until a claim is written down.")
    for c in held:
        print(f"  {c}")
    print(f"\nno match spans both halves: {'yes' if not set(wm) & set(hm) else 'NO'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
