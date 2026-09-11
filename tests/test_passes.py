import pytest

from jaam.compiler import compile_text, compile_text_result
from jaam.passes import ValidateFeedsPass


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
