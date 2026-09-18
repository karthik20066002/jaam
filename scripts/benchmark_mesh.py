"""Compare the established mesh pipeline with JAAM's current optimized pipeline.

Run with the system Python so the native CSXCAD/openEMS bindings are available:
PYTHONPATH=src python3 scripts/benchmark_mesh.py --output-dir /tmp/jaam-mesh-benchmark --solve
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from jaam.compiler import compile_file_result
from jaam.frontend import parse_file
from jaam.passes import GradedMeshCoarseningPass, MergeCollinearWiresPass, ValidateFeedsPass, ValidateMeshResolutionPass
from jaam.runtime import build_native, run_simulation
from jaam.semantics import analyze


MODELS = ("yagi", "helix", "parabolic_arc", "concat")


def baseline_ir(source: Path):
    ir = analyze(parse_file(source))
    for pass_ in (ValidateFeedsPass(), MergeCollinearWiresPass(), GradedMeshCoarseningPass(), ValidateMeshResolutionPass()):
        result = pass_.run(ir)
        if result.diagnostics:
            raise ValueError(result.diagnostics)
        ir = result.ir
    return ir


def metrics(ir):
    csx, fdtd, ports = build_native(ir)
    actual = tuple(len(csx.GetGrid().GetLines(axis)) for axis in "xyz")
    return {
        "vertices": sum(len(op.points) for op in ir.geometry if hasattr(op, "points")),
        "fixedAnchors": sum(len(lines) for lines in (ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z)),
        "nativeCells": actual,
        "nativeTotalCells": actual[0] * actual[1] * actual[2],
    }


def port_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def pattern_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def numerical_delta(before, after):
    b, a = port_rows(before.csv_files[0]), port_rows(after.csv_files[0])
    if [row["frequency_hz"] for row in b] != [row["frequency_hz"] for row in a]:
        raise ValueError("S11 frequency grids differ")
    s11 = max(abs(float(x["s11_db"]) - float(y["s11_db"])) for x, y in zip(b, a))
    impedance = max(
        abs(complex(float(x["resistance_ohm"]), float(x["reactance_ohm"]))
            - complex(float(y["resistance_ohm"]), float(y["reactance_ohm"])))
        / max(abs(complex(float(x["resistance_ohm"]), float(x["reactance_ohm"]))), 1.0)
        for x, y in zip(b, a)
    )
    farfield_b, farfield_a = pattern_rows(before.nf2ff_csv), pattern_rows(after.nf2ff_csv)
    if [(r["theta_deg"], r["phi_deg"]) for r in farfield_b] != [(r["theta_deg"], r["phi_deg"]) for r in farfield_a]:
        raise ValueError("NF2FF angular grids differ")
    gain = max(
        abs(float(x["gain_db"]) - float(y["gain_db"]))
        for x, y in zip(farfield_b, farfield_a)
        if max(float(x["gain_db"]), float(y["gain_db"])) >= -40
    )
    return {"maxS11DeltaDb": s11, "maxImpedanceRelativeDelta": impedance,
            "maxGainDeltaDbAboveMinus40": gain,
            "peakGainDeltaDb": abs(before.peak_gain_db - after.peak_gain_db)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/jaam-mesh-benchmark"))
    parser.add_argument("--solve", action="store_true")
    parser.add_argument("--models", nargs="+", choices=MODELS, default=MODELS)
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[1]
    table = []
    for name in args.models:
        source = repository / "examples/yagi.jaam" if name == "yagi" else repository / "benchmarks" / f"{name}.jaam"
        old_ir = baseline_ir(source)
        result = compile_file_result(source, optimize_mesh_anchors=True)
        new_ir = result.ir
        row = {"model": name, "before": metrics(old_ir), "after": metrics(new_ir),
               "passes": {item.name: item.statistics for item in result.passes if item.name in ("canonicalize-wire-vertices", "mesh-anchor-pruning")}}
        if args.solve:
            old = run_simulation(old_ir, args.output_dir / name / "before")
            new = run_simulation(new_ir, args.output_dir / name / "after")
            row["solverSeconds"] = {"before": old.solver_duration_s, "after": new.solver_duration_s}
            row["numericalDelta"] = numerical_delta(old, new)
        table.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    (args.output_dir / "results.json").write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
