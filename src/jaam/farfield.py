from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Sequence


def gain_surface_points(
    theta_deg: Sequence[float], phi_deg: Sequence[float], gain_db: Sequence[Sequence[float]]
) -> tuple[tuple[float, float, float], ...]:
    if len(gain_db) != len(theta_deg) or any(len(row) != len(phi_deg) for row in gain_db):
        raise ValueError("gain matrix shape must be theta by phi")
    peak = max((value for row in gain_db for value in row), default=0.0)
    points = []
    for theta, row in zip(theta_deg, gain_db):
        polar = math.radians(theta)
        for phi, gain in zip(phi_deg, row):
            azimuth = math.radians(phi)
            radius = 10 ** ((gain - peak) / 20)
            points.append(
                (
                    radius * math.sin(polar) * math.cos(azimuth),
                    radius * math.sin(polar) * math.sin(azimuth),
                    radius * math.cos(polar),
                )
            )
    return tuple(points)


def write_nf2ff_csv(
    path: Path,
    frequency_hz: float,
    theta_deg: Sequence[float],
    phi_deg: Sequence[float],
    gain_db: Sequence[Sequence[float]],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("frequency_hz", "theta_deg", "phi_deg", "gain_db"))
        for theta, row in zip(theta_deg, gain_db):
            writer.writerows((frequency_hz, theta, phi, gain) for phi, gain in zip(phi_deg, row))


def write_farfield_vtp(
    path: Path,
    theta_deg: Sequence[float],
    phi_deg: Sequence[float],
    gain_db: Sequence[Sequence[float]],
) -> None:
    """Write an ASCII VTK PolyData gain surface without requiring VTK at runtime."""
    points = gain_surface_points(theta_deg, phi_deg, gain_db)
    columns = len(phi_deg)
    cells = []
    for row in range(len(theta_deg) - 1):
        for column in range(columns - 1):
            a = row * columns + column
            cells.append((a, a + 1, a + columns + 1, a + columns))
    connectivity = " ".join(str(index) for cell in cells for index in cell)
    offsets = " ".join(str(4 * (index + 1)) for index in range(len(cells)))
    coordinates = " ".join(f"{value:.12g}" for point in points for value in point)
    gains = " ".join(f"{value:.12g}" for row in gain_db for value in row)
    path.write_text(
        f'''<?xml version="1.0"?>
<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian">
  <PolyData><Piece NumberOfPoints="{len(points)}" NumberOfPolys="{len(cells)}">
    <PointData Scalars="gain_db"><DataArray type="Float64" Name="gain_db" format="ascii">{gains}</DataArray></PointData>
    <Points><DataArray type="Float64" NumberOfComponents="3" format="ascii">{coordinates}</DataArray></Points>
    <Polys>
      <DataArray type="Int64" Name="connectivity" format="ascii">{connectivity}</DataArray>
      <DataArray type="Int64" Name="offsets" format="ascii">{offsets}</DataArray>
    </Polys>
  </Piece></PolyData>
</VTKFile>
''',
        encoding="utf-8",
    )
