"""Load the result files named by a completed JAAM run manifest."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
from pathlib import Path

from .results import RadiationPattern, load_nf2ff


@dataclass(frozen=True, slots=True)
class PortSample:
    frequency_hz: float
    s11_db: float
    vswr: float
    resistance_ohm: float
    reactance_ohm: float


@dataclass(frozen=True, slots=True)
class RunResults:
    directory: Path
    manifest: dict
    ports: tuple[tuple[PortSample, ...], ...]
    radiation: RadiationPattern | None


def _named_file(directory: Path, name: str) -> Path:
    if Path(name).name != name:
        raise ValueError(f"invalid artifact filename: {name}")
    path = directory / name
    if not path.is_file():
        raise ValueError(f"artifact output is missing: {path}")
    return path


def load_run_results(directory: Path) -> RunResults:
    directory = directory.resolve()
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"artifact manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "complete":
        raise ValueError(f"run is {manifest.get('status', 'unknown')}")
    outputs = manifest["outputs"]
    ports = []
    for name in outputs.get("ports", []):
        with _named_file(directory, name).open(newline="", encoding="utf-8") as handle:
            rows = tuple(
                PortSample(*(float(row[key]) for key in (
                    "frequency_hz", "s11_db", "vswr", "resistance_ohm", "reactance_ohm"
                )))
                for row in csv.DictReader(handle)
            )
        if not rows:
            raise ValueError(f"port result is empty: {name}")
        ports.append(rows)
    radiation = load_nf2ff(_named_file(directory, outputs["nf2ff"])) if outputs.get("nf2ff") else None
    return RunResults(directory, manifest, tuple(ports), radiation)
