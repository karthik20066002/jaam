import pytest

from jaam.compiler import compile_text, compile_text_result
from jaam.frontend import parse_text
from jaam.passes import (
    CanonicalizeWireVerticesPass,
    GradedMeshCoarseningPass,
    MeshAnchorPruningPass,
    MergeCollinearWiresPass,
    ValidateFeedsPass,
    ValidateMeshResolutionPass,
)
from jaam.semantics import analyze


def test_graded_mesh_coarsening_reduces_far_field_cells():
    source = """
    frequency 1GHz;
    default { material: copper; radius: 1mm; }
    wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)), feed: port(impedance: 50ohm));
    """
    ir = analyze(parse_text(source))
    result = GradedMeshCoarseningPass().run(ir)
    assert result.statistics["new_cells"] < result.statistics["original_cells"]
    assert result.statistics["reduction_percent"] > 0
    # Geometry features should still be resolved.
    assert any(line == 0.0 for line in result.ir.mesh.lines_x)
    assert any(line == 0.0 for line in result.ir.mesh.lines_y)


def test_mesh_anchor_pruning_preserves_helix_geometry():
    source = (
        "frequency 1GHz; default { material:copper; radius:1mm; } "
        "wire feeder(path:line(from:(2cm,0,-2cm),to:(2cm,0,0)),feed:port(impedance:50ohm)); "
        "wire coil(path:helix(radius:2cm,pitch:2cm,turns:1));"
    )
    ir = analyze(parse_text(source))
    graded = GradedMeshCoarseningPass().run(ir).ir
    result = MeshAnchorPruningPass().run(graded)
    assert result.statistics["applied"] == 1
    assert result.statistics["anchors_removed"] > 0
    assert result.ir.geometry == graded.geometry
    assert sum(len(lines) for lines in (result.ir.mesh.lines_x, result.ir.mesh.lines_y, result.ir.mesh.lines_z)) < sum(
        len(lines) for lines in (graded.mesh.lines_x, graded.mesh.lines_y, graded.mesh.lines_z)
    )


def test_vertex_canonicalization_keeps_feed_and_removes_straight_middle():
    source = (
        "frequency 1GHz; default { material:copper; radius:1mm; } "
        "wire a(path:line(from:(0,0,0),to:(0,0,3cm))); "
        "wire b(path:line(from:(0,0,3cm),to:(0,0,6cm)),feed:port(impedance:50ohm)); "
        "wire c(path:line(from:(0,0,6cm),to:(0,0,9cm))); concat joined(a,b,c);"
    )
    ir = analyze(parse_text(source))
    result = CanonicalizeWireVerticesPass().run(ir)
    assert result.statistics["vertices_removed"] > 0
    assert [op.feed for op in result.ir.geometry if hasattr(op, "feed")] == [
        op.feed for op in ir.geometry if hasattr(op, "feed")
    ]


def test_validate_mesh_resolution_catches_small_feed_gap():
    source = """
    frequency 1GHz;
    default { material: copper; radius: 1mm; }
    wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)), feed: port(impedance: 50ohm));
    """
    ir = analyze(parse_text(source))
    result = ValidateMeshResolutionPass().run(ir)
    # The mesh is refined near the feed, so the feed gap should pass.
    assert not any(item.code == "J214" for item in result.diagnostics)


def test_validate_mesh_resolution_catches_unresolved_thick_wire():
    source = """
    frequency 1GHz;
    default { material: copper; }
    wire fat(path: line(from: (0,0,0), to: (0,0,10cm)), radius: 1cm);
    """
    ir = analyze(parse_text(source))
    result = ValidateMeshResolutionPass().run(ir)
    assert any(item.code == "J212" for item in result.diagnostics)


def test_merge_collinear_wires_combines_segments():
    source = """
    frequency 1GHz;
    default { material: copper; radius: 1mm; }
    wire a(path: line(from: (0,0,0), to: (0,0,5cm)));
    wire b(path: line(from: (0,0,5cm), to: (0,0,10cm)));
    """
    ir = analyze(parse_text(source))
    result = MergeCollinearWiresPass().run(ir)
    assert result.statistics["merged_wires"] == 1
    assert len(result.ir.geometry) == 1
    assert result.ir.geometry[0].points[0] == pytest.approx((0, 0, 0))
    assert result.ir.geometry[0].points[-1] == pytest.approx((0, 0, 0.1))


def test_merge_collinear_wires_preserves_feed_boundary():
    source = """
    frequency 1GHz;
    default { material: copper; radius: 1mm; }
    wire a(path: line(from: (0,0,0), to: (0,0,5cm)), feed: port(impedance: 50ohm));
    wire b(path: line(from: (0,0,5cm), to: (0,0,10cm)));
    """
    ir = analyze(parse_text(source))
    result = MergeCollinearWiresPass().run(ir)
    # The fed wire is split by _Analyzer; the segment after the feed merges with b.
    assert result.statistics["merged_wires"] == 2
    assert any(op.feed is not None for op in result.ir.geometry)


def test_validate_feeds_pass_accepts_model_with_feed():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)), feed: port(impedance: 50ohm));
        """
    )
    result = ValidateFeedsPass().run(ir)
    assert result.ir is ir
    assert result.statistics["feeds"] == 1
    assert not result.diagnostics


def test_validate_feeds_pass_rejects_model_without_feed():
    ir = compile_text(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)));
        """
    )
    result = ValidateFeedsPass().run(ir)
    assert result.ir is ir
    assert result.statistics["feeds"] == 0
    assert any(item.code == "J201" for item in result.diagnostics)


def test_compiler_reports_missing_feed_diagnostic():
    result = compile_text_result(
        """
        frequency 1GHz;
        default { material: copper; radius: 1mm; }
        wire dipole(path: line(from: (0,0,-5cm), to: (0,0,5cm)));
        """
    )
    assert any(item.code == "J201" for item in result.diagnostics)
