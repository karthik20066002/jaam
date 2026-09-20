from pathlib import Path

import pytest

from jaam.compiler import compile_file_result
from jaam.scene import build_scene, save_scene_vtm

pv = pytest.importorskip("pyvista")


def test_scene_contains_geometry_domain_feed_and_metadata(tmp_path):
    result = compile_file_result(Path("examples/yagi.jaam"))
    scene = build_scene(result, include_mesh=True)
    assert "driven__a" in scene.keys()
    assert "driven__a:feed" in scene.keys()
    assert "simulation-domain" in scene.keys()
    assert "fdtd-grid" in scene.keys()
    actor = scene["driven__a"]
    assert actor.field_data["primitive_name"][0] == "driven__a"
    assert "examples/yagi.jaam:13" in actor.field_data["source_span"][0]
    output = tmp_path / "scene.vtm"
    save_scene_vtm(result, output)
    assert output.exists()
