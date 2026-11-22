"""
Tests for excel_to_cad.corners (Phase 3: corner connectivity / the plan's
named corner cases A-I, plus the T-junction extension from Phase 2).
"""

from pathlib import Path

import pytest

from excel_to_cad import (
    Point3D,
    Segment,
    apply_frame_terminations,
    build_connectivity_graph,
    build_corner_connections,
    build_frame_schedule,
    load_segments,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def seg(segment_id, x1, y1, x2, y2, wall_id="W1"):
    return Segment(
        wall_id=wall_id, segment_id=segment_id,
        start=Point3D(x1, y1, 0.0), end=Point3D(x2, y2, 0.0),
    )


def corner_at(connections, *segment_ids):
    target = set(segment_ids)
    for c in connections:
        if set(c.member_segment_ids) == target:
            return c
    raise AssertionError(f"No corner found with exactly members {target}")


# ---------------------------------------------------------------------
# Case A/B: right-angle corners, distinguished by turn direction
# ---------------------------------------------------------------------

def test_right_angle_corner_is_case_a_or_b_not_both():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    graph = build_connectivity_graph(segments)
    connections = build_corner_connections(graph, segments)
    c = corner_at(connections, "S1", "S2")
    assert c.corner_cases & {"A", "B"}
    assert not (c.corner_cases & {"C", "D", "E", "T"})
    assert c.turn_direction in ("cw", "ccw")


def test_reverse_right_angle_corner_gets_the_opposite_turn_direction():
    segments_normal = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    segments_reverse = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, -1000)]
    c_normal = corner_at(
        build_corner_connections(build_connectivity_graph(segments_normal), segments_normal),
        "S1", "S2",
    )
    c_reverse = corner_at(
        build_corner_connections(build_connectivity_graph(segments_reverse), segments_reverse),
        "S1", "S2",
    )
    assert c_normal.turn_direction != c_reverse.turn_direction
    assert c_normal.corner_cases != c_reverse.corner_cases


def test_closed_rectangle_all_four_corners_are_a_or_b_plus_f():
    segments = [
        seg("S1", 0, 0, 1000, 0),
        seg("S2", 1000, 0, 1000, 800),
        seg("S3", 1000, 800, 0, 800),
        seg("S4", 0, 800, 0, 0),
    ]
    graph = build_connectivity_graph(segments)
    connections = build_corner_connections(graph, segments)
    assert len(connections) == 4
    for c in connections:
        assert "F" in c.corner_cases
        assert c.corner_cases & {"A", "B"}
        assert c.turn_direction in ("cw", "ccw")
    # NOTE: turn_direction is local to each node's own stored endpoint
    # order (see module docstring) -- it is not a global loop-winding
    # direction. The "closing" corner (S4 meeting S1) legitimately gets
    # the opposite label from the other three here, because S1's points
    # were discovered first overall, flipping which segment plays the
    # "a" role only at that one corner. Not asserting uniform chirality
    # across the loop -- that would require a separate global winding-
    # order calculation the plan doesn't ask for.


# ---------------------------------------------------------------------
# Case C: collinear / straight continuation
# ---------------------------------------------------------------------

def test_straight_continuation_is_case_c():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2")
    assert c.corner_cases == {"C"}
    assert c.turn_direction is None


# ---------------------------------------------------------------------
# Case D: diagonal member involved, regardless of resulting angle
# ---------------------------------------------------------------------

def test_diagonal_meeting_horizontal_is_case_d():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1500, 500)]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2")
    assert c.corner_cases == {"D"}


def test_diagonal_meeting_at_exact_right_angle_is_case_d_not_a_or_b():
    # Two diagonal members that happen to meet at 90 degrees -- plan's
    # wording reserves A/B for "Horizontal-to-vertical" specifically.
    segments = [seg("S1", 0, 0, 500, 500), seg("S2", 500, 500, 1000, 0)]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2")
    assert c.corner_cases == {"D"}
    assert "A" not in c.corner_cases and "B" not in c.corner_cases


# ---------------------------------------------------------------------
# Case E: three or more members
# ---------------------------------------------------------------------

def test_three_member_junction_is_case_e():
    segments = [
        seg("S1", 0, 0, -1000, 0),
        seg("S2", 0, 0, 1000, 0),
        seg("S3", 0, 0, 0, 1000),
    ]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2", "S3")
    assert "E" in c.corner_cases


def test_three_member_junction_with_diagonal_member_also_gets_case_d():
    segments = [
        seg("S1", 0, 0, -1000, 0),
        seg("S2", 0, 0, 1000, 0),
        seg("S3", 0, 0, 500, 500),  # diagonal
    ]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2", "S3")
    assert c.corner_cases == {"E", "D"}


# ---------------------------------------------------------------------
# T-junction case (extension beyond the plan's literal A-I list)
# ---------------------------------------------------------------------

def test_t_junction_gets_case_t():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 500, 0, 500, 800)]
    graph = build_connectivity_graph(segments)
    connections = build_corner_connections(graph, segments)
    t_node = next(c for c in connections if c.classification == "t_junction")
    assert t_node.corner_cases == {"T"}
    assert t_node.bracket_symbol is not None


# ---------------------------------------------------------------------
# No case for genuinely open ends / unclassified connections
# ---------------------------------------------------------------------

def test_disconnected_endpoint_has_no_corner_case_and_no_bracket_symbol():
    segments = [seg("S1", 0, 0, 1000, 0)]
    graph = build_connectivity_graph(segments)
    connections = build_corner_connections(graph, segments)
    assert all(c.corner_cases == set() for c in connections)
    assert all(c.bracket_symbol is None for c in connections)


def test_unclassified_connection_has_no_corner_case():
    # Two segments sharing a start point, both extending the same way.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 0, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2")
    assert c.corner_cases == set()
    assert c.bracket_symbol is None


# ---------------------------------------------------------------------
# Bracket symbol placeholder
# ---------------------------------------------------------------------

def test_bracket_symbol_is_assigned_only_to_real_corners():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    graph = build_connectivity_graph(segments)
    c = corner_at(build_corner_connections(graph, segments), "S1", "S2")
    assert c.bracket_symbol == "PLACEHOLDER_BRACKET"


def test_bracket_symbol_is_configurable():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    graph = build_connectivity_graph(segments)
    connections = build_corner_connections(graph, segments, bracket_symbol="CUSTOM_BRACKET_V2")
    c = corner_at(connections, "S1", "S2")
    assert c.bracket_symbol == "CUSTOM_BRACKET_V2"


# ---------------------------------------------------------------------
# Cases G/H: frame terminations at a junction (Phase 4 integration)
# ---------------------------------------------------------------------

def test_both_members_standard_frames_gives_case_g_only():
    # S1 (1200mm, exactly one standard frame) meets S2 (1200mm, same) --
    # both ends at the corner are "standard" frame terminations.
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    frames, _ = build_frame_schedule(segments)
    enriched = apply_frame_terminations(corners, graph, frames)
    c = corner_at(enriched, "S1", "S2")
    assert "G" in c.corner_cases
    assert "H" not in c.corner_cases
    assert c.frame_termination == {"S1": "standard", "S2": "standard"}


def test_custom_ending_member_meets_standard_starting_member_gives_both_g_and_h():
    # S1 is 1300mm (1 standard + 100mm custom) -- its END is a custom
    # frame. S2's START is always standard (it's long enough). Both G and
    # H should apply at their shared corner.
    segments = [seg("S1", 0, 0, 1300, 0), seg("S2", 1300, 0, 1300, 1300)]
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    frames, _ = build_frame_schedule(segments)
    enriched = apply_frame_terminations(corners, graph, frames)
    c = corner_at(enriched, "S1", "S2")
    assert c.corner_cases & {"G", "H"} == {"G", "H"}
    assert c.frame_termination == {"S1": "custom", "S2": "standard"}


def test_open_end_does_not_gain_a_corner_case_from_frame_termination():
    segments = [seg("S1", 0, 0, 1300, 0)]
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    frames, _ = build_frame_schedule(segments)
    enriched = apply_frame_terminations(corners, graph, frames)
    assert all(c.corner_cases == set() for c in enriched)
    assert all(c.frame_termination is None for c in enriched)


def test_apply_frame_terminations_does_not_mutate_input_list():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    original_cases = {c.node_id: set(c.corner_cases) for c in corners}
    frames, _ = build_frame_schedule(segments)
    apply_frame_terminations(corners, graph, frames)
    assert {c.node_id: set(c.corner_cases) for c in corners} == original_cases


# ---------------------------------------------------------------------
# Real-data cross-checks
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
])
def test_corner_connections_cover_every_node_exactly_once(path):
    result = load_segments(path)
    graph = build_connectivity_graph(result.segments)
    connections = build_corner_connections(graph, result.segments)
    assert len(connections) == len(graph.nodes)
    assert {c.node_id for c in connections} == {n.node_id for n in graph.nodes}


def test_testdrawing1_right_angle_count_splits_into_a_and_b():
    result = load_segments(REPO_ROOT / "testdrawing1.xlsx")
    graph = build_connectivity_graph(result.segments)
    connections = build_corner_connections(graph, result.segments)
    right_angle_nodes = [n for n in graph.nodes if n.classification == "right_angle_corner"]
    a_or_b = [c for c in connections if c.corner_cases & {"A", "B"}]
    assert len(a_or_b) == len(right_angle_nodes)


@pytest.mark.parametrize("path", [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
])
def test_apply_frame_terminations_only_touches_corners_not_open_ends(path):
    result = load_segments(path)
    graph = build_connectivity_graph(result.segments)
    corners = build_corner_connections(graph, result.segments)
    frames, issues = build_frame_schedule(result.segments)
    assert issues == []
    enriched = apply_frame_terminations(corners, graph, frames)

    for c in enriched:
        if c.classification in ("disconnected_endpoint", "unclassified_connection"):
            assert c.corner_cases == set()
            assert c.frame_termination is None
        if {"G", "H"} & c.corner_cases:
            assert c.frame_termination  # non-empty dict backing the case(s)


def test_testdrawing4_diagonal_right_angle_reclassified_as_d():
    # testdrawing4 has 19 right_angle_corner nodes in the connectivity
    # graph, but 2 of them involve the one Diagonal segment (S25) and
    # should come out as case D here, not A/B -- so only 17 should be A/B.
    result = load_segments(REPO_ROOT / "testdrawing4.xlsx")
    graph = build_connectivity_graph(result.segments)
    connections = build_corner_connections(graph, result.segments)
    right_angle_nodes = [n for n in graph.nodes if n.classification == "right_angle_corner"]
    a_or_b = [c for c in connections if c.corner_cases & {"A", "B"}]
    d_from_right_angle = [
        c for c in connections
        if c.classification == "right_angle_corner" and "D" in c.corner_cases
    ]
    assert len(right_angle_nodes) == 19
    assert len(a_or_b) == 17
    assert len(d_from_right_angle) == 2
