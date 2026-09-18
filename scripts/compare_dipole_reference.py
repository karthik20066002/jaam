"""Compare a completed JAAM dipole artifact with the hand-written reference."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jaam.results import load_nf2ff
from jaam.runtime import RunResult
from benchmark_mesh import numerical_delta


def run_files(directory: Path) -> RunResult:
    pattern = load_nf2ff(directory / "nf2ff.csv")
    return RunResult((directory / "port1_s11.csv",), (), nf2ff_csv=directory / "nf2ff.csv",
                     peak_gain_db=pattern.peak_gain_db)


def cut_delta(reference, jaam, method: str) -> float:
    angles_a, gain_a = getattr(reference, method)()
    angles_b, gain_b = getattr(jaam, method)()
    if angles_a != angles_b:
        raise ValueError(f"{method} angles differ")
    return max(abs(a - b) for a, b in zip(gain_a, gain_b) if max(a, b) >= -40)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("jaam_artifact", type=Path)
    parser.add_argument("reference_artifact", type=Path)
    args = parser.parse_args()
    jaam = args.jaam_artifact.resolve()
    reference = args.reference_artifact.resolve()
    delta = numerical_delta(run_files(reference), run_files(jaam))
    pattern_ref = load_nf2ff(reference / "nf2ff.csv")
    pattern_jaam = load_nf2ff(jaam / "nf2ff.csv")
    delta["azimuthCutDeltaDbAboveMinus40"] = cut_delta(pattern_ref, pattern_jaam, "azimuth_cut")
    delta["elevationCutDeltaDbAboveMinus40"] = cut_delta(pattern_ref, pattern_jaam, "elevation_cut")
    delta["withinDocumentedTargets"] = (
        delta["maxS11DeltaDb"] <= 0.1
        and delta["maxImpedanceRelativeDelta"] <= 0.01
        and max(delta["azimuthCutDeltaDbAboveMinus40"], delta["elevationCutDeltaDbAboveMinus40"]) <= 0.5
    )
    print(json.dumps(delta, indent=2, sort_keys=True))
    raise SystemExit(0 if delta["withinDocumentedTargets"] else 1)


if __name__ == "__main__":
    main()
