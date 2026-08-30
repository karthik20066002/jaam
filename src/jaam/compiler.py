from __future__ import annotations

from pathlib import Path

from .frontend import parse_file, parse_text
from .ir import SimulationIR
from .semantics import analyze


def compile_text(source: str, *, filename: str = "<input>") -> SimulationIR:
    return analyze(parse_text(source, filename=filename))


def compile_file(path: Path) -> SimulationIR:
    return analyze(parse_file(path))
