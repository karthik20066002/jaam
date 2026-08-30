from pathlib import Path

from jaam.cli import main


def test_check_command(capsys):
    assert main(["check", "examples/yagi.jaam"]) == 0
    assert "check succeeded" in capsys.readouterr().out


def test_compile_command(tmp_path):
    output = tmp_path / "yagi.py"
    assert main(["compile", "examples/yagi.jaam", "-o", str(output)]) == 0
    assert output.read_text().startswith("#!/usr/bin/env python3")


def test_json_diagnostics(capsys, tmp_path):
    source = tmp_path / "bad.jaam"
    source.write_text("frequency nope;")
    assert main(["check", str(source), "--format", "json"]) == 1
    assert '"code"' in capsys.readouterr().err

