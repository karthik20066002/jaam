from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TypeAlias

from .diagnostics import Diagnostic
from .ir import CurveOp, SimulationIR, WireOp
from .model import SourceSpan


@dataclass(frozen=True, slots=True)
class PassResult:
    """Result of running a single IR-to-IR pass."""

    ir: SimulationIR
    diagnostics: tuple[Diagnostic, ...] = ()
    warnings: tuple[str, ...] = ()
    statistics: dict[str, int] = field(default_factory=dict)


class Pass(ABC):
    """Base class for explicit IR-to-IR transform or validation passes."""

    name: str

    @abstractmethod
    def run(self, ir: SimulationIR) -> PassResult:
        """Run the pass and return the transformed IR plus any diagnostics."""


PassList: TypeAlias = tuple[Pass, ...]


class ValidateFeedsPass(Pass):
    """Ensure at least one feed port exists after geometry lowering."""

    name = "validate-feeds"

    def run(self, ir: SimulationIR) -> PassResult:
        feeds = sum(
            1
            for op in ir.geometry
            if isinstance(op, (CurveOp, WireOp)) and op.feed is not None
        )
        if feeds == 0:
            diagnostic = Diagnostic(
                "J201",
                "at least one feed port is required for S11 simulation",
                SourceSpan.unknown("<input>"),
            )
            return PassResult(
                ir,
                diagnostics=(diagnostic,),
                statistics={"feeds": 0},
            )
        return PassResult(ir, statistics={"feeds": feeds})


DEFAULT_PASSES: PassList = (ValidateFeedsPass(),)
