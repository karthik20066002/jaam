from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .compiler import CompilationResult, compile_file_result
from .diagnostics import CompilationError, render_diagnostics
from .emitter import emit_python
from .ir import CurveOp, SimulationIR, WireOp
from .runtime import NativeDependencyError, run_simulation
from .serialization import compilation_to_dict


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jaam", description="Just Another Antenna Modeller")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "compile", "inspect", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("source", type=Path)
        command.add_argument("--format", choices=("human", "json"), default="human")
        if name == "compile":
            command.add_argument("-o", "--output", type=Path)
        if name == "run":
            command.add_argument("--output-dir", type=Path)
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
        f"mesh: {cells[0]} x {cells[1]} x {cells[2]} cells; max {ir.mesh.max_resolution_m:.6g} m\n"
        f"wires: {thin} thin, {thick} thick"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = compile_file_result(args.source)
        ir = result.ir
    except OSError as exc:
        print(f"jaam: {exc}", file=sys.stderr)
        return 2
    except CompilationError as exc:
        render_diagnostics(exc.diagnostics, fmt=args.format)
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
        output = args.output or args.source.with_suffix(".py")
        output.write_text(emit_python(ir), encoding="utf-8")
        if args.format == "human":
            print(f"wrote {output}")
        return 0
    output_dir = args.output_dir or Path("jaam-out") / args.source.stem
    try:
        result = run_simulation(ir, output_dir)
    except NativeDependencyError as exc:
        print(f"jaam: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"jaam: solver failed: {exc}", file=sys.stderr)
        return 3
    for index, (path, minimum) in enumerate(zip(result.csv_files, result.minimum_s11_db), 1):
        print(f"port {index}: min S11 {minimum:.2f} dB; {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
