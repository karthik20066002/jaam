from __future__ import annotations

import csv
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from .ir import BoxOp, CurveOp, RotPolyOp, SimulationIR, WireOp


class NativeDependencyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    csv_files: tuple[Path, ...]
    minimum_s11_db: tuple[float, ...]


def _native_modules():
    try:
        import numpy as np
        from CSXCAD import ContinuousStructure
        from openEMS import openEMS
    except ImportError as exc:
        raise NativeDependencyError(
            "native CSXCAD/openEMS Python bindings are unavailable; install the "
            "system packages described in docs/native-setup.md"
        ) from exc
    return np, ContinuousStructure, openEMS


def build_native(ir: SimulationIR):
    np, ContinuousStructure, OpenEMS = _native_modules()
    csx = ContinuousStructure()
    properties: dict[str, Any] = {}
    for material in ir.materials:
        if material.kind == "metal":
            properties[material.name] = csx.AddMetal(material.name)
        else:
            properties[material.name] = csx.AddMaterial(
                material.name,
                epsilon=material.epsilon,
                kappa=material.conductivity,
            )

    fdtd = OpenEMS(EndCriteria=1e-5)
    fdtd.SetCSX(csx)
    fdtd.SetGaussExcite(ir.frequency.center_hz, ir.frequency.bandwidth_hz)
    fdtd.SetBoundaryCond([ir.boundary] * 6)
    ports = []
    for op in ir.geometry:
        prop = properties[op.material]
        if isinstance(op, CurveOp):
            prop.AddCurve(points=np.asarray(op.points, dtype=float).T, priority=10)
        elif isinstance(op, WireOp):
            prop.AddWire(points=np.asarray(op.points, dtype=float).T, radius=op.radius_m, priority=10)
        elif isinstance(op, BoxOp):
            prop.AddBox(start=op.start, stop=op.stop, priority=10)
        elif isinstance(op, RotPolyOp):
            norm_dir = {"x": "z", "y": "y", "z": "z"}[op.axis]
            rot_axis = {"x": 0, "y": 0, "z": 1}[op.axis]
            prop.AddRotPoly(
                points=np.asarray(op.points, dtype=float).T,
                norm_dir=norm_dir,
                elevation=op.elevation,
                rot_axis=rot_axis,
                angle=[0.0, 2 * math.pi],
                priority=10,
            )
        if isinstance(op, (CurveOp, WireOp)) and op.feed:
            ports.append(
                fdtd.AddLumpedPort(
                    len(ports) + 1,
                    op.feed.impedance_ohm,
                    op.feed.start,
                    op.feed.stop,
                    op.feed.direction,
                    excite=1 if not ports else 0,
                    priority=20,
                )
            )
    grid = csx.GetGrid()
    grid.SetDeltaUnit(1.0)
    for axis, lines in zip("xyz", (ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z)):
        grid.SetLines(axis, lines)
        grid.SmoothMeshLines(axis, ir.mesh.max_resolution_m, ratio=ir.mesh.grading_ratio)
    return csx, fdtd, ports


def run_simulation(ir: SimulationIR, output_dir: Path) -> RunResult:
    np, _, _ = _native_modules()
    _, fdtd, ports = build_native(ir)
    if not ports:
        raise RuntimeError("S11 requires at least one feed port")
    output_dir.mkdir(parents=True, exist_ok=True)
    fdtd.Run(str(output_dir), cleanup=True)
    if ir.frequency.single_hz:
        frequencies = np.asarray([ir.frequency.single_hz])
    else:
        frequencies = np.linspace(ir.frequency.lower_hz, ir.frequency.upper_hz, 401)
    csv_files: list[Path] = []
    minima: list[float] = []
    for index, port in enumerate(ports, 1):
        port.CalcPort(str(output_dir), frequencies)
        s11 = port.uf_ref / port.uf_inc
        magnitude = np.abs(s11)
        db = 20 * np.log10(np.maximum(magnitude, 1e-300))
        vswr = np.where(magnitude < 1, (1 + magnitude) / (1 - magnitude), np.inf)
        path = output_dir / f"port{index}_s11.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(("frequency_hz", "s11_real", "s11_imag", "s11_db", "vswr"))
            writer.writerows(
                (float(f), float(s.real), float(s.imag), float(level), float(ratio))
                for f, s, level, ratio in zip(frequencies, s11, db, vswr)
            )
        csv_files.append(path)
        minima.append(float(np.min(db)))
    return RunResult(tuple(csv_files), tuple(minima))
