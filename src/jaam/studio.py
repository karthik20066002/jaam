from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from queue import Empty, Queue
import os
import re
import subprocess
import sys
from threading import Thread
from time import monotonic

from .compiler import CompilationResult, compile_text_result
from .diagnostics import CompilationError, Diagnostic
from .ir import BoxOp, CurveOp, WireOp
from .plots import project_geometry
from .plots import front_to_back_ratio, half_power_beamwidth, normalize_gain
from .results import RadiationPattern, load_nf2ff

_PORT_RESULT = re.compile(r";\s*(/.+/port\d+_s11\.csv)$")


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
    show_mesh: bool = True
    show_domain: bool = True
    show_feed: bool = True
    fit_geometry: bool = True
    active_visual: str = "geometry"
    radiation_cut: str = "e"
    normalized_gain: bool = True
    radiation: RadiationPattern | None = None
    artifact_dir: Path | None = None
    radiation_error: str | None = None
    fit_radiation: bool = True
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
        for line in fresh:
            if match := _PORT_RESULT.search(line):
                self.artifact_dir = Path(match.group(1)).parent
                try:
                    self.radiation = load_nf2ff(self.artifact_dir / "nf2ff.csv")
                    self.radiation_error = None
                    self.active_visual = "radiation"
                except (OSError, ValueError) as exc:
                    self.radiation_error = str(exc)
        return tuple(fresh)

    def cancel_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


def launch(path: Path | None = None) -> None:
    try:
        import numpy as np
        from imgui_bundle import imgui, immapp, implot
    except ImportError as exc:
        raise RuntimeError("JAAM Studio requires: uv sync --extra studio") from exc

    state = StudioState.open(path)

    def line_spec(color, weight=1.0):
        spec = implot.Spec()
        spec.line_color = imgui.ImVec4(*color)
        spec.line_weight = weight
        return spec

    def plot_segment(label: str, points, color, weight=1.0) -> None:
        if len(points) < 2:
            return
        xs = np.asarray([point[0] for point in points], dtype=np.float64)
        ys = np.asarray([point[1] for point in points], dtype=np.float64)
        implot.plot_line(label, xs, ys, line_spec(color, weight))

    def geometry_plot() -> None:
        result = state.compilation
        if result is None:
            imgui.text_disabled("Compile a valid model to display geometry.")
            return
        ir = result.ir
        plane = state.active_plane
        axes = {"xy": (0, 1), "xz": (0, 2), "yz": (1, 2)}[plane]
        lo = ir.domain_min
        hi = ir.domain_max

        if imgui.radio_button("XY", plane == "xy"):
            state.active_plane, state.fit_geometry = "xy", True
        imgui.same_line()
        if imgui.radio_button("XZ", plane == "xz"):
            state.active_plane, state.fit_geometry = "xz", True
        imgui.same_line()
        if imgui.radio_button("YZ", plane == "yz"):
            state.active_plane, state.fit_geometry = "yz", True
        imgui.same_line()
        if imgui.button("Fit"):
            state.fit_geometry = True
        _, state.show_mesh = imgui.checkbox("Mesh", state.show_mesh)
        imgui.same_line()
        _, state.show_domain = imgui.checkbox("Domain", state.show_domain)
        imgui.same_line()
        _, state.show_feed = imgui.checkbox("Feed", state.show_feed)

        plot_size = imgui.ImVec2(-1, max(imgui.get_content_region_avail().y - 4, 180))
        if not implot.begin_plot(
            f"##geometry-{state.active_plane}", plot_size, implot.Flags_.equal | implot.Flags_.no_title
        ):
            return
        try:
            labels = {"xy": ("X (m)", "Y (m)"), "xz": ("X (m)", "Z (m)"), "yz": ("Y (m)", "Z (m)")}
            implot.setup_axes(*labels[state.active_plane])
            horizontal, vertical = axes
            if state.fit_geometry:
                x_span = max(hi[horizontal] - lo[horizontal], 1e-9)
                y_span = max(hi[vertical] - lo[vertical], 1e-9)
                implot.setup_axis_limits(
                    implot.ImAxis_.x1,
                    lo[horizontal] - 0.04 * x_span,
                    hi[horizontal] + 0.04 * x_span,
                    implot.Cond_.always,
                )
                implot.setup_axis_limits(
                    implot.ImAxis_.y1,
                    lo[vertical] - 0.04 * y_span,
                    hi[vertical] + 0.04 * y_span,
                    implot.Cond_.always,
                )
                state.fit_geometry = False
            bounds = (
                (lo[horizontal], lo[vertical]),
                (hi[horizontal], lo[vertical]),
                (hi[horizontal], hi[vertical]),
                (lo[horizontal], hi[vertical]),
                (lo[horizontal], lo[vertical]),
            )
            if state.show_domain:
                plot_segment("Domain", bounds, (0.28, 0.52, 0.72, 0.85), 1.5)

            if state.show_mesh:
                mesh_axes = (ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z)
                mesh_spec = line_spec((0.24, 0.29, 0.33, 0.45), 0.5)
                for index, value in enumerate(mesh_axes[horizontal]):
                    xs = np.asarray((value, value), dtype=np.float64)
                    ys = np.asarray((lo[vertical], hi[vertical]), dtype=np.float64)
                    implot.plot_line(f"##mesh-h-{index}", xs, ys, mesh_spec)
                for index, value in enumerate(mesh_axes[vertical]):
                    xs = np.asarray((lo[horizontal], hi[horizontal]), dtype=np.float64)
                    ys = np.asarray((value, value), dtype=np.float64)
                    implot.plot_line(f"##mesh-v-{index}", xs, ys, mesh_spec)

            colors = {
                "copper": (0.95, 0.55, 0.18, 1.0),
                "gold": (1.0, 0.82, 0.25, 1.0),
                "pec": (0.75, 0.82, 0.9, 1.0),
                "earth_dry": (0.48, 0.34, 0.2, 1.0),
            }
            for op in ir.geometry:
                selected = op.name == state.selected_primitive
                color = (0.2, 0.9, 1.0, 1.0) if selected else colors.get(op.material, (0.8, 0.8, 0.8, 1.0))
                plot_segment(op.name, project_geometry(op, state.active_plane), color, 4.0 if selected else 2.5)
                if implot.is_legend_entry_hovered(op.name) and imgui.is_mouse_clicked(0):
                    state.selected_primitive = op.name
                if state.show_feed and isinstance(op, (CurveOp, WireOp)) and op.feed:
                    feed_points = (
                        (op.feed.start[horizontal], op.feed.start[vertical]),
                        (op.feed.stop[horizontal], op.feed.stop[vertical]),
                    )
                    plot_segment(f"Feed {op.feed.impedance_ohm:g} ohm", feed_points, (1.0, 0.2, 0.35, 1.0), 5.0)
            if implot.is_plot_hovered():
                mouse = implot.get_plot_mouse_pos()
                imgui.set_tooltip(f"{labels[state.active_plane][0][0]} {mouse.x:.6g} m\n{labels[state.active_plane][1][0]} {mouse.y:.6g} m")
        finally:
            implot.end_plot()

    def radiation_plot() -> None:
        pattern = state.radiation
        if pattern is None:
            imgui.text_disabled("Run the model to calculate NF2FF radiation cuts.")
            if state.radiation_error:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), state.radiation_error)
            return
        if imgui.radio_button("E-plane / XY", state.radiation_cut == "e"):
            state.radiation_cut, state.fit_radiation = "e", True
        imgui.same_line()
        if imgui.radio_button("H-plane / XZ", state.radiation_cut == "h"):
            state.radiation_cut, state.fit_radiation = "h", True
        imgui.same_line()
        changed_normalization, state.normalized_gain = imgui.checkbox(
            "Normalized", state.normalized_gain
        )
        if changed_normalization:
            state.fit_radiation = True

        if state.radiation_cut == "e":
            angles, absolute_gain = pattern.azimuth_cut()
            cut_name = "E-plane (XY, theta=90 deg)"
        else:
            angles, absolute_gain = pattern.elevation_cut()
            cut_name = "H-plane (XZ, phi=0 deg)"
        gain = normalize_gain(absolute_gain) if state.normalized_gain else absolute_gain
        beamwidth = half_power_beamwidth(angles, gain)
        front_back = front_to_back_ratio(angles, gain) if state.radiation_cut == "e" else None
        imgui.text(
            f"{pattern.frequency_hz / 1e6:.3f} MHz  |  peak {pattern.peak_gain_db:.2f} dBi"
        )
        if beamwidth is not None:
            imgui.same_line()
            imgui.text(f"|  HPBW {beamwidth:.1f} deg")
        if front_back is not None:
            imgui.same_line()
            imgui.text(f"|  F/B {front_back:.2f} dB")

        plot_size = imgui.ImVec2(-1, max(imgui.get_content_region_avail().y - 4, 180))
        if not implot.begin_plot(cut_name, plot_size, implot.Flags_.no_title):
            return
        try:
            implot.setup_axes("Angle (deg)", "Gain (dB)")
            if state.fit_radiation:
                padding = max((max(gain) - min(gain)) * 0.08, 1.0)
                implot.setup_axis_limits(
                    implot.ImAxis_.x1, min(angles), max(angles), implot.Cond_.always
                )
                implot.setup_axis_limits(
                    implot.ImAxis_.y1,
                    min(gain) - padding,
                    max(gain) + padding,
                    implot.Cond_.always,
                )
                state.fit_radiation = False
            plot_segment(
                "Normalized gain" if state.normalized_gain else "Absolute gain",
                tuple(zip(angles, gain)),
                (0.2, 0.82, 1.0, 1.0),
                2.5,
            )
            if implot.is_plot_hovered():
                mouse = implot.get_plot_mouse_pos()
                imgui.set_tooltip(f"angle {mouse.x:.2f} deg\ngain {mouse.y:.2f} dB")
        finally:
            implot.end_plot()

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
        if imgui.radio_button("Geometry", state.active_visual == "geometry"):
            state.active_visual = "geometry"
        imgui.same_line()
        if imgui.radio_button("Radiation cuts", state.active_visual == "radiation"):
            state.active_visual = "radiation"
        imgui.separator()
        if state.compilation:
            ir = state.compilation.ir
            if state.active_visual == "geometry":
                imgui.text_disabled(
                    f"{len(ir.geometry)} primitives  |  mesh {len(ir.mesh.lines_x)-1} x {len(ir.mesh.lines_y)-1} x {len(ir.mesh.lines_z)-1}"
                )
                geometry_plot()
            else:
                radiation_plot()
        imgui.end()

        if changed is False and monotonic() - state.last_edit > 0.35:
            # Debounced checking; reset the timer far into the future until the next edit.
            state.compile_now()
            state.last_edit = float("inf")

    plot_context = implot.create_context()
    try:
        immapp.run(gui_function=gui, window_title="JAAM Studio — LIVE", window_size=(1440, 900))
    finally:
        implot.destroy_context(plot_context)


def _unknown_span():
    from .model import SourceSpan

    return SourceSpan.unknown("<studio>")
