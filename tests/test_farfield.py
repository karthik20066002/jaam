import xml.etree.ElementTree as ET

import pytest

from jaam.farfield import gain_surface_points, write_farfield_vtp, write_nf2ff_csv


def test_gain_surface_is_normalized_and_oriented():
    points = gain_surface_points((0, 90, 180), (0, 90), ((0, 0), (10, 0), (0, 0)))
    assert points[2] == pytest.approx((1, 0, 0))
    assert points[0][2] == pytest.approx(10 ** (-10 / 20))
    assert points[-1][2] < 0


def test_farfield_serializers(tmp_path):
    theta, phi = (0, 90, 180), (0, 180, 360)
    gain = ((0, 0, 0), (3, -2, 3), (0, 0, 0))
    csv_path = tmp_path / "nf2ff.csv"
    vtp_path = tmp_path / "farfield.vtp"
    write_nf2ff_csv(csv_path, 1e9, theta, phi, gain)
    write_farfield_vtp(vtp_path, theta, phi, gain)
    assert len(csv_path.read_text().splitlines()) == 10
    root = ET.parse(vtp_path).getroot()
    piece = root.find("./PolyData/Piece")
    assert piece.attrib["NumberOfPoints"] == "9"
    assert piece.attrib["NumberOfPolys"] == "4"


def test_arrl_grid_three_db_steps_and_cardinal_directions():
    points = gain_surface_points((90,), (0, 90, 180, 270),
                                ((2, -1, -4, -28),), radial_scale="arrl")
    assert points[0] == pytest.approx((1, 0, 0))
    assert points[1] == pytest.approx((0, 0.89, 0))
    assert points[2] == pytest.approx((-0.89 ** 2, 0, 0))
    assert points[3] == pytest.approx((0, -0.89 ** 10, 0))


def test_db_display_floor_does_not_change_gain_samples():
    gains = ((2, -18, -60),)
    points = gain_surface_points((90,), (0, 90, 180), gains, radial_scale="db")
    assert points[1] == pytest.approx((0, 0.5, 0))
    assert points[2] == pytest.approx((0, 0, 0))
    assert gains == ((2, -18, -60),)
