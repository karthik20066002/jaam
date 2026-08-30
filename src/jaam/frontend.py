from __future__ import annotations

from pathlib import Path

from antlr4 import CommonTokenStream, FileStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .diagnostics import CompilationError, Diagnostic
from .grammar.generated.JAAMLexer import JAAMLexer
from .grammar.generated.JAAMParser import JAAMParser
from .grammar.generated.JAAMVisitor import JAAMVisitor
from .model import (
    Argument,
    CallExpr,
    DefaultBlock,
    Directive,
    IdentifierExpr,
    NumberExpr,
    PrimitiveDecl,
    Program,
    SourceSpan,
    TupleExpr,
)


def _span(ctx, filename: str) -> SourceSpan:
    start = ctx.start
    stop = ctx.stop or start
    width = max(1, len(stop.text or ""))
    return SourceSpan(
        filename,
        start.line,
        start.column + 1,
        stop.line,
        stop.column + width + 1,
    )


class _SyntaxErrors(ErrorListener):
    def __init__(self, filename: str):
        self.filename = filename
        self.items: list[Diagnostic] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):  # noqa: N802
        width = max(1, len(getattr(offendingSymbol, "text", "") or ""))
        self.items.append(
            Diagnostic(
                "J001",
                msg,
                SourceSpan(self.filename, line, column + 1, line, column + width + 1),
            )
        )


class _AstBuilder(JAAMVisitor):
    def __init__(self, filename: str):
        self.filename = filename

    def visitProgram(self, ctx):  # noqa: N802
        return Program(tuple(self.visit(item) for item in ctx.statement()))

    def visitStatement(self, ctx):  # noqa: N802
        return self.visit(ctx.getChild(0))

    def visitDefaultBlock(self, ctx):  # noqa: N802
        identifiers = ctx.IDENT()
        exprs = ctx.expr()
        target = identifiers[0].getText() if len(identifiers) == len(exprs) + 1 else None
        offset = 1 if target else 0
        values = tuple(
            (identifiers[index + offset].getText(), self.visit(expr))
            for index, expr in enumerate(exprs)
        )
        return DefaultBlock(target, values, _span(ctx, self.filename))

    def visitPrimitiveDecl(self, ctx):  # noqa: N802
        names = ctx.IDENT()
        args = tuple(self.visit(arg) for arg in ctx.args().arg()) if ctx.args() else ()
        return PrimitiveDecl(names[0].getText(), names[1].getText(), args, _span(ctx, self.filename))

    def visitDirective(self, ctx):  # noqa: N802
        return Directive(ctx.IDENT().getText(), self.visit(ctx.expr()), _span(ctx, self.filename))

    def visitArg(self, ctx):  # noqa: N802
        name = ctx.IDENT().getText() if ctx.IDENT() else None
        return Argument(name, self.visit(ctx.expr()), _span(ctx, self.filename))

    def visitExpr(self, ctx):  # noqa: N802
        return self.visit(ctx.getChild(0))

    def visitTuple(self, ctx):  # noqa: N802
        return TupleExpr(tuple(self.visit(expr) for expr in ctx.expr()), _span(ctx, self.filename))

    def visitCall(self, ctx):  # noqa: N802
        args = tuple(self.visit(arg) for arg in ctx.args().arg()) if ctx.args() else ()
        return CallExpr(ctx.IDENT().getText(), args, _span(ctx, self.filename))

    def visitTerminal(self, node):  # noqa: N802
        token = node.symbol
        span = SourceSpan(
            self.filename,
            token.line,
            token.column + 1,
            token.line,
            token.column + len(token.text) + 1,
        )
        if token.type == JAAMLexer.NUMBER:
            return NumberExpr(token.text, span)
        if token.type == JAAMLexer.IDENT:
            return IdentifierExpr(token.text, span)
        return node.getText()


def parse_text(text: str, *, filename: str = "<input>") -> Program:
    lexer = JAAMLexer(InputStream(text))
    errors = _SyntaxErrors(filename)
    lexer.removeErrorListeners()
    lexer.addErrorListener(errors)
    parser = JAAMParser(CommonTokenStream(lexer))
    parser.removeErrorListeners()
    parser.addErrorListener(errors)
    tree = parser.program()
    if errors.items:
        raise CompilationError(errors.items)
    result = _AstBuilder(filename).visit(tree)
    return Program(result.statements, Path(filename) if filename != "<input>" else None)


def parse_file(path: Path) -> Program:
    return parse_text(path.read_text(encoding="utf-8"), filename=str(path))
