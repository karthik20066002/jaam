from pathlib import Path

from jaam.compiler import compile_file
from jaam.container import PALACE_IMAGE, ContainerEngine, SOLVER_IMAGE
from jaam.doctor import finale_checks


def test_dipole_example_compiles_with_one_feed():
    ir = compile_file(Path("examples/dipole.jaam"))
    assert len(ir.geometry) == 2
    assert sum(getattr(op, "feed", None) is not None for op in ir.geometry) == 1


def test_container_command_is_offline_and_mounts_artifacts(tmp_path):
    command = ContainerEngine("podman").command(tmp_path, "python3", "generated.py")
    assert command[:4] == ["podman", "run", "--rm", "--network=none"]
    assert f"{tmp_path.resolve()}:/work:Z" in command
    assert SOLVER_IMAGE in command


def test_container_run_materializes_port_results_in_artifact_root(monkeypatch, tmp_path):
    generated = tmp_path / "generated-out"
    generated.mkdir()
    (generated / "port1_s11.csv").write_text(
        "frequency_hz,s11_db\n1000000000,-10\n", encoding="utf-8"
    )
    (generated / "nf2ff.csv").write_text(
        "frequency_hz,theta_deg,phi_deg,gain_db\n1000000000,90,0,2\n", encoding="utf-8"
    )

    class Completed:
        returncode = 0

    monkeypatch.setattr("jaam.container.subprocess.run", lambda *args, **kwargs: Completed())
    result = ContainerEngine("podman").run(tmp_path)
    assert result.csv_files == (tmp_path / "port1_s11.csv",)
    assert result.csv_files[0].read_text(encoding="utf-8").endswith("-10\n")
    assert result.nf2ff_csv == tmp_path / "nf2ff.csv"


def test_solve_command_uses_venv_python_and_mounts_artifacts(tmp_path):
    command = ContainerEngine("podman").solve_command(tmp_path)
    assert command[:4] == ["podman", "run", "--rm", "--network=none"]
    assert f"{tmp_path.resolve()}:/work:Z" in command
    assert SOLVER_IMAGE in command
    assert "/opt/openEMS/venv/bin/python3" in command
    assert "/work/generated.py" in command


def test_palace_command_mounts_work_and_passes_config(tmp_path):
    command = ContainerEngine("podman").palace_command(tmp_path)
    assert command[:4] == ["podman", "run", "--rm", "--network=none"]
    assert f"{tmp_path.resolve()}:/work:Z" in command
    assert PALACE_IMAGE in command
    assert command[-2:] == ["--serial", "palace.json"]
    assert "-w" in command


def test_solve_command_accepts_custom_script(tmp_path):
    command = ContainerEngine("podman").solve_command(tmp_path, script="solve.py")
    assert "/work/solve.py" in command


def test_finale_doctor_returns_named_checks(monkeypatch):
    monkeypatch.setattr("jaam.doctor.ContainerEngine.discover", classmethod(lambda cls: ContainerEngine("true")))
    names = {check.name for check in finale_checks()}
    assert {
        "ImGui Bundle",
        "VTK",
        "container engine",
        "pinned solver image",
        "Palace container image",
        "artifact directory",
        "Palace executable",
        "Meep Python",
        "SCUFF-EM scuff-rf",
    } <= names
