from pathlib import Path
import json

from jaam.cli import main
from jaam.runtime import RunResult


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


def test_inspect_command_human(capsys):
    assert main(["inspect", "examples/yagi.jaam"]) == 0
    output = capsys.readouterr().out
    assert "compiler passes:" in output
    assert "domain-and-mesh-construction" in output


def test_inspect_command_json(capsys):
    assert main(["inspect", "examples/yagi.jaam", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == 1
    assert payload["ir"]["geometry"]


def test_run_creates_a_new_timestamped_artifact(monkeypatch, tmp_path, capsys):
    def fake_run(ir, output_dir):
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path)]) == 0
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path)]) == 0
    runs = sorted(tmp_path.iterdir())
    assert len(runs) == 2
    manifests = [json.loads((run / "manifest.json").read_text()) for run in runs]
    assert all(item["status"] == "complete" for item in manifests)
    assert manifests[0]["runId"] != manifests[1]["runId"]
    assert "run " in capsys.readouterr().out
