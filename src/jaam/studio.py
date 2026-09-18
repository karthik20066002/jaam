from __future__ import annotations

from dataclasses import dataclass, field
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any
from pathlib import Path
from queue import Empty, Queue
import json
import math
import os
import subprocess
import sys
from threading import Thread
from time import monotonic

import numpy as np

from .compiler import CompilationResult, compile_text_result
from .diagnostics import CompilationError, Diagnostic
from .ir import BoxOp, CurveOp, SimulationIR, WireOp
from .plots import project_geometry
from .plots import front_to_back_ratio, half_power_beamwidth, normalize_gain
from .results import RadiationPattern, center_cut
from .run_results import RunResults, load_run_results

_ARTIFACT_RESULT = "artifact: "


STARTER_SOURCE = """frequency 1GHz;
boundary free_space;
default { material: copper; radius: 1mm; }
wire dipole(
    path: line(from: (0, 0, -71mm), to: (0, 0, 71mm)),
    feed: port(impedance: 50ohm)
);
"""


_VIZ3D_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jaam-viz3d")
_VIZ3D_RENDERER = None


def _nearest_polar_sample(
    angle_degrees: float,
    sample_angles: tuple[float, ...],
    sample_values: tuple[float, ...],
) -> tuple[float, float]:
    """Return the real pattern sample nearest a polar cursor angle."""
    index = min(
        range(len(sample_angles)),
        key=lambda item: abs((sample_angles[item] - angle_degrees + 180.0) % 360.0 - 180.0),
    )
    return sample_angles[index], sample_values[index]
def _render_3d_frame(
    ir: SimulationIR,
    width: int,
    height: int,
    azimuth: float,
    elevation: float,
    zoom: float,
    show_mesh: bool,
    radiation: RadiationPattern | None,
    radial_scale: str = "arrl",
    pattern_grid: bool = True,
    pattern_structure: bool = False,
) -> np.ndarray:
    global _VIZ3D_RENDERER
    from .viz3d import AntennaViz3D

    if _VIZ3D_RENDERER is None:
        _VIZ3D_RENDERER = AntennaViz3D(ir, show_mesh=show_mesh)
    else:
        if _VIZ3D_RENDERER._ir != ir:
            _VIZ3D_RENDERER.update_ir(ir)
        _VIZ3D_RENDERER.set_show_mesh(show_mesh)
    _VIZ3D_RENDERER.set_pattern_style(radial_scale, pattern_grid, pattern_structure)
    _VIZ3D_RENDERER.set_radiation_pattern(radiation)
    _VIZ3D_RENDERER.set_camera_view(azimuth, elevation, zoom)
    return _VIZ3D_RENDERER.render_to_array(width, height)


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
    optimize_mesh_anchors: bool = False
    active_visual: str = "geometry"
    radiation_cut: str = "e"
    normalized_gain: bool = True
    polar_radiation: bool = True
    center_boresight: bool = True
    radiation: RadiationPattern | None = None
    artifact_dir: Path | None = None
    run_results: RunResults | None = None
    run_status: str = "idle"
    selected_frequency_index: int = 0
    _run_loaded: bool = False
    _cancel_requested: bool = False
    radiation_error: str | None = None
    fit_radiation: bool = True
    presentation_mode: bool = False
    process: subprocess.Popen | None = field(default=None, repr=False)
    show_source_panel: bool = True
    show_solver_log_panel: bool = True
    show_build_panel: bool = True
    show_geometry_panel: bool = True
    show_3d: bool = True
    show_3d_mesh: bool = False
    show_3d_radiation: bool = True
    popped_out_panels: set[str] = field(default_factory=set)
    radial_scale: str = "arrl"
    pattern_grid: bool = True
    pattern_structure: bool = False
    open_dialog_path: str = ""
    save_as_dialog_path: str = ""
    results_dialog_path: str = ""
    about_open: bool = False
    request_quit: bool = False
    solver_log: list[str] = field(default_factory=list)
    _log_queue: Queue[str] = field(default_factory=Queue, repr=False)
    _reader: Thread | None = field(default=None, repr=False)
    _viz3d_texture: Any = field(default=None, repr=False)
    _viz3d_texture_ir: SimulationIR | None = field(default=None, repr=False)
    _viz3d_texture_view: tuple[Any, ...] | None = field(default=None, repr=False)
    _viz3d_future: Future[np.ndarray] | None = field(default=None, repr=False)
    _viz3d_future_key: tuple[Any, ...] | None = field(default=None, repr=False)
    _viz3d_azimuth: float = field(default=25.0, repr=False)
    _viz3d_elevation: float = field(default=55.0, repr=False)
    _viz3d_zoom: float = field(default=1.0, repr=False)
    _viz3d_last_mouse: tuple[float, float] | None = field(default=None, repr=False)
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
                self.source_text, filename=str(self.source_path or "<studio>"),
                optimize_mesh_anchors=self.optimize_mesh_anchors,
            )
            self.diagnostics = self.compilation.diagnostics
            self._viz3d_texture_ir = None
            self._viz3d_texture_view = None
            return True
        except CompilationError as exc:
            self.compilation = None
            self.diagnostics = exc.diagnostics
            return False

    def save(self) -> None:
        if self.source_path is None:
            raise ValueError("choose a source path before saving")
        self.source_path.parent.mkdir(parents=True, exist_ok=True)
        self.source_path.write_text(self.source_text, encoding="utf-8")

    def new_file(self) -> None:
        self.source_path = None
        self.source_text = STARTER_SOURCE
        self.compile_now()

    def open_file(self, path: Path) -> None:
        self.source_path = path
        self.source_text = path.read_text(encoding="utf-8")
        self.compile_now()

    def save_as(self, path: Path) -> None:
        path = path.expanduser()
        if not path.name:
            raise ValueError("choose a file name before saving")
        self.source_path = path
        self.save()

    def start_run(self, output_root: Path = Path("jaam-out")) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("a solver run is already active")
        if self._reader is not None and self._reader.is_alive():
            raise RuntimeError("previous solver log is still finishing")
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
            str((repository / output_root / self.source_path.stem).resolve()),
        ]
        if self.optimize_mesh_anchors:
            full_command.append("--optimize-mesh-anchors")
        self.solver_log.clear()
        while True:
            try:
                self._log_queue.get_nowait()
            except Empty:
                break
        self.solver_log.append("$ " + " ".join(full_command))
        self.artifact_dir = None
        self.run_results = None
        self.radiation = None
        self.radiation_error = None
        self.run_status = "starting"
        self._run_loaded = False
        self._cancel_requested = False
        self.process = subprocess.Popen(
            full_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=repository,
            env=environment,
        )
        self._reader = Thread(target=self._read_solver_output, args=(self.process,), daemon=True)
        self._reader.start()

    def _read_solver_output(self, process: subprocess.Popen) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
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
            if line.startswith(_ARTIFACT_RESULT):
                self.artifact_dir = Path(line[len(_ARTIFACT_RESULT):]).resolve()
                self.run_status = "running"
        if (
            self.process is not None and self.process.poll() is not None
            and (self._reader is None or not self._reader.is_alive()) and not self._run_loaded
        ):
            self._run_loaded = True
            if self._cancel_requested and self.process.returncode != 0:
                self.run_status = "cancelled"
                if self.artifact_dir is not None:
                    manifest_path = self.artifact_dir / "manifest.json"
                    try:
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        if manifest.get("status") == "prepared":
                            manifest["status"] = "cancelled"
                            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                    except (OSError, ValueError):
                        pass
            elif self.process.returncode != 0:
                self.run_status = "failed"
                if self.artifact_dir is not None:
                    try:
                        manifest = json.loads((self.artifact_dir / "manifest.json").read_text(encoding="utf-8"))
                        self.radiation_error = manifest.get("error")
                    except (OSError, ValueError):
                        pass
            elif self.artifact_dir is None:
                self.run_status = "failed"
                self.radiation_error = "solver did not announce an artifact"
            else:
                try:
                    self.load_artifact(self.artifact_dir)
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    self.run_status = "failed"
                    self.radiation_error = str(exc)
        return tuple(fresh)

    def load_artifact(self, directory: Path) -> None:
        results = load_run_results(directory)
        self.artifact_dir = results.directory
        self.run_results = results
        self.radiation = results.radiation
        self._viz3d_texture_ir = None
        self._viz3d_texture_view = None
        self.radiation_error = None
        self.run_status = "complete"
        self.selected_frequency_index = 0
        self.active_visual = "s11" if results.ports else "radiation"

    def cancel_run(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self._cancel_requested = True
            self.process.terminate()

    def _draw_3d_panel(self, embedded_size: tuple[float, float] | None = None) -> None:
        """Render the VTK offscreen view into the 3D View ImGui panel."""
        if not self.show_3d or self.compilation is None:
            return

        from imgui_bundle import hello_imgui, imgui

        flags = imgui.WindowFlags_.no_collapse
        popped_out = "3D View" in self.popped_out_panels
        if popped_out:
            window_class = imgui.WindowClass()
            window_class.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge
            imgui.set_next_window_class(window_class)
            imgui.set_next_window_size(imgui.ImVec2(640, 480), imgui.Cond_.appearing)
            expanded, _ = imgui.begin("3D View", flags=flags)
        else:
            size = embedded_size or (-1.0, -1.0)
            expanded = imgui.begin_child("3D View##embedded", imgui.ImVec2(*size), True)
        try:
            if not expanded:
                return
            if popped_out:
                if imgui.button("Embed"):
                    self.popped_out_panels.discard("3D View")
            else:
                if imgui.button("Pop out"):
                    self.popped_out_panels.add("3D View")
            if self.show_3d_radiation and self.radiation is not None:
                scales = ("arrl", "field", "db")
                imgui.set_next_item_width(160)
                changed, selection = imgui.combo("Radius", scales.index(self.radial_scale),
                    ["ARRL modified log", "Linear field", "dB (40 dB range)"])
                if changed:
                    self.radial_scale = scales[selection]
                _, self.pattern_grid = imgui.checkbox("Pattern grid", self.pattern_grid)
                imgui.same_line()
                _, self.pattern_structure = imgui.checkbox("Antenna", self.pattern_structure)
                imgui.text_wrapped(
                    f"{self.radiation.frequency_hz / 1e6:g} MHz | "
                    f"peak {self.radiation.peak_gain_db:.2f} dBi | color: dBi"
                )
            content_region = imgui.get_content_region_avail()
            width = max(int(content_region.x), 1)
            height = max(int(content_region.y), 1)
            if width < 2 or height < 2:
                return

            ir = self.compilation.ir
            radiation = self.radiation if self.show_3d_radiation else None
            view = (
                self._viz3d_azimuth,
                self._viz3d_elevation,
                self._viz3d_zoom,
                self.show_3d_mesh,
                radiation,
                self.radial_scale,
                self.pattern_grid,
                self.pattern_structure,
            )
            render_width, render_height = width, height
            frame_key = (ir, render_width, render_height, *view)
            texture = self._viz3d_texture
            texture_size = (texture.width, texture.height) if texture is not None else (0, 0)
            needs_render = (
                texture is None
                or texture_size != (render_width, render_height)
                or self._viz3d_texture_ir != ir
                or self._viz3d_texture_view != view
            )

            if needs_render:
                if self._viz3d_future is None:
                    self._viz3d_future_key = frame_key
                    self._viz3d_future = _VIZ3D_EXECUTOR.submit(
                        _render_3d_frame,
                        ir,
                        render_width,
                        render_height,
                        self._viz3d_azimuth,
                        self._viz3d_elevation,
                        self._viz3d_zoom,
                        self.show_3d_mesh,
                        radiation,
                        self.radial_scale,
                        self.pattern_grid,
                        self.pattern_structure,
                    )
                if self._viz3d_future.done():
                    completed_key = self._viz3d_future_key
                    try:
                        array = self._viz3d_future.result()
                    except Exception as exc:
                        self._viz3d_future = None
                        self._viz3d_future_key = None
                        imgui.text_colored((1.0, 0.35, 0.25, 1.0), f"3D render error: {exc}")
                    else:
                        self._viz3d_future = None
                        self._viz3d_future_key = None
                        if completed_key is None:
                            pass
                        elif (
                            not isinstance(array, np.ndarray)
                            or array.dtype != np.uint8
                            or array.ndim != 3
                            or array.shape[2] != 4
                            or array.shape[0] != completed_key[2]
                            or array.shape[1] != completed_key[1]
                        ):
                            imgui.text_colored(
                                (1.0, 0.35, 0.25, 1.0),
                                f"3D render returned unexpected array shape {getattr(array, 'shape', '?')}",
                            )
                        else:
                            try:
                                array.flags.writeable = False
                                self._viz3d_texture = hello_imgui.create_texture_gpu_from_rgba_data(array)
                                self._viz3d_texture_ir = completed_key[0]
                                self._viz3d_texture_view = completed_key[3:]
                                texture = self._viz3d_texture
                            except Exception as exc:
                                imgui.text_colored(
                                    (1.0, 0.35, 0.25, 1.0), f"3D texture upload error: {exc}"
                                )

            if texture is None or texture.texture_id() == 0:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), "3D texture is not available")
                return

            try:
                imgui.image(
                    imgui.ImTextureRef(texture.texture_id()),
                    imgui.ImVec2(float(width), float(height)),
                )
                dragging = imgui.is_item_hovered() and (imgui.is_mouse_down(0) or imgui.is_mouse_down(1))
                if dragging:
                    mouse = imgui.get_mouse_pos()
                    if self._viz3d_last_mouse is not None:
                        delta_x = mouse.x - self._viz3d_last_mouse[0]
                        delta_y = mouse.y - self._viz3d_last_mouse[1]
                        self._viz3d_azimuth = (self._viz3d_azimuth + delta_x * 0.12) % 360.0
                        # Permit a complete orbit over the poles. VTK handles
                        # the view-up transition when the camera is reset.
                        self._viz3d_elevation = max(
                            -179.0, min(179.0, self._viz3d_elevation + delta_y * 0.12)
                        )
                        self._viz3d_texture_ir = None
                        self._viz3d_texture_view = None
                    self._viz3d_last_mouse = (mouse.x, mouse.y)
                else:
                    self._viz3d_last_mouse = None
                if imgui.is_item_hovered():
                    wheel = imgui.get_io().mouse_wheel
                    if wheel:
                        self._viz3d_zoom = max(0.25, min(4.0, self._viz3d_zoom * (1.05**wheel)))
                        self._viz3d_texture_ir = None
                        self._viz3d_texture_view = None
            except Exception as exc:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), f"3D display error: {exc}")
        finally:
            if popped_out:
                imgui.end()
            else:
                imgui.end_child()


def launch(path: Path | None = None) -> None:
    try:
        import numpy as np
        from imgui_bundle import hello_imgui, imgui, immapp, implot
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
            imgui.text_disabled(
                "This artifact has no NF2FF cuts." if state.run_results is not None
                else "Run the model to calculate NF2FF radiation cuts."
            )
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
        imgui.same_line()
        if imgui.radio_button("Polar", state.polar_radiation):
            state.polar_radiation, state.fit_radiation = True, True
        imgui.same_line()
        if imgui.radio_button("Cartesian", not state.polar_radiation):
            state.polar_radiation, state.fit_radiation = False, True
        imgui.same_line()
        _, state.center_boresight = imgui.checkbox("Boresight = 0 deg", state.center_boresight)

        if state.radiation_cut == "e":
            angles, absolute_gain = pattern.azimuth_cut()
            cut_name = "E-plane (XY, theta=90 deg)"
        else:
            angles, absolute_gain = pattern.elevation_cut()
            cut_name = "H-plane (XZ, phi=0 deg)"
        gain = normalize_gain(absolute_gain) if state.normalized_gain else absolute_gain
        peak_index = max(range(len(absolute_gain)), key=absolute_gain.__getitem__)
        global_boresight = angles[peak_index]
        if state.center_boresight:
            display_angles, display_gain = center_cut(angles, gain, global_boresight)
        else:
            display_angles, display_gain = angles, gain
        beamwidth = half_power_beamwidth(angles, gain)
        front_back = front_to_back_ratio(angles, gain) if state.radiation_cut == "e" else None
        imgui.text(
            f"{pattern.frequency_hz / 1e6:.3f} MHz  |  peak {pattern.peak_gain_db:.2f} dBi"
        )
        if state.center_boresight:
            imgui.same_line()
            imgui.text(f"|  boresight {global_boresight:+.0f} deg global")
        if beamwidth is not None:
            imgui.same_line()
            imgui.text(f"|  HPBW {beamwidth:.1f} deg")
        if front_back is not None:
            imgui.same_line()
            imgui.text(f"|  F/B {front_back:.2f} dB")

        if state.polar_radiation:
            if state.normalized_gain:
                radial_min, radial_max = -40.0, 0.0
            else:
                radial_max = np.ceil(max(display_gain) / 5.0) * 5.0
                radial_min = np.floor(min(display_gain) / 5.0) * 5.0
                if radial_max - radial_min < 10.0:
                    radial_min = radial_max - 10.0
        else:
            radial_min = radial_max = 0.0

        plot_size = imgui.ImVec2(-1, max(imgui.get_content_region_avail().y - 4, 180))
        plot_flags = implot.Flags_.no_title | (implot.Flags_.equal if state.polar_radiation else 0)
        if not implot.begin_plot(cut_name, plot_size, plot_flags):
            return
        try:
            if state.polar_radiation:
                axis_flags = implot.AxisFlags_.no_decorations
                implot.setup_axes("", "", axis_flags, axis_flags)
                if state.fit_radiation:
                    implot.setup_axis_limits(implot.ImAxis_.x1, -1.12, 1.12, implot.Cond_.always)
                    implot.setup_axis_limits(implot.ImAxis_.y1, -1.12, 1.12, implot.Cond_.always)
                    state.fit_radiation = False
                circle_angles = tuple(range(0, 361, 3))
                if state.normalized_gain:
                    ring_step = 10.0
                else:
                    ring_step = 5.0 if radial_max - radial_min <= 25.0 else 10.0
                ring_values = tuple(
                    radial_min + ring_step * index
                    for index in range(int(round((radial_max - radial_min) / ring_step)) + 1)
                )
                for ring_value in ring_values:
                    radius = (ring_value - radial_min) / (radial_max - radial_min)
                    ring = tuple(
                        (radius * np.cos(np.deg2rad(angle)), radius * np.sin(np.deg2rad(angle)))
                        for angle in circle_angles
                    )
                    plot_segment(f"##ring-{ring_value}", ring, (0.35, 0.39, 0.43, 0.65), 0.7)
                    if radius > 0:
                        implot.plot_text(
                            f"{ring_value:g} {'dB' if state.normalized_gain else 'dBi'}",
                            0.02,
                            radius,
                            imgui.ImVec2(4, 2),
                        )
                for spoke in range(0, 360, 30):
                    radians = np.deg2rad(spoke)
                    plot_segment(
                        f"##spoke-{spoke}",
                        ((0.0, 0.0), (np.sin(radians), np.cos(radians))),
                        (0.30, 0.34, 0.38, 0.55),
                        0.7,
                    )
                    label_radius = 1.075
                    implot.plot_text(
                        f"{spoke} deg",
                        label_radius * np.sin(radians),
                        label_radius * np.cos(radians),
                    )
                radii = tuple(
                    max(0.0, min(1.0, (value - radial_min) / (radial_max - radial_min)))
                    for value in display_gain
                )
                polar_points = tuple(
                    (radius * np.sin(np.deg2rad(angle)), radius * np.cos(np.deg2rad(angle)))
                    for angle, radius in zip(display_angles, radii)
                )
                if polar_points:
                    polar_points += (polar_points[0],)
                plot_segment(
                    "Radiation pattern",
                    polar_points,
                    (0.15, 0.86, 1.0, 1.0),
                    2.7,
                )
            else:
                implot.setup_axes("Angle (deg)", "Gain (dB)")
                if state.fit_radiation:
                    padding = max((max(gain) - min(gain)) * 0.08, 1.0)
                    implot.setup_axis_limits(
                        implot.ImAxis_.x1, min(display_angles), max(display_angles), implot.Cond_.always
                    )
                    implot.setup_axis_limits(
                        implot.ImAxis_.y1,
                        min(display_gain) - padding,
                        max(display_gain) + padding,
                        implot.Cond_.always,
                    )
                    state.fit_radiation = False
                plot_segment(
                    "Normalized gain" if state.normalized_gain else "Absolute gain",
                    tuple(zip(display_angles, display_gain)),
                    (0.2, 0.82, 1.0, 1.0),
                    2.5,
                )
            if implot.is_plot_hovered():
                mouse = implot.get_plot_mouse_pos()
                if state.polar_radiation:
                    cursor_angle = math.degrees(math.atan2(mouse.x, mouse.y))
                    angle, sample_gain = _nearest_polar_sample(
                        cursor_angle, display_angles, display_gain
                    )
                    unit = "dB" if state.normalized_gain else "dBi"
                    imgui.set_tooltip(f"angle {angle:.2f} deg\ngain {sample_gain:.2f} {unit}")
                else:
                    imgui.set_tooltip(f"angle {mouse.x:.2f} deg\ngain {mouse.y:.2f} dB")
        finally:
            implot.end_plot()

    def results_plot() -> None:
        results = state.run_results
        if results is None or not results.ports:
            imgui.text_disabled("Run the model to calculate S11 and impedance.")
            return
        samples = results.ports[0]
        frequencies = np.asarray([item.frequency_hz / 1e6 for item in samples], dtype=np.float64)
        s11 = np.asarray([item.s11_db for item in samples], dtype=np.float64)
        index = min(state.selected_frequency_index, len(samples) - 1)
        selected = samples[index]
        imgui.text(f"{selected.frequency_hz / 1e6:.3f} MHz  |  S11 {selected.s11_db:.2f} dB")
        imgui.text(f"Z {selected.resistance_ohm:.2f} + j{selected.reactance_ohm:.2f} ohm  |  VSWR {selected.vswr:.2f}")
        imgui.text_disabled("Click the S11 trace to select a frequency.")
        plot_size = imgui.ImVec2(-1, max(imgui.get_content_region_avail().y - 4, 180))
        if implot.begin_plot("S11 / MHz", plot_size, implot.Flags_.no_title):
            try:
                implot.setup_axes("Frequency (MHz)", "S11 (dB)")
                implot.plot_line("S11", frequencies, s11, line_spec((0.2, 0.82, 1.0, 1.0), 2.5))
                implot.plot_scatter("Selected", np.asarray([frequencies[index]]), np.asarray([s11[index]]))
                if implot.is_plot_hovered() and imgui.is_mouse_clicked(0):
                    mouse = implot.get_plot_mouse_pos()
                    state.selected_frequency_index = int(np.argmin(np.abs(frequencies - mouse.x)))
            finally:
                implot.end_plot()

    def _draw_main_menu_bar(state: StudioState) -> float:
        """Render the top main menu bar and return its height in pixels."""
        menu_bar_height = imgui.get_frame_height()
        if not imgui.begin_main_menu_bar():
            return menu_bar_height

        menu_bar_height = imgui.get_window_height()

        io = imgui.get_io()
        compile_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.b, False)
        run_requested = imgui.is_key_pressed(imgui.Key.f5, False)
        save_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.s, False)
        open_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.o, False)
        new_requested = io.key_ctrl and imgui.is_key_pressed(imgui.Key.n, False)

        if imgui.begin_menu("File"):
            if imgui.menu_item("New", "Ctrl+N", False)[0] or new_requested:
                state.new_file()
            if imgui.menu_item("Open...", "Ctrl+O", False)[0] or open_requested:
                state.open_dialog_path = str(state.source_path or "")
                imgui.open_popup("Open Model")
            if imgui.menu_item("Save", "Ctrl+S", False)[0] or save_requested:
                if state.source_path is not None:
                    state.save()
                else:
                    state.save_as_dialog_path = "untitled.jaam"
                    imgui.open_popup("Save As")
            if imgui.menu_item("Save As...", "Ctrl+Shift+S", False)[0]:
                state.save_as_dialog_path = str(state.source_path or "")
                imgui.open_popup("Save As")
            if imgui.menu_item("Open Results...", "", False)[0]:
                state.results_dialog_path = str(state.artifact_dir or "")
                imgui.open_popup("Open Results")
            imgui.separator()
            if imgui.menu_item("Quit", "Alt+F4", False)[0]:
                state.request_quit = True
            imgui.end_menu()

        if imgui.begin_menu("Edit"):
            imgui.menu_item("Preferences", "", False, False)
            imgui.end_menu()

        if imgui.begin_menu("Simulate"):
            if imgui.menu_item("Compile", "Ctrl+B", False)[0] or compile_requested:
                state.compile_now()
            if imgui.menu_item("Run", "F5", False)[0] or run_requested:
                try:
                    state.start_run()
                except (ValueError, RuntimeError) as exc:
                    state.diagnostics = (
                        Diagnostic("J901", str(exc), state.diagnostics[0].span if state.diagnostics else _unknown_span()),
                    )
            if imgui.menu_item("Cancel", "", False, state.process is not None and state.process.poll() is None)[0]:
                state.cancel_run()
            changed, state.optimize_mesh_anchors = imgui.menu_item(
                "Experimental mesh anchors", "", state.optimize_mesh_anchors
            )
            if changed:
                state.compile_now()
            imgui.end_menu()

        if imgui.begin_menu("View"):
            _, state.show_source_panel = imgui.menu_item("Source", "", state.show_source_panel)
            _, state.show_solver_log_panel = imgui.menu_item("Solver Log", "", state.show_solver_log_panel)
            _, state.show_build_panel = imgui.menu_item("Build Trace", "", state.show_build_panel)
            _, state.show_geometry_panel = imgui.menu_item("Geometry", "", state.show_geometry_panel)
            _, state.show_3d = imgui.menu_item("Show 3D", "", state.show_3d)
            _, state.show_3d_mesh = imgui.menu_item("Show 3D Mesh", "", state.show_3d_mesh)
            changed_far_field, state.show_3d_radiation = imgui.menu_item(
                "Show 3D Far Field", "", state.show_3d_radiation
            )
            if changed_far_field:
                state._viz3d_texture_ir = None
                state._viz3d_texture_view = None
            imgui.separator()
            imgui.text_disabled("Pop out panels")
            for panel_name in ("JAAM Source", "Solver Log", "Build / Pass Trace", "Geometry / Mesh", "3D View"):
                popped = panel_name in state.popped_out_panels
                changed, popped = imgui.menu_item(f"{panel_name}##popout", "", popped)
                if changed:
                    if popped:
                        state.popped_out_panels.add(panel_name)
                    else:
                        state.popped_out_panels.discard(panel_name)
            imgui.separator()
            _, state.presentation_mode = imgui.menu_item("Presentation mode", "", state.presentation_mode)
            imgui.end_menu()

        if imgui.begin_menu("Help"):
            if imgui.menu_item("About JAAM Studio", "", False)[0]:
                state.about_open = True
                imgui.open_popup("About JAAM Studio")
            imgui.end_menu()

        imgui.end_main_menu_bar()
        return menu_bar_height


    def _draw_modals(state: StudioState) -> None:
        """Render modal popups triggered from the menu bar."""
        if imgui.begin_popup_modal("Open Model", None)[0]:
            imgui.text("Path to JAAM model")
            _, state.open_dialog_path = imgui.input_text("##open-path", state.open_dialog_path, 1024)
            if imgui.button("Open", imgui.ImVec2(120, 0)):
                path = Path(state.open_dialog_path)
                if path.exists():
                    state.open_file(path)
                    imgui.close_current_popup()
                else:
                    state.diagnostics = (
                        Diagnostic("J902", f"file not found: {path}", _unknown_span()),
                    )
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                imgui.close_current_popup()
            imgui.end_popup()

        if imgui.begin_popup_modal("Save As", None)[0]:
            imgui.text("Save model as")
            _, state.save_as_dialog_path = imgui.input_text("##save-as-path", state.save_as_dialog_path, 1024)
            if imgui.button("Save", imgui.ImVec2(120, 0)):
                path = Path(state.save_as_dialog_path)
                try:
                    state.save_as(path)
                    imgui.close_current_popup()
                except OSError as exc:
                    state.diagnostics = (
                        Diagnostic("J903", f"could not save: {exc}", _unknown_span()),
                    )
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                imgui.close_current_popup()
            imgui.end_popup()

        if imgui.begin_popup_modal("Open Results", None)[0]:
            imgui.text("Completed artifact directory")
            _, state.results_dialog_path = imgui.input_text("##results-path", state.results_dialog_path, 1024)
            if imgui.button("Open", imgui.ImVec2(120, 0)):
                try:
                    state.load_artifact(Path(state.results_dialog_path))
                    imgui.close_current_popup()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    state.radiation_error = str(exc)
            imgui.same_line()
            if imgui.button("Cancel", imgui.ImVec2(120, 0)):
                imgui.close_current_popup()
            if state.radiation_error:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), state.radiation_error)
            imgui.end_popup()

        if state.about_open and imgui.begin_popup_modal("About JAAM Studio", None)[0]:
            imgui.text("JAAM Studio")
            imgui.text_disabled("Just Another Antenna Modeller")
            imgui.separator()
            imgui.text("Version 0.1.0")
            if imgui.button("OK", imgui.ImVec2(120, 0)):
                state.about_open = False
                imgui.close_current_popup()
            imgui.end_popup()


    def gui() -> None:

        state.poll_solver_log()
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.viewports_enable
        menu_bar_height = _draw_main_menu_bar(state)

        available = imgui.get_content_region_avail()
        width = max(float(available.x), 1.0)
        height = max(float(available.y), 1.0)
        margin = 12.0
        gap = 8.0
        compact = width < 1200.0
        left_width = width * (0.50 if compact else 0.64 if not state.presentation_mode else 0.72)
        right_x = left_width + gap
        right_width = width - right_x - margin
        source_height = height * 0.68
        build_height = height * 0.43
        window_flags = imgui.WindowFlags_.no_collapse | imgui.WindowFlags_.no_move
        popout_flags = imgui.WindowFlags_.no_collapse
        layout_condition = imgui.Cond_.always

        top = margin + menu_bar_height

        # The Studio surface is one host window. Panels are children by default;
        # selecting them under View > Pop out panels promotes that panel back to
        # an independently movable ImGui window.
        imgui.begin_child("JAAM Studio##surface", imgui.ImVec2(-1, -1), False)
        panel_modes: dict[str, bool] = {}

        def begin_panel(name: str, position: tuple[float, float], size: tuple[float, float]) -> bool:
            popped_out = name in state.popped_out_panels
            panel_modes[name] = popped_out
            if popped_out:
                window_class = imgui.WindowClass()
                window_class.viewport_flags_override_set = imgui.ViewportFlags_.no_auto_merge
                imgui.set_next_window_class(window_class)
                imgui.set_next_window_pos(imgui.ImVec2(*position), imgui.Cond_.appearing)
                imgui.set_next_window_size(imgui.ImVec2(*size), imgui.Cond_.appearing)
                expanded, _ = imgui.begin(name, flags=popout_flags)
                if expanded and imgui.button("Embed"):
                    state.popped_out_panels.discard(name)
                return expanded
            # Child windows are laid out from the host's cursor, not from
            # screen coordinates. Convert the existing screen-space layout so
            # the embedded mode retains the two-column/two-row arrangement.
            imgui.set_cursor_pos(imgui.ImVec2(position[0], position[1] - menu_bar_height))
            expanded = imgui.begin_child(f"{name}##embedded", imgui.ImVec2(*size), True)
            if expanded and imgui.button("Pop out"):
                state.popped_out_panels.add(name)
            imgui.same_line()
            return expanded

        def end_panel(name: str) -> None:
            if panel_modes.get(name, False):
                imgui.end()
            else:
                imgui.end_child()

        if state.show_source_panel:
            begin_panel("JAAM Source", (margin, top), (left_width - margin, source_height - margin))
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
            end_panel("JAAM Source")
        else:
            changed = False

        if state.show_solver_log_panel:
            begin_panel("Solver Log", (margin, source_height + gap + top - margin), (left_width - margin, height - source_height - gap - top))
            if not state.solver_log:
                imgui.text_disabled("No live run yet. Save the model and press F5.")
            for line in state.solver_log:
                imgui.text_unformatted(line)
            if state.process is not None:
                status = "running" if state.process.poll() is None else f"exited {state.process.returncode}"
                imgui.text(f"Solver: {status}")
            imgui.text(f"Run: {state.run_status}")
            if state.run_results is not None:
                imgui.text(f"Run ID: {state.run_results.manifest['runId']}")
            elif state.artifact_dir is not None:
                imgui.text(f"Artifact: {state.artifact_dir}")
            if state.radiation_error:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), state.radiation_error)
            end_panel("Solver Log")

        if state.show_build_panel:
            begin_panel("Build / Pass Trace", (right_x, top), (right_width, build_height - margin))
            if imgui.button("Compile  Ctrl+B"):
                state.compile_now()
            imgui.same_line()
            if imgui.button("Run  F5"):
                try:
                    state.start_run()
                except (ValueError, RuntimeError) as exc:
                    state.diagnostics = (
                        Diagnostic("J901", str(exc), state.diagnostics[0].span if state.diagnostics else _unknown_span()),
                    )
            imgui.same_line()
            if imgui.button("Cancel"):
                state.cancel_run()
            _, state.presentation_mode = imgui.checkbox("Presentation mode", state.presentation_mode)
            imgui.separator()
            if state.compilation:
                imgui.text_colored((0.35, 0.9, 0.5, 1.0), "COMPILE OK")
                for compiler_pass in state.compilation.passes:
                    imgui.text(f"{compiler_pass.name}: {compiler_pass.duration_ns / 1e6:.3f} ms")
            for diagnostic in state.diagnostics:
                imgui.text_colored((1.0, 0.35, 0.25, 1.0), f"{diagnostic.code}: {diagnostic.message}")
            end_panel("Build / Pass Trace")

        right_bottom_top = build_height + gap + top - margin
        right_bottom_height = height - build_height - gap - top
        chart_share = 0.58 if state.active_visual == "radiation" else 0.44
        geometry_height = right_bottom_height * chart_share if state.show_3d else right_bottom_height

        if state.show_geometry_panel:
            begin_panel("Geometry / Mesh", (right_x, right_bottom_top), (right_width, geometry_height))
            if imgui.radio_button("Geometry", state.active_visual == "geometry"):
                state.active_visual = "geometry"
            imgui.same_line()
            if imgui.radio_button("S11", state.active_visual == "s11"):
                state.active_visual = "s11"
            imgui.same_line()
            if imgui.radio_button("Radiation cuts", state.active_visual == "radiation"):
                state.active_visual = "radiation"
            imgui.separator()
            if state.compilation or state.run_results:
                ir = state.compilation.ir if state.compilation else None
                if state.active_visual == "geometry":
                    if ir is not None:
                        imgui.text_disabled(
                            f"{len(ir.geometry)} primitives  |  planned mesh {len(ir.mesh.lines_x)-1} x {len(ir.mesh.lines_y)-1} x {len(ir.mesh.lines_z)-1}"
                        )
                    geometry_plot()
                elif state.active_visual == "s11":
                    results_plot()
                else:
                    radiation_plot()
            end_panel("Geometry / Mesh")

        if state.show_3d:
            if "3D View" not in state.popped_out_panels:
                imgui.set_cursor_pos(
                    imgui.ImVec2(
                        right_x,
                        right_bottom_top + geometry_height + gap - menu_bar_height,
                    )
                )
                state._draw_3d_panel(
                    (right_width, right_bottom_height - geometry_height - gap)
                )
            else:
                state._draw_3d_panel()

        _draw_modals(state)

        imgui.end_child()

        if changed is False and monotonic() - state.last_edit > 0.35:
            # Debounced checking; reset the timer far into the future until the next edit.
            state.compile_now()
            state.last_edit = float("inf")

        if state.request_quit:
            sys.exit(0)

    plot_context = implot.create_context()
    try:
        runner_params = hello_imgui.RunnerParams()
        runner_params.imgui_window_params.enable_viewports = True
        runner_params.imgui_window_params.default_imgui_window_type = (
            hello_imgui.DefaultImGuiWindowType.provide_full_screen_window
        )
        runner_params.callbacks.show_gui = gui
        runner_params.app_window_params.window_title = "JAAM Studio — LIVE"
        runner_params.app_window_params.window_geometry.size = (1440, 900)
        immapp.run(runner_params)
    finally:
        implot.destroy_context(plot_context)


def _unknown_span():
    from .model import SourceSpan

    return SourceSpan.unknown("<studio>")


def _unknown_span():
    from .model import SourceSpan

    return SourceSpan.unknown("<studio>")
