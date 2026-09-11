# JAAM Studio

JAAM (Just Another Antenna Modeller) is a declarative antenna language, traced
compiler, and native Linux visualization workspace for openEMS. A compact model
lowers to typed geometry, a graded FDTD mesh, native CSXCAD calls, and a
versioned result bundle that Studio can inspect without guessing solver state.

> The finale recording will live here after the validated container run is
> recorded. No precomputed solver result is bundled with this repository.

## 30-second quick start

```sh
./scripts/uv sync --all-extras
./scripts/uv run jaam inspect examples/dipole.jaam
./scripts/uv run --extra studio jaam studio examples/dipole.jaam
```

Inside Studio, `Ctrl+B` compiles, `Ctrl+S` saves, `F5` starts a fresh solver run,
and Cancel terminates the active subprocess. Check a finale machine first with
`./scripts/uv run --extra studio jaam doctor --finale`.

Build the pinned solver image with Podman (preferred) or Docker:

```sh
podman build -t localhost/jaam-openems:7706743cc33f -f container/Containerfile .
```

## Language

```jaam
frequency_lower 900MHz;
frequency_upper 1100MHz;
boundary free_space;
default { material: copper; radius: 1mm; }
wire dipole(
    path: line(from: (0, 0, -71mm), to: (0, 0, 71mm)),
    feed: port(impedance: 50ohm)
);
```

The compiler validates dimensions and topology, expands paths/composites,
eliminates ineffective geometry, chooses thin or thick wire lowering, then
constructs the simulation domain and mesh. `jaam inspect --format json` exposes
the AST-to-IR source map, per-pass timings/statistics, diagnostics, and resolved
IR for tooling.

## Architecture

```text
.jaam source
  -> ANTLR frontend
  -> six traced semantic/lowering passes
  -> typed SimulationIR + source map
     |-> deterministic emitted Python
     |-> PyVista MultiBlock / 2D projection data
     `-> live openEMS run
          -> unique versioned artifact
             (manifest, IR, Python, logs, S11/Z, NF2FF CSV, farfield VTP)
```

The compiler and headless plotting calculations have no GUI dependency. The
`studio` extra adds ImGui Bundle, ImPlot, PyVista, and VTK. PyVista scene building
is lazy and consumes typed IR; each dataset carries primitive, material,
lowering, and source-span metadata.

## Commands

```text
jaam check SOURCE [--format human|json]
jaam inspect SOURCE [--format human|json]
jaam compile SOURCE [-o OUTPUT] [--format human|json]
jaam run SOURCE [--output-dir ROOT] [--format human|json]
jaam studio [SOURCE]
jaam doctor --finale
```

Every `run` creates `ROOT/<UTC timestamp>-<random run id>/`; it never searches
for or reuses old output. `manifest.json` records hashes, versions, pass timing,
mesh cells, solver timing, best-match frequency, minimum S11, peak gain, and
output filenames.

## Validation status

| Check | Status in this checkout |
|---|---|
| Frontend, semantics, emitter, CLI | Automated |
| Pass trace, source map, JSON schema | Automated |
| 2D projection, slicing, measurements, Smith identities | Automated |
| Radiation normalization, HPBW, front/back | Automated with synthetic data |
| PyVista actors, metadata, VTM serialization | Headless smoke test |
| Unique run artifacts and NF2FF VTP writer | Automated |
| Native CSXCAD construction | Optional host test |
| Dipole/Yagi container simulation and numerical reference | Not yet run on this host |

Run the suite with `./scripts/uv run --extra studio pytest`.

## Reproducibility

Host dependencies are locked by `uv.lock`. The Ubuntu 24.04 image pins the
openEMS-Project superproject to commit
`7706743cc33f5a105759eb5010053b8396631357`, which pins its openEMS and CSXCAD
submodules. GUI/VTK rendering stays on the host. The adapter prefers rootless
Podman and can generate equivalent Docker commands.

## Current limitations

- Studio currently exposes source, pass/diagnostic, geometry/mesh, and streaming
  solver-log docks. The off-screen VTK texture, ImPlot geometry canvas, result
  tabs, file dialog, bidirectional picking, and presentation layout still need
  integration; their backend calculations and scene model are present and tested.
- The native runtime rejects multiple feeds explicitly; separate port runs are
  not implemented yet.
- The image definition exists, but `jaam run` still uses host bindings; container
  execution is not connected to the runtime adapter yet.
- Dipole equivalence tolerances and the under-20-second target require a built
  image and have not been claimed here.
- NF2FF capture is implemented against the openEMS API but could not be exercised
  here because native bindings are absent.

See [native setup](docs/native-setup.md) and the [finale script](docs/finale-demo.md).
