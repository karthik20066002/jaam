from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess

SOLVER_IMAGE = "localhost/jaam-openems:7706743cc33f"


class ContainerUnavailableError(RuntimeError):
    pass


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
