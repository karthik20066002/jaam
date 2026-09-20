from __future__ import annotations

from dataclasses import dataclass
import json
import sys
from typing import Iterable, TextIO

from .model import SourceSpan


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    message: str
    span: SourceSpan
    severity: str = "error"

    def as_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "file": self.span.file,
            "line": self.span.line,
            "column": self.span.column,
            "endLine": self.span.end_line,
            "endColumn": self.span.end_column,
        }


class CompilationError(Exception):
    def __init__(self, diagnostics: Iterable[Diagnostic]):
        self.diagnostics = tuple(diagnostics)
        super().__init__("compilation failed")


def render_diagnostics(
    diagnostics: Iterable[Diagnostic], *, fmt: str = "human", stream: TextIO | None = None
) -> None:
    stream = stream or sys.stderr
    items = tuple(diagnostics)
    if fmt == "json":
        json.dump([item.as_dict() for item in items], stream, indent=2)
        stream.write("\n")
        return
    for item in items:
        span = item.span
        print(
            f"{span.file}:{span.line}:{span.column}: {item.severity} "
            f"{item.code}: {item.message}",
            file=stream,
        )
