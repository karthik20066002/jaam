"""VTK offscreen 3D antenna geometry renderer.

VTK is imported lazily so the compiler remains lightweight without the optional
``studio`` dependency extra.
"""

from __future__ import annotations

import ctypes
import sys
from typing import TYPE_CHECKING

import numpy as np

from .ir import BoxOp, CurveOp, FeedSpec, GeometryOp, RotPolyOp, SimulationIR, WireOp
from .results import RadiationPattern
from .farfield import gain_surface_points

if TYPE_CHECKING:
    from vtkmodules.vtkRenderingCore import vtkActor, vtkRenderer, vtkRenderWindow

__all__ = ["AntennaViz3D", "StudioDependencyError"]


class StudioDependencyError(RuntimeError):
    pass


def _save_glx_context():
    """Save the current GLX OpenGL context, if any.

    VTK's offscreen render window makes its own context current and does not
    restore the previous one. We save/restore it so the host GUI (ImGui) keeps
    the context it needs for texture upload and drawing.
    """
    if sys.platform != "linux":
        return None
    try:
        libgl = ctypes.CDLL("libGL.so.1")
    except OSError:
        return None
    libgl.glXGetCurrentContext.restype = ctypes.c_void_p
    libgl.glXGetCurrentDrawable.restype = ctypes.c_void_p
    libgl.glXGetCurrentDisplay.restype = ctypes.c_void_p
    context = libgl.glXGetCurrentContext()
    drawable = libgl.glXGetCurrentDrawable()
    display = libgl.glXGetCurrentDisplay()
    return (context, drawable, display)


def _restore_glx_context(saved) -> None:
    """Restore a GLX context previously saved by ``_save_glx_context``."""
    if saved is None:
        return
    context, drawable, display = saved
    try:
        libgl = ctypes.CDLL("libGL.so.1")
    except OSError:
        return
    libgl.glXMakeCurrent.restype = ctypes.c_int
    libgl.glXMakeCurrent.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    libgl.glXGetCurrentDisplay.restype = ctypes.c_void_p
    # VTK may have created a display; use the current one if we had none.
    if display is None:
        display = libgl.glXGetCurrentDisplay()
    if display is None:
        return
    if context is None:
        # Detach the current context so the caller's context remains unbound,
        # matching the state before VTK rendered.
        libgl.glXMakeCurrent(display, ctypes.c_void_p(0), ctypes.c_void_p(0))
    else:
        libgl.glXMakeCurrent(display, drawable, context)


class AntennaViz3D:
    """Offscreen VTK renderer for JAAM antenna geometry."""

    DEFAULT_WIRE_RADIUS_M = 1e-3
    DEFAULT_FEED_RADIUS_M = 5e-3

    _WIRE_COLOR = (1.0, 0.68, 0.28)  # copper
    _BOX_COLOR = (0.40, 0.65, 0.90)  # light blue
    _ROTPOLY_COLOR = (0.35, 0.75, 0.45)  # green
    _FEED_COLOR = (0.95, 0.20, 0.20)  # red
    _DOMAIN_COLOR = (0.90, 0.90, 0.90)  # light gray
    _BACKGROUND_COLOR = (0.10, 0.10, 0.10)

    def __init__(self, ir: SimulationIR, show_mesh: bool = True) -> None:
        self._ir = ir
        self._show_mesh = show_mesh
        self._renderer: vtkRenderer | None = None
        self._axis_renderer: vtkRenderer | None = None
        self._render_window: vtkRenderWindow | None = None
        self._actors: list[vtkActor] = []
        self._radiation: RadiationPattern | None = None
        self._radial_scale = "arrl"
        self._pattern_grid = True
        self._pattern_structure = False
        self._camera_base = None
        self._axis_camera_base = None
        self._build()

    def _import_vtk(self) -> None:
        """Ensure VTK rendering classes are available.

        Importing ``vtkmodules.vtkRenderingOpenGL2`` registers the OpenGL factory
        required for offscreen rendering.
        """
        try:
            import vtkmodules.vtkRenderingOpenGL2  # noqa: F401
            from vtkmodules.vtkCommonCore import vtkFloatArray, vtkPoints
            from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData, vtkPolyLine
            from vtkmodules.vtkFiltersCore import vtkTubeFilter
            from vtkmodules.vtkFiltersModeling import vtkOutlineFilter
            from vtkmodules.vtkFiltersSources import vtkSphereSource
            from vtkmodules.vtkRenderingAnnotation import vtkAxesActor, vtkScalarBarActor
            from vtkmodules.vtkRenderingCore import (
                vtkActor,
                vtkColorTransferFunction,
                vtkPolyDataMapper,
                vtkRenderer,
                vtkRenderWindow,
                vtkWindowToImageFilter,
            )
            from vtkmodules.util.numpy_support import vtk_to_numpy
        except ImportError as exc:
            raise StudioDependencyError(
                "VTK is unavailable; install JAAM with the 'studio' extra"
            ) from exc

        # Bind names onto the instance so the rest of the class can reference them
        # without repeated imports.
        self._vtk_classes = {
            "vtkPoints": vtkPoints,
            "vtkFloatArray": vtkFloatArray,
            "vtkCellArray": vtkCellArray,
            "vtkPolyData": vtkPolyData,
            "vtkPolyLine": vtkPolyLine,
            "vtkOutlineFilter": vtkOutlineFilter,
            "vtkTubeFilter": vtkTubeFilter,
            "vtkSphereSource": vtkSphereSource,
            "vtkAxesActor": vtkAxesActor,
            "vtkScalarBarActor": vtkScalarBarActor,
            "vtkActor": vtkActor,
            "vtkColorTransferFunction": vtkColorTransferFunction,
            "vtkPolyDataMapper": vtkPolyDataMapper,
            "vtkRenderer": vtkRenderer,
            "vtkRenderWindow": vtkRenderWindow,
            "vtkWindowToImageFilter": vtkWindowToImageFilter,
            "vtk_to_numpy": vtk_to_numpy,
        }

    def _vtk(self, name: str):
        return self._vtk_classes[name]

    def _build(self) -> None:
        self._import_vtk()

        if self._render_window is None:
            self._renderer = self._vtk("vtkRenderer")()
            self._renderer.SetBackground(*self._BACKGROUND_COLOR)
            self._render_window = self._vtk("vtkRenderWindow")()
            self._render_window.OffScreenRenderingOn()
            # The image is already rendered at the panel's native resolution.
            # Multisampling adds work to every orbit frame and softens thin
            # antenna geometry after the texture reaches ImGui.
            self._render_window.SetMultiSamples(0)
            self._render_window.SetNumberOfLayers(2)
            self._renderer.SetLayer(0)
            self._render_window.AddRenderer(self._renderer)
            self._axis_renderer = self._vtk("vtkRenderer")()
            self._axis_renderer.SetLayer(1)
            self._axis_renderer.SetViewport(0.02, 0.02, 0.29, 0.36)
            self._axis_renderer.SetBackground(0.12, 0.12, 0.12)
            self._axis_renderer.InteractiveOff()
            self._render_window.AddRenderer(self._axis_renderer)
            axes_actor = self._vtk("vtkAxesActor")()
            axes_actor.SetTotalLength(1.0, 1.0, 1.0)
            self._axis_renderer.AddActor(axes_actor)
            self._axis_renderer.ResetCamera()
            axis_camera = self._axis_renderer.GetActiveCamera()
            self._axis_camera_base = (
                axis_camera.GetPosition(), axis_camera.GetFocalPoint(), axis_camera.GetViewUp(), axis_camera.GetViewAngle()
            )

        self._rebuild_actors()

    def _clear_actors(self) -> None:
        if self._renderer is None:
            return
        for actor in self._actors:
            self._renderer.RemoveViewProp(actor)
        self._actors.clear()

    def _rebuild_actors(self) -> None:
        self._clear_actors()
        if self._renderer is None:
            return

        for op in (self._ir.geometry if self._radiation is None or self._pattern_structure else ()):
            actor = self._geometry_actor(op)
            self._renderer.AddActor(actor)
            self._actors.append(actor)

            if isinstance(op, (CurveOp, WireOp)) and op.feed is not None:
                feed_actor = self._feed_actor(op.feed)
                self._renderer.AddActor(feed_actor)
                self._actors.append(feed_actor)

        if self._radiation is None:
            domain_actor = self._domain_actor(self._ir.domain_min, self._ir.domain_max)
            self._renderer.AddActor(domain_actor)
            self._actors.append(domain_actor)

        if self._show_mesh:
            grid_actor = self._grid_actor(self._ir)
            self._renderer.AddActor(grid_actor)
            self._actors.append(grid_actor)

        scalar_bar = None
        if self._radiation is not None:
            radiation_actor = self._radiation_actor(self._radiation)
            self._renderer.AddActor(radiation_actor)
            self._actors.append(radiation_actor)
            if self._pattern_grid:
                grid_actor = self._radiation_grid(radiation_actor.GetMapper().GetInput())
                self._renderer.AddActor(grid_actor)
                self._actors.append(grid_actor)
            scalar_bar = self._vtk("vtkScalarBarActor")()
            scalar_bar.SetLookupTable(radiation_actor.GetMapper().GetLookupTable())
            scalar_bar.SetTitle("Gain (dBi)")
            scalar_bar.SetNumberOfLabels(5)
            scalar_bar.SetPosition(0.84, 0.12)
            scalar_bar.SetWidth(0.11)
            scalar_bar.SetHeight(0.58)
            scalar_bar.GetTitleTextProperty().SetColor(0.95, 0.95, 0.95)
            scalar_bar.GetLabelTextProperty().SetColor(0.95, 0.95, 0.95)

        self._renderer.ResetCamera()
        camera = self._renderer.GetActiveCamera()
        self._camera_base = (camera.GetPosition(), camera.GetFocalPoint(), camera.GetViewUp(), camera.GetViewAngle())
        # Add the screen-space legend after fitting the world-space scene so it
        # cannot distort the camera bounds.
        if scalar_bar is not None:
            self._renderer.AddViewProp(scalar_bar)
            self._actors.append(scalar_bar)

    def _geometry_actor(self, op: GeometryOp) -> vtkActor:
        if isinstance(op, (CurveOp, WireOp)):
            return self._wire_actor(op.points, op.radius_m, self._WIRE_COLOR)
        if isinstance(op, BoxOp):
            return self._box_actor(op.start, op.stop, self._BOX_COLOR)
        return self._rotpoly_actor(op, self._ROTPOLY_COLOR)

    def _wire_actor(
        self, points: tuple[tuple[float, float, float], ...], radius_m: float, color: tuple[float, float, float]
    ) -> vtkActor:
        radius = radius_m if radius_m > 0 else self.DEFAULT_WIRE_RADIUS_M

        vtk_points = self._vtk("vtkPoints")()
        for point in points:
            vtk_points.InsertNextPoint(point)

        polyline = self._vtk("vtkPolyLine")()
        polyline.GetPointIds().SetNumberOfIds(len(points))
        for i in range(len(points)):
            polyline.GetPointIds().SetId(i, i)

        cells = self._vtk("vtkCellArray")()
        cells.InsertNextCell(polyline)

        polydata = self._vtk("vtkPolyData")()
        polydata.SetPoints(vtk_points)
        polydata.SetLines(cells)

        tube = self._vtk("vtkTubeFilter")()
        tube.SetInputData(polydata)
        tube.SetRadius(radius)
        tube.SetNumberOfSides(16)
        tube.CappingOn()

        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputConnection(tube.GetOutputPort())

        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetAmbient(0.65)
        actor.GetProperty().SetDiffuse(0.35)
        return actor

    def _box_actor(
        self, start: tuple[float, float, float], stop: tuple[float, float, float], color: tuple[float, float, float]
    ) -> vtkActor:
        from vtkmodules.vtkCommonDataModel import vtkImageData

        bounds = (
            min(start[0], stop[0]),
            max(start[0], stop[0]),
            min(start[1], stop[1]),
            max(start[1], stop[1]),
            min(start[2], stop[2]),
            max(start[2], stop[2]),
        )
        size = (
            max(bounds[1] - bounds[0], 1e-12),
            max(bounds[3] - bounds[2], 1e-12),
            max(bounds[5] - bounds[4], 1e-12),
        )

        image_data = vtkImageData()
        image_data.SetDimensions(2, 2, 2)
        image_data.SetOrigin(bounds[0], bounds[2], bounds[4])
        image_data.SetSpacing(size[0], size[1], size[2])

        outline = self._vtk("vtkOutlineFilter")()
        outline.SetInputData(image_data)

        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputConnection(outline.GetOutputPort())

        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetLineWidth(2.0)
        return actor

    def _rotpoly_actor(self, op: RotPolyOp, color: tuple[float, float, float]) -> vtkActor:
        # Represent the revolved profile as a cylinder aligned with its axis.
        from vtkmodules.vtkCommonTransforms import vtkTransform
        from vtkmodules.vtkFiltersGeneral import vtkTransformPolyDataFilter
        from vtkmodules.vtkFiltersSources import vtkCylinderSource

        radius = max((point[0] ** 2 + point[1] ** 2) ** 0.5 for point in op.points) if op.points else 0.0
        height = max(radius * 2, 1e-12)
        direction = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}[op.axis]
        center = (
            op.elevation * direction[0],
            op.elevation * direction[1],
            op.elevation * direction[2],
        )

        cylinder = vtkCylinderSource()
        cylinder.SetRadius(radius)
        cylinder.SetHeight(height)
        cylinder.SetResolution(32)

        transform = vtkTransform()
        if op.axis == "x":
            transform.RotateWXYZ(90, 0, 1, 0)
        elif op.axis == "y":
            transform.RotateWXYZ(90, 1, 0, 0)
        transform.Translate(*center)

        tpd = vtkTransformPolyDataFilter()
        tpd.SetInputConnection(cylinder.GetOutputPort())
        tpd.SetTransform(transform)

        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputConnection(tpd.GetOutputPort())

        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        return actor

    def _feed_actor(self, feed: FeedSpec) -> vtkActor:
        import math

        center = (
            (feed.start[0] + feed.stop[0]) / 2,
            (feed.start[1] + feed.stop[1]) / 2,
            (feed.start[2] + feed.stop[2]) / 2,
        )
        gap = math.dist(feed.start, feed.stop)
        # Keep the port marker small relative to the antenna so it reads as
        # a feed point, not a ball swallowing the wire.
        radius = min(self.DEFAULT_FEED_RADIUS_M, max(gap * 0.75, 1e-3))

        sphere = self._vtk("vtkSphereSource")()
        sphere.SetCenter(center)
        sphere.SetRadius(radius)
        sphere.SetThetaResolution(16)
        sphere.SetPhiResolution(16)

        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputConnection(sphere.GetOutputPort())

        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*self._FEED_COLOR)
        return actor

    def _domain_actor(
        self, domain_min: tuple[float, float, float], domain_max: tuple[float, float, float]
    ) -> vtkActor:
        return self._box_actor(domain_min, domain_max, self._DOMAIN_COLOR)

    def _grid_actor(self, ir: SimulationIR) -> vtkActor:
        from vtkmodules.vtkCommonCore import vtkPoints
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData

        x_lines, y_lines, z_lines = ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z
        if not x_lines or not y_lines or not z_lines:
            return self._domain_actor(ir.domain_min, ir.domain_max)
        x0, x1 = ir.domain_min[0], ir.domain_max[0]
        y0, y1 = ir.domain_min[1], ir.domain_max[1]
        z0, z1 = ir.domain_min[2], ir.domain_max[2]
        # Central slice planes so the grid cuts through the antenna instead of
        # sitting detached on the far domain walls.
        xm = x_lines[len(x_lines) // 2]
        ym = y_lines[len(y_lines) // 2]
        zm = z_lines[len(z_lines) // 2]
        points = vtkPoints()
        lines = vtkCellArray()

        def add_line(start: tuple[float, float, float], stop: tuple[float, float, float]) -> None:
            first = points.InsertNextPoint(*start)
            second = points.InsertNextPoint(*stop)
            lines.InsertNextCell(2)
            lines.InsertCellPoint(first)
            lines.InsertCellPoint(second)

        # XY plane at z=zm
        for x in x_lines:
            add_line((x, y0, zm), (x, y1, zm))
        for y in y_lines:
            add_line((x0, y, zm), (x1, y, zm))
        # XZ plane at y=ym
        for x in x_lines:
            add_line((x, ym, z0), (x, ym, z1))
        for z in z_lines:
            add_line((x0, ym, z), (x1, ym, z))
        # YZ plane at x=xm
        for y in y_lines:
            add_line((xm, y, z0), (xm, y, z1))
        for z in z_lines:
            add_line((xm, y0, z), (xm, y1, z))

        polydata = vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetLines(lines)
        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputData(polydata)
        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.28, 0.34, 0.40)
        actor.GetProperty().SetLineWidth(1.0)
        return actor

    def _radiation_actor(self, pattern: RadiationPattern) -> vtkActor:
        """Build a gain-shaped NF2FF surface with a gnuplot-style palette."""
        from vtkmodules.vtkCommonDataModel import vtkCellArray, vtkPolyData, vtkQuad

        theta_values = pattern.theta_deg
        phi_values = pattern.phi_deg
        if len(phi_values) > 1 and abs(phi_values[-1] - phi_values[0] - 360.0) < 1e-6:
            phi_values = phi_values[:-1]
        if len(theta_values) < 2 or len(phi_values) < 3:
            raise StudioDependencyError("NF2FF grid is too small for a 3D surface")

        gains = [value for row in pattern.gain_db for value in row]
        peak = max(gains)
        floor = max(min(gains), peak - 40.0)
        if peak - floor < 1e-9:
            floor = peak - 1.0
        span = max(
            self._ir.domain_max[index] - self._ir.domain_min[index]
            for index in range(3)
        )
        scale = max(span * 0.46, 1e-6)
        center = tuple(
            (self._ir.domain_min[index] + self._ir.domain_max[index]) * 0.5
            for index in range(3)
        )

        points = self._vtk("vtkPoints")()
        scalars = self._vtk("vtkFloatArray")()
        scalars.SetName("gain_dbi")
        phi_count = len(phi_values)
        surface = gain_surface_points(
            theta_values, phi_values,
            tuple(row[:phi_count] for row in pattern.gain_db),
            radial_scale=self._radial_scale,
        )
        for theta_index, theta_degrees in enumerate(theta_values):
            for phi_index, phi_degrees in enumerate(phi_values):
                gain = pattern.gain_db[theta_index][phi_index]
                point = surface[theta_index * phi_count + phi_index]
                points.InsertNextPoint(*(center[i] + scale * point[i] for i in range(3)))
                scalars.InsertNextValue(gain)

        cells = vtkCellArray()
        for theta_index in range(len(theta_values) - 1):
            for phi_index in range(phi_count):
                next_phi = (phi_index + 1) % phi_count
                quad = vtkQuad()
                quad.GetPointIds().SetId(0, theta_index * phi_count + phi_index)
                quad.GetPointIds().SetId(1, theta_index * phi_count + next_phi)
                quad.GetPointIds().SetId(2, (theta_index + 1) * phi_count + next_phi)
                quad.GetPointIds().SetId(3, (theta_index + 1) * phi_count + phi_index)
                cells.InsertNextCell(quad)

        polydata = vtkPolyData()
        polydata.SetPoints(points)
        polydata.SetPolys(cells)
        polydata.GetPointData().SetScalars(scalars)

        palette = self._vtk("vtkColorTransferFunction")()
        palette.AddRGBPoint(floor, 0.05, 0.05, 0.45)
        palette.AddRGBPoint(floor + (peak - floor) * 0.25, 0.0, 0.65, 1.0)
        palette.AddRGBPoint(floor + (peak - floor) * 0.50, 0.0, 0.85, 0.25)
        palette.AddRGBPoint(floor + (peak - floor) * 0.75, 1.0, 0.90, 0.0)
        palette.AddRGBPoint(peak, 0.95, 0.05, 0.0)

        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputData(polydata)
        mapper.SetLookupTable(palette)
        mapper.SetScalarRange(floor, peak)
        mapper.ScalarVisibilityOn()
        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        # Opaque, unlit colors correspond directly to the legend. Transparency
        # blended front and back lobes; lighting darkened the same gain by view.
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().LightingOff()
        return actor

    def _radiation_grid(self, surface):
        """Draw sparse angular lines without rebuilding a second surface."""
        pattern = self._radiation
        rows = len(pattern.theta_deg)
        columns = surface.GetNumberOfPoints() // rows
        lines = self._vtk("vtkCellArray")()

        def add(indices):
            lines.InsertNextCell(len(indices))
            for index in indices:
                lines.InsertCellPoint(index)

        # Choose by angle, not sample count: solver grids can have any spacing.
        theta_rows = {min(range(rows), key=lambda i: abs(pattern.theta_deg[i] - angle))
                      for angle in range(15, 180, 15)}
        phi_columns = {min(range(columns), key=lambda i: abs(pattern.phi_deg[i] - angle))
                       for angle in range(0, 360, 15)}
        for row in sorted(theta_rows):
            add([row * columns + col for col in range(columns)] + [row * columns])
        for col in sorted(phi_columns):
            add([row * columns + col for row in range(rows)])
        polydata = self._vtk("vtkPolyData")()
        polydata.SetPoints(surface.GetPoints())
        polydata.SetLines(lines)
        mapper = self._vtk("vtkPolyDataMapper")()
        mapper.SetInputData(polydata)
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        mapper.SetRelativeCoincidentTopologyLineOffsetParameters(0, -20)
        actor = self._vtk("vtkActor")()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.16, 0.19, 0.22)
        actor.GetProperty().LightingOff()
        return actor

    def set_pattern_style(self, radial_scale="arrl", grid=True, structure=False):
        if radial_scale not in ("arrl", "field", "db"):
            raise ValueError(f"unknown radial scale: {radial_scale}")
        style = (radial_scale, grid, structure)
        if style != (self._radial_scale, self._pattern_grid, self._pattern_structure):
            self._radial_scale, self._pattern_grid, self._pattern_structure = style
            if self._radiation is not None:
                self._rebuild_actors()

    def update_ir(self, ir: SimulationIR) -> None:
        """Rebuild the scene actors from a new IR without recreating the render window."""
        self._ir = ir
        self._rebuild_actors()

    def set_show_mesh(self, show_mesh: bool) -> None:
        if self._show_mesh != show_mesh:
            self._show_mesh = show_mesh
            self._rebuild_actors()

    def set_radiation_pattern(self, pattern: RadiationPattern | None) -> None:
        if self._radiation is not pattern:
            self._radiation = pattern
            self._rebuild_actors()

    def set_camera_view(self, azimuth: float, elevation: float, zoom: float = 1.0) -> None:
        """Set the orbit view used for the next render."""
        if self._renderer is None:
            return
        camera = self._renderer.GetActiveCamera()
        position, focal, up, angle = self._camera_base
        camera.SetPosition(position)
        camera.SetFocalPoint(focal)
        camera.SetViewUp(up)
        camera.SetViewAngle(angle)
        camera.Azimuth(azimuth)
        camera.Elevation(elevation)
        camera.Zoom(max(0.1, min(10.0, zoom)))
        camera.OrthogonalizeViewUp()
        self._renderer.ResetCameraClippingRange()
        if self._axis_renderer is not None:
            axis_camera = self._axis_renderer.GetActiveCamera()
            position, focal, up, angle = self._axis_camera_base
            axis_camera.SetPosition(position)
            axis_camera.SetFocalPoint(focal)
            axis_camera.SetViewUp(up)
            axis_camera.SetViewAngle(angle)
            axis_camera.Azimuth(azimuth)
            axis_camera.Elevation(elevation)
            axis_camera.OrthogonalizeViewUp()
            self._axis_renderer.ResetCameraClippingRange()

    def render_to_array(self, width: int, height: int) -> np.ndarray:
        """Render the current scene offscreen and return a contiguous RGBA uint8 array."""
        if self._render_window is None or self._renderer is None:
            raise StudioDependencyError("VTK renderer has not been initialized")

        self._render_window.SetSize(width, height)
        saved_context = _save_glx_context()
        try:
            self._render_window.Render()
            w2i = self._vtk("vtkWindowToImageFilter")()
            w2i.SetInput(self._render_window)
            w2i.SetInputBufferTypeToRGBA()
            w2i.ReadFrontBufferOff()
            w2i.Update()

            image_data = w2i.GetOutput()
            dims = image_data.GetDimensions()
            n_components = image_data.GetNumberOfScalarComponents()

            vtk_array = image_data.GetPointData().GetScalars()
            array = self._vtk("vtk_to_numpy")(vtk_array)
            array = array.reshape((dims[1], dims[0], n_components))
            array = np.flipud(array)
            if n_components > 4:
                array = array[:, :, :4]
            elif n_components == 3:
                alpha = np.full((*array.shape[:2], 1), 255, dtype=array.dtype)
                array = np.concatenate((array, alpha), axis=2)
            elif n_components == 1:
                array = np.repeat(array, 4, axis=2)
                array[:, :, 3] = 255
            if array.shape[2] != 4:
                raise StudioDependencyError(
                    f"VTK returned unsupported image channel count: {n_components}"
                )
            array = array.astype(np.uint8)
            # VTK offscreen vols return alpha ~0 for the background, which
            # ImGui blends as transparent (ghost text showing through).
            # Force a fully opaque frame.
            array[:, :, 3] = 255
            return np.ascontiguousarray(array)
        finally:
            _restore_glx_context(saved_context)
