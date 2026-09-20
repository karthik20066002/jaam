from pathlib import Path

from jaam.backends.meep import ampere_loop, meep_cylinders, meep_fcen, meep_resolution, meep_source
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
    assert meep_resolution(ir) >= 4.0 / 0.003


def test_ampere_loop_is_perpendicular_to_feed() -> None:
    points = ampere_loop((0.02, 0.0, 0.0), "y", 0.0015)
    assert len(points) == 4
    assert {name for _, name in points} == {"hx", "hz"}
    assert all(abs(p[1] - 0.0) < 1e-12 for p, _ in points)


def test_dipole_source_is_z_directed() -> None:
    ir = compile_file(Path("examples/dipole.jaam"))
    source = meep_source(ir)
    assert source["component"] == "z"
