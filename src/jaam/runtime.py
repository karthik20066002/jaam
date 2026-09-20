"""Solver dispatch. Backends live in jaam.backends."""

from __future__ import annotations

from .backends import BACKENDS, DEFAULT_BACKEND, NativeDependencyError, RunResult, run_simulation
from .backends.openems import build_native

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "NativeDependencyError",
    "RunResult",
    "build_native",
    "run_simulation",
]
