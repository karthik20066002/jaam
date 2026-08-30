from pathlib import Path

import pytest

pytest.importorskip("CSXCAD")
pytest.importorskip("openEMS")

from jaam.compiler import compile_file, compile_text
from jaam.runtime import build_native


def test_yagi_constructs_with_native_bindings():
    ir = compile_file(Path("examples/yagi.jaam"))
    csx, _, ports = build_native(ir)
    assert csx.GetQtyProperties() == 5
    assert csx.GetQtyPrimitives() >= len(ir.geometry)
    assert len(ports) == 1
    assert csx.GetGrid().IsValid()


def test_revolve_constructs_with_native_bindings():
    ir = compile_text(
        "frequency 1GHz; default { material:copper; } "
        "wire p(path:line(from:(1cm,0,0),to:(2cm,1cm,0)),radius:1mm); "
        "revolve dish(seed:p,axis:z);"
    )
    csx, fdtd, ports = build_native(ir)
    assert csx.GetQtyPrimitives() == 1
    assert fdtd is not None
    assert ports == []
