import ast
from pathlib import Path

from jaam.compiler import compile_file
from jaam.emitter import emit_python


def test_generated_python_is_deterministic_and_valid():
    ir = compile_file(Path("examples/yagi.jaam"))
    first = emit_python(ir)
    second = emit_python(ir)
    assert first == second
    ast.parse(first)
    assert "AddLumpedPort" in first
    assert "CreateNF2FFBox" in first
    assert '"nf2ff.csv"' in first
    assert "port1_s11.csv" not in first  # filename remains parameterized by port index
