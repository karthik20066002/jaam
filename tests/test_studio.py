from jaam.studio import _nearest_polar_sample


def test_polar_hover_reports_pattern_sample_instead_of_cursor_radius() -> None:
    angles = (-180.0, -90.0, 0.0, 90.0, 180.0)
    gains = (-4.0, 1.5, 2.13, 1.5, -4.0)

    assert _nearest_polar_sample(1.51, angles, gains) == (0.0, 2.13)
    assert _nearest_polar_sample(-92.0, angles, gains) == (-90.0, 1.5)
