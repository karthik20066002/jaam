from jaam.results import load_nf2ff


def test_load_radiation_pattern_and_extract_principal_cuts(tmp_path):
    path = tmp_path / "nf2ff.csv"
    rows = ["frequency_hz,theta_deg,phi_deg,gain_db"]
    for theta in (0, 90, 180):
        for phi in (0, 90, 180, 270, 360):
            rows.append(f"1000000000,{theta},{phi},{10 - abs(theta-90)/9 - min(phi,360-phi)/18}")
    path.write_text("\n".join(rows) + "\n")
    pattern = load_nf2ff(path)
    assert pattern.frequency_hz == 1e9
    assert pattern.peak_gain_db == 10
    angles, gain = pattern.azimuth_cut()
    assert angles == (-180, -90, 0, 90)
    assert gain[2] == 10
    elevation, _ = pattern.elevation_cut()
    assert elevation == (-90, 0, 90)
