from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .compiler import CompilationResult
from .ir import BoxOp, CurveOp, RotPolyOp, SimulationIR, WireOp

SCHEMA_VERSION = 1


def ir_to_dict(ir: SimulationIR) -> dict[str, Any]:
    geometry: list[dict[str, Any]] = []
    for op in ir.geometry:
        item = asdict(op)
        item["kind"] = {
            CurveOp: "curve",
            WireOp: "wire",
            BoxOp: "box",
            RotPolyOp: "rotpoly",
        }[type(op)]
        geometry.append(item)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "frequency": asdict(ir.frequency),
        "boundary": ir.boundary,
        "materials": [asdict(item) for item in ir.materials],
        "geometry": geometry,
        "mesh": asdict(ir.mesh),
        "domainMin": ir.domain_min,
        "domainMax": ir.domain_max,
        "warnings": ir.warnings,
    }


def compilation_to_dict(result: CompilationResult) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": str(result.ast.source or "<input>"),
        "diagnostics": [item.as_dict() for item in result.diagnostics],
        "sourceMap": {name: asdict(span) for name, span in result.source_map.items()},
        "passes": [
            {
                "name": item.name,
                "durationNs": item.duration_ns,
                "statistics": item.statistics,
            }
            for item in result.passes
        ],
        "ir": ir_to_dict(result.ir),
    }
