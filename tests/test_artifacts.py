import json
from pathlib import Path

from jaam.artifacts import create_run_artifact
from jaam.compiler import compile_file_result


def test_run_artifacts_are_versioned_complete_and_unique(tmp_path):
    source = Path("examples/yagi.jaam")
    result = compile_file_result(source)
    first, manifest = create_run_artifact(tmp_path, source, result)
    second, _ = create_run_artifact(tmp_path, source, result)

    assert first != second
    assert first.is_absolute()
    assert manifest["schemaVersion"] == 1
    assert manifest["mesh"]["totalCells"] > 0
    assert len(manifest["hashes"]["sourceSha256"]) == 64
    assert (first / "generated.py").read_text().startswith("#!/usr/bin/env python3")
    assert '"Type": "Driven"' in (first / "palace.json").read_text()
    assert '"cylinders"' in (first / "meep.json").read_text()
    assert "driven__a" in (first / "scuff.json").read_text()
    persisted = json.loads((first / "manifest.json").read_text())
    assert persisted["runId"] == first.name
    assert json.loads((first / "resolved-ir.json").read_text())["geometry"]
