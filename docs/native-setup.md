# Native solver setup

JAAM has two solver backends. `jaam run` defaults to **openEMS** (FDTD). Pass
`--backend palace` for **Palace** (frequency-domain FEM). Studio's Simulate
menu selects the same backends.

Parsing, checking, and Python/JSON emission only require `uv sync`.

## openEMS

`jaam run --backend openems` and the generated programs require the compiled
CSXCAD and openEMS Python bindings.

On this EndeavourOS/Arch host, the available packages are:

```sh
sudo pacman -S antlr4 python-antlr4
sudo pacman -S csxcad-git openems-git python-csxcad-git python-openems-git
```

The latter two are currently provided by the configured Chaotic-AUR repository.
They build against the system Python, so native smoke tests should use that
interpreter with the JAAM source tree on `PYTHONPATH`. The uv Python 3.12
environment remains the reproducible compiler and unit-test baseline.

Verify the native bindings outside their source trees:

```sh
python3 -c 'import CSXCAD, openEMS; print(CSXCAD.__version__, openEMS.__version__)'
```

Run JAAM through the checked-in wrapper so system Python sees both the repository
source and its native system bindings:

```sh
./scripts/jaam-native run examples/yagi.jaam
./scripts/jaam-native run --backend palace examples/yagi.jaam
```

## SCUFF-EM

SCUFF-EM is a surface-integral BEM solver (`scuff-rf`). JAAM writes open
cylindrical PEC tubes (no end caps) in millimetres, rim port polygons on the
feed gap, then `--ZParameters` for S11 and `--EPFile` for far-field samples.

```sh
# local build used in this workspace
export JAAM_SCUFF_RF=/home/axiss/scuff-em/applications/scuff-rf/scuff-rf
jaam run --backend scuff examples/yagi.jaam
jaam compile --backend scuff -o yagi.scuff.json
```

## Meep

Meep is an FDTD solver (MIT). JAAM builds PEC cylinders with the declared
radius, a gap current source, and a near-to-far box.

```sh
# Typical install (conda-forge). PyPI does not ship the MIT solver.
conda install -c conda-forge pymeep
python3 -c "import meep; print(meep.__version__)"
```

```sh
jaam run --backend meep examples/yagi.jaam
jaam compile --backend meep -o yagi.meep.json
```

## Palace

Palace is a 3D FEM full-wave solver. JAAM builds a Gmsh mesh of finite-radius
cylinders, a rectangular lumped-port face in the feed gap, and an absorbing
outer sphere, then writes `palace.json`.

```sh
# Gmsh Python bindings (mesh generation)
./scripts/uv pip install gmsh

# Palace binary on PATH (see https://awslabs.github.io/palace/)
palace --version
```

`jaam compile --backend palace -o palace.json` emits the config without
running the solver. A live run needs `gmsh` on the host to build `mesh.msh`.
Palace itself can be a host binary on `PATH`, or the container image
`localhost/jaam-palace:0.16`.

The openEMS container path (`localhost/jaam-openems:7706743cc33f` running
`generated.py`) is unchanged and only used for `--backend openems`. Palace
does **not** reuse that image.

Fetch and import the Palace image (prebuilt 0.16 SIF from GHCR):

```sh
./scripts/uv sync --extra palace
./scripts/fetch-palace-image
podman run --rm localhost/jaam-palace:0.16 --help
```
