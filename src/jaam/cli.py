from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .artifacts import create_run_artifact, write_manifest
from .compiler import CompilationResult, compile_file_result
from .diagnostics import CompilationError, render_diagnostics
from .emitter import emit_meep_config, emit_palace_config, emit_python, emit_scuff_config
from .ir import CurveOp, SimulationIR, WireOp
from .runtime import BACKENDS, DEFAULT_BACKEND, NativeDependencyError, run_simulation
from .serialization import compilation_to_dict
from .container import ContainerEngine, ContainerUnavailableError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jaam", description="Just Another Antenna Modeller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "compile", "inspect", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--format", choices=("human", "json"), default="human")
        command.add_argument("--optimize-mesh-anchors", action="store_true", help="experimental fixed-anchor pruning for tessellated curves")
        command.add_argument(
            "--backend",
            choices=BACKENDS,
            default=DEFAULT_BACKEND,
            help="solver backend (also selects compile passes)",
        )
        if name == "compile":
            command.add_argument("-o", "--output", type=Path)
        if name == "run":
            command.add_argument("--output-dir", type=Path)
            command.add_argument("--no-farfield", action="store_true", help="skip far-field capture for faster S11 iteration")
            command.add_argument(
                "--farfield",
                choices=("off", "preview", "full"),
                default="full",
                help="far-field sample density (preview is coarser; --no-farfield aliases off)",
            )
    studio = subparsers.add_parser("studio")
    studio.add_argument("source", type=Path, nargs="?")
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--finale", action="store_true", required=True)
    return parser


def _inspection(result: CompilationResult) -> str:
    lines = [_summary(result.ir), "", "compiler passes:"]
    for item in result.passes:
        statistics = ", ".join(f"{key}={value}" for key, value in item.statistics.items())
        lines.append(f"  {item.name}: {item.duration_ns / 1_000_000:.3f} ms ({statistics})")
    lines.append(f"total: {result.duration_ns / 1_000_000:.3f} ms")
    return "\n".join(lines)


def _summary(ir: SimulationIR) -> str:
    thin = sum(isinstance(op, CurveOp) for op in ir.geometry)
    thick = sum(isinstance(op, WireOp) for op in ir.geometry)
    size = tuple(ir.domain_max[i] - ir.domain_min[i] for i in range(3))
    cells = (len(ir.mesh.lines_x) - 1, len(ir.mesh.lines_y) - 1, len(ir.mesh.lines_z) - 1)
    return (
        f"frequency: {ir.frequency.lower_hz:g}..{ir.frequency.upper_hz:g} Hz\n"
        f"domain: {size[0]:.6g} x {size[1]:.6g} x {size[2]:.6g} m\n"
        f"mesh plan: {cells[0]} x {cells[1]} x {cells[2]} intervals before native smoothing; max {ir.mesh.max_resolution_m:.6g} m\n"
        f"wires: {thin} thin, {thick} thick"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "doctor":
        from .doctor import finale_checks

        checks = finale_checks()
        for check in checks:
            label = "ok" if check.ok else "FAIL" if check.required else "skip"
            print(f"{label:4}  {check.name}: {check.detail}")
        return 0 if all(check.ok for check in checks if check.required) else 1
    if args.command == "studio":
        try:
            from .studio import launch

            launch(args.source)
        except (OSError, RuntimeError) as exc:
            print(f"jaam: {exc}", file=sys.stderr)
            return 2
        return 0
    try:
        result = compile_file_result(
            args.source,
            optimize_mesh_anchors=args.optimize_mesh_anchors,
            backend=args.backend,
        )
        ir = result.ir
    except OSError as exc:
        print(f"jaam: {exc}", file=sys.stderr)
        return 2
    except CompilationError as exc:
        render_diagnostics(exc.diagnostics, fmt=args.format)
        return 1

    errors = [item for item in result.diagnostics if item.severity == "error"]
    if errors:
        render_diagnostics(errors, fmt=args.format)
        return 1

    if args.command == "inspect":
        if args.format == "json":
            print(json.dumps(compilation_to_dict(result), indent=2, sort_keys=True))
        else:
            print(_inspection(result))
        return 0
    if args.format == "human":
        print(_summary(ir))
        for warning in ir.warnings:
            print(f"warning: {warning}", file=sys.stderr)
    if args.command == "check":
        if args.format == "human":
            print("check succeeded")
        return 0
    if args.command == "compile":
        if args.backend == "palace":
            output = args.output or args.source.with_suffix(".json")
            output.write_text(emit_palace_config(ir), encoding="utf-8")
        elif args.backend == "meep":
            output = args.output or args.source.with_suffix(".meep.json")
            output.write_text(emit_meep_config(ir), encoding="utf-8")
        elif args.backend == "scuff":
            output = args.output or args.source.with_suffix(".scuff.json")
            output.write_text(emit_scuff_config(ir), encoding="utf-8")
        else:
            output = args.output or args.source.with_suffix(".py")
            output.write_text(emit_python(ir), encoding="utf-8")
        if args.format == "human":
            print(f"wrote {output}")
        return 0
    artifact_root = args.output_dir or Path("jaam-out") / args.source.stem
    output_dir, manifest = create_run_artifact(artifact_root, args.source, result)
    print(f"artifact: {output_dir}", flush=True)
    try:
        try:
            # Prefer the native solver: it writes the full artifact contract
            # (S11, impedance, NF2FF cuts and far-field mesh). The packaged
            # generated script is retained as a dependency fallback.
            run_result = run_simulation(
                ir, output_dir,
                farfield="off" if args.no_farfield else args.farfield,
                backend=args.backend,
            )
            solver_engine = f"host:{args.backend}"
        except NativeDependencyError as native_error:
            try:
                engine = ContainerEngine.discover()
                if not engine.image_exists():
                    raise native_error
                if args.backend not in {"openems"}:
                    raise native_error
                run_result = engine.run(output_dir)
                solver_engine = f"{engine.name}:openems"
            except (ContainerUnavailableError, FileNotFoundError):
                raise native_error
    except NativeDependencyError as exc:
        manifest.update(status="failed", error=str(exc))
        write_manifest(output_dir, manifest)
        print(f"jaam: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        write_manifest(output_dir, manifest)
        print(f"jaam: solver failed: {exc}", file=sys.stderr)
        return 3
    manifest["status"] = "complete"
    manifest["solver"] = {
        "durationSeconds": run_result.solver_duration_s,
        "minimumS11Db": run_result.minimum_s11_db,
        "bestFrequencyHz": run_result.best_frequency_hz,
        "peakGainDb": run_result.peak_gain_db,
        "engine": solver_engine,
    }
    if run_result.native_mesh_cells:
        manifest["mesh"]["nativeCells"] = run_result.native_mesh_cells
        manifest["mesh"]["nativeTotalCells"] = (
            run_result.native_mesh_cells[0] * run_result.native_mesh_cells[1] * run_result.native_mesh_cells[2]
        )
    manifest["outputs"]["ports"] = [path.name for path in run_result.csv_files]
    if run_result.nf2ff_csv:
        manifest["outputs"]["nf2ff"] = run_result.nf2ff_csv.name
    if run_result.farfield_vtp:
        manifest["outputs"]["farfield"] = run_result.farfield_vtp.name
    write_manifest(output_dir, manifest)
    print(f"run {manifest['runId']}: {manifest['createdAt']}")
    for index, (path, minimum) in enumerate(zip(run_result.csv_files, run_result.minimum_s11_db), 1):
        print(f"port {index}: min S11 {minimum:.2f} dB; {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
