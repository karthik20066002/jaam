from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeAlias

from .diagnostics import Diagnostic
from .ir import BoxOp, CurveOp, MeshSpec, RotPolyOp, SimulationIR, WireOp
from .model import SourceSpan


@dataclass(frozen=True, slots=True)
class PassResult:
    """Result of running a single IR-to-IR pass."""

    ir: SimulationIR
    diagnostics: tuple[Diagnostic, ...] = ()
    warnings: tuple[str, ...] = ()
    statistics: dict[str, int] = field(default_factory=dict)


class Pass(ABC):
    """Base class for explicit IR-to-IR transform or validation passes."""

    name: str

    @abstractmethod
    def run(self, ir: SimulationIR) -> PassResult:
        """Run the pass and return the transformed IR plus any diagnostics."""


PassList: TypeAlias = tuple[Pass, ...]


class ValidateFeedsPass(Pass):
    """Ensure at least one feed port exists after geometry lowering."""

    name = "validate-feeds"

    def run(self, ir: SimulationIR) -> PassResult:
        feeds = sum(
            1
            for op in ir.geometry
            if isinstance(op, (CurveOp, WireOp)) and op.feed is not None
        )
        if feeds == 0:
            diagnostic = Diagnostic(
                "J201",
                "at least one feed port is required for S11 simulation",
                SourceSpan.unknown("<input>"),
            )
            return PassResult(
                ir,
                diagnostics=(diagnostic,),
                statistics={"feeds": 0},
            )
        return PassResult(ir, statistics={"feeds": feeds})


class GradedMeshCoarseningPass(Pass):
    """Coarsen the mesh away from geometry while keeping fine cells near features."""

    name = "graded-mesh-coarsening"

    # Distance from any geometry feature that is considered the near-field and
    # therefore keeps the fine resolution.
    near_fraction: float = 0.05
    # Fine resolution as a fraction of wavelength (matches the current _mesh()).
    fine_fraction: float = 1.0 / 20.0
    # Coarse resolution as a fraction of wavelength in the far-field.
    coarse_fraction: float = 1.0 / 8.0
    # Distance over which the resolution transitions from fine to coarse.
    transition_fraction: float = 0.25

    def run(self, ir: SimulationIR) -> PassResult:
        from dataclasses import replace

        wavelength = 299_792_458.0 / ir.frequency.center_hz
        near_dist = wavelength * self.near_fraction
        fine_res = wavelength * self.fine_fraction
        coarse_res = wavelength * self.coarse_fraction
        transition_dist = wavelength * self.transition_fraction

        feature_coords = self._feature_coordinates(ir.geometry)
        original_cells = (
            (len(ir.mesh.lines_x) - 1)
            * (len(ir.mesh.lines_y) - 1)
            * (len(ir.mesh.lines_z) - 1)
        )

        new_lines: list[tuple[float, ...]] = []
        for axis, lines in enumerate((ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z)):
            coords = feature_coords[axis]
            new_lines.append(
                tuple(self._coarsen_axis(lines, coords, near_dist, fine_res, coarse_res, transition_dist))
            )

        new_mesh = MeshSpec(
            new_lines[0],
            new_lines[1],
            new_lines[2],
            ir.mesh.max_resolution_m,
            ir.mesh.grading_ratio,
        )
        new_ir = replace(ir, mesh=new_mesh)

        new_cells = (
            (len(new_mesh.lines_x) - 1)
            * (len(new_mesh.lines_y) - 1)
            * (len(new_mesh.lines_z) - 1)
        )
        return PassResult(
            new_ir,
            statistics={
                "original_cells": original_cells,
                "new_cells": new_cells,
                "reduction_percent": int(round(100 * (1 - new_cells / original_cells))) if original_cells else 0,
            },
        )

    @staticmethod
    def _feature_coordinates(geometry: tuple[CurveOp | WireOp | BoxOp | RotPolyOp, ...]) -> tuple[set[float], set[float], set[float]]:
        axes: tuple[set[float], set[float], set[float]] = (set(), set(), set())
        for op in geometry:
            if isinstance(op, (CurveOp, WireOp)):
                for point in op.points:
                    for i in range(3):
                        axes[i].add(point[i])
                if op.feed:
                    for point in (op.feed.start, op.feed.stop):
                        for i in range(3):
                            axes[i].add(point[i])
            elif isinstance(op, BoxOp):
                for i in range(3):
                    axes[i].add(op.start[i])
                    axes[i].add(op.stop[i])
            elif isinstance(op, RotPolyOp):
                radial = max(abs(value) for point in op.points for value in point)
                axes[0].add(-radial)
                axes[0].add(radial)
                axes[1].add(-radial)
                axes[1].add(radial)
                axes[2].add(op.elevation)
        return axes

    @staticmethod
    def _coarsen_axis(
        lines: tuple[float, ...],
        feature_coords: set[float],
        near_dist: float,
        fine_res: float,
        coarse_res: float,
        transition_dist: float,
    ) -> list[float]:
        if not lines:
            return []
        sorted_lines = sorted(lines)
        if not feature_coords:
            return sorted_lines

        def target_resolution(line: float) -> float:
            min_dist = min(abs(line - coord) for coord in feature_coords)
            if min_dist <= near_dist:
                return fine_res
            t = min(1.0, (min_dist - near_dist) / transition_dist)
            return fine_res + t * (coarse_res - fine_res)

        kept = [sorted_lines[0]]
        for line in sorted_lines[1:]:
            gap = line - kept[-1]
            if gap >= target_resolution(line):
                kept.append(line)
        return kept


DEFAULT_PASSES: PassList = (ValidateFeedsPass(), GradedMeshCoarseningPass())
