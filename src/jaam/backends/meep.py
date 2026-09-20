"""Meep FDTD backend: PEC cylinders, gap source, DFT impedance, near-to-far."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

from jaam.farfield import write_farfield_vtp, write_nf2ff_csv
from jaam.ir import BoxOp, CurveOp, FeedSpec, Point3, RotPolyOp, SimulationIR, WireOp

from .common import NativeDependencyError, RunResult

_C0 = 299_792_458.0
_ETA0 = 376.730313461


def _require_meep():
    try:
        import meep as mp
    except ImportError as exc:
        raise NativeDependencyError(
            "Meep backend requires the meep Python module (conda-forge meep, or a system package)"
        ) from exc
    return mp


def _feeds(ir: SimulationIR) -> list[tuple[CurveOp | WireOp, FeedSpec]]:
    return [
        (op, op.feed)
        for op in ir.geometry
        if isinstance(op, (CurveOp, WireOp)) and op.feed is not None
    ]


def meep_fcen(ir: SimulationIR) -> float:
    """Meep frequency in units of c / metre."""
    return ir.frequency.center_hz / _C0


def meep_fwidth(ir: SimulationIR) -> float:
    if ir.frequency.single_hz:
        return meep_fcen(ir) / 2.0
    return (ir.frequency.upper_hz - ir.frequency.lower_hz) / _C0


def meep_resolution(ir: SimulationIR) -> float:
    wavelength = _C0 / ir.frequency.center_hz
    radii = [
        op.radius_m
        for op in ir.geometry
        if isinstance(op, (CurveOp, WireOp)) and op.radius_m > 0
    ]
    by_lambda = 20.0 / wavelength
    by_wire = 4.0 / (2.0 * min(radii)) if radii else 0.0
    return max(by_lambda, by_wire)


def meep_cylinders(ir: SimulationIR) -> list[dict[str, Any]]:
    cylinders = []
    for op in ir.geometry:
        if not isinstance(op, (CurveOp, WireOp)):
            continue
        for start, stop in zip(op.points, op.points[1:]):
            axis = (stop[0] - start[0], stop[1] - start[1], stop[2] - start[2])
            height = math.sqrt(sum(v * v for v in axis))
            if height <= 1e-12:
                continue
            center = tuple((start[i] + stop[i]) / 2 for i in range(3))
            unit = tuple(v / height for v in axis)
            cylinders.append(
                {
                    "center": center,
                    "axis": unit,
                    "height": height,
                    "radius": op.radius_m,
                    "material": op.material,
                }
            )
    return cylinders


def meep_source(ir: SimulationIR) -> dict[str, Any]:
    feeds = _feeds(ir)
    if not feeds:
        raise RuntimeError("S11 requires at least one feed port")
    if len(feeds) > 1:
        raise RuntimeError("this runtime currently supports exactly one feed")
    _, feed = feeds[0]
    center = tuple((feed.start[i] + feed.stop[i]) / 2 for i in range(3))
    gap = tuple(feed.stop[i] - feed.start[i] for i in range(3))
    return {
        "center": center,
        "size": gap,
        "component": feed.direction,
        "impedance_ohm": feed.impedance_ohm,
        "gap_m": math.sqrt(sum(v * v for v in gap)),
    }


def _component(mp: Any, direction: str):
    return {"x": mp.Ex, "y": mp.Ey, "z": mp.Ez}[direction]


def ampere_loop(center: Point3, direction: str, radius: float) -> list[tuple[Point3, str]]:
    """Four H samples forming a loop around a feed along `direction`."""
    a = max(2.0 * radius, 1e-4)
    x, y, z = center
    if direction == "x":
        return [
            ((x, y, z - a), "hy"),
            ((x, y + a, z), "hz"),
            ((x, y, z + a), "hy"),
            ((x, y - a, z), "hz"),
        ]
    if direction == "y":
        return [
            ((x, y, z - a), "hx"),
            ((x + a, y, z), "hz"),
            ((x, y, z + a), "hx"),
            ((x - a, y, z), "hz"),
        ]
    return [
        ((x, y - a, z), "hx"),
        ((x + a, y, z), "hy"),
        ((x, y + a, z), "hx"),
        ((x - a, y, z), "hy"),
    ]


def _shift(ir: SimulationIR) -> Point3:
    return tuple((ir.domain_min[i] + ir.domain_max[i]) / 2 for i in range(3))


def _to_cell(point: Point3, origin: Point3) -> Point3:
    return (point[0] - origin[0], point[1] - origin[1], point[2] - origin[2])


def run_meep(ir: SimulationIR, output_dir: Path, *, farfield: bool = True) -> RunResult:
    mp = _require_meep()
    feeds = _feeds(ir)
    if not feeds:
        raise RuntimeError("S11 requires at least one feed port")
    if len(feeds) > 1:
        raise RuntimeError(
            "multiple independently excited ports require separate simulations; "
            "this runtime currently supports exactly one feed"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "solver.log.jsonl"

    def log(event: str, **fields: Any) -> None:
        item = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    fcen = meep_fcen(ir)
    fwidth = max(meep_fwidth(ir), fcen / 4.0)
    resolution = meep_resolution(ir)
    origin = _shift(ir)
    wavelength = _C0 / ir.frequency.center_hz
    dpml = max(wavelength / 2.0, 8.0 / resolution)
    cell = tuple((ir.domain_max[i] - ir.domain_min[i]) + 2.0 * dpml for i in range(3))
    source = meep_source(ir)
    src_center = _to_cell(source["center"], origin)
    src_size = source["size"]
    ecomp = _component(mp, source["component"])

    geometry = []
    for cyl in meep_cylinders(ir):
        geometry.append(
            mp.Cylinder(
                radius=cyl["radius"],
                height=cyl["height"],
                axis=mp.Vector3(*cyl["axis"]),
                center=mp.Vector3(*_to_cell(cyl["center"], origin)),
                material=mp.metal,
            )
        )
    for op in ir.geometry:
        if not isinstance(op, BoxOp):
            continue
        lo = _to_cell(op.start, origin)
        hi = _to_cell(op.stop, origin)
        center = tuple((lo[i] + hi[i]) / 2 for i in range(3))
        size = tuple(abs(hi[i] - lo[i]) for i in range(3))
        material = mp.metal if op.material in {"copper", "gold", "pec"} else mp.Medium(epsilon=4)
        geometry.append(mp.Block(size=mp.Vector3(*size), center=mp.Vector3(*center), material=material))
    if any(isinstance(op, RotPolyOp) for op in ir.geometry):
        raise RuntimeError("Meep backend does not yet mesh revolve solids")

    sources = [
        mp.Source(
            mp.GaussianSource(fcen, fwidth=fwidth),
            component=ecomp,
            center=mp.Vector3(*src_center),
            size=mp.Vector3(*src_size),
        )
    ]
    sim = mp.Simulation(
        cell_size=mp.Vector3(*cell),
        boundary_layers=[mp.PML(dpml)],
        geometry=geometry,
        sources=sources,
        resolution=resolution,
        force_complex_fields=True,
        eps_averaging=False,
    )
    nfreq = 1 if ir.frequency.single_hz else 21
    dft_e = sim.add_dft_fields([ecomp], fcen, fwidth, nfreq, center=mp.Vector3(*src_center), size=mp.Vector3(*src_size))
    fed, feed = feeds[0]
    loop = ampere_loop(src_center, feed.direction, fed.radius_m)
    hmap = {"hx": mp.Hx, "hy": mp.Hy, "hz": mp.Hz}
    dft_h = [
        sim.add_dft_fields([hmap[name]], fcen, fwidth, nfreq, center=mp.Vector3(*point), size=mp.Vector3())
        for point, name in loop
    ]
    loop_side = max(4.0 * fed.radius_m, 2e-4)
    n2f = None
    if farfield:
        box = tuple(c - 2.0 * dpml for c in cell)
        n2f = sim.add_near2far(
            fcen,
            fwidth,
            nfreq,
            mp.Near2FarRegion(center=mp.Vector3(0, 0, 0.5 * box[2]), size=mp.Vector3(box[0], box[1], 0)),
            mp.Near2FarRegion(center=mp.Vector3(0, 0, -0.5 * box[2]), size=mp.Vector3(box[0], box[1], 0), weight=-1),
            mp.Near2FarRegion(center=mp.Vector3(0, 0.5 * box[1], 0), size=mp.Vector3(box[0], 0, box[2])),
            mp.Near2FarRegion(center=mp.Vector3(0, -0.5 * box[1], 0), size=mp.Vector3(box[0], 0, box[2]), weight=-1),
            mp.Near2FarRegion(center=mp.Vector3(0.5 * box[0], 0, 0), size=mp.Vector3(0, box[1], box[2])),
            mp.Near2FarRegion(center=mp.Vector3(-0.5 * box[0], 0, 0), size=mp.Vector3(0, box[1], box[2]), weight=-1),
        )

    log(
        "solver-start",
        backend="meep",
        resolution=resolution,
        fcen=fcen,
        cell=cell,
    )
    started = perf_counter()
    sim.run(until_after_sources=mp.stop_when_fields_decayed(50, ecomp, mp.Vector3(*src_center), 1e-6))
    duration = perf_counter() - started

    e_array = sim.get_dft_array(dft_e, ecomp, 0)
    voltage = complex(-source["gap_m"] * complex(e_array.mean()))
    # ∮ H·dl on a square of side loop_side around the feed axis.
    h_samples = []
    for dft, (_, name) in zip(dft_h, loop):
        h_samples.append(complex(sim.get_dft_array(dft, hmap[name], 0).mean()))
    current = loop_side * (h_samples[0] + h_samples[1] - h_samples[2] - h_samples[3])
    if abs(current) < 1e-30:
        raise RuntimeError("Meep feed current DFT is zero; check the gap source and mesh")
    z_in = voltage / current
    gamma = (z_in - source["impedance_ohm"]) / (z_in + source["impedance_ohm"])
    s11_db = 20.0 * math.log10(max(abs(gamma), 1e-300))
    magnitude = abs(gamma)
    vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else float("inf")
    freq_hz = ir.frequency.center_hz
    s11_path = output_dir / "port1_s11.csv"
    with s11_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ("frequency_hz", "s11_real", "s11_imag", "s11_db", "vswr", "resistance_ohm", "reactance_ohm")
        )
        writer.writerow((freq_hz, gamma.real, gamma.imag, s11_db, vswr, z_in.real, z_in.imag))

    native_cells = tuple(max(1, int(round(cell[i] * resolution))) for i in range(3))
    if not farfield or n2f is None:
        log("solver-complete", durationSeconds=duration, bestFrequencyHz=freq_hz, farfield=False)
        return RunResult((s11_path,), (s11_db,), (freq_hz,), duration, native_mesh_cells=native_cells)

    theta_deg = tuple(float(t) for t in range(0, 181, 5))
    phi_deg = tuple(float(p) for p in range(0, 361, 5))
    radius = 100.0 * wavelength
    intensity = []
    for theta in theta_deg:
        row = []
        polar = math.radians(theta)
        for phi in phi_deg:
            azimuth = math.radians(phi)
            point = mp.Vector3(
                radius * math.sin(polar) * math.cos(azimuth),
                radius * math.sin(polar) * math.sin(azimuth),
                radius * math.cos(polar),
            )
            far = sim.get_farfield(n2f, point)
            ex, ey, ez = complex(far[0], far[1]), complex(far[2], far[3]), complex(far[4], far[5])
            mag2 = abs(ex) ** 2 + abs(ey) ** 2 + abs(ez) ** 2
            row.append(radius * radius * mag2 / (2.0 * _ETA0))
        intensity.append(row)
    radiated = 0.0
    peak = 0.0
    dtheta = math.radians(5.0)
    dphi = math.radians(5.0)
    for i, theta in enumerate(theta_deg):
        weight = math.sin(math.radians(theta)) * dtheta * dphi
        for value in intensity[i]:
            radiated += value * weight
            peak = max(peak, value)
    if radiated <= 0:
        raise RuntimeError("Meep far-field radiated power is zero")
    gain_rows = []
    peak_db = 10.0 * math.log10(max(4.0 * math.pi * peak / radiated, 1e-300))
    for row in intensity:
        gain_rows.append(
            tuple(10.0 * math.log10(max(4.0 * math.pi * value / radiated, 1e-300)) for value in row)
        )
    nf2ff_csv = output_dir / "nf2ff.csv"
    farfield_vtp = output_dir / "farfield.vtp"
    write_nf2ff_csv(nf2ff_csv, freq_hz, theta_deg, phi_deg, gain_rows)
    write_farfield_vtp(farfield_vtp, theta_deg, phi_deg, gain_rows)
    log("solver-complete", durationSeconds=duration, bestFrequencyHz=freq_hz, peakGainDb=peak_db)
    return RunResult(
        (s11_path,),
        (s11_db,),
        (freq_hz,),
        duration,
        nf2ff_csv,
        farfield_vtp,
        peak_db,
        native_cells,
    )
