from pathlib import Path

from jaam.backends.scuff import AXIAL_MM, NCIRC, _write_sphere_ep, scuff_objects, write_scuff_inputs
from jaam.viz3d import load_gmsh22_triangles
from jaam.compiler import compile_file
from jaam.emitter import emit_scuff_config


def test_scuff_yagi_mesh_has_six_open_tubes(tmp_path: Path) -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    objects = scuff_objects(ir)
    names = [item["name"] for item in objects]
    assert "driven__a" in names
    assert "driven__b" in names
    assert len(objects) == 6
    assert all(item["radius_mm"] == 1.5 for item in objects)
    job = write_scuff_inputs(ir, tmp_path, stem="yagi")
    mesh = job["mesh"].read_text()
    assert mesh.splitlines()[1] == "2.2 0 8"
    assert "PhysicalNames" in mesh
    ports = job["ports"].read_text()
    assert "POBJECT driven__b" in ports
    assert "MOBJECT driven__a" in ports
    assert "PPOLYGON" in ports
    assert job["currents"].read_text().startswith("2.45")
    assert job["triangles"] > 0
    points, triangles = load_gmsh22_triangles(job["mesh"])
    assert len(points) == job["nodes"]
    assert len(triangles) == job["triangles"]
    assert all(0 <= index < len(points) for tri in triangles for index in tri)


def test_scuff_manifest_is_deterministic() -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    text = emit_scuff_config(ir)
    assert text == emit_scuff_config(ir)
    assert '"units": "mm"' in text
    assert "driven__a" in text


def test_scuff_preview_epfile_is_15_degree_grid(tmp_path: Path) -> None:
    thetas, phis = _write_sphere_ep(tmp_path / "sphere.ep", 1000.0, 15)
    assert thetas[0] == 0.0 and thetas[-1] == 180.0
    assert phis[0] == 0.0 and phis[-1] == 360.0
    assert thetas[1] - thetas[0] == 15.0
    assert AXIAL_MM == 4.0
    assert NCIRC == 8


def test_helix_becomes_a_tube() -> None:
    ir = compile_file(Path("examples/helix.jaam"))
    objects = scuff_objects(ir)
    assert objects
    assert max(len(item["points_mm"]) for item in objects) > 8


def test_scuff_port_polygons_sit_on_tube_rims(tmp_path: Path) -> None:
    """Regression: polygons must encircle the open tube rims (metal-gap ends).

    Placing them on the feed faces leaves them floating in the empty gap and
    scuff-rf aborts with 'no edges specified or detected for positive port'.
    """
    import math

    ir = compile_file(Path("examples/yagi.jaam"))
    feed = next(op.feed for op in ir.geometry if getattr(op, "feed", None) is not None)
    feed_mid = tuple((feed.start[i] + feed.stop[i]) / 2 for i in range(3))
    job = write_scuff_inputs(ir, tmp_path, stem="yagi-rims")
    objects = {item["name"]: item for item in scuff_objects(ir)}
    lines = job["ports"].read_text().splitlines()
    for key, name in (("PPOLYGON", "driven__b"), ("MPOLYGON", "driven__a")):
        values = [float(tok) for tok in next(item for item in lines if item.strip().startswith(key)).split()[1:]]
        centroid = tuple(sum(values[i::3]) / 8 for i in range(3))
        ends = (objects[name]["points_mm"][0], objects[name]["points_mm"][-1])
        nearest = min(ends, key=lambda p: math.dist(p, tuple(v * 1000.0 for v in feed_mid)))
        assert math.dist(centroid, nearest) < 1e-9
