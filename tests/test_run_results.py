import csv
import json

import pytest

from jaam.run_results import load_run_results
from jaam.studio import StudioState


def _artifact(tmp_path, status="complete"):
    directory = tmp_path / "run-1"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps({
        "runId": "run-1", "status": status,
        "outputs": {"ports": ["port1_s11.csv"], "nf2ff": "nf2ff.csv"},
    }))
    with (directory / "port1_s11.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("frequency_hz", "s11_db", "vswr", "resistance_ohm", "reactance_ohm"))
        writer.writerow((1e9, -10, 2, 45, 3))
    (directory / "nf2ff.csv").write_text(
        "frequency_hz,theta_deg,phi_deg,gain_db\n1000000000,90,0,2\n"
    )
    return directory


def test_studio_loads_results_from_completed_manifest(tmp_path):
    directory = _artifact(tmp_path)
    state = StudioState.open(None)
    state.load_artifact(directory)
    assert state.run_status == "complete"
    assert state.run_results.manifest["runId"] == "run-1"
    assert state.run_results.ports[0][0].resistance_ohm == 45
    assert state.radiation.peak_gain_db == 2
    assert state.active_visual == "s11"


def test_incomplete_manifest_cannot_be_shown_as_results(tmp_path):
    directory = _artifact(tmp_path, status="failed")
    with pytest.raises(ValueError, match="failed"):
        load_run_results(directory)


def test_studio_ignores_csv_paths_in_solver_log(tmp_path):
    state = StudioState.open(None)
    state._log_queue.put("port 1: min S11 -10 dB; /tmp/old/port1_s11.csv")
    state.poll_solver_log()
    assert state.artifact_dir is None
    assert state.run_results is None


def test_studio_finishes_run_from_announced_manifest(tmp_path):
    directory = _artifact(tmp_path)
    state = StudioState.open(None)

    class Done:
        returncode = 0

        def poll(self):
            return 0

    state.process = Done()
    state._log_queue.put(f"artifact: {directory}")
    state.poll_solver_log()
    assert state.run_status == "complete"
    assert state.run_results.directory == directory.resolve()


def test_cancelled_run_marks_prepared_manifest(tmp_path):
    directory = _artifact(tmp_path, status="prepared")
    state = StudioState.open(None)

    class Cancelled:
        returncode = -15

        def poll(self):
            return -15

    state.process = Cancelled()
    state._cancel_requested = True
    state._log_queue.put(f"artifact: {directory}")
    state.poll_solver_log()
    assert state.run_status == "cancelled"
    assert json.loads((directory / "manifest.json").read_text())["status"] == "cancelled"
