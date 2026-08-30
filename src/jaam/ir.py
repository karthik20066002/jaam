from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

Point3: TypeAlias = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class FrequencySpec:
    lower_hz: float
    upper_hz: float
    single_hz: float | None = None

    @property
    def center_hz(self) -> float:
        return self.single_hz or (self.lower_hz + self.upper_hz) / 2

    @property
    def bandwidth_hz(self) -> float:
        return self.center_hz / 2 if self.single_hz else (self.upper_hz - self.lower_hz) / 2


@dataclass(frozen=True, slots=True)
class MaterialSpec:
    name: str
    kind: str
    epsilon: float | None = None
    conductivity: float | None = None


@dataclass(frozen=True, slots=True)
class FeedSpec:
    impedance_ohm: float
    start: Point3
    stop: Point3
    direction: str


@dataclass(frozen=True, slots=True)
class CurveOp:
    name: str
    points: tuple[Point3, ...]
    material: str
    radius_m: float
    feed: FeedSpec | None = None


@dataclass(frozen=True, slots=True)
class WireOp:
    name: str
    points: tuple[Point3, ...]
    material: str
    radius_m: float
    feed: FeedSpec | None = None


@dataclass(frozen=True, slots=True)
class BoxOp:
    name: str
    start: Point3
    stop: Point3
    material: str


@dataclass(frozen=True, slots=True)
class RotPolyOp:
    name: str
    points: tuple[tuple[float, float], ...]
    axis: str
    elevation: float
    material: str


GeometryOp: TypeAlias = CurveOp | WireOp | BoxOp | RotPolyOp


@dataclass(frozen=True, slots=True)
class MeshSpec:
    lines_x: tuple[float, ...]
    lines_y: tuple[float, ...]
    lines_z: tuple[float, ...]
    max_resolution_m: float
    grading_ratio: float = 1.5


@dataclass(frozen=True, slots=True)
class SimulationIR:
    frequency: FrequencySpec
    boundary: str
    materials: tuple[MaterialSpec, ...]
    geometry: tuple[GeometryOp, ...]
    mesh: MeshSpec
    domain_min: Point3
    domain_max: Point3
    warnings: tuple[str, ...] = field(default_factory=tuple)

