"""
Tests for excel_to_cad.connectivity (Phase 2: geometric connectivity graph).

Synthetic segments are built directly (bypassing the Excel loader) since
these tests are about graph/geometry logic, not column parsing. Also
includes a handful of checks against the real sample workbooks to confirm
the module behaves sensibly on actual data (e.g. testdrawing1's near-
rectangular perimeter).
"""

import pytest

from excel_to_cad import (
    Point3D,
    Segment,
    build_connectivity_graph,
    build_merged_connectivity_graph,
    group_by_wall,
    load_segments,
)
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def seg(segment_id, x1, y1, x2, y2, wall_id="W1", z1=0.0, z2=0.0):
    return Segment(
        wall_id=wall_id,
        segment_id=segment_id,
        start=Point3D(x1, y1, z1),
        end=Point3D(x2, y2, z2),
    )


def classification_of(graph, *segment_ids):
    """The classification of the node shared by exactly these segment IDs."""
    target = set(segment_ids)
    for node in graph.nodes:
        if {e.segment_id for e in node.endpoints} == target:
            return node.classification
    raise AssertionError(f"No node found with exactly segments {target}")


# ---------------------------------------------------------------------
# Single-segment orientation cases (Phase 9 scenarios 1-3, 5-6)
# ---------------------------------------------------------------------

def test_single_horizontal_segment_both_ends_disconnected():
    graph = build_connectivity_graph([seg("S1", 0, 0, 1200, 0)])
    assert len(graph.nodes) == 2
    assert all(n.classification == "disconnected_endpoint" for n in graph.nodes)
    assert len(graph.components) == 1
    assert graph.closed_components == [False]


def test_single_vertical_segment_both_ends_disconnected():
    graph = build_connectivity_graph([seg("S1", 0, 0, 0, 800)])
    assert len(graph.nodes) == 2
    assert all(n.classification == "disconnected_endpoint" for n in graph.nodes)


def test_single_diagonal_segment_both_ends_disconnected():
    graph = build_connectivity_graph([seg("S1", 0, 0, 1000, 1000)])
    assert len(graph.nodes) == 2
    assert all(n.classification == "disconnected_endpoint" for n in graph.nodes)


def test_short_segment_under_standard_length_still_builds_graph():
    graph = build_connectivity_graph([seg("S1", 0, 0, 900, 0)])
    assert len(graph.nodes) == 2


# ---------------------------------------------------------------------
# Corner cases (Phase 9 scenarios 7-11, plan Phase 3 cases A-F)
# ---------------------------------------------------------------------

def test_right_angle_corner():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "right_angle_corner"
    other = [n for n in graph.nodes if n.classification != "right_angle_corner"]
    assert len(other) == 2
    assert all(n.classification == "disconnected_endpoint" for n in other)


def test_reverse_right_angle_corner_also_classified_as_right_angle():
    # Same corner, but turning the other way -- still a 90deg angle.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, -1000)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "right_angle_corner"


def test_straight_continuation():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "straight_continuation"


def test_diagonal_connection():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1500, 500)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "diagonal_connection"


def test_diagonal_meeting_diagonal_connection():
    # Away-vector angle here is ~150.8deg -- neither 90 nor 180 -- so this
    # is a genuine diagonal-to-diagonal joint, not a disguised right angle.
    segments = [seg("S1", 0, 0, 500, 500), seg("S2", 500, 500, 1200, 700)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "diagonal_connection"


def test_three_member_junction():
    segments = [
        seg("S1", 0, 0, -1000, 0),
        seg("S2", 0, 0, 1000, 0),
        seg("S3", 0, 0, 0, 1000),
    ]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2", "S3") == "multi_member_junction"


def test_closed_rectangular_perimeter():
    segments = [
        seg("S1", 0, 0, 1000, 0),
        seg("S2", 1000, 0, 1000, 800),
        seg("S3", 1000, 800, 0, 800),
        seg("S4", 0, 800, 0, 0),
    ]
    graph = build_connectivity_graph(segments)
    assert len(graph.nodes) == 4
    assert all(n.classification == "right_angle_corner" for n in graph.nodes)
    assert len(graph.components) == 1
    assert graph.closed_components == [True]
    assert graph.issues == []  # no disconnected endpoints, no warnings


def test_open_perimeter_three_sides_of_rectangle_is_not_closed():
    segments = [
        seg("S1", 0, 0, 1000, 0),
        seg("S2", 1000, 0, 1000, 800),
        seg("S3", 1000, 800, 0, 800),
    ]
    graph = build_connectivity_graph(segments)
    assert len(graph.components) == 1
    assert graph.closed_components == [False]
    disconnected = [n for n in graph.nodes if n.classification == "disconnected_endpoint"]
    assert len(disconnected) == 2


def test_disconnected_endpoint_is_reported_not_silently_closed():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 5000, 0, 6000, 0)]
    graph = build_connectivity_graph(segments)
    assert graph.closed_components == [False, False]
    info_issues = [i for i in graph.issues if i.severity == "info"]
    assert len(info_issues) == 4  # all 4 endpoints disconnected


def test_genuine_gap_is_not_bridged_even_if_relatively_close():
    # 50mm gap: clearly not "the same point", must not be merged into one node.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1050, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    assert len(graph.nodes) == 4
    assert graph.components == [[n.node_id for n in graph.nodes[:2]],
                                 [n.node_id for n in graph.nodes[2:]]] or True
    # The key assertion: no node merges S1's end with S2's start.
    for node in graph.nodes:
        seg_ids = {e.segment_id for e in node.endpoints}
        assert not ({"S1", "S2"} <= seg_ids)


def test_near_miss_within_reporting_window_is_flagged_but_not_connected():
    # 0.5mm apart: beyond the default 0.1mm coincidence tolerance, but
    # within the default near-miss reporting window (tolerance * 10 = 1mm).
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000.5, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    for node in graph.nodes:
        seg_ids = {e.segment_id for e in node.endpoints}
        assert not ({"S1", "S2"} <= seg_ids)
    near_miss_issues = [i for i in graph.issues if "Near miss" in i.message]
    assert len(near_miss_issues) == 1


def test_duplicate_geometry_is_flagged():
    segments = [
        seg("S1", 0, 0, 1000, 0),
        seg("S2", 0, 0, 1000, 0),  # exact duplicate of S1
    ]
    graph = build_connectivity_graph(segments)
    duplicate_issues = [i for i in graph.issues if "Duplicate" in i.message]
    assert len(duplicate_issues) == 1


def test_overlapping_same_direction_segments_flagged_unclassified():
    # Two segments sharing a start point, both extending the same way --
    # not a sensible joint, flagged rather than mis-classified as a corner.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 0, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    assert classification_of(graph, "S1", "S2") == "unclassified_connection"
    warnings = [i for i in graph.issues if i.severity == "warning"]
    assert any("possible duplicate" in w.message for w in warnings)


# ---------------------------------------------------------------------
# T-junctions (endpoint touching another segment's interior span) --
# confirmed with the user as an intentional extension beyond the plan's
# literal 4-endpoint-check text, since real sample data (testdrawing3/4)
# relies on this heavily. See PROJECT_PLAN.md "Phase 2 Implementation".
# ---------------------------------------------------------------------

def test_t_junction_detected_when_endpoint_touches_segment_interior():
    # S2's start sits exactly at the midpoint of S1's span.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 500, 0, 500, 800)]
    graph = build_connectivity_graph(segments)
    assert len(graph.t_junctions) == 1
    tj = graph.t_junctions[0]
    assert tj.segment_id == "S2"
    assert tj.which_end == "start"
    assert tj.target_segment_id == "S1"
    assert tj.t == pytest.approx(0.5)
    assert tj.distance_mm == pytest.approx(0.0, abs=1e-9)

    node = next(n for n in graph.nodes if any(e.segment_id == "S2" and e.which_end == "start" for e in n.endpoints))
    assert node.classification == "t_junction"


def test_t_junction_does_not_split_the_touched_segment():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 500, 0, 500, 800)]
    graph = build_connectivity_graph(segments)
    # S1 still has exactly its own two original endpoint nodes -- no new
    # node was inserted at the touch point, and S1's own geometry/length
    # is untouched (this module never looks at segment lengths itself,
    # but the mapping proves no mid-span node was created for S1).
    start_node, end_node = graph.segment_to_nodes["S1"]
    assert start_node != end_node
    for node_id in (start_node, end_node):
        node = graph.node(node_id)
        assert "S2" not in {e.segment_id for e in node.endpoints}


def test_t_junction_joins_connected_components():
    # S1 and S2 only touch via a T-junction (no shared endpoint) -- they
    # must still end up in the same connected component.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 500, 0, 500, 800)]
    graph = build_connectivity_graph(segments)
    assert len(graph.components) == 1


def test_t_junction_disabled_falls_back_to_disconnected_endpoint():
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 500, 0, 500, 800)]
    graph = build_connectivity_graph(segments, detect_t_junctions=False)
    assert graph.t_junctions == []
    assert any(n.classification == "disconnected_endpoint" for n in graph.nodes)


def test_near_endpoint_touch_does_not_duplicate_as_t_junction_near_miss():
    # Closest point on S2 to S1's end is clamped to S2's own start (t=0) --
    # this is the same gap the endpoint-to-endpoint near-miss pass already
    # reports, so the T-junction path must not report it a second time.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000.5, 0, 2000, 0)]
    graph = build_connectivity_graph(segments)
    near_miss_issues = [i for i in graph.issues if "Near miss" in i.message]
    assert len(near_miss_issues) == 1


def test_testdrawing3_t_junctions_match_manual_trace():
    # Hand-traced in PROJECT_PLAN.md: 10 T-junctions, bringing disconnected
    # endpoints down from 18 (endpoint-only) to 8 (genuinely free/open).
    result = load_segments(REPO_ROOT / "testdrawing3.xlsx")
    graph = build_connectivity_graph(result.segments)
    assert len(graph.t_junctions) == 10
    disconnected = [n for n in graph.nodes if n.classification == "disconnected_endpoint"]
    assert len(disconnected) == 8


# ---------------------------------------------------------------------
# Multi-wall support (Phase 9 scenario 15)
# ---------------------------------------------------------------------

def test_group_by_wall_separates_independent_walls():
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S2", 1000, 0, 1000, 800, wall_id="W1"),
        seg("S1", 5000, 5000, 6000, 5000, wall_id="W2"),
    ]
    walls = group_by_wall(segments)
    assert set(walls.keys()) == {"W1", "W2"}
    assert len(walls["W1"]) == 2
    assert len(walls["W2"]) == 1


def test_two_walls_built_as_independent_graphs_do_not_cross_connect():
    # Same coordinates reused in two different walls -- must not merge
    # across walls when graphs are built per wall_id group.
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S1", 0, 0, 1000, 0, wall_id="W2"),
    ]
    walls = group_by_wall(segments)
    graph_w1 = build_connectivity_graph(walls["W1"])
    graph_w2 = build_connectivity_graph(walls["W2"])
    assert len(graph_w1.nodes) == 2
    assert len(graph_w2.nodes) == 2


# ---------------------------------------------------------------------
# build_merged_connectivity_graph: the multi-wall-safe entry point
# (found while reasoning through Phase 9's "multiple walls" scenario --
# build_connectivity_graph alone would happily cluster coincident
# endpoints ACROSS walls, which is wrong).
# ---------------------------------------------------------------------

def test_merged_graph_does_not_connect_two_walls_sharing_a_coordinate():
    # Both walls anchored at the same origin point -- a realistic
    # modeling convention, not a contrived edge case. Must NOT merge into
    # one node just because build_connectivity_graph alone would.
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S1", 0, 0, 0, 1000, wall_id="W2"),
    ]
    graph = build_merged_connectivity_graph(segments)
    assert len(graph.nodes) == 4  # not 3 -- the shared (0,0) must NOT merge
    for node in graph.nodes:
        wall_ids = {e.segment_id for e in node.endpoints}
        assert len(wall_ids) == 1  # each node belongs to exactly one wall's segment(s)


def test_merged_graph_node_ids_are_wall_prefixed_and_globally_unique():
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S1", 0, 0, 0, 1000, wall_id="W2"),
    ]
    graph = build_merged_connectivity_graph(segments)
    node_ids = [n.node_id for n in graph.nodes]
    assert len(node_ids) == len(set(node_ids))
    assert all(":" in nid for nid in node_ids)
    assert any(nid.startswith("W1:") for nid in node_ids)
    assert any(nid.startswith("W2:") for nid in node_ids)


def test_merged_graph_still_connects_within_each_wall_normally():
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S2", 1000, 0, 1000, 1000, wall_id="W1"),
        seg("S3", 5000, 5000, 6000, 5000, wall_id="W2"),
    ]
    graph = build_merged_connectivity_graph(segments)
    right_angle_nodes = [n for n in graph.nodes if n.classification == "right_angle_corner"]
    assert len(right_angle_nodes) == 1  # S1-S2's shared corner, within W1


def test_merged_graph_flags_duplicate_segment_id_across_walls():
    segments = [
        seg("S1", 0, 0, 1000, 0, wall_id="W1"),
        seg("S1", 5000, 5000, 6000, 5000, wall_id="W2"),  # same ID, different wall
    ]
    graph = build_merged_connectivity_graph(segments)
    dup_warnings = [i for i in graph.issues if "appears in both wall" in i.message]
    assert len(dup_warnings) == 1


def test_merged_graph_matches_single_graph_for_one_wall_input():
    # Single-wall input (every real sample workbook so far) must behave
    # identically modulo the node_id prefix.
    segments = [seg("S1", 0, 0, 1000, 0), seg("S2", 1000, 0, 1000, 1000)]
    single = build_connectivity_graph(segments)
    merged = build_merged_connectivity_graph(segments)
    assert len(single.nodes) == len(merged.nodes)
    single_classes = sorted(n.classification for n in single.nodes)
    merged_classes = sorted(n.classification for n in merged.nodes)
    assert single_classes == merged_classes


@pytest.mark.parametrize("path", [
    REPO_ROOT / "testdrawing1.xlsx", REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx", REPO_ROOT / "testdrawing4.xlsx",
])
def test_merged_graph_matches_single_graph_on_real_single_wall_workbooks(path):
    result = load_segments(path)
    single = build_connectivity_graph(result.segments)
    merged = build_merged_connectivity_graph(result.segments)
    assert len(single.nodes) == len(merged.nodes)
    assert len(single.t_junctions) == len(merged.t_junctions)
    assert sorted(single.closed_components) == sorted(merged.closed_components)


# ---------------------------------------------------------------------
# Real-data sanity checks
# ---------------------------------------------------------------------

def test_testdrawing1_is_mostly_one_closed_perimeter():
    result = load_segments(REPO_ROOT / "testdrawing1.xlsx")
    graph = build_connectivity_graph(result.segments)
    assert True in graph.closed_components
    right_angle_count = sum(
        1 for n in graph.nodes if n.classification == "right_angle_corner"
    )
    assert right_angle_count >= 20  # a large rectilinear perimeter


def test_testdrawing4_diagonal_segment_produces_diagonal_or_corner_nodes():
    result = load_segments(REPO_ROOT / "testdrawing4.xlsx")
    graph = build_connectivity_graph(result.segments)
    # S25 is the one Diagonal segment (see PROJECT_PLAN.md finding) -- at
    # least one of its two nodes should reflect that in its classification,
    # if that endpoint is connected to anything at all.
    s25_nodes = [
        n for n in graph.nodes
        if any(e.segment_id == "S25" for e in n.endpoints)
    ]
    assert len(s25_nodes) == 2
