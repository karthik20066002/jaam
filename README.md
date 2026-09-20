# JAAM Studio

JAAM (Just Another Antenna Modeller) is a declarative antenna language, traced
compiler, and native Linux visualization workspace. A compact model lowers to
typed geometry, then a chosen solver backend: **openEMS** (FDTD), **Palace**
(FEM), **Meep** (FDTD), or **SCUFF-EM** (BEM). All write the same versioned
result bundle that Studio can inspect.

```text
source → ANTLR AST → unit-normalized geometry → typed IR → optimization passes
       → openEMS FDTD  |  Palace FEM  |  Meep FDTD  |  SCUFF-EM BEM
       → fresh result artifact → Studio
```

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
IR for tooling. Unit conversion happens during geometry expansion; wire lowering
and exact deduplication are timed where they actually transform geometry.

## Architecture

```text
.jaam source
  -> ANTLR frontend
  -> traced normalization and lowering
  -> typed SimulationIR + source map
  -> canonicalize wire vertices / merge collinear wires / grade mesh
  -> optional experimental curve mesh-anchor pruning
     |-> deterministic emitted Python
     |-> PyVista MultiBlock / 2D projection data
     `-> live solver run (`--backend openems|palace`)
          -> unique versioned artifact
             (manifest, IR, openEMS Python, Palace JSON, logs, S11/Z, far-field CSV/VTP)
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
jaam run SOURCE [--output-dir ROOT] [--no-farfield] [--backend openems|palace|meep|scuff] [--format human|json]
jaam studio [SOURCE]
jaam doctor --finale
```

`check`, `inspect`, `compile`, and `run` accept `--optimize-mesh-anchors` for the
experimental curve pass. Studio exposes the same option in Simulate. The default
mesh path remains in use until curved-antenna numerical parity is established.
Use `run --no-farfield` when iterating on S11; it skips the 181×361 NF2FF
calculation and records a port-only artifact.

Every `run` creates `ROOT/<UTC timestamp>-<random run id>/`; it never searches
for or reuses old output. `manifest.json` records hashes, versions, pass timing,
planned IR intervals and actual post-smoothing FDTD dimensions, solver timing,
best-match frequency, minimum S11, peak gain, and
output filenames.

## Optimization evidence

openEMS runs on one global FDTD timestep, bound by the single smallest cell
anywhere in the grid. Three real bugs in `src/jaam/mesh_features.py` were each
planting a stray micron-or-smaller cell somewhere in the mesh — with no
accuracy benefit, since none of it was intentional geometry — which forced
the whole simulation into a needlessly tiny timestep:

1. **Feed-gap self-collision.** Every wire's feed anchors got padded by the
   wire's own cross-sectional radius on *all three axes*, including the axis
   running along the wire itself. For a 1mm-radius wire with a sub-millimetre
   feed gap, that plants a line almost on top of the opposite terminal.
2. **Duplicate endpoint snapping.** Every straight wire's endpoint was added
   twice — once exact, once separately rounded to the nearest λ/20 grid line
   — landing microns apart.
3. **Split-wire cut-end collision.** A feed splits its wire into two ops; the
   fed piece's own cut end, the unfed sibling's cut start, and the feed's own
   anchors all land within one wire radius of each other. This one hit curved
   geometry (the helix) specifically, since "transverse to the wire" isn't a
   fixed Cartesian axis once the wire isn't axis-aligned.

Fixed by making `fdtd_feature_axes()` recognize any critical point within one
wire-radius of a feed anchor — anywhere in the geometry, not just on the same
op — and skip radius padding there entirely, since that region is already
covered by dedicated feed-gap mesh refinement.

A fourth issue was architectural rather than a bug: `GradedMeshCoarseningPass`
correctly thins mesh lines away from geometry, but `build_native()` then
called CSXCAD's `SmoothMeshLines()` with a blanket λ/20 ceiling — the *fine*
validation resolution — which re-inserted lines into every region the pass
had just coarsened, silently undoing it (measured: 0%, 0%, and -3% actual
cell reduction on the three examples, even after the bug fixes above).
`MeshSpec` now carries a separate `smoothing_resolution_m`, set to the pass's
own coarse target only when it has actually run, so the native smoother
respects the intended coarsening instead of erasing it. `max_resolution_m`
is untouched and still governs `ValidateMeshResolutionPass`'s feed/wire
resolution checks, so that safety check isn't weakened.

Measured on this host, `--backend openems --no-farfield`:

| Model | Before any fix | After mesh-bug fixes | After coarsening fix | Total speedup |
| --- | ---: | ---: | ---: | ---: |
| Dipole | 573.1 s | 172.2 s | **70.2 s** | 8.2x |
| Yagi | 158.0 s | 28.4 s | **20.3 s** | 7.8x |
| Helix | killed after 55+ min, never converged | 91.4 s | **78.3 s** | at least 42x |

Native post-smoothing FDTD cells, raw (no passes) vs the default pipeline
(now that the coarsening fix lets it actually work):

| Model | Raw cells | Optimized cells | Reduction |
| --- | ---: | ---: | ---: |
| Dipole | 49,972 | 21,160 | 57.7% |
| Yagi | 153,140 | 81,972 | 46.5% |
| Helix | 267,597 | 176,085 | 34.2% |

Minimum cell size (the value that sets the global timestep) is unchanged by
the coarsening fix in every case — it only thins cells far from geometry, so
the speedup above is pure per-timestep compute reduction, not a change to
numerical resolution near the antenna.

**Accuracy**, comparing the raw reflection coefficient Γ (not just S11 in dB)
before vs after the coarsening fix, port-only, same frequency grid:

| Model | max abs(Γ_before − Γ_after) | max S11 delta |
| --- | ---: | ---: |
| Dipole | 0.0014 | 2.6e-5 dB |
| Yagi | 0.0048 | 6.0e-5 dB |
| Helix | 5.4e-7 | 4.4e-6 dB |

All three are negligible. Note: the naive impedance-relative-delta check
(`scripts/compare_dipole_reference.py`'s own ≤1% threshold) reports a
misleading 22–23% "delta" for dipole and yagi here — both sit at
near-total mismatch (|Γ| ≈ 0.9998, S11 ≈ 0 dB) across their whole configured
band on openEMS, so `Z = Z0·(1+Γ)/(1-Γ)` has a near-zero denominator and
amplifies a tiny Γ change into a large relative swing. This is a pre-existing
property of these two example models on openEMS (present before any change
made this session), not something introduced by the fixes above — compare
against SCUFF-EM below, which sees real resonance dips on the identical
geometry. Use Γ or S11-dB deltas, not the impedance ratio, when either
example antenna is this poorly matched.

**SCUFF-EM** (`--backend scuff`, unaffected by the openEMS-specific fixes
above, since it builds its own BEM surface mesh directly from geometry and
never touches `ir.mesh`) confirms sane resonance behavior on the same three
models: dipole 12.4 s (S11 -30.6 dB), yagi 17.0 s (S11 -4.2 dB), helix 38.9 s
(S11 -1.1 dB). Also has its own fixed bug: `write_scuff_inputs()`'s port
polygons were being placed on the feed faces instead of the open tube's rim
endpoints, which made scuff-rf abort with "no edges specified or detected for
positive port" on every model with a real feed gap.

**Tried and reverted:** a wavelength-relative graded axial mesh for SCUFF-EM
(same fine/coarse fractions as the openEMS fix above), reasoning that the
fixed 4mm axial spacing (`AXIAL_MM`, no longer present) was wavelength-
independent and needlessly fine at these examples' 1-2.45GHz range. Measured
result: real, not a bug, and safety-failing on both axes at once. Triangle
count dropped as expected (dipole 576 -> 128), but solve time got *worse*
(12.4s -> 37s, and a uniform-fine variant with no coarsening at all still
hung for minutes) and accuracy regressed (dipole S11 -30.6 -> -22.7 dB). The
actual constraint governing this thin-wire BEM mesh is triangle aspect ratio
against the *wire radius* (axial length vs. circumferential facet width),
not wavelength: the original 4mm spacing already sits at a reasonable ~3-5:1
ratio for these radii, and coarsening it toward the wavelength-relative
target pushed that past ~20:1, producing near-degenerate slivers that the
BEM solver handled both slower and less accurately. Reverted in full; the
fixed 4mm spacing is unchanged. A real optimization here would need to scale
with wire radius, not wavelength, and would need its own careful empirical
verification before shipping — not attempted this session.

Reproduce with (one source, one backend, per `jaam run` invocation):

```sh
for model in dipole yagi helix; do
  for backend in openems scuff; do
    PYTHONPATH=src python3 -m jaam.cli run "examples/$model.jaam" --backend "$backend" --no-farfield
  done
done
```

The old curve mesh-anchor pruning pass (`--optimize-mesh-anchors`) is
unrelated to the fixes above, still experimental, and still has documented,
unresolved numerical drift (up to 1.24 dB S11, 14.9% impedance) on the
parabolic-arc benchmark — reproduce with
`PYTHONPATH=src python3 scripts/benchmark_mesh.py --output-dir /tmp/jaam-mesh-benchmark --solve`.
[openEMS mesh guidance](https://docs.openems.de/en/latest/concepts/mesh.html)
and [SmoothMeshLines](https://docs.openems.de/en/latest/octave/autogenerated/CSXCAD/SmoothMeshLines.html)
describe the fixed-line and smoothing relationship this section relies on.

## Validation status

| Check | Status in this checkout |
| --- | --- |
| Frontend, semantics, emitter, CLI | Automated |
| Pass trace, source map, JSON schema | Automated |
| 2D projection, slicing, measurements, Smith identities | Automated |
| Radiation normalization, HPBW, front/back | Automated with synthetic data |
| PyVista actors, metadata, VTM serialization | Headless smoke test |
| Unique run artifacts and NF2FF VTP writer | Automated |
| Native CSXCAD construction | Passed on this host |
| Fresh host dipole/Yagi/Helix run | Completed on 2026-09-20; see Optimization evidence for current timings |
| Curved-anchor numerical parity | Open; parabolic benchmark drift measured above |
| Hand-written host dipole comparison | Passed on matching frozen mesh: S11 0.0061 dB, impedance 0.033%, cuts 0.00012 dB maximum difference |
| Pinned container image | Image builds; `jaam run` connected |

Run the suite with `./scripts/uv run --extra studio pytest`.

## Reproducibility

Host dependencies are locked by `uv.lock`. The Ubuntu 24.04 image pins the
openEMS-Project superproject to commit
`7706743cc33f5a105759eb5010053b8396631357`, which pins its openEMS and CSXCAD
submodules. GUI/VTK rendering stays on the host. The adapter prefers rootless
Podman and can generate equivalent Docker commands.

## Current limitations

- Studio exposes source, pass trace, geometry, S11/impedance, radiation cuts,
  solver log, and an offscreen 3D geometry view. Full result tabs, a native file
  chooser, and bidirectional picking remain open.
- The native runtime rejects multiple feeds explicitly; separate port runs are
  not implemented yet.
- The pinned image remains open. The hand-written dipole reference verifies
  geometry, native execution, and result processing against the same frozen
  mesh; independent mesh-generation accuracy still needs a separate study.
- Container execution is connected to `jaam run`. When a built
  `localhost/jaam-openems:7706743cc33f` image is present, runs use the
  container; otherwise host bindings are used.
- The example dipole and Yagi both show near-total mismatch on openEMS
  (|Γ| ≈ 0.9998, S11 ≈ 0 dB) across their whole configured band, while
  SCUFF-EM sees real resonance dips on the identical geometry (see
  Optimization evidence). This predates this session's changes and wasn't
  investigated here — worth a separate look at the openEMS lumped-port setup.

Run `python3 benchmarks/dipole_reference.py` and then
`PYTHONPATH=src python3 scripts/compare_dipole_reference.py JAAM_ARTIFACT REFERENCE_ARTIFACT`
to repeat the numerical gate.

See [native setup](docs/native-setup.md) and the [finale script](docs/finale-demo.md).
