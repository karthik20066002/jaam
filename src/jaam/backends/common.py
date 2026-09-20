from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class NativeDependencyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RunResult:
    csv_files: tuple[Path, ...]
    minimum_s11_db: tuple[float, ...]
    best_frequency_hz: tuple[float, ...] = ()
    solver_duration_s: float = 0.0
    nf2ff_csv: Path | None = None
    farfield_vtp: Path | None = None
    peak_gain_db: float | None = None
    native_mesh_cells: tuple[int, int, int] = ()


BACKENDS = ("openems", "palace", "meep", "scuff")
DEFAULT_BACKEND = "openems"


def farfield_mode(farfield: bool | str) -> str:
    if farfield is False or farfield == "off":
        return "off"
    if farfield == "preview":
        return "preview"
    return "full"
