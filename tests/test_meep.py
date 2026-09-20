from pathlib import Path

from jaam.backends.meep import ampere_loop, ampere_loop_half_width, meep_cylinders, meep_fcen, meep_resolution, meep_source
from jaam.compiler import compile_file
from jaam.emitter import emit_meep_config



def test_meep_yagi_uses_finite_radius_cylinders_and_y_feed() -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    cylinders = meep_cylinders(ir)
    assert cylinders
    assert all(item["radius"] == 0.0015 for item in cylinders)
    assert len(cylinders) == 6
    source = meep_source(ir)
    assert source["component"] == "y"
    assert source["impedance_ohm"] == 50.0
    assert source["gap_m"] > 0
    text = emit_meep_config(ir)
    assert text == emit_meep_config(ir)
    assert '"component": "y"' in text


def test_meep_frequency_is_in_units_of_c_over_metre() -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    assert abs(meep_fcen(ir) - 2.45e9 / 299_792_458.0) < 1e-12
    wavelength = 299_792_458.0 / ir.frequency.center_hz
    assert meep_resolution(ir) == 20.0 / wavelength


def test_meep_resolution_is_wavelength_driven_not_wire_radius_driven() -> None:
    """Regression: resolution must not scale with wire radius.

    It used to (4 cells across the wire diameter), which sounds reasonable
    in isolation but forces Meep's single global grid resolution to that
    value everywhere in the domain: for examples/dipole.jaam's 1mm wire
    radius in a decimetre-scale domain, that demanded ~2.7 billion cells
    (~130GB) for a model whose wavelength alone only needs ~100,000.
    """
    ir = compile_file(Path("examples/dipole.jaam"))
    wavelength = 299_792_458.0 / ir.frequency.center_hz
    radii = [op.radius_m for op in ir.geometry if hasattr(op, "radius_m")]
    assert radii and min(radii) <= 0.001  # this model's thin wire is still present
    assert meep_resolution(ir) == 20.0 / wavelength
    assert meep_resolution(ir) < 100.0  # not the ~2000 the old wire-radius term demanded


def test_ampere_loop_is_perpendicular_to_feed() -> None:
    points = ampere_loop((0.02, 0.0, 0.0), "y", 0.0015, 163.4)
    assert len(points) == 4
    assert {name for _, name in points} == {"hx", "hz"}
    assert all(abs(p[1] - 0.0) < 1e-12 for p, _ in points)


def test_ampere_loop_spans_multiple_grid_cells_not_just_wire_radius() -> None:
    """Regression: a loop sized only to the wire's own radius falls within a
    single Yee cell once resolution is wavelength- rather than radius-driven,
    so the 4 H-field DFT samples are interpolation noise rather than real
    circulation. Confirmed empirically: at the old radius-only sizing, a
    Yagi's measured |gamma| came out numerically greater than 1 -- a
    physical impossibility for a passive reflection coefficient.
    """
    radius = 0.0015
    resolution = 163.4  # examples/yagi.jaam and examples/helix.jaam's actual resolution
    cell_size = 1.0 / resolution
    half_width = ampere_loop_half_width(radius, resolution)
    assert half_width > 2 * radius  # not just the old radius-based value
    assert half_width >= cell_size  # spans at least one full cell each way


def test_dipole_source_is_z_directed() -> None:
    ir = compile_file(Path("examples/dipole.jaam"))
    source = meep_source(ir)
    assert source["component"] == "z"
