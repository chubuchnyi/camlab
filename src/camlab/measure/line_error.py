"""How far each pitch line is from where the camera says it should be — as a human would measure it.

The metric this replaces sampled the model markings and asked each point for the nearest paint
pixel within 40 px. That number cannot be checked against anything on screen, and it was wrong in
ways that only showed up when someone looked: it is blind to a line sliding along itself, it lets
one marking match a different marking's paint, it saturates at its own bound, and the solved camera
was not even at its minimum (`findings/the-metric-does-not-measure-camera-error.md`).

**The eye compares lines to lines.** "This line is thirty pixels below where it should be." So does
this: for each model marking it reports a **signed perpendicular offset in pixels** and an **angle
difference in degrees**, both measured against the detected segment it corresponds to, both drawn
in the viewer, and both checkable with the ruler.

That last part is the point. A number you can put a ruler on is a number that can be wrong out
loud. The previous one could not be.

**Correspondence, not proximity.** A model line matches a detected segment only if their directions
agree and they overlap along their shared direction. Nearest-anything is what let a goal-area line
score itself against the goal line.

**Both directions are errors.** A model line predicted visible with no segment under it is a miss
and is reported as one; a detected segment with no model line is reported too, because it is
either a marking the camera has put somewhere else entirely or something that is not a pitch line.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from camlab.core.pitch import pitch_polylines
from camlab.measure.residual import world_to_image

#: Directions must agree to this for two lines to be the same marking. Generous next to the errors
#: being measured — a 30 px offset over a 900 px line is under 2° — and tight enough that the two
#: perpendicular families of a pitch never collide.
MATCH_ANGLE_DEG = 8.0

#: And they must overlap by at least this fraction of the model line's projected length. Without
#: it, a short fragment at one end of the pitch can "correspond" to a line at the other end that
#: happens to be parallel.
MIN_OVERLAP = 0.25

#: Beyond this the pairing is not believable as the same marking, and the model line is reported as
#: a MISS rather than as a large offset. Deliberately far above the errors seen so far: a bound
#: that the data reaches is a bound that hides the tail, which is how the old metric ended up
#: reporting its own ceiling on every frame.
MAX_OFFSET_PX = 250.0


@dataclass(frozen=True)
class LineError:
    """One model marking, and the detected line it should have landed on.

    Attributes:
        marking: Index into `pitch_polylines()`.
        offset_px: **Signed** perpendicular distance from the model line to the detected one,
            measured at the middle of their overlap. Positive is along the model line's left
            normal, so the sign says which way to move — that is what makes it drawable.
        angle_deg: Signed direction difference. An offset of zero with a large angle is a line
            pivoted about its middle, which an unsigned distance would average away to nothing.
        overlap_px: How much of the two lines actually face each other. Small means the number is
            supported by a short stretch and should be read with that in mind.
        model_uv: The model line's projected endpoints, `(2, 2)`.
        found_uv: The matched detected segment's endpoints, or None for a miss.
        p1_uv, p2_uv: The two points the offset is measured BETWEEN — one on the model line, one
            on the detected line. The viewer draws exactly this pair, and a ruler dropped on those
            two points must read `offset_px`.
    """

    marking: int
    offset_px: float
    angle_deg: float
    overlap_px: float
    model_uv: np.ndarray
    found_uv: np.ndarray | None
    p1_uv: np.ndarray | None
    p2_uv: np.ndarray | None

    @property
    def matched(self) -> bool:
        return self.found_uv is not None


def straight_markings() -> list[tuple[int, np.ndarray]]:
    """`(index, (2, 2) world endpoints)` for every marking that is straight in the world.

    Circles and arcs are excluded: they have no single direction, so "the angle between them"
    is not defined, and they cannot belong to a parallel family.
    """
    out = []
    for k, poly in enumerate(pitch_polylines()):
        xy = np.asarray(poly, dtype=float)[:, :2]
        if len(xy) < 2:
            continue
        d = xy[-1] - xy[0]
        n = float(np.linalg.norm(d))
        if n < 1e-9:
            continue
        perp = np.abs((xy - xy[0]) @ np.array([-d[1], d[0]]) / n)
        if perp.max() > 0.05:                       # 5 cm off straight: an arc, not a line
            continue
        out.append((k, xy[[0, -1]]))
    return out


def _unit(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    return d / (np.linalg.norm(d) + 1e-12)


def _overlap(model: np.ndarray, found: np.ndarray) -> tuple[float, float, float]:
    """Extent of `found` projected onto `model`'s direction, clipped to `model`. `(lo, hi, len)`."""
    u = _unit(model[0], model[1])
    t_model = np.array([0.0, float((model[1] - model[0]) @ u)])
    t_found = np.sort((found - model[0]) @ u)
    lo = max(t_model[0], t_found[0])
    hi = min(t_model[1], t_found[1])
    return lo, hi, max(0.0, hi - lo)


def compare_line(model: np.ndarray, found: np.ndarray) -> tuple[float, float, float, np.ndarray,
                                                                np.ndarray]:
    """`(signed offset px, signed angle deg, overlap px, point on model, point on found)`.

    The offset is measured at the middle of the overlap, perpendicular to the model line, which is
    where a human would hold a ruler: at the part of the line both actually cover.
    """
    u = _unit(model[0], model[1])
    nrm = np.array([-u[1], u[0]])                   # left normal of the model line
    lo, hi, length = _overlap(model, found)
    t_mid = (lo + hi) / 2.0 if length > 0 else float((model[1] - model[0]) @ u) / 2.0
    p_model = model[0] + t_mid * u

    v = _unit(found[0], found[1])
    if v @ u < 0:
        v = -v                                      # same sense, so the angle is not 180-ambiguous

    # The FOOT OF THE PERPENDICULAR from p_model onto the detected line — i.e. the nearest point
    # on it. The first version instead solved for the point on the detected line with the same
    # normal coordinate as p_model, which is identically p_model's own offset and therefore
    # returned 0.0 for every line on every frame. It looked like a perfect camera.
    t = float((p_model - found[0]) @ v)
    p_found = found[0] + t * v

    offset = float((p_found - p_model) @ nrm)
    angle = float(np.degrees(np.arctan2(float(v[0] * u[1] - v[1] * u[0]), float(v @ u))))
    return offset, angle, length, p_model, p_found


def line_errors(segments: np.ndarray, focal: float, rvec, centre, width: int, height: int,
                cx: float | None = None, cy: float | None = None,
                *, match_angle_deg: float = MATCH_ANGLE_DEG,
                min_overlap: float = MIN_OVERLAP,
                max_offset_px: float = MAX_OFFSET_PX) -> list[LineError]:
    """Every straight marking the camera puts in frame, against the segments actually detected.

    `cx, cy` default to the image centre **only** if not given. Pass `ClipInfo.principal_point`:
    on a cropped clip the optical axis is not the centre of the frames on disk, and this clip's is
    638 px away from it.
    """
    cx = width / 2.0 if cx is None else cx
    cy = height / 2.0 if cy is None else cy
    h = world_to_image(focal, rvec, centre, width, height, cx=cx, cy=cy)

    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    seg_pts = [np.array([[s[0], s[1]], [s[2], s[3]]]) for s in segments]
    seg_dir = [_unit(p[0], p[1]) for p in seg_pts]

    model: list = []
    for k, world in straight_markings():
        q = np.column_stack([world, np.ones(2)]) @ h.T
        if np.any(np.abs(q[:, 2]) < 1e-9):
            continue
        uv = q[:, :2] / q[:, 2, None]
        if not np.isfinite(uv).all():
            continue
        # Both ends must be near the frame. A marking crossing the image border is still usable;
        # one entirely outside it is not evidence about anything.
        if not ((-width < uv[:, 0]).all() and (uv[:, 0] < 2 * width).all()
                and (-height < uv[:, 1]).all() and (uv[:, 1] < 2 * height).all()):
            continue
        if np.linalg.norm(uv[1] - uv[0]) < 40.0:
            continue

        u = _unit(uv[0], uv[1])
        cands = []
        for si, (p, v) in enumerate(zip(seg_pts, seg_dir, strict=True)):
            if abs(float(v @ u)) < np.cos(np.radians(match_angle_deg)):
                continue
            off, ang, ov, p1, p2 = compare_line(uv, p)
            if ov < min_overlap * float(np.linalg.norm(uv[1] - uv[0])):
                continue
            if abs(off) > max_offset_px:
                continue
            cands.append((si, off, ang, ov, p1, p2, p))
        model.append((k, uv, u, cands))

    return _assign_in_order(model, seg_pts)


def _assign_in_order(model, seg_pts):
    """Choose one segment per model line so the assignment PRESERVES ORDER within each family.

    Picking each line's nearest parallel segment independently is what let a marking measure itself
    against its neighbour — the same fault as the old metric's nearest-paint, one level up. But
    parallel markings appear in the image in the same order as in the world, always, so a valid
    assignment is monotone in the perpendicular coordinate. That constraint is free and it removes
    the whole failure: a line cannot swap onto its neighbour without its neighbour swapping past
    it, which a monotone matching forbids.

    Grouped by direction, then a sequence alignment (gaps allowed on both sides, since a marking
    may be undetected and a detected segment may be no marking of ours) minimising total |offset|.
    """
    out: list[LineError] = []
    used: set[int] = set()
    # Families: model lines whose image directions agree. A pitch gives two, but a frame that shows
    # only a corner can give one, and grouping rather than assuming keeps that honest.
    families: list[list] = []
    for entry in model:
        u = entry[2]
        for fam in families:
            if abs(float(u @ fam[0][2])) > np.cos(np.radians(MATCH_ANGLE_DEG)):
                fam.append(entry)
                break
        else:
            families.append([entry])

    for fam in families:
        # Order both sides along the family's shared normal.
        u0 = fam[0][2]
        nrm = np.array([-u0[1], u0[0]])
        fam = sorted(fam, key=lambda e: float(((e[1][0] + e[1][1]) / 2) @ nrm))
        seg_ids = sorted({c[0] for e in fam for c in e[3]},
                         key=lambda i: float(((seg_pts[i][0] + seg_pts[i][1]) / 2) @ nrm))

        # Sequence alignment. cost = |offset|; a gap on either side costs a flat penalty, so an
        # unmatched marking is preferred over a wrong match but not over a plausible one.
        GAP = float(max_offset_px_default())
        n_m, n_s = len(fam), len(seg_ids)
        dp = np.full((n_m + 1, n_s + 1), np.inf)
        back = np.zeros((n_m + 1, n_s + 1), dtype=np.int8)
        dp[0, :] = np.arange(n_s + 1) * 0.0            # skipping a detected segment is free
        for i in range(1, n_m + 1):
            dp[i, 0] = dp[i - 1, 0] + GAP
            back[i, 0] = 1
        for i in range(1, n_m + 1):
            byseg = {c[0]: c for c in fam[i - 1][3]}
            for j in range(1, n_s + 1):
                c = byseg.get(seg_ids[j - 1])
                take = dp[i - 1, j - 1] + (abs(c[1]) if c is not None else np.inf)
                skip_m = dp[i - 1, j] + GAP
                skip_s = dp[i, j - 1]
                best = min(take, skip_m, skip_s)
                dp[i, j] = best
                back[i, j] = 0 if best == take else (1 if best == skip_m else 2)

        i, j = n_m, n_s
        chosen: dict[int, tuple] = {}
        while i > 0:
            if back[i, j] == 0 and j > 0:
                byseg = {c[0]: c for c in fam[i - 1][3]}
                c = byseg.get(seg_ids[j - 1])
                if c is not None:
                    chosen[fam[i - 1][0]] = c
                i, j = i - 1, j - 1
            elif back[i, j] == 1 or j == 0:
                i -= 1
            else:
                j -= 1

        for k, uv, _u, _cands in fam:
            c = chosen.get(k)
            if c is None:
                out.append(LineError(k, float("nan"), float("nan"), 0.0, uv, None, None, None))
            else:
                _si, off, ang, ov, p1, p2, p = c
                used.add(_si)
                out.append(LineError(k, off, ang, ov, uv, p, p1, p2))
    return sorted(out, key=lambda e: e.marking)


def max_offset_px_default() -> float:
    return MAX_OFFSET_PX


def summarise(errors: list[LineError]) -> dict:
    """The headline numbers, with the misses kept visible rather than dropped."""
    matched = [e for e in errors if e.matched]
    offs = np.array([abs(e.offset_px) for e in matched]) if matched else np.array([])
    angs = np.array([abs(e.angle_deg) for e in matched]) if matched else np.array([])
    return {
        "n_lines": len(errors),
        "n_matched": len(matched),
        "n_missed": len(errors) - len(matched),
        "worst_offset_px": float(offs.max()) if offs.size else float("nan"),
        "median_offset_px": float(np.median(offs)) if offs.size else float("nan"),
        "worst_angle_deg": float(angs.max()) if angs.size else float("nan"),
        "worst_marking": int(matched[int(np.argmax(offs))].marking) if offs.size else -1,
    }
