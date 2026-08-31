from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
import os
import subprocess
import sys
from threading import Thread
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
    solver_log: list[str] = field(default_factory=list)
    _log_queue: Queue[str] = field(default_factory=Queue, repr=False)
    _reader: Thread | None = field(default=None, repr=False)
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
        repository = Path(__file__).resolve().parents[2]
        # openEMS is packaged for the host interpreter. Keep Studio itself in
        # uv, but deliberately execute simulations with the system Python.
        command = ["/usr/bin/python3", "-m", "jaam.cli"]
        environment = os.environ.copy()
        source_root = str(repository / "src")
        environment["PYTHONPATH"] = source_root + (
            os.pathsep + environment["PYTHONPATH"] if environment.get("PYTHONPATH") else ""
        )
        full_command = [
            *command,
            "run",
            str(self.source_path),
            "--output-dir",
            str(output_root / self.source_path.stem),
        ]
        self.solver_log.clear()
        self.solver_log.append("$ " + " ".join(full_command))
        self.process = subprocess.Popen(
            full_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=repository,
            env=environment,
        )
        self._reader = Thread(target=self._read_solver_output, daemon=True)
        self._reader.start()

    def _read_solver_output(self) -> None:
        if self.process is None or self.process.stdout is None:
            return
        for line in self.process.stdout:
            self._log_queue.put(line.rstrip())

    def poll_solver_log(self) -> tuple[str, ...]:
        fresh = []
        while True:
            try:
                fresh.append(self._log_queue.get_nowait())
            except Empty:
                break
        self.solver_log.extend(fresh)
        return tuple(fresh)

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
        state.poll_solver_log()
        io = imgui.get_io()
        width = max(float(io.display_size.x), 960.0)
        height = max(float(io.display_size.y), 640.0)
        margin = 12.0
        gap = 8.0
        left_width = width * (0.64 if not state.presentation_mode else 0.72)
        right_x = left_width + gap
        right_width = width - right_x - margin
        source_height = height * 0.68
        build_height = height * 0.43
        window_flags = imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_move

        compile_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.b, False)
        run_requested = imgui.is_key_pressed(imgui.Key.f5, False)
        save_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.s, False)

        imgui.set_next_window_pos(imgui.ImVec2(margin, margin), imgui.Cond_.always)
        imgui.set_next_window_size(
            imgui.ImVec2(left_width - margin, source_height - margin), imgui.Cond_.always
        )
        imgui.begin("JAAM Source", flags=window_flags)
        imgui.text_colored((0.30, 0.78, 1.0, 1.0), "JAAM STUDIO  /  SOURCE")
        imgui.same_line()
        imgui.text_disabled(str(state.source_path or "Untitled"))
        imgui.separator()
        changed, text = imgui.input_text_multiline(
            "##source", state.source_text, imgui.ImVec2(-1, -1)
        )
        if changed:
            state.source_text = text
            state.last_edit = monotonic()
        imgui.end()

        imgui.set_next_window_pos(imgui.ImVec2(margin, source_height + gap), imgui.Cond_.always)
        imgui.set_next_window_size(
            imgui.ImVec2(left_width - margin, height - source_height - gap - margin),
            imgui.Cond_.always,
        )
        imgui.begin("Solver Log", flags=window_flags)
        if not state.solver_log:
            imgui.text_disabled("No live run yet. Save the model and press F5.")
        for line in state.solver_log:
            imgui.text_unformatted(line)
        if state.process is not None:
            status = "running" if state.process.poll() is None else f"exited {state.process.returncode}"
            imgui.text(f"Solver: {status}")
        imgui.end()

        imgui.set_next_window_pos(imgui.ImVec2(right_x, margin), imgui.Cond_.always)
        imgui.set_next_window_size(
            imgui.ImVec2(right_width, build_height - margin), imgui.Cond_.always
        )
        imgui.begin("Build / Pass Trace", flags=window_flags)
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
        imgui.separator()
        if state.compilation:
            imgui.text_colored((0.35, 0.9, 0.5, 1.0), "COMPILE OK")
            for compiler_pass in state.compilation.passes:
                imgui.text(f"{compiler_pass.name}: {compiler_pass.duration_ns / 1e6:.3f} ms")
        for diagnostic in state.diagnostics:
            imgui.text_colored((1.0, 0.35, 0.25, 1.0), f"{diagnostic.code}: {diagnostic.message}")
        imgui.end()

        imgui.set_next_window_pos(imgui.ImVec2(right_x, build_height + gap), imgui.Cond_.always)
        imgui.set_next_window_size(
            imgui.ImVec2(right_width, height - build_height - gap - margin), imgui.Cond_.always
        )
        imgui.begin("Geometry / Mesh", flags=window_flags)
        if state.compilation:
            ir = state.compilation.ir
            imgui.text_colored((0.30, 0.78, 1.0, 1.0), f"{state.active_plane.upper()} PROJECTION")
            imgui.text(f"Primitives  {len(ir.geometry)}")
            imgui.text(
                f"Mesh cells  {len(ir.mesh.lines_x)-1} x {len(ir.mesh.lines_y)-1} x {len(ir.mesh.lines_z)-1}"
            )
            imgui.separator()
            for op in ir.geometry:
                selected, _ = imgui.selectable(op.name, state.selected_primitive == op.name)
                if selected:
                    state.selected_primitive = op.name
        imgui.end()

        if changed is False and monotonic() - state.last_edit > 0.35:
            # Debounced checking; reset the timer far into the future until the next edit.
            state.compile_now()
            state.last_edit = float("inf")

    immapp.run(gui_function=gui, window_title="JAAM Studio — LIVE", window_size=(1440, 900))


def _unknown_span():
    from .model import SourceSpan

    return SourceSpan.unknown("<studio>")
