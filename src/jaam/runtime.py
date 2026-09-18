from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

from .farfield import write_farfield_vtp, write_nf2ff_csv
from .ir import BoxOp, CurveOp, RotPolyOp, SimulationIR, WireOp


class NativeDependencyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    csv_files: tuple[Path, ...]
    minimum_s11_db: tuple[float, ...]
    best_frequency_hz: tuple[float, ...] = ()
    solver_duration_s: float = 0.0
    nf2ff_csv: Path | None = None
    farfield_vtp: Path | None = None
    peak_gain_db: float | None = None
    native_mesh_cells: tuple[int, int, int] = ()


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


def run_simulation(ir: SimulationIR, output_dir: Path, *, farfield: bool = True) -> RunResult:
    np, _, _ = _native_modules()
    csx, fdtd, ports = build_native(ir)
    grid = csx.GetGrid()
    # openEMS reports the line counts as its FDTD simulation dimensions.
    native_mesh_cells = tuple(len(grid.GetLines(axis)) for axis in "xyz")
    if not ports:
        raise RuntimeError("S11 requires at least one feed port")
    if len(ports) > 1:
        raise RuntimeError(
            "multiple independently excited ports require separate simulations; "
            "this runtime currently supports exactly one feed"
        )
    nf2ff = fdtd.CreateNF2FFBox() if farfield else None
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "solver.log.jsonl"

    def log(event: str, **fields) -> None:
        item = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    log("solver-start")
    started = perf_counter()
    try:
        fdtd.Run(str(output_dir), cleanup=True)
    except Exception as exc:
        log("solver-failed", error=str(exc))
        raise
    solver_duration = perf_counter() - started
    if ir.frequency.single_hz:
        frequencies = np.asarray([ir.frequency.single_hz])
    else:
        frequencies = np.linspace(ir.frequency.lower_hz, ir.frequency.upper_hz, 401)
    csv_files: list[Path] = []
    minima: list[float] = []
    best_frequencies: list[float] = []
    feed = next(
        op.feed
        for op in ir.geometry
        if isinstance(op, (CurveOp, WireOp)) and op.feed is not None
    )
    for index, port in enumerate(ports, 1):
        port.CalcPort(str(output_dir), frequencies)
        s11 = port.uf_ref / port.uf_inc
        magnitude = np.abs(s11)
        db = 20 * np.log10(np.maximum(magnitude, 1e-300))
        vswr = np.where(magnitude < 1, (1 + magnitude) / (1 - magnitude), np.inf)
        impedance = feed.impedance_ohm * (1 + s11) / (1 - s11)
        path = output_dir / f"port{index}_s11.csv"
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ("frequency_hz", "s11_real", "s11_imag", "s11_db", "vswr", "resistance_ohm", "reactance_ohm")
            )
            writer.writerows(
                (float(f), float(s.real), float(s.imag), float(level), float(ratio), float(z.real), float(z.imag))
                for f, s, level, ratio, z in zip(frequencies, s11, db, vswr, impedance)
            )
        csv_files.append(path)
        minima.append(float(np.min(db)))
        best_frequencies.append(float(frequencies[int(np.argmin(db))]))
    if not farfield:
        log("solver-complete", durationSeconds=solver_duration, bestFrequencyHz=best_frequencies[0], farfield=False)
        return RunResult(
            tuple(csv_files), tuple(minima), tuple(best_frequencies), solver_duration,
            native_mesh_cells=native_mesh_cells,
        )
    theta_deg = np.linspace(0.0, 180.0, 181)
    phi_deg = np.linspace(0.0, 360.0, 361)
    best_frequency = best_frequencies[0]
    farfield = nf2ff.CalcNF2FF(
        str(output_dir),
        best_frequency,
        theta_deg,
        phi_deg,
        read_cached=False,
    )
    magnitude = np.squeeze(np.asarray(farfield.E_norm, dtype=float))
    expected = (len(theta_deg), len(phi_deg))
    if magnitude.shape == expected[::-1]:
        magnitude = magnitude.T
    if magnitude.shape != expected:
        raise RuntimeError(f"unexpected NF2FF matrix shape {magnitude.shape}; expected {expected}")
    normalized_db = 20 * np.log10(np.maximum(magnitude / np.max(magnitude), 1e-300))
    directivity = float(np.ravel(np.asarray(farfield.Dmax))[0])
    peak_gain_db = 10 * math.log10(max(directivity, 1e-300))
    gain_db = normalized_db + peak_gain_db
    nf2ff_csv = output_dir / "nf2ff.csv"
    farfield_vtp = output_dir / "farfield.vtp"
    gain_rows = tuple(tuple(float(value) for value in row) for row in gain_db)
    write_nf2ff_csv(nf2ff_csv, best_frequency, theta_deg, phi_deg, gain_rows)
    write_farfield_vtp(farfield_vtp, theta_deg, phi_deg, gain_rows)
    log(
        "solver-complete",
        durationSeconds=solver_duration,
        bestFrequencyHz=best_frequency,
        peakGainDb=peak_gain_db,
    )
    return RunResult(
        tuple(csv_files),
        tuple(minima),
        tuple(best_frequencies),
        solver_duration,
        nf2ff_csv,
        farfield_vtp,
        peak_gain_db,
        native_mesh_cells,
    )
