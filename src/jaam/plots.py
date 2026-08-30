"""Backend-independent geometry and RF calculations shared by JAAM Studio views."""
from __future__ import annotations

import math
from typing import Iterable, Literal, Sequence

from .ir import BoxOp, CurveOp, GeometryOp, Point3, RotPolyOp, WireOp

Plane = Literal["xy", "xz", "yz"]
_PLANE_AXES = {"xy": (0, 1, 2), "xz": (0, 2, 1), "yz": (1, 2, 0)}


def project_point(point: Point3, plane: Plane) -> tuple[float, float]:
    horizontal, vertical, _ = _PLANE_AXES[plane]
    return point[horizontal], point[vertical]


def project_geometry(op: GeometryOp, plane: Plane) -> tuple[tuple[float, float], ...]:
    if isinstance(op, (CurveOp, WireOp)):
        return tuple(project_point(point, plane) for point in op.points)
    if isinstance(op, BoxOp):
        horizontal, vertical, _ = _PLANE_AXES[plane]
        a, b = op.start, op.stop
        return (
            (a[horizontal], a[vertical]),
            (b[horizontal], a[vertical]),
            (b[horizontal], b[vertical]),
            (a[horizontal], b[vertical]),
            (a[horizontal], a[vertical]),
        )
    radius = max((math.hypot(*point) for point in op.points), default=0.0)
    return ((-radius, op.elevation), (radius, op.elevation))


def intersects_slice(op: GeometryOp, plane: Plane, coordinate: float, tolerance: float = 1e-9) -> bool:
    """Return whether an actor intersects the plane's hidden-axis slice."""
    _, _, hidden = _PLANE_AXES[plane]
    if isinstance(op, (CurveOp, WireOp)):
        values = [point[hidden] for point in op.points]
    elif isinstance(op, BoxOp):
        values = [op.start[hidden], op.stop[hidden]]
    else:
        # Revolved solids conservatively occupy their radial envelope.
        radius = max((math.hypot(*point) for point in op.points), default=0.0)
        values = [op.elevation - radius, op.elevation + radius]
    return min(values) - tolerance <= coordinate <= max(values) + tolerance


def distance(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError("measurement points must have the same dimension")
    return math.dist(a, b)


def mesh_cell_size(lines: Sequence[float], coordinate: float) -> float | None:
    for start, stop in zip(lines, lines[1:]):
        if start <= coordinate <= stop:
            return stop - start
    return None


def reflection_from_impedance(
    resistance: float, reactance: float, reference: float = 50.0
) -> complex:
    if reference <= 0:
        raise ValueError("reference impedance must be positive")
    impedance = complex(resistance, reactance)
    if math.isinf(abs(impedance)):
        return 1 + 0j
    return (impedance - reference) / (impedance + reference)


def impedance_from_reflection(gamma: complex, reference: float = 50.0) -> complex:
    if reference <= 0:
        raise ValueError("reference impedance must be positive")
    if abs(1 - gamma) < 1e-15:
        return complex(math.inf, 0.0)
    return reference * (1 + gamma) / (1 - gamma)


def normalize_gain(values_db: Iterable[float]) -> tuple[float, ...]:
    values = tuple(values_db)
    if not values:
        return ()
    peak = max(values)
    return tuple(value - peak for value in values)


def _crossing(x1: float, y1: float, x2: float, y2: float, level: float) -> float:
    return x1 + (level - y1) * (x2 - x1) / (y2 - y1)


def half_power_beamwidth(angles_deg: Sequence[float], gain_db: Sequence[float]) -> float | None:
    if len(angles_deg) != len(gain_db) or len(gain_db) < 3:
        return None
    peak = max(range(len(gain_db)), key=gain_db.__getitem__)
    level = gain_db[peak] - 3.0
    left = next((i for i in range(peak, 0, -1) if gain_db[i - 1] < level <= gain_db[i]), None)
    right = next((i for i in range(peak, len(gain_db) - 1) if gain_db[i] >= level > gain_db[i + 1]), None)
    if left is None or right is None:
        return None
    left_angle = _crossing(angles_deg[left - 1], gain_db[left - 1], angles_deg[left], gain_db[left], level)
    right_angle = _crossing(angles_deg[right], gain_db[right], angles_deg[right + 1], gain_db[right + 1], level)
    return right_angle - left_angle


def front_to_back_ratio(angles_deg: Sequence[float], gain_db: Sequence[float]) -> float | None:
    if len(angles_deg) != len(gain_db) or not gain_db:
        return None
    front = max(range(len(gain_db)), key=gain_db.__getitem__)
    target = (angles_deg[front] + 180.0) % 360.0
    back = min(range(len(angles_deg)), key=lambda i: abs(((angles_deg[i] - target + 180) % 360) - 180))
    return gain_db[front] - gain_db[back]
