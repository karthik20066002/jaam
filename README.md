# JAAM — Just Another Antenna Modeller

JAAM is a declarative language for antenna geometry and openEMS simulations. The
compiler parses `.jaam` models, validates physical units and geometry, lowers them
to CSXCAD operations, builds an FDTD mesh, and either emits Python or runs openEMS.

## Development

The project uses [uv](https://docs.astral.sh/uv/):

```sh
./scripts/uv sync --all-extras
./scripts/uv run pytest
./scripts/uv run jaam check examples/yagi.jaam
./scripts/uv run jaam compile examples/yagi.jaam -o /tmp/yagi.py
```

The wrapper is still uv; it only redirects uv's downloaded interpreter and cache
to ignored `.uv-python/` and `.uv-cache/` directories inside this checkout.

The uv-managed environment covers parsing, compilation, and tests. Direct solver
execution additionally needs native CSXCAD/openEMS bindings; see
[`docs/native-setup.md`](docs/native-setup.md).

On a host with those system bindings, run simulations with:

```sh
./scripts/jaam-native run examples/yagi.jaam
```

## Commands

```text
jaam check SOURCE [--format human|json]
jaam compile SOURCE [-o OUTPUT] [--format human|json]
jaam run SOURCE [--output-dir DIR] [--format human|json]
```

`compile` emits a standalone Python program. Both `run` and the emitted program
execute openEMS and write one S11 CSV per feed port.
