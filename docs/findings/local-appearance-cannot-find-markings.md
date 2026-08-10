# Local appearance cannot tell a marking from a mowing stripe

Measured 2026-08-10, after a human read the overlay on frames 8, 13, 16, 17 and 18 and reported
what the error was being measured **against**:

- frame 8, 13: the goal line's error measured from a dark line on the grass by the boards, running
  parallel to the boards, not from a marking
- frame 16: the overlay's goal line compared with that grass line (−55 px) while the real goal line
  was compared with the *next* overlay line (−23 px) — an assignment shifted by one
- frame 18: two overlay lines compared against the same goal line, and a line perpendicular to the
  goal line compared against the goal **net** (−94 px)

## Two filters tried, both dead

**Colour.** Pitch paint is white — low saturation, high value — and grass is not, so a colour test
should separate them. It does not.

| | saturation | value |
|---|---|---|
| matched segments | 62–106 | 176–255 |
| unmatched | 63–92 | 200–255 |

The distributions overlap almost entirely. A "white and unsaturated" filter, which was the obvious
next move, would have changed nothing.

**Ridge contrast.** Centre brightness minus the darker flank, at 3 px and 10 px out. Frame 18:

| matched | ±3 px | ±10 px | | unmatched | ±3 px | ±10 px |
|---|---|---|---|---|---|---|
| ✓ | 65 | 61 | | ✗ | **68** | 61 |
| ✓ | 61 | 55 | | ✗ | **67** | 59 |
| ✓ | 34 | 43 | | ✗ | 62 | 56 |
| ✓ | 17 | 15 | | ✗ | 60 | 54 |

The false lines score **higher** than several real markings. Frame 16 has the same shape.

## Why, and it is not a threshold problem

`paint_masks` looks for *a bright narrow ridge with turf on both sides*. **A mowing-stripe boundary
is exactly that.** So is the bright edge of a shadow, and so are parts of a goal net. The test is
not too loose; it is a correct description of something other than paint as well as of paint.

No local appearance test separates them, and the two most plausible ones are now ruled out by
measurement rather than left as untried ideas.

## What has to replace it

The discriminator must be **global and geometric**: a candidate line is a marking if it takes part
in a configuration consistent with a pitch. Its family must meet at one vanishing point, its
spacing from its neighbours must match the Laws, it must have a perpendicular partner. A mowing
stripe joins the wrong family or sits at the wrong spacing; a net has neither.

Which collapses two problems into one: **detection and correspondence are the same problem**, and
it is the hard half of auto-aim (task #11). That was scoped as needed to remove the `--scene`
dependency. It turns out to be needed for the *metric* as well, which is a much more immediate
reason to build it.

There is also a plain bug in the current assignment, separate from all of this: on frames 16 and 18
two model lines matched the same detected line, which the order-preserving alignment forbids within
a family. Either the family grouping is splitting lines that belong together, or the traceback is
wrong. Reproduce on frame 18 first.

## The wider lesson, which is the same one as everywhere else in this project

Both filters were about to be implemented on the strength of being obviously right. Measuring them
first cost twenty minutes and saved building two things that do not work. The pattern across this
whole thread is that plausible reasoning about this data has been wrong far more often than it has
been right, and the only defence that has held is checking against an answer known in advance.
