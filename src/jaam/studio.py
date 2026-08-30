from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
import sys
from time import monotonic

from .compiler import CompilationResult, compile_text_result
from .diagnostics import CompilationError, Diagnostic


STARTER_SOURCE = """frequency 1GHz;
boundary free_space;
default { material: copper; radius: 1mm; }
wire dipole(
    path: line(from: (0, 0, -71mm), to: (0, 0, 71mm)),
    feed: port(impedance: 50ohm)
);
"""


@dataclass(slots=True)
class StudioState:
    source_path: Path | None = None
    source_text: str = STARTER_SOURCE
    compilation: CompilationResult | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    selected_primitive: str | None = None
    active_plane: str = "xy"
    slice_coordinate: float = 0.0
    presentation_mode: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False)
    last_edit: float = field(default_factory=monotonic)

    @classmethod
    def open(cls, path: Path | None) -> "StudioState":
        if path is None:
            state = cls()
        else:
            state = cls(path, path.read_text(encoding="utf-8"))
        state.compile_now()
        return state

    def compile_now(self) -> bool:
        try:
            self.compilation = compile_text_result(
                self.source_text, filename=str(self.source_path or "<studio>")
            )
            self.diagnostics = self.compilation.diagnostics
            return True
        except CompilationError as exc:
            self.compilation = None
            self.diagnostics = exc.diagnostics
            return False

    def save(self) -> None:
        if self.source_path is None:
            raise ValueError("choose a source path before saving")
        self.source_path.write_text(self.source_text, encoding="utf-8")

    def start_run(self, output_root: Path = Path("jaam-out")) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("a solver run is already active")
        if self.source_path is None:
            raise ValueError("save the source before running openEMS")
        self.save()
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "jaam.cli",
                "run",
                str(self.source_path),
                "--output-dir",
                str(output_root / self.source_path.stem),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def cancel_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


def launch(path: Path | None = None) -> None:
    try:
        from imgui_bundle import imgui, immapp
    except ImportError as exc:
        raise RuntimeError("JAAM Studio requires: uv sync --extra studio") from exc

    state = StudioState.open(path)

    def gui() -> None:
        imgui.dock_space_over_viewport()
        io = imgui.get_io()
        compile_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.b)
        run_requested = imgui.is_key_pressed(imgui.Key.f5)
        save_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.s)
        imgui.begin("JAAM Source")
        changed, text = imgui.input_text_multiline(
            "##source", state.source_text, imgui.ImVec2(-1, -1)
        )
        if changed:
            state.source_text = text
            state.last_edit = monotonic()
        imgui.end()

        imgui.begin("Build")
        if imgui.button("Compile  Ctrl+B") or compile_requested:
            state.compile_now()
        imgui.same_line()
        if imgui.button("Run  F5") or run_requested:
            try:
                state.start_run()
            except (ValueError, RuntimeError) as exc:
                state.diagnostics = (
                    Diagnostic("J901", str(exc), state.diagnostics[0].span if state.diagnostics else _unknown_span()),
                )
        imgui.same_line()
        if imgui.button("Cancel"):
            state.cancel_run()
        if save_requested and state.source_path is not None:
            state.save()
        _, state.presentation_mode = imgui.checkbox("Presentation mode", state.presentation_mode)
        if state.compilation:
            for compiler_pass in state.compilation.passes:
                imgui.text(f"{compiler_pass.name}: {compiler_pass.duration_ns / 1e6:.3f} ms")
        for diagnostic in state.diagnostics:
            imgui.text_colored((1.0, 0.35, 0.25, 1.0), f"{diagnostic.code}: {diagnostic.message}")
        imgui.end()

        imgui.begin("Geometry / Mesh")
        if state.compilation:
            ir = state.compilation.ir
            imgui.text(f"Primitives: {len(ir.geometry)}")
            imgui.text(f"Projection: {state.active_plane.upper()}")
            imgui.text(
                f"Mesh: {len(ir.mesh.lines_x)-1} x {len(ir.mesh.lines_y)-1} x {len(ir.mesh.lines_z)-1}"
            )
            for op in ir.geometry:
                selected, _ = imgui.selectable(op.name, state.selected_primitive == op.name)
                if selected:
                    state.selected_primitive = op.name
        imgui.end()

        if changed is False and monotonic() - state.last_edit > 0.35:
            # Debounced checking; reset the timer far into the future until the next edit.
            state.compile_now()
            state.last_edit = float("inf")

    immapp.run(gui_function=gui, window_title="JAAM Studio", window_size=(1440, 900))


def _unknown_span():
    from .model import SourceSpan

    return SourceSpan.unknown("<studio>")
