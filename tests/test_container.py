from pathlib import Path

from jaam.compiler import compile_file
from jaam.container import ContainerEngine, SOLVER_IMAGE
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


def test_finale_doctor_returns_named_checks(monkeypatch):
    monkeypatch.setattr("jaam.doctor.ContainerEngine.discover", classmethod(lambda cls: ContainerEngine("true")))
    names = {check.name for check in finale_checks()}
    assert {"ImGui Bundle", "VTK", "container engine", "pinned solver image", "artifact directory"} <= names
