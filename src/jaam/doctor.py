from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import subprocess
import tempfile

from .container import ContainerEngine, ContainerUnavailableError, PALACE_IMAGE, SOLVER_IMAGE


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def finale_checks() -> tuple[Check, ...]:
    checks = []
    solver_image_available = False
    palace_image_available = False
    for module, label in (("imgui_bundle", "ImGui Bundle"), ("pyvista", "PyVista"), ("vtk", "VTK")):
        available = importlib.util.find_spec(module) is not None
        checks.append(Check(label, available, "available" if available else "missing; install the studio extra"))
    try:
        engine = ContainerEngine.discover()
        checks.append(Check("container engine", True, engine.name))
        solver_image_available = engine.image_exists()
        checks.append(Check("pinned solver image", solver_image_available, SOLVER_IMAGE if solver_image_available else f"missing: {SOLVER_IMAGE}", required=False))
        palace_image_available = engine.image_exists(PALACE_IMAGE)
        checks.append(Check("Palace container image", palace_image_available, PALACE_IMAGE if palace_image_available else f"missing: {PALACE_IMAGE}", required=False))
    except ContainerUnavailableError as exc:
        checks.append(Check("container engine", False, str(exc)))
        checks.append(Check("pinned solver image", False, "not checked", required=False))
        checks.append(Check("Palace container image", False, "not checked", required=False))
    host = subprocess.run(
        ["/usr/bin/python3", "-c", "import CSXCAD, openEMS; print(CSXCAD.__version__, openEMS.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    native = host.returncode == 0
    checks.append(Check("openEMS host bindings", native, host.stdout.strip() if native else host.stderr.strip() or "unavailable", required=False))
    palace = subprocess.run(["sh", "-c", "command -v palace"], capture_output=True, text=True, check=False)
    checks.append(Check("Palace executable", palace.returncode == 0, palace.stdout.strip() or "not on PATH", required=False))
    gmsh = importlib.util.find_spec("gmsh") is not None
    checks.append(Check("Gmsh Python", gmsh, "available" if gmsh else "missing; needed for Palace meshes", required=False))
    meep = importlib.util.find_spec("meep") is not None
    checks.append(Check("Meep Python", meep, "available" if meep else "missing; conda-forge meep or a system package", required=False))
    scuff = subprocess.run(["sh", "-c", "command -v scuff-rf"], capture_output=True, text=True, check=False)
    scuff_fallback = Path("/home/axiss/scuff-em/applications/scuff-rf/scuff-rf")
    scuff_ok = scuff.returncode == 0 or scuff_fallback.is_file()
    if scuff.returncode == 0:
        scuff_detail = scuff.stdout.strip()
    elif scuff_ok:
        scuff_detail = str(scuff_fallback)
    else:
        scuff_detail = "not on PATH"
    checks.append(Check("SCUFF-EM scuff-rf", scuff_ok, scuff_detail, required=False))
    checks.append(
        Check(
            "solver execution",
            native or solver_image_available or palace.returncode == 0 or palace_image_available or meep or scuff_ok,
            "openEMS, Palace, Meep, or SCUFF",
        )
    )
    try:
        with tempfile.TemporaryDirectory(prefix="jaam-doctor-") as directory:
            probe = Path(directory) / "write-test"
            probe.write_text("ok", encoding="utf-8")
        checks.append(Check("artifact directory", True, "writable"))
    except OSError as exc:
        checks.append(Check("artifact directory", False, str(exc)))
    return tuple(checks)
