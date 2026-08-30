import math

import pytest

from jaam.ir import BoxOp
from jaam.plots import (
    distance,
    front_to_back_ratio,
    half_power_beamwidth,
    impedance_from_reflection,
    intersects_slice,
    mesh_cell_size,
    normalize_gain,
    project_geometry,
    reflection_from_impedance,
)


def test_xy_projection_and_slice_for_box():
    box = BoxOp("sample", (-1, -2, -3), (1, 2, 3), "pec")
    assert project_geometry(box, "xy") == ((-1, -2), (1, -2), (1, 2), (-1, 2), (-1, -2))
    assert intersects_slice(box, "xy", 2.5)
    assert not intersects_slice(box, "xy", 3.1)


def test_measurements_and_mesh_cell_lookup():
    assert distance((0, 0, 0), (3, 4, 0)) == 5
    assert mesh_cell_size((-1, 0, 0.25, 1), 0.1) == pytest.approx(0.25)
    assert mesh_cell_size((-1, 1), 2) is None


def test_smith_chart_identities():
    assert reflection_from_impedance(50, 0) == pytest.approx(0j)
    assert reflection_from_impedance(0, 0) == pytest.approx(-1 + 0j)
    assert reflection_from_impedance(math.inf, 0) == pytest.approx(1 + 0j)
    assert reflection_from_impedance(50, 50).imag > 0
    assert reflection_from_impedance(50, -50).imag < 0
    assert impedance_from_reflection(0j) == pytest.approx(50 + 0j)


def test_radiation_metrics_with_synthetic_cut():
    angles = (-90, -60, -30, 0, 30, 60, 90, 180)
    gain = (-12, -6, -3, 0, -3, -6, -12, -18)
    assert normalize_gain((1, 4, 2)) == (-3, 0, -2)
    assert half_power_beamwidth(angles, gain) == pytest.approx(60)
    assert front_to_back_ratio(angles, gain) == pytest.approx(18)
