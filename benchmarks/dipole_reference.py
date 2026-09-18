"""Hand-written openEMS reference for the 900–1100 MHz JAAM dipole.

The mesh lines are an explicit frozen numerical setup matching JAAM's established
dipole mesh. The geometry, port, solve, and result processing are coded directly
with CSXCAD/openEMS rather than calling JAAM's compiler or runtime.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import uuid

import numpy as np
from CSXCAD import ContinuousStructure
from openEMS import openEMS


XY_LINES = (
    -0.177150088818, -0.1391893555, -0.101228622182, -0.063267888864,
    -0.037960733318, -0.012653577773, 0.0, 0.012653577773,
    0.037960733318, 0.075921466636, 0.113882199955, 0.151842933273,
    0.177150088818,
)
Z_LINES = (
    -0.248150088818, -0.2101893555, -0.172228622182, -0.134267888864,
    -0.108960733318, -0.083653577773, -0.071, -0.059333333333,
    -0.036, -0.012666666667, -0.001, -0.000333333333, 0.000333333333,
    0.001, 0.012666666667, 0.036, 0.059333333333, 0.071,
    0.083653577773, 0.108960733318, 0.146921466636, 0.184882199955,
    0.222842933273, 0.248150088818,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("/tmp/jaam-dipole-reference"))
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    output = (args.output_dir / run_id).resolve()
    output.mkdir(parents=True, exist_ok=False)

    csx = ContinuousStructure()
    copper = csx.AddMetal("copper")
    copper.AddCurve(points=np.asarray(((0, 0, -0.071), (0, 0, -0.001)), dtype=float).T, priority=10)
    copper.AddCurve(points=np.asarray(((0, 0, 0.001), (0, 0, 0.071)), dtype=float).T, priority=10)

    fdtd = openEMS(EndCriteria=1e-5)
    fdtd.SetCSX(csx)
    fdtd.SetGaussExcite(1e9, 2e8)
    fdtd.SetBoundaryCond(["PML_8"] * 6)
    port = fdtd.AddLumpedPort(1, 50, (0, 0, -0.001), (0, 0, 0.001), "z", excite=1, priority=20)
    grid = csx.GetGrid()
    grid.SetDeltaUnit(1.0)
    for axis, lines in (("x", XY_LINES), ("y", XY_LINES), ("z", Z_LINES)):
        grid.SetLines(axis, lines)
        grid.SmoothMeshLines(axis, 0.01362692990909091, ratio=1.5)
    fdtd_dimensions = [len(grid.GetLines(axis)) for axis in "xyz"]
    nf2ff = fdtd.CreateNF2FFBox()
    fdtd.Run(str(output), cleanup=True)

    frequencies = np.linspace(900e6, 1100e6, 401)
    port.CalcPort(str(output), frequencies)
    gamma = port.uf_ref / port.uf_inc
    magnitude = np.abs(gamma)
    s11_db = 20 * np.log10(np.maximum(magnitude, 1e-300))
    vswr = np.where(magnitude < 1, (1 + magnitude) / (1 - magnitude), np.inf)
    impedance = 50 * (1 + gamma) / (1 - gamma)
    with (output / "port1_s11.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("frequency_hz", "s11_db", "vswr", "resistance_ohm", "reactance_ohm"))
        writer.writerows(
            (float(f), float(s), float(v), float(z.real), float(z.imag))
            for f, s, v, z in zip(frequencies, s11_db, vswr, impedance)
        )

    best_frequency = float(frequencies[int(np.argmin(s11_db))])
    theta = np.linspace(0, 180, 181)
    phi = np.linspace(0, 360, 361)
    pattern = nf2ff.CalcNF2FF(str(output), best_frequency, theta, phi, read_cached=False)
    field = np.squeeze(np.asarray(pattern.E_norm, dtype=float))
    if field.shape == (len(phi), len(theta)):
        field = field.T
    if field.shape != (len(theta), len(phi)):
        raise RuntimeError(f"unexpected NF2FF shape: {field.shape}")
    peak_gain = 10 * math.log10(float(np.ravel(np.asarray(pattern.Dmax))[0]))
    gain = 20 * np.log10(np.maximum(field / np.max(field), 1e-300)) + peak_gain
    with (output / "nf2ff.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("frequency_hz", "theta_deg", "phi_deg", "gain_db"))
        for t_index, t in enumerate(theta):
            for p_index, p in enumerate(phi):
                writer.writerow((best_frequency, float(t), float(p), float(gain[t_index, p_index])))

    (output / "reference.json").write_text(json.dumps({
        "runId": run_id, "fdtdDimensions": fdtd_dimensions,
        "bestFrequencyHz": best_frequency, "minimumS11Db": float(np.min(s11_db)),
        "peakGainDb": peak_gain,
    }, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
