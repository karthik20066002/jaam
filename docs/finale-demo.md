# Five-minute finale script

## 0:00–0:30 — Why a language

Open `examples/dipole.jaam`. The model says what the antenna is—not how to
sequence CSXCAD calls, split a feed gap, reserve PML cells, or grade a mesh.

## 0:30–1:20 — Compiler and IR

Run `jaam inspect examples/dipole.jaam`. Point to the actual normalization,
lowering, and IR-to-IR passes. Typed `SimulationIR` is the boundary: emitted Python, execution, 2D
projection, VTK actors, and artifacts consume the same resolved structure.

## 1:20–2:10 — Geometry and mesh

Compare XY/XZ/YZ geometry and the 3D XYZ indicator. Enable domain, mesh, and feed layers. Explain
that electrically thin conductors lower to curves while larger conductors retain
a physical radius. Measure element length, feed gap, and a mesh cell.

## 2:10–3:15 — Live solve

Press F5. Read the UTC run ID and show the new artifact directory. Host bindings
execute this demo; the pinned Ubuntu image is a separate reproducibility gate. Progress streams live,
cancellation terminates the process, and there is no cached fallback.

## 3:15–4:15 — Results

Select a frequency on the S11 trace. Studio shows S11, VSWR,
resistance/reactance, and E/H cuts from the completed artifact. A Smith cursor
and 3D radiation lobe remain future work. NF2FF is evaluated at the
measured best-match frequency rather than a hard-coded demo value.

## 4:15–5:00 — Declarative reuse

Open the Yagi. Repeated elements share defaults but remain traceable. Close on
the manifest: hashes, exact versions, timings, planned and actual mesh dimensions, and raw results make
every claim inspectable.

# Q&A

**Why a DSL instead of a Python helper?**

The compiler owns units, defaults, topology, source spans, lowering decisions,
diagnostics, and deterministic artifacts before arbitrary code executes.

**Why keep an IR?**

It prevents emitters and visualizers from independently reinterpreting source.

**What are the passes?**

Directives/defaults; geometry expansion with unit normalization; semantic
validation; dead-structure elimination; thin/thick lowering; exact deduplication;
domain/mesh; feed validation; vertex canonicalization; collinear merge; graded
mesh; resolution validation. Optional anchor pruning runs before validation.

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
dB, impedance within 1%, and far-field cuts within 0.5 dB. The hand-written
host comparison passes on a frozen matching mesh; the pinned-container run and
independent mesh-generation study remain open.
