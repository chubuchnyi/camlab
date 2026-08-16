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

#: And they must overlap by at least this fraction of the model line's **visible** length — the
#: part inside the image, after `clip_to_image`. Without any such rule, a short fragment at one end
#: of the pitch can "correspond" to a line at the other end that happens to be parallel. Measured
#: against the *projected* length instead, which is what this used to do, it rejects markings that
#: are sitting exactly on their paint: a line running toward the horizon projects to thousands of
#: pixels and no detector can cover a quarter of that.
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


def world_family(world: np.ndarray, tol_deg: float = 5.0) -> int:
    """Which parallel family a marking belongs to, decided in the WORLD where it is exact.

    Not in the image. Perspective spreads a parallel family's image directions apart — markings 1,
    8 and 11 of this pitch span 22.1 deg to 32.5 deg on one real frame, eleven degrees, against an
    8 deg threshold. Grouping on that is order-dependent: the first two agree, the third does not,
    and which family it lands in depends on the order they were visited. Two members of one world
    family then end up in different image families, where the order-preserving assignment cannot
    see them — and two model lines can claim the same detected segment, which is what a human saw
    on frames 16 and 18.

    A pitch has exactly two families and the world says which is which, exactly, for free.
    """
    d = world[1] - world[0]
    ang = float(np.degrees(np.arctan2(d[1], d[0]))) % 180.0
    return 0 if min(ang, 180.0 - ang) < 45.0 else 1


#: `straight_markings`' answer, built on first use. A module global rather than `functools.cache`
#: so that a test which changes the pitch model can clear it by name.
_STRAIGHT: list[tuple[int, np.ndarray]] | None = None


def straight_markings() -> list[tuple[int, np.ndarray]]:
    """`(index, (2, 2) world endpoints)` for every marking that is straight in the world.

    Circles and arcs are excluded: they have no single direction, so "the angle between them"
    is not defined, and they cannot belong to a parallel family.

    **Built once.** It takes no arguments and reads only the pitch constants, so every call
    returned the identical list — and it rebuilt all 23 polylines to do it, arcs sampled with
    `linspace` and all. `line_errors` calls it once per evaluation and an LM refit issues about
    105 of those per frame: measured on `broadcast`, 6300 calls costing **5.1 s of a 42.7 s carry
    stage**, 12 %, for an answer that cannot change.

    The endpoints come back **read-only**. Handing out a shared mutable array is how a cache turns
    one caller's scratch edit into every later caller's wrong answer, and this repo has the
    equivalent already written down for run directories. Nothing here mutates them today; the flag
    is so that the day something does, it says so instead of quietly changing the metric.
    """
    global _STRAIGHT
    if _STRAIGHT is None:
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
            if perp.max() > 0.05:                   # 5 cm off straight: an arc, not a line
                continue
            ends = xy[[0, -1]]
            ends.flags.writeable = False
            out.append((k, ends))
        _STRAIGHT = out
    return _STRAIGHT


#: `_straight_markings_h`'s answer. Separate from `_STRAIGHT` because it is derived from it and
#: clearing one must clear the other; `_clear_pitch_cache` is the only thing that should.
_STRAIGHT_H: list[tuple[int, np.ndarray, np.ndarray, int]] | None = None


def _straight_markings_h() -> list[tuple[int, np.ndarray, np.ndarray, int]]:
    """`(index, world endpoints, HOMOGENEOUS endpoints, family)` for every straight marking.

    All four are constants of the pitch and `line_errors` needs all four on every evaluation.
    Building `np.column_stack([world, np.ones(2)])` inside its loop cost 209 000 allocations a
    stage for seventeen fixed 2x3 arrays, and `world_family` an `arctan2` and a `degrees` for each.
    """
    global _STRAIGHT_H
    if _STRAIGHT_H is None:
        got = []
        for k, world in straight_markings():
            homo = np.column_stack([world, np.ones(2)])
            homo.flags.writeable = False
            got.append((k, world, homo, world_family(world)))
        _STRAIGHT_H = got
    return _STRAIGHT_H


#: The same markings' homogeneous endpoints as one `(M, 2, 3)` array, so the whole set projects in
#: one matmul instead of seventeen. Verified bit-for-bit against the per-marking `(2, 3) @ h.T`.
_STRAIGHT_STACK: np.ndarray | None = None


def _straight_homogeneous() -> np.ndarray:
    global _STRAIGHT_STACK
    if _STRAIGHT_STACK is None:
        got = np.stack([homo for _k, _w, homo, _f in _straight_markings_h()])
        got.flags.writeable = False
        _STRAIGHT_STACK = got
    return _STRAIGHT_STACK


def _clear_pitch_cache() -> None:
    """Drop what `straight_markings` and `_straight_markings_h` built. For tests that move the
    pitch model, and for nothing else — the pitch does not change during a solve."""
    global _STRAIGHT, _STRAIGHT_H, _STRAIGHT_STACK
    _STRAIGHT = _STRAIGHT_H = _STRAIGHT_STACK = None


def _unit(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    d = b - a
    return d / (np.linalg.norm(d) + 1e-12)


def clip_to_image(seg: np.ndarray, width: int, height: int) -> np.ndarray | None:
    """The part of a segment inside the image, or None if none of it is. Liang–Barsky.

    Everything downstream must measure against THIS and not against the projected marking, because
    a marking running toward the horizon projects to thousands of pixels of which a few hundred are
    on screen. The detector can only ever find the part that is visible, so requiring it to cover a
    fraction of the whole is requiring the impossible: one measured frame projects marking #1 to
    11,115 px, where the longest thing any detector could return covers 10 % — and marking #3 was
    rejected at 24 % overlap while sitting 0.2 px off its paint at 0.7 deg.
    """
    p0, p1 = np.asarray(seg, float)
    d = p1 - p0
    t0, t1 = 0.0, 1.0
    for p, q in ((-d[0], p0[0]), (d[0], width - 1 - p0[0]),
                 (-d[1], p0[1]), (d[1], height - 1 - p0[1])):
        if abs(p) < 1e-12:
            if q < 0:
                return None                     # parallel to this edge and outside it
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    if t1 <= t0:
        return None
    return np.array([p0 + t0 * d, p0 + t1 * d])


def _overlap(model: np.ndarray, found: np.ndarray,
             u: np.ndarray | None = None) -> tuple[float, float, float]:
    """Extent of `found` projected onto `model`'s direction, clipped to `model`. `(lo, hi, len)`.

    `u` is `model`'s unit direction. The caller almost always has it already — `line_errors`
    computes it once per marking and then compares that marking against every detected segment —
    and recomputing it here made `_unit` the second most-called function in the repo.
    """
    u = _unit(model[0], model[1]) if u is None else u
    t_model = np.array([0.0, float((model[1] - model[0]) @ u)])
    t_found = np.sort((found - model[0]) @ u)
    lo = max(t_model[0], t_found[0])
    hi = min(t_model[1], t_found[1])
    return lo, hi, max(0.0, hi - lo)


def compare_line(model: np.ndarray, found: np.ndarray, *,
                 u: np.ndarray | None = None, nrm: np.ndarray | None = None,
                 v: np.ndarray | None = None) -> tuple[float, float, float, np.ndarray,
                                                       np.ndarray]:
    """`(signed offset px, signed angle deg, overlap px, point on model, point on found)`.

    The offset is measured at the middle of the overlap, perpendicular to the model line, which is
    where a human would hold a ruler: at the part of the line both actually cover.

    `u`, `nrm` and `v` are the model's unit direction, its left normal, and the found segment's
    unit direction. They are optional and default to being computed here, which is what every
    caller outside `line_errors` wants. `line_errors` passes them, because it already has all
    three: `u` and `nrm` are per-marking and this runs per marking PER SEGMENT, and `v` is
    `seg_dir[si]`, computed once for the whole call. Recomputing them here meant a 2-vector norm
    ran about four times per comparison and `np.linalg.norm` was called a million times a stage.
    """
    u = _unit(model[0], model[1]) if u is None else u
    nrm = np.array([-u[1], u[0]]) if nrm is None else nrm    # left normal of the model line
    lo, hi, length = _overlap(model, found, u)
    t_mid = (lo + hi) / 2.0 if length > 0 else float((model[1] - model[0]) @ u) / 2.0
    p_model = model[0] + t_mid * u

    v = _unit(found[0], found[1]) if v is None else v
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


def _rowdot(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise dot of 2-vectors, **bit-for-bit what `a @ b` returns on one pair**.

    `b` may be a single `(2,)` vector or one per row.

    This exists because the obvious spellings are not equal to the scalar one and this repo's
    metric is compared with `==`. Probed over 20 000 random pairs against `[a @ b for a, b in ...]`:

        `(A * B).sum(axis=1)`                  differs
        `A @ b`  (a gemv, for fixed `b`)       differs
        `A[:, 0] * B[:, 0] + A[:, 1] * B[:, 1]` differs
        `np.einsum('ij,ij->i', A, B)`          differs
        `np.matmul(A[:, None, :], B[:, :, None])`  **equal on every pair**

    BLAS's two-element dot fuses its multiply and add — one rounding — and every elementwise form
    rounds the product and then the sum. The difference is 1e-16 relative and it is not academic:
    `_assign_in_order` settles which segment a marking gets with `best == take`, and a solve
    minimises this number a hundred times a frame.

    A stack of matrix-vector products, `(M, 2, 2) @ u`, is NOT affected — it already agrees with
    the single `(2, 2) @ u` — so `_overlap`'s projection is left as it was written.
    """
    return np.matmul(a[:, None, :], np.broadcast_to(b, a.shape)[:, :, None]).reshape(-1)


def _visible_markings(h, width, height):
    """Every straight marking projected, clipped and measured at once.

    Returns `(indices into _straight_markings_h, clipped endpoints (M, 2, 2), unit direction,
    left normal, own length along that direction, visible length)` for the markings that survive.

    This was a Python loop over seventeen markings, each doing a projection, a `clip_to_image`, a
    `_unit` and two norms — about ten numpy calls on 2-element arrays, seventeen times, on every
    one of the ~50 evaluations an LM refit makes. `clip_to_image` stays as the readable
    single-segment definition and as what this is checked against; Liang-Barsky vectorises because
    its four edge tests are the same four tests for every segment, and an element that has already
    been clipped out simply stops mattering rather than needing an early return.
    """
    homo = _straight_homogeneous()
    q = homo @ h.T                                        # (M, 2, 3)
    z = q[:, :, 2]
    live = (np.abs(z) >= 1e-9).all(axis=1)
    # 1.0 where the point is degenerate, so the division neither warns nor produces a NaN that
    # would then have to be told apart from a real one. Those rows are already dead.
    uv = q[:, :, :2] / np.where(np.abs(z) < 1e-9, 1.0, z)[:, :, None]
    live &= np.isfinite(uv).all(axis=(1, 2))

    p0, d = uv[:, 0], uv[:, 1] - uv[:, 0]
    t0, t1 = np.zeros(len(uv)), np.ones(len(uv))
    for p, qq in ((-d[:, 0], p0[:, 0]), (d[:, 0], width - 1 - p0[:, 0]),
                  (-d[:, 1], p0[:, 1]), (d[:, 1], height - 1 - p0[:, 1])):
        par = np.abs(p) < 1e-12
        live &= ~(par & (qq < 0))                         # parallel to this edge and outside it
        t = np.zeros(len(uv))
        np.divide(qq, p, out=t, where=~par)
        neg, pos = (~par) & (p < 0), (~par) & (p >= 0)
        # The order is the algorithm: each test reads the bound BEFORE this edge updates it, and
        # a segment takes one branch or the other, never both.
        live &= ~(neg & (t > t1))
        t0 = np.where(neg, np.maximum(t0, t), t0)
        live &= ~(pos & (t < t0))
        t1 = np.where(pos, np.minimum(t1, t), t1)
    live &= t1 > t0

    vis = np.stack([p0 + t0[:, None] * d, p0 + t1[:, None] * d], axis=1)
    dv = vis[:, 1] - vis[:, 0]
    # `sqrt(_rowdot(d, d))`, NOT `np.linalg.norm(d, axis=1)`: the axis form is not bit-for-bit the
    # 1-D one this replaces. Probed over 5000 random 2-vectors.
    vis_len = np.sqrt(_rowdot(dv, dv))
    live &= vis_len >= 40.0

    idx = np.flatnonzero(live)
    dv, vis_len = dv[idx], vis_len[idx]
    u = dv / (vis_len + 1e-12)[:, None]
    nrm = np.stack([-u[:, 1], u[:, 0]], axis=1)
    return idx, vis[idx], u, nrm, _rowdot(dv, u), vis_len


def _candidates(uv, u, nrm, seg_pts, seg_dir, min_cos, min_overlap_px, max_offset_px):
    """`compare_line(uv, p)` against every detected segment, for ONE marking.

    Kept as the single-marking definition and as what `_candidates_grid` is checked against; the
    grid below is this function done for every marking at once. `compare_line` in turn is the
    single-PAIR definition every other caller and every test uses. Three statements of the same
    arithmetic, each one the reference for the next.

    **Every 2-vector dot goes through `_rowdot`, and the reason is not style.** The first version
    used `(A * B).sum(axis=1)`, which is the obvious way to write a row-wise dot and is **not
    bit-for-bit what `a @ b` returns**. The equivalence check caught it at once: offsets moved by
    1e-16 to 9e-14 on 12 of 14 clips. That is far below any measurement here and it still matters,
    because `_assign_in_order` settles its alignment with `best == take` — an exact float
    comparison — so a last-bit difference can hand a marking a different segment.
    """
    if not len(seg_pts):
        return []
    cos_all = _rowdot(seg_dir, u)
    passes = np.abs(cos_all) >= min_cos
    if not passes.any():
        return []
    idx = np.flatnonzero(passes)
    found, vdir, cos = seg_pts[idx], seg_dir[idx], cos_all[idx]

    span = float((uv[1] - uv[0]) @ u)
    t_found = np.sort((found - uv[0]) @ u, axis=1)
    lo = np.maximum(0.0, t_found[:, 0])
    hi = np.minimum(span, t_found[:, 1])
    length = np.maximum(0.0, hi - lo)

    t_mid = np.where(length > 0, (lo + hi) / 2.0, span / 2.0)
    p_model = uv[0] + t_mid[:, None] * u
    v = np.where((cos < 0)[:, None], -vdir, vdir)
    t = _rowdot(p_model - found[:, 0], v)
    p_found = found[:, 0] + t[:, None] * v
    offset = _rowdot(p_found - p_model, nrm)
    angle = np.degrees(np.arctan2(v[:, 0] * u[1] - v[:, 1] * u[0], _rowdot(v, u)))

    keep = (length >= min_overlap_px) & (np.abs(offset) <= max_offset_px)
    return [(int(idx[j]), float(offset[j]), float(angle[j]), float(length[j]),
             p_model[j], p_found[j], found[j])
            for j in np.flatnonzero(keep)]


def _candidates_grid(uv, u, nrm, span, gate_px, seg_pts, seg_dir, min_cos, max_offset_px):
    """`_candidates` for EVERY visible marking at once — one dispatch instead of seventeen.

    The arrays are per marking: `uv` the clipped endpoints `(M, 2, 2)`, `u` its unit direction
    `(M, 2)`, `nrm` its left normal, `span` its own length along `u`, `gate_px` the overlap a
    candidate must clear. Returns a list of `M` candidate lists, in the order `_candidates` gave
    them — ascending segment index — so `_assign_in_order` sees exactly what it saw.

    **Measured before it was written, which is the only reason it exists.** `_candidates` costs
    5.8 us for one marking and 97.9 us for the seventeen a frame has; the identical arithmetic over
    seventeen times the segments in ONE call costs 7.1 us. **93 % of it was interpreter dispatch**,
    and the ceiling was 13.9x. That is the same disease as `_across_on_normal`'s 322 trips over
    2.3 KB, one level up: the arrays here are `(17, 12)` and fit in L1 twice over, so nothing is
    being computed faster — it is being asked for once instead of seventeen times.

    It is NOT the same conclusion as vectorising over segments alone, which is measured in
    `making-it-fast-again-2026-08-16.md` §5 to be a wash below ten segments a frame. The marking
    count is fixed by the pitch model at seventeen and does not depend on the clip, the detector or
    the threshold, so this multiplier is a property of the geometry rather than of the data.

    Two traps in writing it, both probed against the scalar form before a line was changed:
    `np.linalg.norm(d, axis=1)` is **not** bit-for-bit the 1-D `np.linalg.norm(d)` — use
    `sqrt(_rowdot(d, d))` — and a flattened `_rowdot` does **not** reproduce a matrix-vector
    product — use `np.matmul(F, U[..., None])`, which does, exactly.
    """
    m, n = len(uv), len(seg_pts)
    if not m or not n:
        return [[] for _ in range(m)]

    # (M, N, ...) — every marking against every segment. `np.broadcast_to` gives views; only the
    # results are materialised.
    seg_g = np.broadcast_to(seg_dir, (m, n, 2))
    u_g = np.broadcast_to(u[:, None, :], (m, n, 2))
    cos = _rowdot(seg_g.reshape(-1, 2), u_g.reshape(-1, 2)).reshape(m, n)

    # `_overlap`: each segment's extent projected onto the marking's direction, clipped to it.
    delta = seg_pts[None, :, :, :] - uv[:, None, 0, None, :]          # (M, N, 2, 2)
    t_found = np.sort(np.matmul(delta, u[:, None, :, None])[..., 0], axis=2)
    lo = np.maximum(0.0, t_found[:, :, 0])
    hi = np.minimum(span[:, None], t_found[:, :, 1])
    length = np.maximum(0.0, hi - lo)

    # `compare_line`: the offset at the middle of the overlap, perpendicular to the marking.
    t_mid = np.where(length > 0, (lo + hi) / 2.0, (span / 2.0)[:, None])
    p_model = uv[:, None, 0, :] + t_mid[..., None] * u[:, None, :]
    v = np.where((cos < 0)[..., None], -seg_g, seg_g)
    found0 = np.broadcast_to(seg_pts[None, :, 0, :], (m, n, 2))
    t = _rowdot((p_model - found0).reshape(-1, 2), v.reshape(-1, 2)).reshape(m, n)
    p_found = found0 + t[..., None] * v
    offset = _rowdot((p_found - p_model).reshape(-1, 2),
                     np.broadcast_to(nrm[:, None, :], (m, n, 2)).reshape(-1, 2)).reshape(m, n)
    vu = _rowdot(v.reshape(-1, 2), u_g.reshape(-1, 2)).reshape(m, n)
    angle = np.degrees(np.arctan2(v[:, :, 0] * u[:, None, 1] - v[:, :, 1] * u[:, None, 0], vu))

    keep = ((np.abs(cos) >= min_cos) & (length >= gate_px[:, None])
            & (np.abs(offset) <= max_offset_px))
    rows, cols = np.nonzero(keep)
    out: list[list] = [[] for _ in range(m)]
    for r, c in zip(rows, cols, strict=True):
        out[r].append((int(c), float(offset[r, c]), float(angle[r, c]), float(length[r, c]),
                       p_model[r, c], p_found[r, c], seg_pts[c]))
    return out


def line_errors(segments: np.ndarray, focal: float, rvec, centre, width: int, height: int,
                cx: float | None = None, cy: float | None = None,
                *, match_angle_deg: float = MATCH_ANGLE_DEG,
                min_overlap: float = MIN_OVERLAP,
                max_offset_px: float = MAX_OFFSET_PX) -> list[LineError]:
    """Every straight marking the camera puts in frame, against the segments actually detected.

    `cx, cy` default to the image centre **only** if not given, and the image centre is wrong on a
    cropped clip: the optical axis is not the centre of the frames on disk.

    **Given a camera file, pass ITS `cx`/`cy`.** This used to say "pass `ClipInfo.principal_point`",
    which is right only when fitting a camera from scratch. Once a camera exists it records the axis
    it was fitted with, and that is the one its numbers mean. They differ, and not by a little:
    `fan` solved at (540, 304) where `ClipInfo.principal_point` derives (540, -334), because the
    clip is a crop and that property answers "where is the axis in the SOURCE frame". Scoring one
    `fan` frame through the clip's value found **1 model marking and 0 matches**, against 8 and 7
    through the camera's own — a silent, total loss that reads as "this frame has no markings".
    """
    cx = width / 2.0 if cx is None else cx
    cy = height / 2.0 if cy is None else cy
    h = world_to_image(focal, rvec, centre, width, height, cx=cx, cy=cy)

    # One `(N, 2, 2)` array viewed as a list of endpoints, and the directions in one vectorised
    # pass, rather than two Python loops building N small arrays each. Identical values — a
    # 2-vector's norm is the same two multiplies and one add either way — and `line_errors` is
    # called about 105 times per frame by one LM refit, always on the SAME segments.
    segments = np.asarray(segments, dtype=float).reshape(-1, 4)
    seg_pts = segments.reshape(-1, 2, 2)
    delta = seg_pts[:, 1] - seg_pts[:, 0]
    seg_dir = delta / (np.linalg.norm(delta, axis=1) + 1e-12)[:, None]
    # Hoisted out of the per-marking, per-segment loop it used to sit in: it depends on nothing
    # inside it, and it was costing a `radians` and a `cos` on all 141 000 comparisons a stage.
    min_cos = float(np.cos(np.radians(match_angle_deg)))

    # Every marking projected, clipped and measured in one pass, then every (marking, segment)
    # pair in one more. This was two nested Python loops — seventeen markings, each compared with
    # every segment — issuing a few hundred numpy calls on 2-element arrays per evaluation, and an
    # LM refit makes about fifty evaluations a frame. Clipping keeps the whole visible extent and
    # everything below measures against THAT, which replaced a "both ends within twice the frame"
    # test that threw away every marking running toward the horizon — the ones with the most pixels
    # on screen — and fixed the overlap denominator at the same time, both faults being the same
    # mistake: treating the projected length as the measurable length.
    idx, uv, u, nrm, span, vis_len = _visible_markings(h, width, height)
    cands = _candidates_grid(uv, u, nrm, span, min_overlap * vis_len,
                             seg_pts, seg_dir, min_cos, max_offset_px)
    marks = _straight_markings_h()
    model = [(marks[i][0], uv[j], u[j], cands[j], marks[i][3]) for j, i in enumerate(idx)]

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
    # Grouped by WORLD direction, which is exact, rather than by image direction, which perspective
    # smears across more than the threshold. See `world_family`.
    by_family: dict[int, list] = {}
    for entry in model:
        by_family.setdefault(entry[4], []).append(entry)
    families = list(by_family.values())

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

        for k, uv, _u, _cands, _fk in fam:
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
