from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import subprocess
import tempfile

from .container import ContainerEngine, ContainerUnavailableError, SOLVER_IMAGE


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def finale_checks() -> tuple[Check, ...]:
    checks = []
    solver_image_available = False
    for module, label in (("imgui_bundle", "ImGui Bundle"), ("pyvista", "PyVista"), ("vtk", "VTK")):
        available = importlib.util.find_spec(module) is not None
        checks.append(Check(label, available, "available" if available else "missing; install the studio extra"))
    try:
        engine = ContainerEngine.discover()
        checks.append(Check("container engine", True, engine.name))
        solver_image_available = engine.image_exists()
        checks.append(Check("pinned solver image", solver_image_available, SOLVER_IMAGE if solver_image_available else f"missing: {SOLVER_IMAGE}", required=False))
    except ContainerUnavailableError as exc:
        checks.append(Check("container engine", False, str(exc)))
        checks.append(Check("pinned solver image", False, "not checked", required=False))
    host = subprocess.run(
        ["/usr/bin/python3", "-c", "import CSXCAD, openEMS; print(CSXCAD.__version__, openEMS.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    native = host.returncode == 0
    checks.append(Check("host solver bindings", native, host.stdout.strip() if native else host.stderr.strip() or "unavailable"))
    checks.append(Check("solver execution", native or solver_image_available, "pinned container image" if solver_image_available else "host bindings" if native else "unavailable"))
    try:
        with tempfile.TemporaryDirectory(prefix="jaam-doctor-") as directory:
            probe = Path(directory) / "write-test"
            probe.write_text("ok", encoding="utf-8")
        checks.append(Check("artifact directory", True, "writable"))
    except OSError as exc:
        checks.append(Check("artifact directory", False, str(exc)))
    return tuple(checks)
