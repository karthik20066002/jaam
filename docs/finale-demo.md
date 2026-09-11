# Five-minute finale script

## 0:00–0:30 — Why a language

Open `examples/dipole.jaam`. The model says what the antenna is—not how to
sequence CSXCAD calls, split a feed gap, reserve PML cells, or grade a mesh.

## 0:30–1:20 — Compiler and IR

Run `jaam inspect examples/dipole.jaam`. Point to the six named passes and their
statistics. Typed `SimulationIR` is the boundary: emitted Python, execution, 2D
projection, VTK actors, and artifacts consume the same resolved structure.

## 1:20–2:10 — Geometry and mesh

Compare XY/XZ/YZ geometry. Enable domain, PML, mesh, and feed layers. Explain
that electrically thin conductors lower to curves while larger conductors retain
a physical radius. Measure element length, feed gap, and a mesh cell.

## 2:10–3:15 — Live solve

Press F5. Read the UTC run ID and show the new artifact directory. The pinned
Ubuntu image makes solver binaries reproducible. Progress streams live,
cancellation terminates the process, and there is no cached fallback.

## 3:15–4:15 — Results

Select the S11 minimum. The intended shared cursor updates S11, VSWR,
resistance/reactance, Smith, E/H cuts, and the 3D lobe. NF2FF is evaluated at the
measured best-match frequency rather than a hard-coded demo value.

## 4:15–5:00 — Declarative reuse

Open the Yagi. Repeated elements share defaults but remain traceable. Close on
the manifest: hashes, exact versions, timings, mesh cells, and raw results make
every claim inspectable.

# Q&A

**Why a DSL instead of a Python helper?**

The compiler owns units, defaults, topology, source spans, lowering decisions,
diagnostics, and deterministic artifacts before arbitrary code executes.

**Why keep an IR?**

It prevents emitters and visualizers from independently reinterpreting source.

**What are the passes?**

Defaults/unit resolution; path/composite expansion; validation/constant folding;
dead-structure elimination/deduplication; thin/thick lowering; domain/mesh.

**What is the thin-wire tradeoff?**

Curves are efficient for electrically thin conductors but do not resolve a
cross-section. JAAM exposes its wavelength-based lowering choice in metadata.

**Why openEMS?**

It is an open FDTD solver with CSXCAD geometry, graded meshes, ports, PML, and
NF2FF, so generated work stays inspectable.

**How do you prevent a cached demo?**

Every F5 uses a UTC timestamp plus random ID and `exist_ok=False`. The manifest
hashes source, IR, and generated Python; the solver writes fresh logs and output.

**How is numerical credibility established?**

The intended gate compares the dipole to hand-written openEMS: S11 within 0.1
dB, impedance within 1%, and far-field cuts within 0.5 dB. Until the pinned
container produces those measurements, JAAM labels the gate unverified.
