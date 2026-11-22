"""
Tests for excel_to_cad.supports (Phase 6: support/bracket placement
policy).

Covers each placement policy individually, deduplication, the combined
resolver, and that dxf_export's default behavior is unchanged from before
Phase 6 existed (a support at every recognized corner).
"""

from pathlib import Path

import pytest

from excel_to_cad import (
    Point3D,
    Segment,
    SupportPlacementConfig,
    build_connectivity_graph,
    build_corner_connections,
    build_dxf_document,
    build_frame_schedule,
    combine_support_points,
    resolve_support_points,
    supports_at_corners,
    supports_at_explicit_coordinates,
    supports_at_frame_boundaries,
    supports_at_segment_endpoints,
    supports_by_spacing,
    load_segments,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


def seg(segment_id, x1, y1, x2, y2):
    return Segment(
        wall_id="W1", segment_id=segment_id,
        start=Point3D(x1, y1, 0.0), end=Point3D(x2, y2, 0.0),
    )


def build_pipeline(segments):
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    frames, issues = build_frame_schedule(segments)
    assert issues == []
    return frames, corners


# ---------------------------------------------------------------------
# Individual policies
# ---------------------------------------------------------------------

def test_supports_at_corners_excludes_open_ends():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    points = supports_at_corners(corners)
    assert len(points) == 1  # only the real corner, not the 2 open ends
    assert points[0].source == "corner"


def test_supports_at_segment_endpoints_includes_every_end_even_open_ones():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    points = supports_at_segment_endpoints(segments)
    assert len(points) == 4  # 2 segments x 2 ends each, including open ones
    assert all(p.source == "segment_endpoint" for p in points)


def test_supports_at_frame_boundaries_standard_only_excludes_custom_touching():
    # 2500mm -> 2 standard + 1 custom (100mm). Only one internal boundary
    # is standard-to-standard; the other touches the custom frame.
    segments = [seg("S1", 0, 0, 2500, 0)]
    frames, corners = build_pipeline(segments)
    standard_only = supports_at_frame_boundaries(frames, standard_only=True)
    all_boundaries = supports_at_frame_boundaries(frames, standard_only=False)
    assert len(standard_only) == 1
    assert len(all_boundaries) == 2


def test_supports_at_frame_boundaries_never_includes_segment_ends():
    segments = [seg("S1", 0, 0, 3600, 0)]  # 3 standard frames, exact multiple
    frames, corners = build_pipeline(segments)
    points = supports_at_frame_boundaries(frames, standard_only=False)
    assert len(points) == 2  # 2 internal boundaries for 3 frames, not 4
    xs = {p.point[0] for p in points}
    assert 0 not in xs
    assert 3600 not in xs


def test_supports_by_spacing_places_points_along_segment():
    segments = [seg("S1", 0, 0, 1000, 0)]
    points = supports_by_spacing(segments, spacing_mm=300)
    xs = sorted(p.point[0] for p in points)
    assert xs == pytest.approx([0, 300, 600, 900])  # stops before exceeding 1000


def test_supports_by_spacing_rejects_non_positive_spacing():
    with pytest.raises(ValueError):
        supports_by_spacing([seg("S1", 0, 0, 1000, 0)], spacing_mm=0)


def test_supports_at_explicit_coordinates_passthrough():
    coords = [(10, 20, 0), (30, 40, 0)]
    points = supports_at_explicit_coordinates(coords)
    assert [p.point for p in points] == coords
    assert all(p.source == "explicit" for p in points)


# ---------------------------------------------------------------------
# Deduplication / combination
# ---------------------------------------------------------------------

def test_combine_support_points_dedupes_near_identical_points():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    corner_points = supports_at_corners(corners)
    endpoint_points = supports_at_segment_endpoints(segments)
    # The corner point and one of S1's/S2's endpoints are the same physical
    # location -- must collapse to one, not duplicate.
    combined = combine_support_points(corner_points, endpoint_points)
    unique_locations = {round(p.point[0], 2) for p in combined} | \
                        {round(p.point[1], 2) for p in combined}
    # 3 physical points total (2 open ends + 1 shared corner), not 5.
    all_points = corner_points + endpoint_points
    assert len(all_points) == 5  # 1 corner + 4 endpoint-policy points
    assert len(combined) == 3


def test_combine_support_points_keeps_first_occurrence_order():
    a = supports_at_explicit_coordinates([(0, 0, 0)])
    b = supports_at_explicit_coordinates([(0, 0, 0)])
    combined = combine_support_points(a, b)
    assert len(combined) == 1
    assert combined[0] is a[0]  # first list's point wins, not the second's


def test_combine_support_points_does_not_merge_genuinely_distinct_points():
    a = supports_at_explicit_coordinates([(0, 0, 0)])
    b = supports_at_explicit_coordinates([(50, 0, 0)])
    combined = combine_support_points(a, b, dedupe_tolerance_mm=0.1)
    assert len(combined) == 2


# ---------------------------------------------------------------------
# resolve_support_points / SupportPlacementConfig
# ---------------------------------------------------------------------

def test_default_config_matches_corners_only():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    config = SupportPlacementConfig()
    points = resolve_support_points(config, segments, frames, corners)
    assert len(points) == 1
    assert points[0].source == "corner"


def test_config_can_combine_multiple_policies():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    config = SupportPlacementConfig(at_corners=True, at_segment_endpoints=True)
    points = resolve_support_points(config, segments, frames, corners)
    # 1 corner + 2 genuinely open ends (the shared corner point is deduped
    # against the matching segment-endpoint points).
    assert len(points) == 3


def test_config_with_everything_disabled_returns_no_supports():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, corners = build_pipeline(segments)
    config = SupportPlacementConfig(at_corners=False)
    points = resolve_support_points(config, segments, frames, corners)
    assert points == []


def test_config_spacing_and_corners_combined_and_deduped():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, corners = build_pipeline(segments)
    # Spacing of 1200mm lands exactly on both of S1's own endpoints.
    config = SupportPlacementConfig(at_corners=True, spacing_mm=1200)
    points = resolve_support_points(config, segments, frames, corners)
    sources = {p.source for p in points}
    assert "spacing" in sources
    # No duplicate symbol at the coincident start point.
    xs = sorted(round(p.point[0]) for p in points)
    assert xs == [0, 1200]


# ---------------------------------------------------------------------
# dxf_export integration: default behavior unchanged, config respected
# ---------------------------------------------------------------------

def test_dxf_export_default_support_behavior_is_unchanged_from_before_phase_6():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    circles = [e for e in doc.modelspace() if e.dxftype() == "CIRCLE"
               and e.dxf.layer == "SUPPORT_SYMBOLS"]
    assert len(circles) == 1  # same as the original hard-coded behavior


def test_dxf_export_respects_custom_support_config():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners = build_pipeline(segments)
    config = SupportPlacementConfig(at_corners=True, at_segment_endpoints=True)
    doc = build_dxf_document(segments, frames, corners, support_config=config)
    circles = [e for e in doc.modelspace() if e.dxftype() == "CIRCLE"
               and e.dxf.layer == "SUPPORT_SYMBOLS"]
    assert len(circles) == 3


# ---------------------------------------------------------------------
# Real-data sanity checks
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_corner_policy_matches_corners_with_cases(path):
    result = load_segments(path)
    graph = build_connectivity_graph(result.segments)
    corners = build_corner_connections(graph, result.segments)
    frames, issues = build_frame_schedule(result.segments)
    assert issues == []
    points = supports_at_corners(corners)
    assert len(points) == len([c for c in corners if c.corner_cases])


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_endpoint_policy_covers_every_segment_twice(path):
    result = load_segments(path)
    points = supports_at_segment_endpoints(result.segments)
    assert len(points) == len(result.segments) * 2
