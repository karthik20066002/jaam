"""Regression tests for the FDTD feature-axis mesh anchors.

All three bugs here manifested the same way downstream: openEMS uses one
global timestep bound by the single smallest cell anywhere in the grid, so
a single stray micron-scale mesh line (from any of them) collapsed the
timestep for the *entire* simulation and multiplied wall-clock solve time
by several x, with no accuracy benefit (the extra lines were never
intentional).
"""
from __future__ import annotations

from jaam.ir import FeedSpec, WireOp
from jaam.mesh_features import fdtd_feature_axes


def test_feed_anchors_get_no_radius_padding() -> None:
    """Feed start/stop must not be padded by the wire's cross-sectional
    radius on any axis.

    Reproduces the dipole bug: a 1mm-radius wire with a 0.667mm feed gap
    got a z-axis line at feed.stop - radius/2, landing inside/past the
    opposite terminal and forcing a ~250x-too-small global timestep.
    """
    radius = 0.001
    feed = FeedSpec(
        impedance_ohm=50.0,
        start=(0.0, 0.0, -0.000333333333),
        stop=(0.0, 0.0, 0.000333333333),
        direction="z",
    )
    wire = WireOp(
        name="dipole__a",
        points=((0.0, 0.0, -0.071), (0.0, 0.0, -0.001)),
        material="copper",
        radius_m=radius,
        feed=feed,
    )
    axes = fdtd_feature_axes((wire,), wavelength=0.3)

    # feed.start/stop share x=y=0 with the wire's far tip, so only the z
    # axis (where the feed's own coordinate is distinct) discriminates
    # whether the feed itself got padded.
    assert feed.stop[2] - radius / 2.0 not in axes[2], "feed anchor was padded by wire radius"
    assert feed.stop[2] + radius / 2.0 not in axes[2]
    assert feed.start[2] - radius / 2.0 not in axes[2]
    # The exact feed boundaries must still be present as hard anchors.
    assert feed.start[2] in axes[2]
    assert feed.stop[2] in axes[2]
    # A point far from the feed still gets its ordinary cross-section padding.
    tip = wire.points[0]
    assert tip[0] + radius in axes[0]
    assert tip[1] + radius in axes[1]


def test_straight_wire_endpoint_is_not_duplicated_by_lambda20_snapping() -> None:
    """A wire endpoint must appear exactly once, not twice microns apart.

    Reproduces the yagi bug: a straight 2-point wire's endpoint was added
    both exactly (via the critical-point list) and separately rounded to
    the nearest lambda/20 grid line (via the tessellation-thinning loop
    meant for curves), planting a near-zero-width cell next to every
    straight wire in the model.
    """
    wavelength = 299_792_458.0 / 2.45e9
    min_step = wavelength / 20.0
    endpoint = -0.0245
    wire = WireOp(
        name="director3",
        points=((0.11, endpoint, 0.0), (0.11, -endpoint, 0.0)),
        material="copper",
        radius_m=0.0015,
        feed=None,
    )
    axes = fdtd_feature_axes((wire,), wavelength=wavelength)
    y_axis = axes[1]

    snapped_twin = round(endpoint / min_step) * min_step
    assert endpoint in y_axis
    assert snapped_twin not in y_axis or snapped_twin == endpoint


def test_split_wire_cut_ends_do_not_collide_across_pieces() -> None:
    """A feed splits one wire into two ops (see semantics._split_path); the
    fed piece's own cut end and the unfed sibling's cut start land within
    one wire-radius of the feed and of each other.

    Reproduces the helix bug: each piece padded its own cut end by
    +/-radius independently, and because the two ends sit only ~2x radius
    apart (a typical metal gap), the two padding halos interleaved into a
    sub-micron gap on axes transverse to the feed direction, on a wire
    whose local direction is not axis-aligned (a coil), so no single axis
    exclusion could catch it.
    """
    radius = 0.0015
    feed = FeedSpec(
        impedance_ohm=50.0,
        start=(0.0178, -0.00755, 0.0542),
        stop=(0.0182, -0.00665, 0.0544),
        direction="y",
    )
    fed_piece = WireOp(
        name="antenna__a",
        points=((0.0195, 0.0, 0.0), (0.01750, -0.00805, 0.0540)),
        material="copper",
        radius_m=radius,
        feed=feed,
    )
    sibling = WireOp(
        name="antenna__b",
        points=((0.01850, -0.00615, 0.0546), (0.0195, 0.0, 0.0560)),
        material="copper",
        radius_m=radius,
        feed=None,
    )
    axes = fdtd_feature_axes((fed_piece, sibling), wavelength=0.1224)

    for axis_values in axes:
        sorted_values = sorted(axis_values)
        gaps = [b - a for a, b in zip(sorted_values, sorted_values[1:])]
        assert not gaps or min(gaps) > 1e-4, f"sub-micron cell survived: {min(gaps) if gaps else None}"
