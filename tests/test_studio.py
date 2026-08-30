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
