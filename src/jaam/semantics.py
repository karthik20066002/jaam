from __future__ import annotations

from dataclasses import dataclass, replace
import math
import re
from time import perf_counter_ns
from typing import Callable, Sequence

from .diagnostics import CompilationError, Diagnostic
from .ir import (
    BoxOp,
    CurveOp,
    FeedSpec,
    FrequencySpec,
    GeometryOp,
    MaterialSpec,
    MeshSpec,
    Point3,
    RotPolyOp,
    SimulationIR,
    WireOp,
)
from .model import (
    CallExpr,
    DefaultBlock,
    Directive,
    Expr,
    IdentifierExpr,
    NumberExpr,
    PrimitiveDecl,
    Program,
    SourceSpan,
    TupleExpr,
)

C0 = 299_792_458.0
_NUMBER = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([A-Za-z]*)$")
_UNITS: dict[str, tuple[str, float]] = {
    "": ("scalar", 1.0),
    "m": ("length", 1.0),
    "cm": ("length", 1e-2),
    "mm": ("length", 1e-3),
    "um": ("length", 1e-6),
    "nm": ("length", 1e-9),
    "Hz": ("frequency", 1.0),
    "kHz": ("frequency", 1e3),
    "MHz": ("frequency", 1e6),
    "GHz": ("frequency", 1e9),
    "deg": ("angle", math.pi / 180),
    "rad": ("angle", 1.0),
    "ohm": ("resistance", 1.0),
}
_MATERIALS = {
    "pec": MaterialSpec("pec", "metal"),
    "copper": MaterialSpec("copper", "metal"),
    "gold": MaterialSpec("gold", "metal"),
    "earth_dry": MaterialSpec("earth_dry", "dielectric", epsilon=4.0, conductivity=0.001),
}
_BOUNDARIES = {"free_space": "PML_8", "pml_8": "PML_8", "pec": "PEC", "mur": "MUR"}
TraceCallback = Callable[[str, int, dict[str, int]], None]


@dataclass(frozen=True, slots=True)
class _Quantity:
    value: float
    dimension: str


@dataclass(slots=True)
class _WireSource:
    name: str
    points: tuple[Point3, ...]
    radius: float
    material: str
    impedance: float | None
    span: SourceSpan
    consumed: bool = False


@dataclass(slots=True)
class _BoxSource:
    name: str
    start: Point3
    stop: Point3
    material: str
    span: SourceSpan
    consumed: bool = False


class _Analyzer:
    def __init__(self, program: Program, trace: TraceCallback | None = None):
        self.program = program
        self.errors: list[Diagnostic] = []
        self.warnings: list[str] = []
        self.global_defaults: dict[str, Expr] = {}
        self.type_defaults: dict[str, dict[str, Expr]] = {}
        self.names: dict[str, _WireSource | _BoxSource] = {}
        self.rotations: list[RotPolyOp] = []
        self.trace = trace

    def _record(self, name: str, started_ns: int, **statistics: int) -> None:
        if self.trace is not None:
            self.trace(name, perf_counter_ns() - started_ns, statistics)

    def error(self, code: str, message: str, span: SourceSpan) -> None:
        self.errors.append(Diagnostic(code, message, span))

    def analyze(self) -> SimulationIR:
        started = perf_counter_ns()
        frequency, boundary = self._directives()
        self._collect_defaults()
        self._record("directives-and-defaults", started, defaults=len(self.global_defaults) + sum(map(len, self.type_defaults.values())))
        if frequency is None:
            self._raise()
            raise AssertionError
        wavelength = C0 / frequency.upper_hz
        started = perf_counter_ns()
        for statement in self.program.statements:
            if isinstance(statement, PrimitiveDecl):
                self._primitive(statement, wavelength)
        self._record("geometry-expansion-and-unit-normalization", started, declarations=len(self.names), revolutions=len(self.rotations))
        started = perf_counter_ns()
        self._raise()
        self._record("semantic-validation", started, diagnostics=len(self.errors), warnings=len(self.warnings))

        started = perf_counter_ns()
        effective: list[_WireSource | _BoxSource] = []
        for source in self.names.values():
            if source.consumed:
                continue
            if isinstance(source, _WireSource):
                if self._path_length(source.points) <= 1e-12:
                    self.warnings.append(f"dropped zero-length wire '{source.name}'")
                    continue
            else:
                if any(b <= a for a, b in zip(source.start, source.stop)):
                    self.warnings.append(f"dropped degenerate box '{source.name}'")
                    continue
            effective.append(source)
        self._record("dead-structure-elimination", started, effective_declarations=len(effective))

        started = perf_counter_ns()
        geometry: list[GeometryOp] = []
        for source in effective:
            if isinstance(source, _WireSource):
                feed = self._make_feed(source, wavelength) if source.impedance is not None else None
                cls = CurveOp if source.radius / wavelength < 0.02 else WireOp
                if feed:
                    left, right = self._split_path(source.points, feed.start, feed.stop)
                    geometry.append(cls(f"{source.name}__a", left, source.material, source.radius, feed))
                    geometry.append(cls(f"{source.name}__b", right, source.material, source.radius, None))
                else:
                    geometry.append(cls(source.name, source.points, source.material, source.radius, None))
            else:
                geometry.append(BoxOp(source.name, source.start, source.stop, source.material))
        geometry.extend(self.rotations)
        self._record("thin-and-thick-wire-lowering", started, thin_wires=sum(isinstance(op, CurveOp) for op in geometry), thick_wires=sum(isinstance(op, WireOp) for op in geometry))

        started = perf_counter_ns()
        geometry = self._deduplicate(geometry)
        if not geometry:
            self.error("J220", "program contains no effective geometry", SourceSpan.unknown())
            self._raise()
        self._record("exact-geometry-deduplication", started, effective_primitives=len(geometry))

        started = perf_counter_ns()
        domain_min, domain_max, geometry = self._domain(geometry, wavelength, boundary)
        mesh = self._mesh(geometry, domain_min, domain_max, wavelength)
        used = {op.material for op in geometry}
        materials = tuple(_MATERIALS[name] for name in sorted(used))
        self._record("domain-and-mesh-construction", started, mesh_cells=(len(mesh.lines_x) - 1) * (len(mesh.lines_y) - 1) * (len(mesh.lines_z) - 1), materials=len(materials))
        return SimulationIR(
            frequency,
            boundary,
            materials,
            tuple(geometry),
            mesh,
            domain_min,
            domain_max,
            tuple(self.warnings),
        )

    def _raise(self) -> None:
        if self.errors:
            raise CompilationError(self.errors)

    def _directives(self) -> tuple[FrequencySpec | None, str]:
        found: dict[str, Directive] = {}
        for statement in self.program.statements:
            if not isinstance(statement, Directive):
                continue
            if statement.name not in {"frequency", "frequency_lower", "frequency_upper", "boundary"}:
                self.error("J101", f"unknown directive '{statement.name}'", statement.span)
                continue
            if statement.name in found:
                self.error("J102", f"duplicate directive '{statement.name}'", statement.span)
            found[statement.name] = statement
        frequency = None
        single = found.get("frequency")
        lower = found.get("frequency_lower")
        upper = found.get("frequency_upper")
        if single and (lower or upper):
            self.error("J103", "use either frequency or frequency_lower/frequency_upper, not both", single.span)
        elif single:
            value = self._number(single.value, "frequency")
            if value is not None and value > 0:
                frequency = FrequencySpec(value, value, value)
            elif value is not None:
                self.error("J104", "frequency must be positive", single.span)
        elif lower and upper:
            lo = self._number(lower.value, "frequency")
            hi = self._number(upper.value, "frequency")
            if lo is not None and hi is not None:
                if 0 < lo < hi:
                    frequency = FrequencySpec(lo, hi)
                else:
                    self.error("J105", "frequency range must satisfy 0 < lower < upper", lower.span)
        else:
            span = (lower or upper).span if (lower or upper) else SourceSpan.unknown()
            self.error("J106", "a frequency or complete frequency range is required", span)
        boundary = "PML_8"
        if directive := found.get("boundary"):
            if isinstance(directive.value, IdentifierExpr) and directive.value.name in _BOUNDARIES:
                boundary = _BOUNDARIES[directive.value.name]
            else:
                self.error("J107", "boundary must be free_space, pml_8, pec, or mur", directive.span)
        return frequency, boundary

    def _collect_defaults(self) -> None:
        for statement in self.program.statements:
            if not isinstance(statement, DefaultBlock):
                continue
            target = self.global_defaults if statement.target is None else self.type_defaults.setdefault(statement.target, {})
            for name, value in statement.values:
                if name in target:
                    self.error("J110", f"duplicate default '{name}' in the same scope", statement.span)
                target[name] = value

    def _primitive(self, decl: PrimitiveDecl, wavelength: float) -> None:
        if decl.name in self.names:
            self.error("J120", f"duplicate primitive name '{decl.name}'", decl.span)
            return
        if decl.kind == "wire":
            values = self._bind(decl, ("path", "radius", "material", "feed"), required=("path",))
            values = self._defaults(decl.kind, values)
            path = self._path(values.get("path"), wavelength)
            radius = self._number(values.get("radius"), "length")
            material = self._material(values.get("material"))
            impedance = self._port(values.get("feed")) if values.get("feed") else None
            if path is not None and radius is not None and material is not None:
                if radius <= 0:
                    self.error("J121", "wire radius must be positive", decl.span)
                else:
                    self.names[decl.name] = _WireSource(decl.name, path, radius, material, impedance, decl.span)
        elif decl.kind == "box":
            values = self._bind(decl, ("size", "at", "material"), required=("size", "at"))
            values = self._defaults(decl.kind, values)
            size = self._vector(values.get("size"), "length", 3)
            at = self._vector(values.get("at"), "length", 3)
            material = self._material(values.get("material"))
            if size and at and material:
                if any(component <= 0 for component in size):
                    self.error("J123", "box size components must be positive", decl.span)
                else:
                    stop = tuple(a + s for a, s in zip(at, size))
                    self.names[decl.name] = _BoxSource(decl.name, at, stop, material, decl.span)
        elif decl.kind == "concat":
            self._concat(decl)
        elif decl.kind == "revolve":
            self._revolve(decl)
        else:
            self.error("J122", f"unknown primitive '{decl.kind}'", decl.span)

    def _defaults(self, kind: str, values: dict[str, Expr]) -> dict[str, Expr]:
        result = dict(values)
        for name, value in self.type_defaults.get(kind, {}).items():
            result.setdefault(name, value)
        for name, value in self.global_defaults.items():
            result.setdefault(name, value)
        return result

    def _bind(
        self, decl: PrimitiveDecl, fields: tuple[str, ...], *, required: tuple[str, ...] = ()
    ) -> dict[str, Expr]:
        result: dict[str, Expr] = {}
        positional = 0
        named_seen = False
        for arg in decl.args:
            if arg.name is None:
                if named_seen:
                    self.error("J130", "positional argument cannot follow a named argument", arg.span)
                    continue
                if positional >= len(fields):
                    self.error("J131", f"too many arguments for {decl.kind}", arg.span)
                    continue
                name = fields[positional]
                positional += 1
            else:
                named_seen = True
                name = arg.name
                if name not in fields:
                    self.error("J132", f"unknown {decl.kind} argument '{name}'", arg.span)
                    continue
            if name in result:
                self.error("J133", f"duplicate argument '{name}'", arg.span)
            result[name] = arg.value
        for name in required:
            if name not in result:
                self.error("J134", f"missing required argument '{name}'", decl.span)
        return result

    def _number(self, expr: Expr | None, expected: str) -> float | None:
        if expr is None:
            return None
        if not isinstance(expr, NumberExpr):
            self.error("J140", f"expected {expected} number", expr.span)
            return None
        match = _NUMBER.match(expr.text)
        if not match or match.group(2) not in _UNITS:
            self.error("J141", f"unknown or malformed unit in '{expr.text}'", expr.span)
            return None
        value = float(match.group(1))
        dimension, multiplier = _UNITS[match.group(2)]
        if dimension == "scalar":
            if expected == "angle":
                multiplier = math.pi / 180
            elif expected in {"length", "frequency", "resistance", "scalar"}:
                multiplier = 1.0
            elif value != 0:
                self.error("J142", f"expected {expected}, got dimensionless number", expr.span)
                return None
        elif dimension != expected:
            self.error("J143", f"expected {expected}, got {dimension}", expr.span)
            return None
        return value * multiplier

    def _vector(self, expr: Expr | None, dimension: str, size: int) -> Point3 | None:
        if not isinstance(expr, TupleExpr) or len(expr.items) != size:
            span = expr.span if expr else SourceSpan.unknown()
            self.error("J144", f"expected a {size}-component {dimension} tuple", span)
            return None
        values = [self._number(item, dimension) for item in expr.items]
        return tuple(values) if all(value is not None for value in values) else None  # type: ignore[return-value]

    def _material(self, expr: Expr | None) -> str | None:
        if not isinstance(expr, IdentifierExpr):
            span = expr.span if expr else SourceSpan.unknown()
            self.error("J145", "material is required and must be an identifier", span)
            return None
        if expr.name not in _MATERIALS:
            self.error("J146", f"unknown material '{expr.name}'", expr.span)
            return None
        return expr.name

    def _port(self, expr: Expr) -> float | None:
        if not isinstance(expr, CallExpr) or expr.name != "port":
            self.error("J150", "feed must be port(impedance: ...)", expr.span)
            return None
        fake = PrimitiveDecl("port", "<feed>", expr.args, expr.span)
        values = self._bind(fake, ("impedance",), required=("impedance",))
        value = self._number(values.get("impedance"), "resistance")
        if value is not None and value <= 0:
            self.error("J151", "port impedance must be positive", expr.span)
            return None
        return value

    def _path(self, expr: Expr | None, wavelength: float) -> tuple[Point3, ...] | None:
        if not isinstance(expr, CallExpr):
            span = expr.span if expr else SourceSpan.unknown()
            self.error("J160", "path must be a path-builder call", span)
            return None
        fake = PrimitiveDecl(expr.name, "<path>", expr.args, expr.span)
        if expr.name == "line":
            values = self._bind(fake, ("from", "to"), required=("from", "to"))
            start = self._vector(values.get("from"), "length", 3)
            stop = self._vector(values.get("to"), "length", 3)
            return (start, stop) if start and stop else None
        if expr.name == "helix":
            values = self._bind(fake, ("radius", "pitch", "turns"), required=("radius", "pitch", "turns"))
            radius = self._number(values.get("radius"), "length")
            pitch = self._number(values.get("pitch"), "length")
            turns = self._number(values.get("turns"), "scalar")
            if not radius or pitch is None or not turns or radius <= 0 or turns <= 0:
                self.error("J161", "helix radius and turns must be positive", expr.span)
                return None
            from .mesh_features import path_sample_count

            count = path_sample_count(
                arc_length=2 * math.pi * radius * turns,
                wavelength=wavelength,
                turns=turns,
            )
            return tuple(
                (radius * math.cos(2 * math.pi * turns * i / count), radius * math.sin(2 * math.pi * turns * i / count), pitch * turns * i / count)
                for i in range(count + 1)
            )
        if expr.name == "simple_arc":
            values = self._bind(fake, ("radius", "start_angle", "end_angle"), required=("radius", "start_angle", "end_angle"))
            radius = self._number(values.get("radius"), "length")
            start = self._number(values.get("start_angle"), "angle")
            stop = self._number(values.get("end_angle"), "angle")
            if radius is None or start is None or stop is None or radius <= 0:
                return None
            from .mesh_features import path_sample_count

            count = path_sample_count(
                arc_length=abs(stop - start) * radius,
                wavelength=wavelength,
                angle_rad=stop - start,
            )
            return tuple((radius * math.cos(start + (stop - start) * i / count), radius * math.sin(start + (stop - start) * i / count), 0.0) for i in range(count + 1))
        if expr.name == "parabolic_arc":
            values = self._bind(fake, ("focal_length", "aperture"), required=("focal_length", "aperture"))
            focal = self._number(values.get("focal_length"), "length")
            aperture = self._number(values.get("aperture"), "length")
            if not focal or not aperture or focal <= 0 or aperture <= 0:
                self.error("J162", "parabolic focal length and aperture must be positive", expr.span)
                return None
            from .mesh_features import path_sample_count

            count = path_sample_count(arc_length=aperture, wavelength=wavelength)
            return tuple((((-aperture / 2 + aperture * i / count) ** 2) / (4 * focal), -aperture / 2 + aperture * i / count, 0.0) for i in range(count + 1))
        if expr.name == "curve":
            self.error("J163", "curve() is reserved and not supported in v1", expr.span)
        else:
            self.error("J164", f"unknown path builder '{expr.name}'", expr.span)
        return None

    def _concat(self, decl: PrimitiveDecl) -> None:
        if any(arg.name is not None for arg in decl.args) or len(decl.args) < 2:
            self.error("J170", "concat requires at least two positional wire names", decl.span)
            return
        sources: list[_WireSource] = []
        for arg in decl.args:
            if not isinstance(arg.value, IdentifierExpr) or not isinstance(self.names.get(arg.value.name), _WireSource):
                self.error("J171", "concat arguments must reference earlier wires", arg.span)
                return
            sources.append(self.names[arg.value.name])  # type: ignore[arg-type]
        feeds = [source.impedance for source in sources if source.impedance is not None]
        if len(feeds) > 1:
            self.error("J172", "concat may contain at most one feed", decl.span)
            return
        if len({source.material for source in sources}) != 1 or len({source.radius for source in sources}) != 1:
            self.error("J173", "v1 concat segments must share material and radius", decl.span)
            return
        points = list(sources[0].points)
        for source in sources[1:]:
            delta = tuple(points[-1][i] - source.points[0][i] for i in range(3))
            points.extend(tuple(point[i] + delta[i] for i in range(3)) for point in source.points[1:])
        for source in sources:
            source.consumed = True
        first = sources[0]
        self.names[decl.name] = _WireSource(decl.name, tuple(points), first.radius, first.material, feeds[0] if feeds else None, decl.span)

    def _revolve(self, decl: PrimitiveDecl) -> None:
        values = self._bind(decl, ("seed", "axis", "material"), required=("seed", "axis"))
        values = self._defaults(decl.kind, values)
        seed_expr = values.get("seed")
        axis_expr = values.get("axis")
        material = self._material(values.get("material"))
        if not isinstance(seed_expr, IdentifierExpr) or seed_expr.name not in self.names:
            self.error("J180", "revolve seed must reference an earlier wire or box", seed_expr.span if seed_expr else decl.span)
            return
        if not isinstance(axis_expr, IdentifierExpr) or axis_expr.name not in {"x", "y", "z"}:
            self.error("J181", "revolve axis must be x, y, or z", axis_expr.span if axis_expr else decl.span)
            return
        if material is None:
            return
        seed = self.names[seed_expr.name]
        axis = axis_expr.name
        points3 = seed.points if isinstance(seed, _WireSource) else self._box_profile(seed, axis)
        projected, elevation = self._project_profile(points3, axis, decl.span)
        if projected is None:
            return
        seed.consumed = True
        self.rotations.append(RotPolyOp(decl.name, projected, axis, elevation, material))

    def _box_profile(self, box: _BoxSource, axis: str) -> tuple[Point3, ...]:
        a, b = box.start, box.stop
        if axis == "z":
            return ((a[0], a[1], a[2]), (b[0], a[1], a[2]), (b[0], b[1], a[2]), (a[0], b[1], a[2]))
        if axis == "y":
            return ((a[0], a[1], a[2]), (b[0], a[1], a[2]), (b[0], a[1], b[2]), (a[0], a[1], b[2]))
        return ((a[0], a[1], a[2]), (a[0], b[1], a[2]), (a[0], b[1], b[2]), (a[0], a[1], b[2]))

    def _project_profile(self, points: tuple[Point3, ...], axis: str, span: SourceSpan):
        constant_index = {"x": 2, "y": 1, "z": 2}[axis]
        values = [point[constant_index] for point in points]
        if max(values) - min(values) > 1e-9:
            self.error("J182", "revolve seed must be planar", span)
            return None, 0.0
        if axis == "z":
            projected = tuple((point[0], point[1]) for point in points)
        elif axis == "y":
            projected = tuple((point[0], point[2]) for point in points)
        else:
            projected = tuple((point[1], point[2]) for point in points)
        return projected, values[0]

    def _make_feed(self, source: _WireSource, wavelength: float) -> FeedSpec:
        total = self._path_length(source.points)
        target = total / 2
        traversed = 0.0
        midpoint = source.points[0]
        tangent = (1.0, 0.0, 0.0)
        for a, b in zip(source.points, source.points[1:]):
            length = math.dist(a, b)
            if traversed + length >= target:
                fraction = (target - traversed) / length
                midpoint = tuple(a[i] + (b[i] - a[i]) * fraction for i in range(3))
                tangent = tuple((b[i] - a[i]) / length for i in range(3))
                break
            traversed += length
        # The port must span the *entire* conductor gap: anything narrower
        # leaves a physically disconnected sliver of free space between the
        # port terminals and the actual wire ends on each side (the port
        # excites nothing but its own capacitance to two nearby, unconnected
        # stubs). That produced a near-total-mismatch, huge-reactance result
        # on both openEMS and Meep -- confirmed against SCUFF-EM, which
        # places its port directly on the conductor rim and sees a normal
        # resonance on the identical geometry.
        metal_gap = min(max(2 * source.radius, wavelength / 1000), total / 10)
        start = tuple(midpoint[i] - tangent[i] * metal_gap / 2 for i in range(3))
        stop = tuple(midpoint[i] + tangent[i] * metal_gap / 2 for i in range(3))
        direction = "xyz"[max(range(3), key=lambda i: abs(tangent[i]))]
        return FeedSpec(source.impedance or 50.0, start, stop, direction)

    def _domain(self, geometry: list[GeometryOp], wavelength: float, boundary: str):
        points: list[Point3] = []
        for op in geometry:
            if isinstance(op, (CurveOp, WireOp)):
                points.extend(op.points)
            elif isinstance(op, BoxOp):
                points.extend((op.start, op.stop))
            else:
                radial = max(abs(value) for point in op.points for value in point)
                points.extend(((-radial, -radial, op.elevation), (radial, radial, op.elevation)))
        pml_reservation = 8 * (wavelength / 20) if boundary == "PML_8" else 0.0
        padding = wavelength / 4 + pml_reservation
        lo = tuple(min(point[i] for point in points) - padding for i in range(3))
        hi = tuple(max(point[i] for point in points) + padding for i in range(3))
        result: list[GeometryOp] = []
        for op in geometry:
            if isinstance(op, BoxOp) and op.material == "earth_dry":
                result.append(replace(op, start=(lo[0], lo[1], op.start[2]), stop=(hi[0], hi[1], op.stop[2])))
            else:
                result.append(op)
        return lo, hi, result

    def _mesh(self, geometry: Sequence[GeometryOp], lo: Point3, hi: Point3, wavelength: float) -> MeshSpec:
        max_res = wavelength / 20
        from .mesh_features import fdtd_feature_axes

        sampled = fdtd_feature_axes(geometry, wavelength)
        axes: list[set[float]] = [{lo[i], hi[i], *sampled[i]} for i in range(3)]
        for op in geometry:
            if isinstance(op, (CurveOp, WireOp)) and op.feed:
                self._refine_feed_gap(axes, op.feed)
            elif isinstance(op, BoxOp):
                for i in range(3):
                    edge_lo, edge_hi = op.start[i], op.stop[i]
                    axes[i].update((edge_lo, edge_hi, edge_lo - max_res / 3, edge_lo + max_res / 3, edge_hi - max_res / 3, edge_hi + max_res / 3))
        lines = [self._fill_lines(sorted(axis), max_res) for axis in axes]
        return MeshSpec(tuple(lines[0]), tuple(lines[1]), tuple(lines[2]), max_res)

    @staticmethod
    def _refine_feed_gap(axes: list[set[float]], feed: FeedSpec) -> None:
        """Subdivide the feed gap so it spans at least three mesh cells."""
        gap = tuple(feed.stop[i] - feed.start[i] for i in range(3))
        length = math.dist(feed.start, feed.stop)
        if length <= 0:
            return
        # Find dominant axis of the feed gap.
        dominant = max(range(3), key=lambda i: abs(gap[i]))
        step = gap[dominant] / 3.0
        for index in (1, 2):
            axes[dominant].add(feed.start[dominant] + index * step)

    @staticmethod
    def _fill_lines(lines: list[float], max_res: float) -> list[float]:
        output = [lines[0]]
        for stop in lines[1:]:
            start = output[-1]
            count = max(1, math.ceil((stop - start) / max_res))
            output.extend(start + (stop - start) * i / count for i in range(1, count + 1))
        return sorted(set(round(value, 12) for value in output))

    def _deduplicate(self, geometry: list[GeometryOp]) -> list[GeometryOp]:
        seen: set[tuple] = set()
        result: list[GeometryOp] = []
        for op in geometry:
            if isinstance(op, (CurveOp, WireOp)):
                key = (type(op).__name__, op.points, op.material, op.radius_m, op.feed)
            elif isinstance(op, BoxOp):
                key = (type(op).__name__, op.start, op.stop, op.material)
            else:
                key = (type(op).__name__, op.points, op.axis, op.elevation, op.material)
            if key in seen:
                self.warnings.append(f"deduplicated geometry '{op.name}'")
                continue
            seen.add(key)
            result.append(op)
        return result

    @staticmethod
    def _path_length(points: Sequence[Point3]) -> float:
        return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

    @staticmethod
    def _split_path(points: tuple[Point3, ...], gap_start: Point3, gap_stop: Point3):
        total = _Analyzer._path_length(points)
        midpoint_distance = total / 2
        gap = math.dist(gap_start, gap_stop)

        def point_at(target: float) -> tuple[Point3, int]:
            traversed = 0.0
            for index, (a, b) in enumerate(zip(points, points[1:])):
                length = math.dist(a, b)
                if traversed + length >= target:
                    fraction = (target - traversed) / length
                    return tuple(a[i] + (b[i] - a[i]) * fraction for i in range(3)), index
                traversed += length
            return points[-1], len(points) - 2

        left_end, left_index = point_at(midpoint_distance - gap / 2)
        right_start, right_index = point_at(midpoint_distance + gap / 2)
        left = points[: left_index + 1] + (left_end,)
        right = (right_start,) + points[right_index + 1 :]
        return left, right


def analyze(program: Program, *, trace: TraceCallback | None = None) -> SimulationIR:
    return _Analyzer(program, trace).analyze()
