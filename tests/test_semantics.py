from pathlib import Path

import pytest

from jaam.compiler import compile_file, compile_file_result, compile_text
from jaam.diagnostics import CompilationError
from jaam.ir import BoxOp, CurveOp, RotPolyOp, WireOp
from jaam.frontend import parse_text
from jaam.semantics import analyze


def test_semantic_pass_trace_is_ordered_and_measured():
    source = (
        "frequency 1GHz; default { material:copper; radius:1mm; } "
        "wire element(path:line(from:(-1cm,0,0),to:(1cm,0,0)));"
    )
    entries = []
    analyze(parse_text(source), trace=lambda name, duration, stats: entries.append((name, duration, stats)))
    assert [entry[0] for entry in entries] == [
        "directives-and-defaults",
        "geometry-expansion-and-unit-normalization",
        "semantic-validation",
        "dead-structure-elimination",
        "thin-and-thick-wire-lowering",
        "exact-geometry-deduplication",
        "domain-and-mesh-construction",
    ]
    assert all(duration >= 0 for _, duration, _ in entries)
    assert entries[-1][2]["mesh_cells"] > 0


def test_helix_fdtd_cells_are_not_millions() -> None:
    ir = compile_file(Path("examples/helix.jaam"))
    cells = (len(ir.mesh.lines_x) - 1) * (len(ir.mesh.lines_y) - 1) * (len(ir.mesh.lines_z) - 1)
    points = sum(len(op.points) for op in ir.geometry if hasattr(op, "points"))
    assert 50 <= points <= 140
    assert cells < 400_000
    radius = 0.0015
    stem_x = 0.0195
    assert any(abs(line - (stem_x - radius)) < 1e-9 for line in ir.mesh.lines_x)
    assert any(abs(line - (stem_x + radius)) < 1e-9 for line in ir.mesh.lines_x)


def test_yagi_feed_port_spans_the_full_metal_gap() -> None:
    """Regression: the port must touch both conductor ends, not float in a
    narrower sub-segment centered inside the metal gap.

    A port narrower than the metal gap leaves a physically disconnected
    sliver of free space between the port terminals and the actual wire
    ends on each side -- the port excites nothing but its own capacitance
    to two nearby, unconnected stubs. Confirmed against SCUFF-EM (whose
    port sits directly on the conductor rim): the narrower port produced a
    near-total-mismatch, huge-reactance result on both openEMS and Meep for
    the identical geometry.
    """
    ir = compile_file(Path("examples/yagi.jaam"))
    fed = next(op for op in ir.geometry if getattr(op, "feed", None) is not None)
    other = next(op for op in ir.geometry if op.name.startswith("driven__") and op is not fed)
    feed = fed.feed
    assert feed is not None
    metal_lo = min(fed.points[-1][1], other.points[0][1])
    metal_hi = max(fed.points[-1][1], other.points[0][1])
    port_lo = min(feed.start[1], feed.stop[1])
    port_hi = max(feed.start[1], feed.stop[1])
    assert abs(metal_lo - port_lo) < 1e-9
    assert abs(metal_hi - port_hi) < 1e-9


def test_yagi_mesh_resolves_declared_radius() -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    radius = 0.0015
    for value in (-radius, -radius / 2, radius / 2, radius):
        assert any(abs(line - value) < 1e-9 for line in ir.mesh.lines_z)


def test_helix_example_compiles():
    ir = compile_file(Path("examples/helix.jaam"))
    assert ir.frequency.single_hz == 2.45e9
    wires = [op for op in ir.geometry if hasattr(op, "points")]
    assert any(op.feed is not None for op in wires)
    assert sum(len(op.points) for op in wires) > 24
    xs = [p[0] for op in wires for p in op.points]
    zs = [p[2] for op in wires for p in op.points]
    assert max(xs) - min(xs) > 0.03
    assert max(zs) - min(zs) > 0.1


def test_canonical_yagi_compiles():
    ir = compile_file(Path("examples/yagi.jaam"))
    assert ir.frequency.single_hz == 2.45e9
    assert ir.boundary == "PML_8"
    assert sum(isinstance(op, CurveOp) for op in ir.geometry) == 6
    assert sum(op.feed is not None for op in ir.geometry if isinstance(op, CurveOp)) == 1
    assert all(len(lines) > 2 for lines in (ir.mesh.lines_x, ir.mesh.lines_y, ir.mesh.lines_z))
    wavelength = 299_792_458 / 2.45e9
    assert ir.domain_max[2] >= 0.64 * wavelength


def test_compilation_result_links_lowered_geometry_to_source():
    result = compile_file_result(Path("examples/yagi.jaam"))
    assert result.ast.source == Path("examples/yagi.jaam")
    assert result.ir.geometry
    assert result.passes[0].name == "parse"
    assert result.duration_ns >= 0
    assert result.source_map["driven__a"].line == 13
    assert result.source_map["driven__b"].line == 13


def test_scuff_compile_skips_fdtd_mesh_passes() -> None:
    scuff = compile_file_result(Path("examples/yagi.jaam"), backend="scuff")
    openems = compile_file_result(Path("examples/yagi.jaam"), backend="openems")
    assert "graded-mesh-coarsening" not in {item.name for item in scuff.passes}
    assert "graded-mesh-coarsening" in {item.name for item in openems.passes}


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
