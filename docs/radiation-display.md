# Radiation display

Studio's 3D radiation view uses the stored NF2FF theta/phi samples, with theta
measured from +Z and phi from +X toward +Y. No beam rotation or gain adjustment is
applied. Colors show absolute dBi on a peak-relative 40 dB color range (or the
actual range when narrower). Values below the color floor saturate blue.

The Radius selector changes the appearance of the surface, not the results:

- **ARRL modified log** (default): `r = 0.89 ** ((peak - gain) / 3)`.
- **Linear field**: `r = 10 ** ((gain - peak) / 20)`.
- **dB (40 dB range)**: `r = max(0, 1 + (gain - peak) / 40)`.

Radius is normalized to the peak and drawn at an arbitrary spatial scale; it is
not a propagation distance. The antenna overlay is optional. The pattern grid
follows sampled theta/phi lines nearest each 15-degree interval. VTP exports
retain the original linear-field radius for compatibility.

This is an approximation of the documented 4nec2 display conventions, not an
exact reproduction of its renderer. The 4nec2 manual documents a DirectX F9
viewer, blue-to-red multicolor patterns, ARRL-style scaling, and a separate
gnuplot interface for plot export. Studio retains VTK for interaction.

References:

- [4nec2 manual, Pattern F4, Viewer F9, and gnuplot sections](https://hamwaves.com/antennas/doc/4nec2.rtf.pdf)
- [ARRL Handbook supplement, Coordinates for Radiation Patterns](https://www.arrl.org/files/file/ARRL%20Handbook%20Supplemental%20Files/2023%20Edition/Radio%20Supplement.pdf)
