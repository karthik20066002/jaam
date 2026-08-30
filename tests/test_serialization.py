import json
from pathlib import Path

from jaam.compiler import compile_file_result
from jaam.serialization import compilation_to_dict, ir_to_dict


def test_ir_serialization_is_versioned_and_json_safe():
    result = compile_file_result(Path("examples/yagi.jaam"))
    payload = ir_to_dict(result.ir)
    assert payload["schemaVersion"] == 1
    assert payload["geometry"][0]["kind"] == "curve"
    json.dumps(payload, sort_keys=True)


def test_compilation_serialization_includes_trace_and_source_map():
    payload = compilation_to_dict(compile_file_result(Path("examples/yagi.jaam")))
    assert payload["passes"][0]["name"] == "parse"
    assert payload["sourceMap"]["driven__a"]["line"] == 13
    assert payload["ir"]["mesh"]["lines_x"]
