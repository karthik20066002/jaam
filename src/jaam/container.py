from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time

SOLVER_IMAGE = "localhost/jaam-openems:7706743cc33f"
PALACE_IMAGE = "localhost/jaam-palace:0.16"


class ContainerUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ContainerRunResult:
    csv_files: tuple[Path, ...]
    minimum_s11_db: tuple[float, ...]
    best_frequency_hz: tuple[float, ...]
    solver_duration_s: float
    peak_gain_db: float | None = None
    native_mesh_cells: tuple[int, int, int] = ()
    nf2ff_csv: Path | None = None
    farfield_vtp: Path | None = None


@dataclass(frozen=True, slots=True)
class ContainerEngine:
    executable: str

    @property
    def name(self) -> str:
        return Path(self.executable).name

    @classmethod
    def discover(cls) -> "ContainerEngine":
        for candidate in ("podman", "docker"):
            if executable := shutil.which(candidate):
                return cls(executable)
        raise ContainerUnavailableError("neither rootless Podman nor Docker is available")

    def image_exists(self, image: str = SOLVER_IMAGE) -> bool:
        completed = subprocess.run(
            [self.executable, "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0

    def build(self, repository: Path, image: str = SOLVER_IMAGE) -> None:
        subprocess.run(
            [self.executable, "build", "-t", image, "-f", "container/Containerfile", "."],
            cwd=repository,
            check=True,
        )

    def command(self, artifact_dir: Path, *command: str, image: str = SOLVER_IMAGE) -> list[str]:
        artifact_dir = artifact_dir.resolve()
        return [
            self.executable,
            "run",
            "--rm",
            "--network=none",
            "-v",
            f"{artifact_dir}:/work:Z",
            image,
            *command,
        ]

    def solve_command(self, artifact_dir: Path, script: str = "generated.py") -> list[str]:
        """Build the podman run command to execute generated.py inside the openEMS container."""
        return [
            self.executable,
            "run",
            "--rm",
            "--network=none",
            "-v",
            f"{artifact_dir.resolve()}:/work:Z",
            SOLVER_IMAGE,
            "/opt/openEMS/venv/bin/python3",
            f"/work/{script}",
        ]

    def palace_command(self, artifact_dir: Path, image: str = PALACE_IMAGE) -> list[str]:
        """Run Palace on a prepared artifact directory (mesh.msh + palace.json)."""
        artifact_dir = artifact_dir.resolve()
        return [
            self.executable,
            "run",
            "--rm",
            "--network=none",
            "-v",
            f"{artifact_dir}:/work:Z",
            "-w",
            "/work",
            image,
            "--serial",
            "palace.json",
        ]

    def run(self, artifact_dir: Path, script: str = "generated.py") -> ContainerRunResult:
        """Execute generated.py inside the container and parse S11 results."""
        start = time.perf_counter()
        completed = subprocess.run(
            self.solve_command(artifact_dir, script),
            cwd=artifact_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        duration = time.perf_counter() - start

        out_dir = artifact_dir / "generated-out"
        # The generated program writes into generated-out/, but a run artifact
        # is deliberately flat: its manifest names outputs by basename and the
        # Studio loader resolves them from the artifact root. Materialize the
        # container results there before returning them to the CLI.
        csv_files = []
        for generated_path in sorted(out_dir.glob("port*_s11.csv")):
            artifact_path = artifact_dir / generated_path.name
            shutil.copy2(generated_path, artifact_path)
            csv_files.append(artifact_path)
        csv_files = tuple(csv_files)
        nf2ff_csv = None
        generated_nf2ff = out_dir / "nf2ff.csv"
        if generated_nf2ff.is_file():
            nf2ff_csv = artifact_dir / generated_nf2ff.name
            shutil.copy2(generated_nf2ff, nf2ff_csv)

        minima: list[float] = []
        best_freqs: list[float] = []
        for path in csv_files:
            with path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            if not rows:
                minima.append(float("inf"))
                best_freqs.append(0.0)
                continue
            db_values = [float(row["s11_db"]) for row in rows]
            freq_values = [float(row["frequency_hz"]) for row in rows]
            best_idx = min(range(len(db_values)), key=lambda i: db_values[i])
            minima.append(db_values[best_idx])
            best_freqs.append(freq_values[best_idx])

        return ContainerRunResult(
            csv_files=csv_files,
            minimum_s11_db=tuple(minima),
            best_frequency_hz=tuple(best_freqs),
            solver_duration_s=duration,
            nf2ff_csv=nf2ff_csv,
        )
