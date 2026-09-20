from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias


@dataclass(frozen=True, slots=True)
class SourceSpan:
    file: str
    line: int
    column: int
    end_line: int
    end_column: int

    @classmethod
    def unknown(cls, file: str = "<unknown>") -> "SourceSpan":
        return cls(file, 1, 1, 1, 1)


@dataclass(frozen=True, slots=True)
class NumberExpr:
    text: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class IdentifierExpr:
    name: str
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class TupleExpr:
    items: tuple[Expr, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Argument:
    name: str | None
    value: Expr
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class CallExpr:
    name: str
    args: tuple[Argument, ...]
    span: SourceSpan


Expr: TypeAlias = NumberExpr | IdentifierExpr | TupleExpr | CallExpr


@dataclass(frozen=True, slots=True)
class DefaultBlock:
    target: str | None
    values: tuple[tuple[str, Expr], ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class PrimitiveDecl:
    kind: str
    name: str
    args: tuple[Argument, ...]
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class Directive:
    name: str
    value: Expr
    span: SourceSpan


Statement: TypeAlias = DefaultBlock | PrimitiveDecl | Directive


@dataclass(frozen=True, slots=True)
class Program:
    statements: tuple[Statement, ...]
    source: Path | None = None

