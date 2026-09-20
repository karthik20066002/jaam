"""Palace FEM backend: Gmsh cylinders + lumped-port face + driven solve."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
from time import perf_counter
from typing import Any

from jaam.farfield import write_farfield_vtp, write_nf2ff_csv
from jaam.ir import BoxOp, CurveOp, FeedSpec, Point3, RotPolyOp, SimulationIR, WireOp

from .common import NativeDependencyError, RunResult

ATTR_PEC = 1
ATTR_PORT = 2
ATTR_ABSORB = 3
ATTR_AIR = 4

_ETA0 = 376.730313461
_C0 = 299_792_458.0


def _require_gmsh():
    try:
        import gmsh
    except ImportError as exc:
        raise NativeDependencyError(
            "Palace backend requires the gmsh Python package to build the FEM mesh"
        ) from exc
    return gmsh


def _palace_command(output_dir: Path) -> list[str]:
    executable = shutil.which("palace")
    if executable is not None:
        return [executable, "palace.json"]
    from jaam.container import PALACE_IMAGE, ContainerEngine, ContainerUnavailableError

    try:
        engine = ContainerEngine.discover()
    except ContainerUnavailableError as exc:
        raise NativeDependencyError(
            "Palace backend needs the palace executable on PATH, or a container image "
            f"tagged {PALACE_IMAGE}"
        ) from exc
    if not engine.image_exists(PALACE_IMAGE):
        raise NativeDependencyError(
            f"Palace backend needs the palace executable on PATH, or image {PALACE_IMAGE}"
        )
    return engine.palace_command(output_dir)


def _wavelength(ir: SimulationIR) -> float:
    return _C0 / ir.frequency.center_hz


def _feeds(ir: SimulationIR) -> list[tuple[CurveOp | WireOp, FeedSpec]]:
    found = []
    for op in ir.geometry:
        if isinstance(op, (CurveOp, WireOp)) and op.feed is not None:
            found.append((op, op.feed))
    return found


def _vec_sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a: Point3, b: Point3) -> Point3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(a: Point3, s: float) -> Point3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec_len(a: Point3) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _vec_norm(a: Point3) -> Point3:
    length = _vec_len(a)
    if length <= 0.0:
        raise ValueError("zero-length vector")
    return _vec_scale(a, 1.0 / length)


def _vec_cross(a: Point3, b: Point3) -> Point3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _domain_sphere(ir: SimulationIR) -> tuple[Point3, float]:
    points: list[Point3] = []
    for op in ir.geometry:
        if isinstance(op, (CurveOp, WireOp)):
            points.extend(op.points)
        elif isinstance(op, BoxOp):
            points.extend((op.start, op.stop))
        elif isinstance(op, RotPolyOp):
            radial = max(math.hypot(p[0], p[1]) for p in op.points) if op.points else 0.0
            points.append((radial, radial, op.elevation))
            points.append((-radial, -radial, op.elevation))
    if not points:
        raise RuntimeError("Palace mesh requires geometry")
    center = tuple(sum(p[i] for p in points) / len(points) for i in range(3))
    extent = max(_vec_len(_vec_sub(p, center)) for p in points)
    radius = extent + 0.75 * _wavelength(ir)
    return center, radius


def _port_frame(feed: FeedSpec, radius: float) -> tuple[Point3, Point3, Point3, float]:
    axis = _vec_sub(feed.stop, feed.start)
    gap = _vec_len(axis)
    if gap <= 0:
        raise RuntimeError("feed gap has zero length")
    tangent = _vec_norm(axis)
    helper = (1.0, 0.0, 0.0) if abs(tangent[0]) < 0.9 else (0.0, 1.0, 0.0)
    width = _vec_norm(_vec_cross(tangent, helper))
    mid = _vec_scale(_vec_add(feed.start, feed.stop), 0.5)
    return mid, tangent, width, gap


def palace_direction(feed: FeedSpec) -> str:
    axis = {"x": 0, "y": 1, "z": 2}[feed.direction]
    sign = "+" if feed.stop[axis] >= feed.start[axis] else "-"
    return f"{sign}{feed.direction.upper()}"


def farfield_samples(*, step_deg: int = 5) -> list[list[float]]:
    return [[float(theta), float(phi)] for theta in range(0, 181, step_deg) for phi in range(0, 361, step_deg)]


def build_palace_config(ir: SimulationIR, *, mesh_name: str = "mesh.msh", farfield: bool = True) -> dict[str, Any]:
    feeds = _feeds(ir)
    if not feeds:
        raise RuntimeError("S11 requires at least one feed port")
    if len(feeds) > 1:
        raise RuntimeError("this runtime currently supports exactly one feed")
    _, feed = feeds[0]
    freq_ghz = [ir.frequency.center_hz / 1e9] if ir.frequency.single_hz else [
        ir.frequency.lower_hz / 1e9,
        ir.frequency.upper_hz / 1e9,
    ]
    if ir.frequency.single_hz:
        samples: dict[str, Any] = {"Type": "Point", "Freq": freq_ghz, "SaveStep": 1}
    else:
        lo = ir.frequency.lower_hz / 1e9
        hi = ir.frequency.upper_hz / 1e9
        samples = {
            "Type": "Linear",
            "MinFreq": lo,
            "MaxFreq": hi,
            "FreqStep": max((hi - lo) / 4.0, 1e-6),
            "SaveStep": 1,
        }
    boundaries: dict[str, Any] = {
        "Absorbing": {"Attributes": [ATTR_ABSORB]},
        "PEC": {"Attributes": [ATTR_PEC]},
        "LumpedPort": [
            {
                "Index": 1,
                "R": feed.impedance_ohm,
                "Excitation": True,
                "Attributes": [ATTR_PORT],
                "Direction": palace_direction(feed),
            }
        ],
    }
    if farfield:
        boundaries["Postprocessing"] = {
            "FarField": {"Attributes": [ATTR_ABSORB], "ThetaPhis": farfield_samples()}
        }
    return {
        "Problem": {"Type": "Driven", "Verbose": 2, "Output": "postpro"},
        "Model": {"Mesh": mesh_name, "L0": 1.0},
        "Domains": {"Materials": [{"Attributes": [ATTR_AIR], "Permittivity": 1.0, "Permeability": 1.0}]},
        "Boundaries": boundaries,
        "Solver": {
            "Order": 2,
            "Device": "CPU",
            "Driven": {"Samples": [samples]},
            "Linear": {"Type": "Default", "KSPType": "GMRES", "Tol": 1.0e-8, "MaxIts": 200},
        },
    }


def write_palace_config(ir: SimulationIR, path: Path, *, farfield: bool = True) -> dict[str, Any]:
    config = build_palace_config(ir, farfield=farfield)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return config


def write_palace_mesh(ir: SimulationIR, path: Path) -> tuple[int, int]:
    gmsh = _require_gmsh()
    feeds = _feeds(ir)
    if len(feeds) != 1:
        raise RuntimeError("Palace mesh currently supports exactly one feed")
    fed, feed = feeds[0]
    center, sphere_radius = _domain_sphere(ir)
    mid, tangent, width, gap = _port_frame(feed, fed.radius_m)
    wavelength = _wavelength(ir)

    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Verbosity", 2)
        gmsh.model.add("jaam")
        occ = gmsh.model.occ
        sphere = occ.addSphere(center[0], center[1], center[2], sphere_radius)
        cylinders = []
        for op in ir.geometry:
            if not isinstance(op, (CurveOp, WireOp)):
                continue
            for start, stop in zip(op.points, op.points[1:]):
                delta = _vec_sub(stop, start)
                if _vec_len(delta) <= 1e-12:
                    continue
                cylinders.append(
                    (3, occ.addCylinder(start[0], start[1], start[2], delta[0], delta[1], delta[2], op.radius_m))
                )
        half_t = _vec_scale(tangent, gap / 2.0)
        half_w = _vec_scale(width, fed.radius_m)
        corners = (
            _vec_add(_vec_add(mid, _vec_scale(half_t, -1.0)), _vec_scale(half_w, -1.0)),
            _vec_add(_vec_add(mid, half_t), _vec_scale(half_w, -1.0)),
            _vec_add(_vec_add(mid, half_t), half_w),
            _vec_add(_vec_add(mid, _vec_scale(half_t, -1.0)), half_w),
        )
        point_tags = [occ.addPoint(*corner, 0) for corner in corners]
        line_tags = [
            occ.addLine(point_tags[i], point_tags[(i + 1) % 4]) for i in range(4)
        ]
        loop = occ.addCurveLoop(line_tags)
        port = occ.addPlaneSurface([loop])
        if cylinders:
            occ.cut([(3, sphere)], cylinders, removeObject=True, removeTool=True)
        volumes = occ.getEntities(3)
        _out, mapping = occ.fragment(volumes, [(2, port)], removeObject=True, removeTool=True)
        occ.synchronize()
        port_tags = [tag for dim, tag in mapping[len(volumes)] if dim == 2]
        if not port_tags:
            raise RuntimeError("Palace mesh lost the lumped-port face during boolean fragment")

        def bbox(dim: int, tag: int) -> tuple[float, ...]:
            return occ.getBoundingBox(dim, tag)

        def spans_sphere(box: tuple[float, ...]) -> bool:
            return all(abs(box[i] - (center[i] - sphere_radius)) < 0.05 * sphere_radius for i in range(3)) and all(
                abs(box[i + 3] - (center[i] + sphere_radius)) < 0.05 * sphere_radius for i in range(3)
            )

        volumes = occ.getEntities(3)
        surfaces = occ.getEntities(2)
        air = [tag for dim, tag in volumes if spans_sphere(bbox(dim, tag))]
        if not air:
            air = [tag for _, tag in volumes]
        outer = [tag for dim, tag in surfaces if spans_sphere(bbox(dim, tag))]
        pec = [tag for _, tag in surfaces if tag not in set(outer) | set(port_tags)]
        if not air or not outer or not pec:
            raise RuntimeError(
                f"Palace mesh tagging failed (air={air}, outer={outer}, port={port_tags}, pec={len(pec)})"
            )
        gmsh.model.addPhysicalGroup(3, air, ATTR_AIR)
        gmsh.model.addPhysicalGroup(2, pec, ATTR_PEC)
        gmsh.model.addPhysicalGroup(2, port_tags, ATTR_PORT)
        gmsh.model.addPhysicalGroup(2, outer, ATTR_ABSORB)

        n_circle = 8
        gmsh.option.setNumber("Mesh.MeshSizeMin", 2.0 * math.pi * max(fed.radius_m, 1e-6) / n_circle / 2.0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", wavelength / 3.0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", n_circle)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.model.mesh.field.add("Extend", 1)
        gmsh.model.mesh.field.setNumbers(1, "SurfacesList", pec + port_tags)
        gmsh.model.mesh.field.setNumber(1, "DistMax", sphere_radius)
        gmsh.model.mesh.field.setNumber(1, "SizeMax", wavelength / 3.0)
        gmsh.model.mesh.field.setAsBackgroundMesh(1)
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)
        gmsh.model.mesh.generate(3)
        gmsh.model.mesh.setOrder(1)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.write(str(path))
        _, tet_tags, _ = gmsh.model.mesh.getElements(3)
        n_tets = sum(len(tags) for tags in tet_tags)
        _, face_tags, _ = gmsh.model.mesh.getElements(2)
        n_faces = sum(len(tags) for tags in face_tags)
        return n_tets, n_faces
    finally:
        gmsh.finalize()


def _column(row: dict[str, str], *needles: str) -> str | None:
    for key, value in row.items():
        lowered = key.strip().lower()
        if all(needle.lower() in lowered for needle in needles):
            return value
    return None


def parse_port_s(path: Path) -> list[dict[str, float]]:
    rows = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            freq = _column(row, "f (ghz)") or _column(row, "ghz")
            db = _column(row, "|s", "db") or _column(row, "s[1][1]| (db)")
            real = _column(row, "re{s") or _column(row, "re{s[1][1]}")
            imag = _column(row, "im{s") or _column(row, "im{s[1][1]}")
            if freq is None or db is None:
                continue
            item = {
                "frequency_hz": float(freq) * 1e9,
                "s11_db": float(db),
            }
            if real is not None and imag is not None:
                item["s11_real"] = float(real)
                item["s11_imag"] = float(imag)
            rows.append(item)
    if not rows:
        raise RuntimeError(f"no S-parameter samples in {path}")
    return rows


def parse_port_impedance(voltage_path: Path, current_path: Path, z0: float) -> dict[float, complex]:
    def samples(path: Path, kind: str) -> dict[float, complex]:
        values = {}
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                freq = _column(row, "f (ghz)") or _column(row, "ghz")
                real = _column(row, f"re{{{kind}") or _column(row, "re{")
                imag = _column(row, f"im{{{kind}") or _column(row, "im{")
                if freq is None or real is None or imag is None:
                    continue
                values[round(float(freq) * 1e9, 3)] = complex(float(real), float(imag))
        return values

    if not voltage_path.is_file() or not current_path.is_file():
        return {}
    voltages = samples(voltage_path, "v")
    currents = samples(current_path, "i")
    impedances = {}
    for freq, voltage in voltages.items():
        current = currents.get(freq)
        if current is None or abs(current) < 1e-30:
            continue
        impedances[freq] = voltage / current
    return impedances or {}


def parse_farfield_re(path: Path) -> tuple[float, tuple[float, ...], tuple[float, ...], tuple[tuple[float, ...], ...], float]:
    samples: dict[tuple[float, float], float] = {}
    frequencies: set[float] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            freq = _column(row, "f (ghz)") or _column(row, "ghz")
            theta = _column(row, "theta")
            phi = _column(row, "phi")
            parts = []
            for component in ("e_x", "e_y", "e_z"):
                real = _column(row, "re", component) or _column(row, f"r*re{{{component}")
                imag = _column(row, "im", component) or _column(row, f"r*im{{{component}")
                if real is None or imag is None:
                    continue
                parts.append(float(real) ** 2 + float(imag) ** 2)
            if freq is None or theta is None or phi is None or len(parts) != 3:
                continue
            frequencies.add(float(freq) * 1e9)
            samples[(float(theta), float(phi))] = math.sqrt(sum(parts))
    if len(frequencies) != 1 or not samples:
        raise RuntimeError(f"far-field CSV must contain one populated frequency: {path}")
    theta = tuple(sorted({key[0] for key in samples}))
    phi = tuple(sorted({key[1] for key in samples}))
    intensity = []
    for t in theta:
        row = []
        for p in phi:
            mag = samples.get((t, p))
            if mag is None:
                raise RuntimeError("far-field CSV is not a complete theta/phi grid")
            row.append(mag * mag / (2.0 * _ETA0))
        intensity.append(row)
    peak = 0.0
    radiated = 0.0
    dtheta = math.radians(theta[1] - theta[0]) if len(theta) > 1 else math.radians(5.0)
    dphi = math.radians(phi[1] - phi[0]) if len(phi) > 1 else math.radians(5.0)
    for i, t in enumerate(theta):
        weight = math.sin(math.radians(t)) * dtheta * dphi
        for value in intensity[i]:
            radiated += value * weight
            peak = max(peak, value)
    if radiated <= 0:
        raise RuntimeError("far-field radiated power is zero")
    gain_rows = []
    peak_directivity = 4.0 * math.pi * peak / radiated
    peak_db = 10.0 * math.log10(max(peak_directivity, 1e-300))
    for i, _ in enumerate(theta):
        gain_rows.append(
            tuple(10.0 * math.log10(max(4.0 * math.pi * value / radiated, 1e-300)) for value in intensity[i])
        )
    return frequencies.pop(), theta, phi, tuple(gain_rows), peak_db


def _write_s11_csv(
    path: Path, rows: list[dict[str, float]], impedances: dict[float, complex], z0: float
) -> tuple[float, float]:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ("frequency_hz", "s11_real", "s11_imag", "s11_db", "vswr", "resistance_ohm", "reactance_ohm")
        )
        written = []
        for row in rows:
            freq = row["frequency_hz"]
            db = row["s11_db"]
            real = row.get("s11_real")
            imag = row.get("s11_imag")
            if real is None or imag is None:
                mag = 10 ** (db / 20.0)
                gamma = complex(mag, 0.0)
            else:
                gamma = complex(real, imag)
            magnitude = abs(gamma)
            vswr = (1 + magnitude) / (1 - magnitude) if magnitude < 1 else float("inf")
            z = impedances.get(round(freq, 3))
            if z is None and magnitude < 1:
                z = z0 * (1 + gamma) / (1 - gamma)
            elif z is None:
                z = complex(float("nan"), float("nan"))
            writer.writerow((freq, gamma.real, gamma.imag, db, vswr, z.real, z.imag))
            written.append((db, freq))
    best_db, best_freq = min(written)
    return best_db, best_freq


def run_palace(ir: SimulationIR, output_dir: Path, *, farfield: bool = True) -> RunResult:
    feeds = _feeds(ir)
    if not feeds:
        raise RuntimeError("S11 requires at least one feed port")
    if len(feeds) > 1:
        raise RuntimeError(
            "multiple independently excited ports require separate simulations; "
            "this runtime currently supports exactly one feed"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    mesh_path = output_dir / "mesh.msh"
    config_path = output_dir / "palace.json"
    log_path = output_dir / "solver.log.jsonl"

    def log(event: str, **fields: Any) -> None:
        item = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    n_tets, n_faces = write_palace_mesh(ir, mesh_path)
    write_palace_config(ir, config_path, farfield=farfield)
    command = _palace_command(output_dir)
    log("solver-start", backend="palace", tets=n_tets, faces=n_faces, command=command)
    started = perf_counter()
    completed = subprocess.run(
        command,
        cwd=output_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = perf_counter() - started
    (output_dir / "palace.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "palace.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        log("solver-failed", error=completed.stderr[-2000:] or completed.stdout[-2000:])
        raise RuntimeError(f"palace exited {completed.returncode}")
    postpro = output_dir / "postpro"
    port_s = next(postpro.rglob("port-S.csv"), None) if postpro.is_dir() else None
    if port_s is None:
        raise RuntimeError("palace did not write port-S.csv")
    s_rows = parse_port_s(port_s)
    z0 = feeds[0][1].impedance_ohm
    voltage = next(postpro.rglob("port-V.csv"), Path())
    current = next(postpro.rglob("port-I.csv"), Path())
    impedances = parse_port_impedance(voltage, current, z0)
    s11_path = output_dir / "port1_s11.csv"
    best_db, best_freq = _write_s11_csv(s11_path, s_rows, impedances, z0)
    if not farfield:
        log("solver-complete", durationSeconds=duration, bestFrequencyHz=best_freq, farfield=False)
        return RunResult((s11_path,), (best_db,), (best_freq,), duration, native_mesh_cells=(n_tets, n_faces, 0))
    far_path = next(postpro.rglob("farfield-rE.csv"), None)
    if far_path is None:
        raise RuntimeError("palace did not write farfield-rE.csv")
    frequency, theta, phi, gain, peak_db = parse_farfield_re(far_path)
    nf2ff_csv = output_dir / "nf2ff.csv"
    farfield_vtp = output_dir / "farfield.vtp"
    write_nf2ff_csv(nf2ff_csv, frequency, theta, phi, gain)
    write_farfield_vtp(farfield_vtp, theta, phi, gain)
    log("solver-complete", durationSeconds=duration, bestFrequencyHz=best_freq, peakGainDb=peak_db)
    return RunResult(
        (s11_path,),
        (best_db,),
        (best_freq,),
        duration,
        nf2ff_csv,
        farfield_vtp,
        peak_db,
        (n_tets, n_faces, 0),
    )
