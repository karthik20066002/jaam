import pytest

from jaam.diagnostics import CompilationError
from jaam.frontend import parse_text
from jaam.model import DefaultBlock, PrimitiveDecl


def test_parses_defaults_comments_and_wire():
    program = parse_text(
        """
        // comment
        default { material: copper; }
        /* block */ default wire { radius: 1mm; }
        wire dipole(path: line(from: (0, -1mm, 0), to: (0, 1mm, 0)));
        """
    )
    assert isinstance(program.statements[0], DefaultBlock)
    assert program.statements[0].target is None
    assert isinstance(program.statements[1], DefaultBlock)
    assert program.statements[1].target == "wire"
    assert isinstance(program.statements[2], PrimitiveDecl)


def test_rejects_single_component_tuple():
    with pytest.raises(CompilationError):
        parse_text("wire x(path: line(from: (0), to: (0, 0, 0)));" )

