import pytest

from jaam.compiler import compile_text, compile_text_result
from jaam.frontend import parse_text
from jaam.passes import GradedMeshCoarseningPass, ValidateFeedsPass
from jaam.semantics import analyze


def test_graded_mesh_coarsening_reduces_far_field_cells():
    source = """
    frequency 1GHz;
    default { material: copper; radius: 1mm; }
    wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)), feed: port(impedance: 50ohm));
    """
    ir = analyze(parse_text(source))
    result = GradedMeshCoarseningPass().run(ir)
    assert result.statistics["new_cells"] < result.statistics["original_cells"]
    assert result.statistics["reduction_percent"] > 0
    # Geometry features should still be resolved.
    assert any(line == 0.0 for line in result.ir.mesh.lines_x)
    assert any(line == 0.0 for line in result.ir.mesh.lines_y)


def test_validate_feeds_pass_accepts_model_with_feed():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)), feed: port(impedance: 50ohm));
        """
    )
    result = ValidateFeedsPass().run(ir)
    assert result.ir is ir
    assert result.statistics["feeds"] == 1
    assert not result.diagnostics


def test_validate_feeds_pass_rejects_model_without_feed():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)));
        """
    )
    result = ValidateFeedsPass().run(ir)
    assert result.ir is ir
    assert result.statistics["feeds"] == 0
    assert any(item.code == "J201" for item in result.diagnostics)


def test_compiler_reports_missing_feed_diagnostic():
    result = compile_text_result(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)));
        """
    )
    assert any(item.code == "J201" for item in result.diagnostics)
