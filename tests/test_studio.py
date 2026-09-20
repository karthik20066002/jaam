from pathlib import Path

from jaam.studio import STARTER_SOURCE, StudioState, _nearest_polar_sample


def test_polar_hover_reports_pattern_sample_instead_of_cursor_radius() -> None:
    angles = (-180.0, -90.0, 0.0, 90.0, 180.0)
    gains = (-4.0, 1.5, 2.13, 1.5, -4.0)

    assert _nearest_polar_sample(1.51, angles, gains) == (0.0, 2.13)
    assert _nearest_polar_sample(-92.0, angles, gains) == (-90.0, 1.5)


def test_native_picker_failure_falls_back_to_in_app_dialog(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "model.jaam"
    path.write_text(STARTER_SOURCE, encoding="utf-8")
    state = StudioState.open(path)

    def boom(*_args, **_kwargs):
        raise RuntimeError("no zenity")

    monkeypatch.setattr("jaam.studio.start_native_file_dialog", boom)
    state.request_open_dialog()
    assert state.pending_popup == "Open Model"
    assert state._native_dialog is None

    state.request_save_as_dialog()
    assert state.pending_popup == "Save As"


def test_native_save_result_writes_file(tmp_path: Path) -> None:
    state = StudioState.open(None)
    dest = tmp_path / "out"
    state.apply_native_dialog_result("save", str(dest))
    saved = dest.with_suffix(".jaam")
    assert state.source_path == saved
    assert saved.read_text(encoding="utf-8") == STARTER_SOURCE


def test_native_open_result_loads_file(tmp_path: Path) -> None:
    path = tmp_path / "antenna.jaam"
    path.write_text("frequency 900MHz;\n", encoding="utf-8")
    state = StudioState.open(None)
    state.apply_native_dialog_result("open", [str(path)])
    assert state.source_path == path
    assert state.source_text == "frequency 900MHz;\n"
