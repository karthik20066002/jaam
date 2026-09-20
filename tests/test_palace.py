from pathlib import Path

from jaam.backends.common import BACKENDS
from jaam.backends.palace import _palace_command
from jaam.container import PALACE_IMAGE, ContainerEngine
from jaam.backends.palace import (
    ATTR_ABSORB,
    ATTR_AIR,
    ATTR_PEC,
    ATTR_PORT,
    build_palace_config,
    palace_direction,
    parse_farfield_re,
    parse_port_s,
)
from jaam.compiler import compile_file
from jaam.emitter import emit_palace_config
from jaam.ir import FeedSpec


def test_palace_config_for_yagi_uses_driven_lumped_port() -> None:
    ir = compile_file(Path("examples/yagi.jaam"))
    config = build_palace_config(ir)
    assert config["Problem"]["Type"] == "Driven"
    assert config["Domains"]["Materials"][0]["Attributes"] == [ATTR_AIR]
    assert config["Boundaries"]["PEC"]["Attributes"] == [ATTR_PEC]
    assert config["Boundaries"]["Absorbing"]["Attributes"] == [ATTR_ABSORB]
    driven = config["Solver"]["Driven"]["Samples"][0]
    assert driven["Type"] == "Point"
    assert driven["Freq"] == [2.45]
    port = config["Boundaries"]["LumpedPort"][0]
    assert port["Attributes"] == [ATTR_PORT]
    assert port["R"] == 50.0
    assert port["Direction"] == "+Y"
    assert port["Excitation"] is True
    samples = config["Boundaries"]["Postprocessing"]["FarField"]["ThetaPhis"]
    assert [90.0, 0.0] in samples
    assert [90.0, 180.0] in samples
    text = emit_palace_config(ir)
    assert '"Type": "Driven"' in text
    assert text == emit_palace_config(ir)


def test_palace_direction_follows_feed_axis() -> None:
    assert palace_direction(FeedSpec(50.0, (0, 0, -1), (0, 0, 1), "z")) == "+Z"
    assert palace_direction(FeedSpec(50.0, (0, 1, 0), (0, -1, 0), "y")) == "-Y"


def test_parse_port_s_csv(tmp_path: Path) -> None:
    path = tmp_path / "port-S.csv"
    path.write_text(
        "        f (GHz),            Re{S[1][1]},            Im{S[1][1]},          |S[1][1]| (dB),     arg{S[1][1]} (deg.)\n"
        " 2.45000000e+00,        +1.000000000000e-01,        -2.000000000000e-01,        -1.234000000000e+01,         0.0\n",
        encoding="utf-8",
    )
    rows = parse_port_s(path)
    assert rows[0]["frequency_hz"] == 2.45e9
    assert rows[0]["s11_db"] == -12.34
    assert rows[0]["s11_real"] == 0.1
    assert rows[0]["s11_imag"] == -0.2


def test_parse_farfield_re_builds_directivity_grid(tmp_path: Path) -> None:
    path = tmp_path / "farfield-rE.csv"
    header = (
        "f (GHz),exc,theta (deg.),phi (deg.),"
        "r*Re{E_x} (V),r*Im{E_x} (V),r*Re{E_y} (V),r*Im{E_y} (V),r*Re{E_z} (V),r*Im{E_z} (V)\n"
    )
    rows = [header]
    for theta in (0.0, 90.0, 180.0):
        for phi in (0.0, 90.0, 180.0, 270.0, 360.0):
            ez = 1.0 if theta == 90.0 else 0.1
            rows.append(f"2.45,1,{theta},{phi},0,0,0,0,{ez},0\n")
    path.write_text("".join(rows), encoding="utf-8")
    frequency, theta, phi, gain, peak = parse_farfield_re(path)
    assert frequency == 2.45e9
    assert theta == (0.0, 90.0, 180.0)
    assert 90.0 in phi
    equator = gain[theta.index(90.0)]
    pole = gain[theta.index(0.0)]
    assert max(equator) > max(pole)
    assert peak == max(value for row in gain for value in row)


def test_backend_names() -> None:
    assert BACKENDS == ("openems", "palace", "meep", "scuff")


def test_palace_invoker_falls_back_to_container(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jaam.backends.palace.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "jaam.container.ContainerEngine.discover",
        classmethod(lambda cls: ContainerEngine("podman")),
    )
    monkeypatch.setattr("jaam.container.ContainerEngine.image_exists", lambda self, image=None: True)
    command = _palace_command(tmp_path)
    assert PALACE_IMAGE in command
    assert command[-2:] == ["--serial", "palace.json"]
