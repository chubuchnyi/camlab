# Archive

Documents that were true when written and have since been superseded. Kept because a retraction is
worth more than a deletion — several of this project's expensive mistakes were made twice, and the
second time only because the first was not written down where anyone would look.

**Nothing here should be read as current.** For that, `docs/STATUS.md`.

| file | what it was | what replaced it |
|---|---|---|
| `ranking-2026-08-10.md` | a snapshot of how the calibration methods ranked on 10 August | `findings/the-metric-had-a-ceiling.md` — that ranking was taken with a metric that could not report an error above 40 px, so every number in it is a floor rather than a measurement |
| `the-camera-was-never-refitted.md` | the incident where the viewer served a stale solve after every refit, twice, and a human caught it both times | fixed; the viewer reads the selected camera and `runs/` is listed in full. Kept because the failure mode — a green pipeline serving old numbers — recurred later in a different shape when `deploy.sh` shipped HEAD rather than the working tree |

## Also historical, but still where it was

`docs/spec.md` (907 lines, Russian) is the original plan and design argument, written before any of
this was measured. It is not archived because it is still the only place several decisions are
argued rather than merely stated — but its **milestones and its schedule are obsolete**. M1 through
M3 as written there describe work that is done, and the plan it lays out for M2 (a PTZ model with
one position and a smooth focal) was arrived at, but by a different route than it proposes and
after the discovery that the position line is a degeneracy rather than a trajectory.

Read the spec for *why*, `docs/STATUS.md` for *what*.
