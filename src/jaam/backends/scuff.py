"""SCUFF-EM BEM backend: open cylindrical PEC tubes, rim ports, EPFile far field."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import shutil
import subprocess
from time import perf_counter
from typing import Any

from jaam.farfield import write_farfield_vtp, write_nf2ff_csv
from jaam.ir import BoxOp, CurveOp, FeedSpec, Point3, RotPolyOp, SimulationIR, WireOp

from .common import NativeDependencyError, RunResult, farfield_mode

_C0 = 299_792_458.0
_ETA0 = 376.730313461
_M_TO_MM = 1000.0
NCIRC = 8
AXIAL_MM = 4.0


def _scuff_rf() -> Path:
    configured = os.environ.get("JAAM_SCUFF_RF")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    which = shutil.which("scuff-rf")
    if which:
        candidates.append(Path(which))
    candidates.append(Path("/home/axiss/scuff-em/applications/scuff-rf/scuff-rf"))
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise NativeDependencyError(
        "SCUFF backend requires scuff-rf on PATH, JAAM_SCUFF_RF, or the local scuff-em build"
    )


def _feeds(ir: SimulationIR) -> list[tuple[CurveOp | WireOp, FeedSpec]]:
    return [
        (op, op.feed)
        for op in ir.geometry
        if isinstance(op, (CurveOp, WireOp)) and op.feed is not None
    ]


def _vec_sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _vec_add(a: Point3, b: Point3) -> Point3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _vec_scale(a: Point3, s: float) -> Point3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _vec_dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a: Point3, b: Point3) -> Point3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _vec_len(a: Point3) -> float:
    return math.sqrt(_vec_dot(a, a))


def _vec_norm(a: Point3) -> Point3:
    length = _vec_len(a)
    if length <= 1e-15:
        raise ValueError("zero-length vector")
    return _vec_scale(a, 1.0 / length)


def _to_mm(point: Point3) -> Point3:
    return _vec_scale(point, _M_TO_MM)


def _frame(tangent: Point3) -> tuple[Point3, Point3]:
    helper = (1.0, 0.0, 0.0) if abs(tangent[0]) < 0.9 else (0.0, 1.0, 0.0)
    normal = _vec_norm(_vec_cross(tangent, helper))
    binormal = _vec_cross(tangent, normal)
    return normal, binormal


def _rotate_onto(vector: Point3, t0: Point3, t1: Point3) -> Point3:
    axis = _vec_cross(t0, t1)
    sine = _vec_len(axis)
    cosine = _vec_dot(t0, t1)
    if sine < 1e-12:
        return vector if cosine > 0 else _vec_scale(vector, -1.0)
    axis = _vec_scale(axis, 1.0 / sine)
    kxv = _vec_cross(axis, vector)
    return _vec_add(
        _vec_add(_vec_scale(vector, cosine), _vec_scale(kxv, sine)),
        _vec_scale(axis, _vec_dot(axis, vector) * (1.0 - cosine)),
    )


def _resample(points: tuple[Point3, ...], spacing: float) -> list[Point3]:
    if len(points) < 2:
        raise ValueError("a wire needs at least two points")
    sampled = [points[0]]
    for start, stop in zip(points, points[1:]):
        delta = _vec_sub(stop, start)
        length = _vec_len(delta)
        if length <= 1e-12:
            continue
        steps = max(1, int(round(length / spacing)))
        for i in range(1, steps + 1):
            sampled.append(_vec_add(start, _vec_scale(delta, i / steps)))
    return sampled


def _tangents(points: list[Point3]) -> list[Point3]:
    tangents = []
    last = len(points) - 1
    for i, point in enumerate(points):
        if i == 0:
            tangents.append(_vec_norm(_vec_sub(points[1], point)))
        elif i == last:
            tangents.append(_vec_norm(_vec_sub(point, points[i - 1])))
        else:
            tangents.append(_vec_norm(_vec_sub(points[i + 1], points[i - 1])))
    return tangents


def _rings(points: list[Point3], radius: float) -> list[list[Point3]]:
    tangents = _tangents(points)
    normal, binormal = _frame(tangents[0])
    rings = []
    for i, point in enumerate(points):
        if i:
            normal = _rotate_onto(normal, tangents[i - 1], tangents[i])
            binormal = _vec_cross(tangents[i], normal)
        ring = []
        for k in range(NCIRC):
            angle = 2.0 * math.pi * k / NCIRC
            offset = _vec_add(_vec_scale(normal, radius * math.cos(angle)), _vec_scale(binormal, radius * math.sin(angle)))
            ring.append(_vec_add(point, offset))
        rings.append(ring)
    return rings


def _rim_polygon(center: Point3, tangent: Point3, radius: float) -> list[Point3]:
    normal, binormal = _frame(_vec_norm(tangent))
    poly_r = radius / math.cos(math.pi / NCIRC) * 1.05
    return [
        _vec_add(
            center,
            _vec_add(_vec_scale(normal, poly_r * math.cos(angle)), _vec_scale(binormal, poly_r * math.sin(angle))),
        )
        for angle in (2.0 * math.pi * k / NCIRC for k in range(NCIRC))
    ]


def scuff_objects(ir: SimulationIR) -> list[dict[str, Any]]:
    objects = []
    for op in ir.geometry:
        if not isinstance(op, (CurveOp, WireOp)):
            continue
        objects.append(
            {
                "name": op.name,
                "points_mm": [_to_mm(point) for point in op.points],
                "radius_mm": op.radius_m * _M_TO_MM,
                "feed": op.feed,
            }
        )
    if not objects:
        raise RuntimeError("SCUFF backend currently supports wire geometry only")
    if any(isinstance(op, (BoxOp, RotPolyOp)) for op in ir.geometry):
        raise RuntimeError("SCUFF backend does not yet mesh boxes or revolved solids")
    return objects


def _add_object_mesh(
    nodes: list[Point3],
    tris: list[tuple[int, int, int, int]],
    points_mm: list[Point3],
    radius_mm: float,
    tag: int,
) -> None:
    sampled = _resample(tuple(points_mm), AXIAL_MM)
    rings = _rings(sampled, radius_mm)
    index_rings = []
    for ring in rings:
        start = len(nodes)
        nodes.extend(ring)
        index_rings.append(list(range(start, start + NCIRC)))
    for a, b in zip(index_rings, index_rings[1:]):
        for k in range(NCIRC):
            k2 = (k + 1) % NCIRC
            n00, n10, n01, n11 = a[k] + 1, b[k] + 1, a[k2] + 1, b[k2] + 1
            tris.append((tag, n00, n10, n11))
            tris.append((tag, n00, n11, n01))


def write_scuff_inputs(ir: SimulationIR, directory: Path, *, stem: str = "model") -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    objects = scuff_objects(ir)
    nodes: list[Point3] = []
    tris: list[tuple[int, int, int, int]] = []
    for tag, obj in enumerate(objects, start=1):
        obj["tag"] = tag
        _add_object_mesh(nodes, tris, obj["points_mm"], obj["radius_mm"], tag)

    mesh_path = directory / f"{stem}.msh"
    geo_path = directory / f"{stem}.scuffgeo"
    ports_path = directory / f"{stem}.ports"
    currents_path = directory / f"{stem}.portcurrents"

    names = [(obj["tag"], obj["name"]) for obj in objects]
    lines = ["$MeshFormat", "2.2 0 8", "$EndMeshFormat", "$PhysicalNames", str(len(names))]
    for tag, name in names:
        lines.append(f'2 {tag} "{name}"')
    lines += ["$EndPhysicalNames", "$Nodes", str(len(nodes))]
    for i, (x, y, z) in enumerate(nodes, start=1):
        lines.append(f"{i} {x:.16g} {y:.16g} {z:.16g}")
    lines += ["$EndNodes", "$Elements", str(len(tris))]
    for index, (tag, n1, n2, n3) in enumerate(tris, start=1):
        lines.append(f"{index} 2 2 {tag} {tag} {n1} {n2} {n3}")
    lines.append("$EndElements")
    mesh_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    geo = [f"MESHPATH {directory.resolve()}"]
    for obj in objects:
        geo.append(
            "\n".join(
                (
                    f"OBJECT {obj['name']}",
                    f"\tMESHFILE {mesh_path.name}",
                    f"\tMESHTAG  {obj['tag']}",
                    "ENDOBJECT",
                )
            )
        )
    geo_path.write_text("\n\n".join(geo) + "\n", encoding="utf-8")

    feeds = _feeds(ir)
    if len(feeds) != 1:
        raise RuntimeError("SCUFF backend currently supports exactly one feed")
    fed, feed = feeds[0]
    mate_name = fed.name[:-3] + "__b" if fed.name.endswith("__a") else None
    mate = next((obj for obj in objects if obj["name"] == mate_name), None)
    if mate is None:
        raise RuntimeError(f"fed wire {fed.name} has no complementary half")
    # The port polygons must lie ON the open tube rims (the metal-gap ends).
    # These now coincide with feed.start/feed.stop (see semantics._make_feed),
    # but rim_nearest is kept as a defensive lookup against the actual sampled
    # mesh rather than trusting that coincidence, since a mismatch here means
    # the polygons float in empty mesh and scuff-rf finds 0 edges.
    feed_mid = tuple((feed.start[i] + feed.stop[i]) / 2 for i in range(3))

    def rim_nearest(points_mm: list[Point3], ref: Point3) -> Point3:
        return min((points_mm[0], points_mm[-1]),
                   key=lambda p: math.dist(p[:3], ref[:3]))

    fed_obj = next(obj for obj in objects if obj["name"] == fed.name)
    p_center = rim_nearest(mate["points_mm"], _to_mm(feed_mid))
    m_center = rim_nearest(fed_obj["points_mm"], _to_mm(feed_mid))
    tangent = _vec_sub(feed.stop, feed.start)
    p_poly = _rim_polygon(p_center, tangent, fed.radius_m * _M_TO_MM)
    m_poly = _rim_polygon(m_center, tangent, fed.radius_m * _M_TO_MM)
    def poly_line(kind: str, verts: list[Point3]) -> str:
        return "  " + kind + " " + " ".join(f"{value:.16g}" for point in verts for value in point)

    ports_path.write_text(
        "\n".join(
            (
                "PORT",
                f"  POBJECT {mate['name']}",
                f"  MOBJECT {fed.name}",
                poly_line("PPOLYGON", p_poly),
                poly_line("MPOLYGON", m_poly),
                "ENDPORT",
                "",
            )
        ),
        encoding="utf-8",
    )
    freq_ghz = ir.frequency.center_hz / 1e9
    currents_path.write_text(f"{freq_ghz} 1.0 0.0\n", encoding="utf-8")
    return {
        "mesh": mesh_path,
        "geometry": geo_path,
        "ports": ports_path,
        "currents": currents_path,
        "nodes": len(nodes),
        "triangles": len(tris),
        "objects": [obj["name"] for obj in objects],
        "z0": feed.impedance_ohm,
        "freq_ghz": freq_ghz,
    }


def emit_scuff_manifest(ir: SimulationIR) -> str:
    import json

    objects = scuff_objects(ir)
    feeds = _feeds(ir)
    payload = {
        "objects": [{"name": obj["name"], "radius_mm": obj["radius_mm"]} for obj in objects],
        "feed_count": len(feeds),
        "ncir": NCIRC,
        "axial_mm": AXIAL_MM,
        "units": "mm",
        "frequency_ghz": ir.frequency.center_hz / 1e9,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _parse_zparms(path: Path, z0: float) -> list[dict[str, float]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [float(tok) for tok in line.split()]
            if len(parts) < 3:
                continue
            z = complex(parts[1], parts[2])
            gamma = (z - z0) / (z + z0)
            mag = abs(gamma)
            db = 20.0 * math.log10(max(mag, 1e-300))
            vswr = (1 + mag) / (1 - mag) if mag < 1 else float("inf")
            rows.append(
                {
                    "frequency_hz": parts[0] * 1e9,
                    "s11_real": gamma.real,
                    "s11_imag": gamma.imag,
                    "s11_db": db,
                    "vswr": vswr,
                    "resistance_ohm": z.real,
                    "reactance_ohm": z.imag,
                }
            )
    if not rows:
        raise RuntimeError(f"no Z-parameter samples in {path}")
    return rows


def _write_s11(path: Path, rows: list[dict[str, float]]) -> tuple[float, float]:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ("frequency_hz", "s11_real", "s11_imag", "s11_db", "vswr", "resistance_ohm", "reactance_ohm")
        )
        best = (rows[0]["s11_db"], rows[0]["frequency_hz"])
        for row in rows:
            writer.writerow(
                (
                    row["frequency_hz"],
                    row["s11_real"],
                    row["s11_imag"],
                    row["s11_db"],
                    row["vswr"],
                    row["resistance_ohm"],
                    row["reactance_ohm"],
                )
            )
            if row["s11_db"] < best[0]:
                best = (row["s11_db"], row["frequency_hz"])
    return best


def _parse_fields(path: Path) -> tuple[Any, Any, Any]:
    import numpy as np

    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            values = [float(tok) for tok in line.split()]
            if len(values) < 15:
                raise ValueError(f"{path}: expected 15 columns, got {len(values)}")
            rows.append(values[:15])
    data = np.asarray(rows, dtype=float)
    xyz = data[:, 0:3]
    e = data[:, 3:9:2] + 1j * data[:, 4:9:2]
    h = data[:, 9:15:2] + 1j * data[:, 10:15:2]
    return xyz, e, h


def _radial_poynting(xyz: Any, e: Any, h: Any) -> Any:
    import numpy as np

    flux = 0.5 * np.real(np.cross(np.conj(e), h))
    norms = np.linalg.norm(xyz, axis=1)
    rhat = xyz / norms[:, None]
    return np.einsum("ij,ij->i", rhat, flux)


def _write_sphere_ep(path: Path, radius_mm: float, step_deg: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    thetas = tuple(float(t) for t in range(0, 181, step_deg))
    phis = tuple(float(p) for p in range(0, 361, step_deg))
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"# sphere R={radius_mm} mm, step={step_deg} deg\n")
        for theta in thetas:
            polar = math.radians(theta)
            for phi in phis:
                azimuth = math.radians(phi)
                x = radius_mm * math.sin(polar) * math.cos(azimuth)
                y = radius_mm * math.sin(polar) * math.sin(azimuth)
                z = radius_mm * math.cos(polar)
                handle.write(f"{x:.10e} {y:.10e} {z:.10e}\n")
    return thetas, phis


def _run_scuff(command: list[str], cwd: Path, log_path: Path) -> str:
    env = dict(os.environ)
    env["SCUFF_MESH_PATH"] = str(cwd)
    completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(completed.stdout)
        handle.write(completed.stderr)
    if completed.returncode != 0:
        raise RuntimeError(f"scuff-rf exited {completed.returncode}; see {log_path}")
    return completed.stdout


def run_scuff(ir: SimulationIR, output_dir: Path, *, farfield: bool | str = True) -> RunResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "solver.log.jsonl"
    scuff_log = output_dir / "scuff-rf.log"
    job = write_scuff_inputs(ir, output_dir, stem="model")
    scuff = _scuff_rf()

    def log(event: str, **fields: Any) -> None:
        import json

        item = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, sort_keys=True) + "\n")

    log("solver-start", backend="scuff", triangles=job["triangles"], objects=job["objects"])
    started = perf_counter()
    _run_scuff(
        [
            str(scuff),
            "--geometry",
            str(job["geometry"]),
            "--portfile",
            str(job["ports"]),
            "--frequency",
            str(job["freq_ghz"]),
            "--ZParameters",
            "--SParameters",
        ],
        output_dir,
        scuff_log,
    )
    zparms = sorted(output_dir.glob("*.zparms"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not zparms:
        raise RuntimeError("scuff-rf did not write a .zparms file")
    rows = _parse_zparms(zparms[0], job["z0"])
    s11_path = output_dir / "port1_s11.csv"
    best_db, best_freq = _write_s11(s11_path, rows)

    quality = farfield_mode(farfield)
    if quality == "off":
        duration = perf_counter() - started
        log("solver-complete", durationSeconds=duration, farfield=False)
        return RunResult((s11_path,), (best_db,), (best_freq,), duration, native_mesh_cells=(job["triangles"], job["nodes"], 0))

    wavelength_mm = 300.0 / job["freq_ghz"]
    radius_mm = max(1000.0, 8.0 * wavelength_mm)
    ep_path = output_dir / "sphere.ep"
    step = 15 if quality == "preview" else 5
    thetas, phis = _write_sphere_ep(ep_path, radius_mm, step)
    stdout = _run_scuff(
        [
            str(scuff),
            "--geometry",
            str(job["geometry"]),
            "--portfile",
            str(job["ports"]),
            "--portcurrentFile",
            str(job["currents"]),
            "--EPFile",
            str(ep_path),
        ],
        output_dir,
        scuff_log,
    )
    fields = None
    for line in stdout.splitlines():
        if "written to file" in line:
            name = line.rsplit(" ", 1)[-1].rstrip(".")
            candidate = Path(name) if Path(name).is_absolute() else output_dir / name
            if candidate.is_file():
                fields = candidate
                break
    if fields is None:
        found = sorted(output_dir.glob("*.fields"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not found:
            raise RuntimeError("scuff-rf did not write a .fields file")
        fields = found[0]
    xyz, e, h = _parse_fields(fields)
    pr = _radial_poynting(xyz, e, h)
    expected = len(thetas) * len(phis)
    if len(pr) != expected:
        raise RuntimeError(f"far-field samples {len(pr)} != {expected}")
    import numpy as np

    intensity = np.asarray(pr).reshape(len(thetas), len(phis))
    radiated = 0.0
    peak = 0.0
    dtheta = math.radians(float(step))
    dphi = math.radians(float(step))
    for i, theta in enumerate(thetas):
        weight = math.sin(math.radians(theta)) * dtheta * dphi
        for value in intensity[i]:
            flux = max(float(value), 0.0) * (radius_mm * 1e-3) ** 2
            radiated += flux * weight
            peak = max(peak, flux)
    if radiated <= 0:
        raise RuntimeError("SCUFF far-field radiated power is zero")
    gain_rows = []
    peak_db = 10.0 * math.log10(max(4.0 * math.pi * peak / radiated, 1e-300))
    for i, _ in enumerate(thetas):
        gain_rows.append(
            tuple(
                10.0 * math.log10(max(4.0 * math.pi * max(float(value), 0.0) * (radius_mm * 1e-3) ** 2 / radiated, 1e-300))
                for value in intensity[i]
            )
        )
    nf2ff_csv = output_dir / "nf2ff.csv"
    farfield_vtp = output_dir / "farfield.vtp"
    write_nf2ff_csv(nf2ff_csv, best_freq, thetas, phis, gain_rows)
    write_farfield_vtp(farfield_vtp, thetas, phis, gain_rows)
    duration = perf_counter() - started
    log("solver-complete", durationSeconds=duration, peakGainDb=peak_db)
    return RunResult(
        (s11_path,),
        (best_db,),
        (best_freq,),
        duration,
        nf2ff_csv,
        farfield_vtp,
        peak_db,
        (job["triangles"], job["nodes"], 0),
    )
