from pathlib import Path

import pytest

from jaam.compiler import compile_file, compile_text
from jaam.diagnostics import CompilationError
from jaam.ir import BoxOp, CurveOp, RotPolyOp, WireOp


def test_canonical_yagi_compiles():
    ir = compile_file(Path("examples/yagi.jaam"))
    assert ir.frequency.single_hz == 2.45e9
    assert ir.boundary == "PML_8"
    assert sum(isinstance(op, CurveOp) for op in ir.geometry) == 6
    assert sum(op.feed is not None for op in ir.geometry if isinstance(op, CurveOp)) == 1
    assert all(len(lines) > 2 for lines in (ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z))
    wavelength = 299_792_458 / 2.45e9
    assert ir.domain_max[2] >= 0.64 * wavelength


def test_thick_wire_and_unit_conversion():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material: copper; }
        wire fat(path: line(from: (0,0,0), to: (0,0,10cm)), radius: 1cm);
        """
    )
    assert isinstance(ir.geometry[0], WireOp)
    assert ir.geometry[0].radius_m == pytest.approx(0.01)


def test_ground_extends_to_domain():
    ir = compile_text(
        """
        frequency 100MHz;
        box ground(size: (1m,1m,0.5m), at: (0,0,-0.5m), material: earth_dry);
        """
    )
    ground = next(op for op in ir.geometry if isinstance(op, BoxOp))
    assert ground.start[:2] == ir.domain_min[:2]
    assert ground.stop[:2] == ir.domain_max[:2]


def test_frequency_modes_are_exclusive():
    with pytest.raises(CompilationError) as caught:
        compile_text(
            "frequency 1GHz; frequency_lower 1GHz; frequency_upper 2GHz; "
            "box b(size:(1,1,1), at:(0,0,0), material:pec);"
        )
    assert any(item.code == "J103" for item in caught.value.diagnostics)


def test_unknown_material_is_rejected():
    with pytest.raises(CompilationError) as caught:
        compile_text(
            "frequency 1GHz; box b(size:(1,1,1), at:(0,0,0), material:unobtanium);"
        )
    assert any(item.code == "J146" for item in caught.value.diagnostics)


def test_concat_consumes_and_chains_sources():
    ir = compile_text(
        """
        frequency 1GHz;
        default wire { material:copper; radius:1mm; }
        wire a(path:line(from:(0,0,0), to:(0,0,1cm)));
        wire b(path:line(from:(1m,0,0), to:(1m,0,2cm)));
        concat joined(a,b);
        """
    )
    assert len(ir.geometry) == 1
    assert ir.geometry[0].name == "joined"
    assert ir.geometry[0].points[-1] == pytest.approx((0, 0, 0.03))


def test_revolve_consumes_planar_seed():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material:copper; }
        wire profile(path:line(from:(1cm,0,0), to:(2cm,1cm,0)), radius:1mm);
        revolve dish(seed:profile, axis:z);
        """
    )
    assert len(ir.geometry) == 1
    assert isinstance(ir.geometry[0], RotPolyOp)


def test_exact_geometry_is_deduplicated():
    ir = compile_text(
        """
        frequency 1GHz;
        box a(size:(1cm,1cm,1cm), at:(0,0,0), material:pec);
        box b(size:(1cm,1cm,1cm), at:(0,0,0), material:pec);
        """
    )
    assert len(ir.geometry) == 1
    assert any("deduplicated" in warning for warning in ir.warnings)


def test_negative_box_size_is_rejected():
    with pytest.raises(CompilationError) as caught:
        compile_text("frequency 1GHz; box b(size:(1cm,-1cm,1cm), at:(0,0,0), material:pec);")
    assert any(item.code == "J123" for item in caught.value.diagnostics)
