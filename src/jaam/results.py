from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RadiationPattern:
    frequency_hz: float
    theta_deg: tuple[float, ...]
    phi_deg: tuple[float, ...]
    gain_db: tuple[tuple[float, ...], ...]

    @property
    def peak_gain_db(self) -> float:
        return max(value for row in self.gain_db for value in row)

    def azimuth_cut(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """XY/E-plane cut at theta=90°, centered to -180..180 degrees."""
        row = min(range(len(self.theta_deg)), key=lambda index: abs(self.theta_deg[index] - 90.0))
        samples = sorted(
            (((phi + 180.0) % 360.0) - 180.0, self.gain_db[row][column])
            for column, phi in enumerate(self.phi_deg)
            if phi < 360.0
        )
        return tuple(item[0] for item in samples), tuple(item[1] for item in samples)

    def elevation_cut(self) -> tuple[tuple[float, ...], tuple[float, ...]]:
        """XZ/H-plane cut at phi=0°, expressed as -90..90 degrees."""
        column = min(range(len(self.phi_deg)), key=lambda index: abs(self.phi_deg[index]))
        angles = tuple(90.0 - theta for theta in reversed(self.theta_deg))
        values = tuple(self.gain_db[row][column] for row in reversed(range(len(self.theta_deg))))
        return angles, values


def load_nf2ff(path: Path) -> RadiationPattern:
    samples: dict[tuple[float, float], float] = {}
    frequencies = set()
    theta_values = set()
    phi_values = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            frequency = float(row["frequency_hz"])
            theta = float(row["theta_deg"])
            phi = float(row["phi_deg"])
            frequencies.add(frequency)
            theta_values.add(theta)
            phi_values.add(phi)
            samples[(theta, phi)] = float(row["gain_db"])
    if len(frequencies) != 1 or not samples:
        raise ValueError("NF2FF CSV must contain exactly one populated frequency")
    theta = tuple(sorted(theta_values))
    phi = tuple(sorted(phi_values))
    try:
        gain = tuple(tuple(samples[(t, p)] for p in phi) for t in theta)
    except KeyError as exc:
        raise ValueError("NF2FF CSV does not contain a complete theta/phi grid") from exc
    return RadiationPattern(frequencies.pop(), theta, phi, gain)
