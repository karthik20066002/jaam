import json

from jaam.cli import main
from jaam.runtime import NativeDependencyError, RunResult


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
    def fake_run(ir, output_dir, **kwargs):
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        nf2ff = output_dir / "nf2ff.csv"
        farfield = output_dir / "farfield.vtp"
        nf2ff.write_text("frequency_hz,theta_deg,phi_deg,gain_db\n")
        farfield.write_text("<VTKFile/>")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25, nf2ff, farfield, 2.1)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: False)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path)]) == 0
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path)]) == 0
    runs = sorted(tmp_path.iterdir())
    assert len(runs) == 2
    manifests = [json.loads((run / "manifest.json").read_text()) for run in runs]
    assert all(item["status"] == "complete" for item in manifests)
    assert manifests[0]["runId"] != manifests[1]["runId"]
    assert all(item["outputs"]["farfield"] == "farfield.vtp" for item in manifests)
    assert all(item["solver"]["peakGainDb"] == 2.1 for item in manifests)
    assert "run " in capsys.readouterr().out


def test_no_farfield_run_records_s11_only(monkeypatch, tmp_path):
    seen = []

    def fake_run(ir, output_dir, *, farfield=True, backend="openems"):
        seen.append((farfield, backend))
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: False)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path), "--no-farfield"]) == 0
    manifest = json.loads((next(tmp_path.iterdir()) / "manifest.json").read_text())
    assert seen == [("off", "openems")]
    assert manifest["outputs"]["ports"] == ["port1_s11.csv"]
    assert "nf2ff" not in manifest["outputs"]


def test_run_forwards_palace_backend(monkeypatch, tmp_path):
    seen = []

    def fake_run(ir, output_dir, *, farfield=True, backend="openems"):
        seen.append(backend)
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: False)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path), "--backend", "palace"]) == 0
    assert seen == ["palace"]


def test_run_forwards_meep_backend(monkeypatch, tmp_path):
    seen = []

    def fake_run(ir, output_dir, *, farfield=True, backend="openems"):
        seen.append(backend)
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: False)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path), "--backend", "meep"]) == 0
    assert seen == ["meep"]


def test_compile_meep_writes_json(tmp_path):
    output = tmp_path / "yagi.meep.json"
    assert main(["compile", "examples/yagi.jaam", "--backend", "meep", "-o", str(output)]) == 0
    text = output.read_text()
    assert '"cylinders"' in text
    assert '"component": "y"' in text


def test_run_forwards_scuff_backend(monkeypatch, tmp_path):
    seen = []

    def fake_run(ir, output_dir, *, farfield=True, backend="openems"):
        seen.append(backend)
        csv_path = output_dir / "port1_s11.csv"
        csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
        return RunResult((csv_path,), (-10.0,), (1.0,), 0.25)

    monkeypatch.setattr("jaam.cli.run_simulation", fake_run)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: False)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path), "--backend", "scuff"]) == 0
    assert seen == ["scuff"]


def test_compile_scuff_writes_json(tmp_path):
    output = tmp_path / "yagi.scuff.json"
    assert main(["compile", "examples/yagi.jaam", "--backend", "scuff", "-o", str(output)]) == 0
    assert "driven__a" in output.read_text()


def test_compile_palace_writes_json(tmp_path):
    output = tmp_path / "yagi.json"
    assert main(["compile", "examples/yagi.jaam", "--backend", "palace", "-o", str(output)]) == 0
    text = output.read_text()
    assert '"Type": "Driven"' in text
    assert "LumpedPort" in text


def test_container_is_used_only_if_native_solver_is_unavailable(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise NativeDependencyError("not installed")

    csv_path = tmp_path / "port1_s11.csv"
    csv_path.write_text("frequency_hz,s11_db\n1,-10\n")
    fallback = RunResult((csv_path,), (-10.0,), (1.0,), 0.25)
    monkeypatch.setattr("jaam.cli.run_simulation", unavailable)
    monkeypatch.setattr("jaam.cli.ContainerEngine.image_exists", lambda self, image=None: True)
    monkeypatch.setattr("jaam.cli.ContainerEngine.run", lambda self, output_dir: fallback)
    assert main(["run", "examples/yagi.jaam", "--output-dir", str(tmp_path / "runs")]) == 0
