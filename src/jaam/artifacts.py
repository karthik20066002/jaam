from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import uuid

from . import __version__
from .compiler import CompilationResult
from .emitter import emit_meep_config, emit_palace_config, emit_python, emit_scuff_config
from .serialization import SCHEMA_VERSION, ir_to_dict


def create_run_artifact(
    root: Path, source: Path, result: CompilationResult
) -> tuple[Path, dict]:
    """Create a fresh run directory; existing solver output is never reused."""
    created = datetime.now(timezone.utc)
    run_id = f"{created:%Y%m%dT%H%M%S.%fZ}-{uuid.uuid4().hex[:8]}"
    # openEMS changes the process working directory while running. Always hand
    # the solver an absolute artifact path so that simulation and log files do
    # not move out from under the runtime.
    run_dir = (root / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)

    ir_text = json.dumps(ir_to_dict(result.ir), indent=2, sort_keys=True) + "\n"
    generated = emit_python(result.ir)
    palace_json = emit_palace_config(result.ir)
    meep_json = emit_meep_config(result.ir)
    scuff_json = emit_scuff_config(result.ir)
    (run_dir / "resolved-ir.json").write_text(ir_text, encoding="utf-8")
    (run_dir / "generated.py").write_text(generated, encoding="utf-8")
    (run_dir / "palace.json").write_text(palace_json, encoding="utf-8")
    (run_dir / "meep.json").write_text(meep_json, encoding="utf-8")
    (run_dir / "scuff.json").write_text(scuff_json, encoding="utf-8")
    cell_counts = [
        len(result.ir.mesh.lines_x) - 1,
        len(result.ir.mesh.lines_y) - 1,
        len(result.ir.mesh.lines_z) - 1,
    ]
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "createdAt": created.isoformat(),
        "status": "prepared",
        "source": str(source.resolve()),
        "hashes": {
            "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "irSha256": hashlib.sha256(ir_text.encode()).hexdigest(),
            "generatedPythonSha256": hashlib.sha256(generated.encode()).hexdigest(),
            "palaceJsonSha256": hashlib.sha256(palace_json.encode()).hexdigest(),
            "meepJsonSha256": hashlib.sha256(meep_json.encode()).hexdigest(),
            "scuffJsonSha256": hashlib.sha256(scuff_json.encode()).hexdigest(),
        },
        "versions": {"jaam": __version__, "python": platform.python_version()},
        "compiler": {
            "durationNs": result.duration_ns,
            "passes": [asdict(item) for item in result.passes],
        },
        "mesh": {
            "plannedCells": cell_counts,
            "plannedTotalCells": cell_counts[0] * cell_counts[1] * cell_counts[2],
            "cells": cell_counts,
            "totalCells": cell_counts[0] * cell_counts[1] * cell_counts[2],
        },
        "outputs": {
            "ir": "resolved-ir.json",
            "python": "generated.py",
            "palace": "palace.json",
            "meep": "meep.json",
            "scuff": "scuff.json",
            "solverLog": "solver.log.jsonl",
        },
    }
    write_manifest(run_dir, manifest)
    return run_dir, manifest


def write_manifest(run_dir: Path, manifest: dict) -> None:
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
