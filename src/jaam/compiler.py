from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter_ns

from .diagnostics import Diagnostic
from .frontend import parse_file, parse_text
from .ir import SimulationIR
from .model import PrimitiveDecl, Program, SourceSpan
from .passes import DEFAULT_PASSES, PassResult
from .semantics import analyze


@dataclass(frozen=True, slots=True)
class PassTrace:
    name: str
    duration_ns: int
    statistics: dict[str, int]


@dataclass(frozen=True, slots=True)
class CompilationResult:
    ast: Program
    ir: SimulationIR
    diagnostics: tuple[Diagnostic, ...]
    source_map: dict[str, SourceSpan]
    passes: tuple[PassTrace, ...]

    @property
    def duration_ns(self) -> int:
        return sum(item.duration_ns for item in self.passes)


def _compile(program: Program, parse_duration_ns: int) -> CompilationResult:
    passes = [PassTrace("parse", parse_duration_ns, {"statements": len(program.statements)})]

    def record(name: str, duration_ns: int, statistics: dict[str, int]) -> None:
        passes.append(PassTrace(name, duration_ns, statistics))

    ir = analyze(program, trace=record)

    diagnostics: list[Diagnostic] = []
    for pass_ in DEFAULT_PASSES:
        started = perf_counter_ns()
        result = pass_.run(ir)
        ir = result.ir
        diagnostics.extend(result.diagnostics)
        passes.append(PassTrace(pass_.name, perf_counter_ns() - started, result.statistics))
        if result.diagnostics:
            break

    declarations = {
        statement.name: statement.span
        for statement in program.statements
        if isinstance(statement, PrimitiveDecl)
    }
    source_map = {}
    for op in ir.geometry:
        declaration_name = op.name.rsplit("__", 1)[0]
        if declaration_name in declarations:
            source_map[op.name] = declarations[declaration_name]
    diagnostics.extend(
        Diagnostic("J900", warning, SourceSpan.unknown(str(program.source or "<input>")), "warning")
        for warning in ir.warnings
    )
    return CompilationResult(program, ir, tuple(diagnostics), source_map, tuple(passes))


def compile_text_result(source: str, *, filename: str = "<input>") -> CompilationResult:
    started = perf_counter_ns()
    program = parse_text(source, filename=filename)
    return _compile(program, perf_counter_ns() - started)


def compile_file_result(path: Path) -> CompilationResult:
    started = perf_counter_ns()
    program = parse_file(path)
    return _compile(program, perf_counter_ns() - started)


def compile_text(source: str, *, filename: str = "<input>") -> SimulationIR:
    return compile_text_result(source, filename=filename).ir


def compile_file(path: Path) -> SimulationIR:
    return compile_file_result(path).ir
