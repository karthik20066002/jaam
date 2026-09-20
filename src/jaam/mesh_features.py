"""FDTD mesh anchors that are not the geometric polyline."""

from __future__ import annotations

import math
from collections.abc import Iterable

from .ir import BoxOp, CurveOp, Point3, RotPolyOp, WireOp

_C0 = 299_792_458.0


def fdtd_feature_axes(
    geometry: Iterable[CurveOp | WireOp | BoxOp | RotPolyOp],
    wavelength: float,
) -> tuple[set[float], set[float], set[float]]:
    """Sparse Cartesian features for openEMS, including ±radius on kept points."""
    geometry = tuple(geometry)
    axes: tuple[set[float], set[float], set[float]] = (set(), set(), set())
    min_step = wavelength / 20.0
    # A feed splits its wire into two ops (see semantics._split_path): the
    # fed piece's own cut end, the unfed sibling's cut start, and the feed's
    # own start/stop all land within one wire-radius of each other. Collect
    # every feed's anchors up front, across the whole geometry, so a critical
    # point on ANY op (not just the one carrying the feed) can be recognized
    # as feed-adjacent below.
    feed_points: set[Point3] = set()
    for op in geometry:
        if isinstance(op, (CurveOp, WireOp)) and op.feed is not None:
            feed_points.add(op.feed.start)
            feed_points.add(op.feed.stop)
    for op in geometry:
        if isinstance(op, (CurveOp, WireOp)):
            _add_wire_features(axes, op, min_step, feed_points)
        elif isinstance(op, BoxOp):
            for i in range(3):
                axes[i].add(op.start[i])
                axes[i].add(op.stop[i])
        elif isinstance(op, RotPolyOp):
            radial = max(abs(value) for point in op.points for value in point)
            axes[0].update((-radial, radial))
            axes[1].update((-radial, radial))
            axes[2].add(op.elevation)
    return axes


def _add_wire_features(
    axes: tuple[set[float], set[float], set[float]],
    op: CurveOp | WireOp,
    min_step: float,
    feed_points: set[Point3],
) -> None:
    # Interior path samples are snapped to λ/20 so a helix does not stamp a
    # unique line per tessellation vertex. Endpoints/feed/bbox stay exact:
    # the two path ends are excluded here since `critical` (below) adds them
    # unsnapped. Without this, a straight wire's exact endpoint and its
    # rounded λ/20 twin land microns apart, planting a near-zero-width cell
    # that collapses the FDTD timestep for the whole domain.
    endpoints = {op.points[0], op.points[-1]}
    for point in _sparse_path(op.points, min_step):
        if point in endpoints:
            continue
        for i in range(3):
            axes[i].add(round(point[i] / min_step) * min_step if min_step else point[i])
    critical = [op.points[0], op.points[-1]]
    if op.feed is not None:
        critical.extend((op.feed.start, op.feed.stop))
    for i in range(3):
        critical.append(min(op.points, key=lambda point: point[i]))
        critical.append(max(op.points, key=lambda point: point[i]))
    radius = op.radius_m
    for point in critical:
        for i in range(3):
            axes[i].add(point[i])
        # Any point within one wire-radius of a feed anchor already sits
        # inside that feed's dedicated gap-refinement region (see
        # semantics._refine_feed_gap / _metal_gap_ends), on this op or its
        # split sibling. Padding it by ±radius here plants lines that
        # interleave with the feed's own fine mesh, sometimes microns apart,
        # collapsing the FDTD timestep for the whole domain for no accuracy
        # benefit.
        if radius > 0 and not any(math.dist(point, feed) <= radius for feed in feed_points):
            for i in range(3):
                axes[i].update(
                    (point[i] - radius, point[i] - radius / 2.0, point[i] + radius / 2.0, point[i] + radius)
                )


def _sparse_path(points: tuple[Point3, ...], min_step: float) -> list[Point3]:
    if not points:
        return []
    kept = [points[0]]
    for point in points[1:]:
        if max(abs(point[i] - kept[-1][i]) for i in range(3)) >= min_step:
            kept.append(point)
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def path_sample_count(*, arc_length: float, wavelength: float, turns: float | None = None, angle_rad: float | None = None) -> int:
    """Helix/arc tessellation: λ/20 along the wire, ≤15° per sample, with a floor."""
    count_len = max(1, int(math.ceil(arc_length / max(wavelength / 20.0, 1e-12))))
    count_ang = 0
    if turns is not None:
        count_ang = int(math.ceil(turns * 360.0 / 15.0))
        floor = max(24, int(math.ceil(turns * 16.0)))
    elif angle_rad is not None:
        count_ang = int(math.ceil(abs(angle_rad) * 180.0 / (15.0 * math.pi)))
        floor = 8
    else:
        floor = 8
    return max(floor, count_len, count_ang)
