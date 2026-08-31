from pathlib import Path

from jaam.cli import main
from jaam.studio import StudioState


def test_studio_state_compiles_and_saves(tmp_path):
    path = tmp_path / "dipole.jaam"
    state = StudioState.open(None)
    assert state.compilation is not None
    state.source_path = path
    state.save()
    assert path.read_text() == state.source_text

    state.source_text = "frequency nope;"
    assert not state.compile_now()
    assert state.diagnostics[0].code.startswith("J")


def test_studio_cli_delegates_to_launcher(monkeypatch, tmp_path):
    source = tmp_path / "model.jaam"
    source.write_text("frequency 1GHz;")
    seen = []
    monkeypatch.setattr("jaam.studio.launch", lambda path: seen.append(path))
    assert main(["studio", str(source)]) == 0
    assert seen == [source]


def test_solver_log_polling_is_non_blocking():
    state = StudioState.open(None)
    state._log_queue.put("iteration 100")
    state._log_queue.put("iteration 200")
    assert state.poll_solver_log() == ("iteration 100", "iteration 200")
    assert state.poll_solver_log() == ()
    assert state.solver_log == ["iteration 100", "iteration 200"]


def test_solver_uses_system_python_with_repository_on_path(monkeypatch, tmp_path):
    source = tmp_path / "dipole.jaam"
    state = StudioState.open(None)
    state.source_path = source
    calls = []

    class Process:
        stdout = ()

        def poll(self):
            return 0

    monkeypatch.setattr("jaam.studio.subprocess.Popen", lambda command, **options: calls.append((command, options)) or Process())
    state.start_run(tmp_path / "runs")
    command, options = calls[0]
    assert command[:3] == ["/usr/bin/python3", "-m", "jaam.cli"]
    assert command[3:5] == ["run", str(source)]
    assert options["cwd"] == Path(__file__).resolve().parents[1]
    assert options["env"]["PYTHONPATH"].split(":")[0].endswith("/src")
