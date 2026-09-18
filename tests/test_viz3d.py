"""Smoke tests for the VTK offscreen antenna geometry visualiser."""

from __future__ import annotations

import numpy as np
import pytest

from jaam.ir import (
    BoxOp,
    FeedSpec,
    FrequencySpec,
    MaterialSpec,
    MeshSpec,
    SimulationIR,
    WireOp,
)

vtk = pytest.importorskip("vtkmodules", reason="VTK is not installed")

from jaam.viz3d import AntennaViz3D  # noqa: E402
from jaam.results import RadiationPattern  # noqa: E402


def _minimal_ir() -> SimulationIR:
    """Return a minimal SimulationIR containing one wire and one box."""
    copper = MaterialSpec(name="copper", kind="metal", conductivity=5.8e7)
    substrate = MaterialSpec(name="substrate", kind="dielectric", epsilon=4.3)
    return SimulationIR(
        frequency=FrequencySpec(lower_hz=1e9, upper_hz=2e9),
        boundary="MUR",
        materials=(copper, substrate),
        geometry=(
            WireOp(
                name="driven-wire",
                points=((-0.25, 0.0, 0.0), (0.25, 0.0, 0.0)),
                material="copper",
                radius_m=1e-3,
                feed=FeedSpec(
                    impedance_ohm=50.0,
                    start=(-0.01, 0.0, 0.0),
                    stop=(0.01, 0.0, 0.0),
                    direction="x",
                ),
            ),
            BoxOp(
                name="ground-plane",
                start=(-0.3, -0.3, -0.05),
                stop=(0.3, 0.3, 0.0),
                material="copper",
            ),
        ),
        mesh=MeshSpec(
            lines_x=(-0.3, -0.25, 0.0, 0.25, 0.3),
            lines_y=(-0.3, 0.0, 0.3),
            lines_z=(-0.05, 0.0, 0.05),
            max_resolution_m=1e-3,
        ),
        domain_min=(-0.35, -0.35, -0.1),
        domain_max=(0.35, 0.35, 0.1),
    )


def test_viz3d_smoke() -> None:
    """AntennaViz3D renders a wire-and-box scene to a uint8 RGBA array."""
    ir = _minimal_ir()
    viz = AntennaViz3D(ir)

    image = viz.render_to_array(200, 200)

    assert isinstance(image, np.ndarray)
    assert image.shape == (200, 200, 4)
    assert image.dtype == np.uint8


def test_camera_view_is_absolute_not_accumulated() -> None:
    viz = AntennaViz3D(_minimal_ir(), show_mesh=False)
    viz.set_camera_view(20, 15, 1.2)
    first = viz._renderer.GetActiveCamera().GetPosition()
    viz.set_camera_view(20, 15, 1.2)
    assert viz._renderer.GetActiveCamera().GetPosition() == pytest.approx(first)


def test_nf2ff_surface_uses_gain_scalars_and_renders() -> None:
    pattern = RadiationPattern(
        frequency_hz=1e9,
        theta_deg=(0.0, 90.0, 180.0),
        phi_deg=(0.0, 90.0, 180.0, 270.0, 360.0),
        gain_db=((0.0, 0.0, 0.0, 0.0, 0.0), (2.0, -3.0, -8.0, -3.0, 2.0), (0.0, 0.0, 0.0, 0.0, 0.0)),
    )
    viz = AntennaViz3D(_minimal_ir(), show_mesh=False)
    viz.set_radiation_pattern(pattern)

    image = viz.render_to_array(240, 180)

    assert image.shape == (180, 240, 4)
    assert viz._actors[0].GetMapper().GetScalarRange() == pytest.approx((-8.0, 2.0))


def test_farfield_preserves_deep_nulls_and_export_orientation() -> None:
    from jaam.farfield import gain_surface_points

    pattern = RadiationPattern(1e9, (0, 90, 180), (0, 90, 180, 270, 360),
        ((-60,) * 5, (2, -60, -8, -60, 2), (-60,) * 5))
    ir = _minimal_ir()
    viz = AntennaViz3D(ir, show_mesh=False)
    viz.set_pattern_style("field", False, False)
    actor = viz._radiation_actor(pattern)
    mesh = actor.GetMapper().GetInput()
    expected = gain_surface_points(pattern.theta_deg, pattern.phi_deg[:-1],
                                   tuple(row[:-1] for row in pattern.gain_db))
    center = np.array(ir.domain_min) / 2 + np.array(ir.domain_max) / 2
    scale = max(np.array(ir.domain_max) - np.array(ir.domain_min)) * 0.46
    for index, point in enumerate(expected):
        assert mesh.GetPoint(index) == pytest.approx(center + scale * np.array(point), abs=1e-8)
    assert actor.GetProperty().GetOpacity() == 1
    assert not actor.GetProperty().GetLighting()


def test_pattern_style_switch_rebuilds_without_changing_gain():
    pattern = RadiationPattern(1e9, (0, 90, 180), (0, 90, 180, 270, 360),
        ((-30,) * 5, (2, -28, -8, -28, 2), (-30,) * 5))
    viz = AntennaViz3D(_minimal_ir(), show_mesh=False)
    viz.set_radiation_pattern(pattern)
    arrl = viz._actors[0].GetMapper().GetInput()
    point = arrl.GetPoint(5)
    scalar = arrl.GetPointData().GetScalars().GetTuple1(5)
    count = viz._renderer.GetViewProps().GetNumberOfItems()
    viz.set_pattern_style("field", False, False)
    linear = viz._actors[0].GetMapper().GetInput()
    assert linear.GetPoint(5) != pytest.approx(point)
    assert linear.GetPointData().GetScalars().GetTuple1(5) == scalar
    assert viz._renderer.GetViewProps().GetNumberOfItems() == count - 1
