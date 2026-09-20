from __future__ import annotations

from pathlib import Path

from jaam.ir import SimulationIR

from .common import BACKENDS, DEFAULT_BACKEND, NativeDependencyError, RunResult


def run_simulation(
    ir: SimulationIR,
    output_dir: Path,
    *,
    farfield: bool | str = True,
    backend: str = DEFAULT_BACKEND,
) -> RunResult:
    name = backend.lower()
    if name == "openems":
        from .openems import run_openems

        return run_openems(ir, output_dir, farfield=farfield)
    if name == "palace":
        from .palace import run_palace

        return run_palace(ir, output_dir, farfield=farfield)
    if name == "meep":
        from .meep import run_meep

        return run_meep(ir, output_dir, farfield=farfield)
    if name == "scuff":
        from .scuff import run_scuff

        return run_scuff(ir, output_dir, farfield=farfield)
    raise NativeDependencyError(f"unknown solver backend {backend!r}; expected one of {BACKENDS}")
