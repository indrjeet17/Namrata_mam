"""
Phase 3: corner connectivity -- the plan's stated highest-priority phase.

This module does NOT rebuild connectivity (that's Phase 2's
ConnectivityGraph) -- it interprets that already-validated graph against
the plan's named corner cases (A-I), assigns a placeholder bracket symbol
where the real connector shape is unavailable (true for all four sample
workbooks -- confirmed in Phase 1, none contain bracket/support geometry),
and leaves a documented hook for Phase 4 to fill in the frame-dependent
cases (G, H) once frame sequences exist.

Mapping from the plan's corner cases to this implementation:

  A. Horizontal-to-vertical 90-degree corner   -> degree-2, ~90deg angle,
     both members axis-aligned (non-diagonal); turn direction 'ccw'.
  B. Reverse 90-degree corner                  -> same as A but turn
     direction 'cw'. ("Reverse" is read as the mirror-image turn of a
     plain right-angle corner; see _turn_direction for the convention.)
  C. Collinear segments meeting end-to-end     -> degree-2, ~180deg angle
     (ConnectivityGraph's "straight_continuation").
  D. Diagonal member(s) meeting horizontal,
     vertical, or diagonal members             -> any junction where at
     least one connected member is non-axis-aligned, REGARDLESS of the
     resulting angle (so a diagonal-vs-diagonal 90deg corner is D, not
     A/B -- A/B is reserved for genuinely "Horizontal-to-vertical", per
     the plan's own wording).
  E. Three or more segments at one endpoint    -> degree >= 3
     ("multi_member_junction").
  F. Closed wall/frame perimeter               -> connected-component-level
     flag (ConnectivityGraph.closed_components), added on top of whatever
     per-node case(s) already apply -- a rectangle's corners are each
     A/B *and* F, not F instead of A/B.
  G. Standard frame ends at the junction       -> populated by
     apply_frame_terminations() once Phase 4 frame sequences exist: added
     if ANY member meeting at this node has a "standard" frame touching
     it here.
  H. Custom-length frame terminates at the
     junction                                  -> same mechanism, for a
     "custom" frame touching this node. G and H can both apply at one
     corner if different members end there with different frame types.
  I. Multiple connected members and support
     symbols                                   -> support-symbol placement
     policy is explicitly configurable per Phase 6 ("at every standard
     frame boundary" / "at segment endpoints" / "at selected corners" /
     etc.) and no sample workbook contains symbol data (confirmed Phase
     1), so this module does not decide which corners get a symbol --
     only which corners are *structurally* multi-member (same set as E).

Extension beyond the plan's literal A-I list: T-junctions (see
connectivity.py) are a distinct, real, and common pattern in the sample
data that the plan's case list doesn't name at all. They get their own
case tag, "T", documented here rather than silently folded into E (a
T-junction is exactly two Segment records, not three, even though it
behaves like a 3-arm junction physically).
"""

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Set

from .connectivity import (
    ConnectivityGraph,
    Node,
    Segment,
    away_from_node_vector,
    axis_classification,
)
from .frames import Frame, determine_frame_terminations

DEFAULT_COINCIDENCE_TOLERANCE_MM = 0.1

# No sample workbook contains bracket/support block geometry (confirmed in
# Phase 1 inspection) -- every corner gets this single, clearly-named
# placeholder until real connector data becomes available. Deliberately one
# generic symbol rather than invented per-case shapes we have no evidence
# for (see module docstring, case I).
DEFAULT_BRACKET_SYMBOL = "PLACEHOLDER_BRACKET"


@dataclass
class CornerConnection:
    node_id: str
    point: tuple  # (x, y, z)
    degree: int
    member_segment_ids: List[str]
    classification: str  # carried from Node, e.g. "right_angle_corner"
    corner_cases: Set[str] = field(default_factory=set)  # subset of A-I, T
    turn_direction: Optional[str] = None  # "cw" / "ccw", only for 2-member right angles
    is_closed_perimeter_member: bool = False
    bracket_symbol: Optional[str] = None
    # member_segment_id -> "standard"/"custom", for the frame touching
    # THIS node specifically. Filled in by apply_frame_terminations() once
    # Phase 4 frame sequences exist; None until then.
    frame_termination: Optional[Dict[str, str]] = None
    notes: str = ""


def _turn_direction(graph: ConnectivityGraph, node: Node, by_id: Dict[str, Segment]) -> Optional[str]:
    """
    Chirality of a 2-member corner, relative to the node's stored endpoint
    order (deterministic, but an arbitrary reference frame -- not a claim
    about which physical side is "normal" vs "reverse" in the source
    drawing). Computed in the XY plane only (every sample segment is
    planar; a true out-of-plane corner would need a 3D generalization not
    exercised by any current data).

    This is a *local* label, not a global loop-winding direction: around a
    closed perimeter, the "closing" corner (where the last segment meets
    the first) can legitimately report the opposite label from the other
    corners, because which segment's endpoint was discovered first differs
    there. Do not assume uniform chirality across a whole closed loop --
    that would need a separate global winding-order calculation (e.g.
    shoelace formula), which the plan doesn't ask for.
    """
    if node.degree != 2:
        return None
    a, b = node.endpoints
    seg_a, seg_b = by_id[a.segment_id], by_id[b.segment_id]
    va = away_from_node_vector(seg_a, a.which_end)
    vb = away_from_node_vector(seg_b, b.which_end)
    cross_z = va[0] * vb[1] - va[1] * vb[0]
    if abs(cross_z) < 1e-9:
        return None  # collinear or degenerate -- no meaningful chirality
    return "ccw" if cross_z > 0 else "cw"


def _corner_cases_for_node(
    node: Node,
    graph: ConnectivityGraph,
    by_id: Dict[str, Segment],
    closed_node_ids: Set[str],
    tolerance_mm: float,
) -> Set[str]:
    cases: Set[str] = set()
    classification = node.classification

    if classification == "disconnected_endpoint":
        pass  # not a corner at all
    elif classification == "t_junction":
        cases.add("T")
    elif classification == "straight_continuation":
        cases.add("C")
    elif classification == "right_angle_corner":
        members = [by_id[e.segment_id] for e in node.endpoints]
        if any(axis_classification(m, tolerance_mm) == "diagonal" for m in members):
            cases.add("D")
        else:
            turn = _turn_direction(graph, node, by_id)
            cases.add("A" if turn == "ccw" else "B" if turn == "cw" else "A")
    elif classification == "diagonal_connection":
        cases.add("D")
    elif classification == "multi_member_junction":
        cases.add("E")
        members = [by_id[e.segment_id] for e in node.endpoints]
        if any(axis_classification(m, tolerance_mm) == "diagonal" for m in members):
            cases.add("D")
    # "unclassified_connection" intentionally gets no case -- it's flagged
    # as a warning by Phase 2 (e.g. possible duplicate geometry) rather
    # than forced into one of the plan's named buckets.

    if cases and node.node_id in closed_node_ids:
        cases.add("F")

    return cases


def build_corner_connections(
    graph: ConnectivityGraph,
    segments: List[Segment],
    bracket_symbol: str = DEFAULT_BRACKET_SYMBOL,
    tolerance_mm: float = DEFAULT_COINCIDENCE_TOLERANCE_MM,
) -> List[CornerConnection]:
    """
    Build one CornerConnection per graph node (including disconnected
    endpoints, so Phase 7's validation report has a single place to look
    at every endpoint -- open ones included).
    """
    by_id = {s.segment_id: s for s in segments}

    closed_node_ids: Set[str] = set()
    for component, is_closed in zip(graph.components, graph.closed_components):
        if is_closed:
            closed_node_ids.update(component)

    connections = []
    for node in graph.nodes:
        cases = _corner_cases_for_node(node, graph, by_id, closed_node_ids, tolerance_mm)
        turn = _turn_direction(graph, node, by_id) if node.degree == 2 else None

        connections.append(CornerConnection(
            node_id=node.node_id,
            point=node.point.as_tuple(),
            degree=node.degree,
            member_segment_ids=sorted({e.segment_id for e in node.endpoints}),
            classification=node.classification,
            corner_cases=cases,
            turn_direction=turn,
            is_closed_perimeter_member=node.node_id in closed_node_ids,
            bracket_symbol=bracket_symbol if cases else None,
            notes=node.details,
        ))

    return connections


def apply_frame_terminations(
    connections: List[CornerConnection],
    graph: ConnectivityGraph,
    frames: List[Frame],
) -> List[CornerConnection]:
    """
    Fill in corner cases G ("a standard frame ends at the junction") and H
    ("a custom-length frame terminates at the junction") now that Phase 4
    frame sequences exist. Returns new CornerConnection objects (does not
    mutate the input list) with frame_termination populated and G/H added
    to corner_cases where applicable.

    Only applies to nodes that are already recognized corners/junctions
    (already have at least one corner case) -- a lone open end isn't "a
    junction" just because a frame happens to terminate there.
    """
    terminations = determine_frame_terminations(frames)

    enriched = []
    for conn in connections:
        if not conn.corner_cases:
            enriched.append(conn)
            continue

        node = graph.node(conn.node_id)
        member_terminations: Dict[str, str] = {}
        for endpoint in node.endpoints:
            frame_type = terminations.get((endpoint.segment_id, endpoint.which_end))
            if frame_type is not None:
                member_terminations[endpoint.segment_id] = frame_type

        new_cases = set(conn.corner_cases)
        if any(t == "standard" for t in member_terminations.values()):
            new_cases.add("G")
        if any(t == "custom" for t in member_terminations.values()):
            new_cases.add("H")

        enriched.append(replace(
            conn, corner_cases=new_cases, frame_termination=member_terminations or None,
        ))

    return enriched
