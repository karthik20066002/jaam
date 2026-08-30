"""PyVista scene construction from typed JAAM IR.

PyVista is imported lazily so the compiler remains lightweight without the
optional ``studio`` dependency extra.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .compiler import CompilationResult
from .ir import BoxOp, CurveOp, RotPolyOp, WireOp

if TYPE_CHECKING:
    import pyvista as pv


class StudioDependencyError(RuntimeError):
    pass


def _pyvista():
    try:
        import pyvista as pv
    except ImportError as exc:
        raise StudioDependencyError(
            "PyVista/VTK is unavailable; install JAAM with the 'studio' extra"
        ) from exc
    return pv


def _tag(dataset, name: str, material: str, lowering: str, result: CompilationResult) -> None:
    dataset.field_data["primitive_name"] = [name]
    dataset.field_data["material"] = [material]
    dataset.field_data["lowering_mode"] = [lowering]
    if span := result.source_map.get(name):
        dataset.field_data["source_span"] = [
            f"{span.file}:{span.line}:{span.column}:{span.end_line}:{span.end_column}"
        ]


def build_scene(result: CompilationResult, *, include_mesh: bool = False):
    """Build a named MultiBlock scene directly from a compilation result."""
    pv = _pyvista()
    scene = pv.MultiBlock()
    for op in result.ir.geometry:
        if isinstance(op, CurveOp):
            dataset = pv.lines_from_points(op.points)
            lowering = "thin"
        elif isinstance(op, WireOp):
            centerline = pv.lines_from_points(op.points)
            dataset = centerline.tube(radius=op.radius_m)
            lowering = "thick"
        elif isinstance(op, BoxOp):
            dataset = pv.Box(
                bounds=(op.start[0], op.stop[0], op.start[1], op.stop[1], op.start[2], op.stop[2])
            )
            lowering = "solid"
        else:
            radial = max((sum(value * value for value in point) ** 0.5 for point in op.points), default=0.0)
            dataset = pv.Cylinder(
                center=(0, 0, op.elevation),
                direction={"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[op.axis],
                radius=radial,
                height=max(radial * 2, 1e-12),
            )
            lowering = "revolved"
        _tag(dataset, op.name, op.material, lowering, result)
        scene[op.name] = dataset

        if isinstance(op, (CurveOp, WireOp)) and op.feed:
            feed = pv.Box(
                bounds=(
                    min(op.feed.start[0], op.feed.stop[0]), max(op.feed.start[0], op.feed.stop[0]),
                    min(op.feed.start[1], op.feed.stop[1]), max(op.feed.start[1], op.feed.stop[1]),
                    min(op.feed.start[2], op.feed.stop[2]), max(op.feed.start[2], op.feed.stop[2]),
                )
            )
            feed.field_data["impedance_ohm"] = [op.feed.impedance_ohm]
            scene[f"{op.name}:feed"] = feed

    lo, hi = result.ir.domain_min, result.ir.domain_max
    domain = pv.Box(bounds=(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]))
    domain.field_data["boundary"] = [result.ir.boundary]
    scene["simulation-domain"] = domain

    if include_mesh:
        grid = pv.RectilinearGrid(
            result.ir.mesh.lines_x, result.ir.mesh.lines_y, result.ir.mesh.lines_z
        )
        scene["fdtd-grid"] = grid
    return scene


def save_scene_vtm(result: CompilationResult, path: Path, *, include_mesh: bool = False) -> None:
    """Serialize the typed geometry as a VTK multiblock dataset."""
    build_scene(result, include_mesh=include_mesh).save(path)
