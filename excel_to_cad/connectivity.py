"""
Phase 2: geometric connectivity graph.

Builds the graph of segment endpoints (nodes) and segments (edges), strictly
by endpoint coincidence within a configurable tolerance -- never by
proximity heuristics, ID adjacency, or assumed chaining.

This matters concretely: Phase 1 inspection of the sample workbooks found
that the source data's own "Continuity Status" column is a naive
"does segment N's start equal segment (N-1)'s end" check, not a real
connectivity graph -- it misses genuine connections between non-consecutive
segment IDs (confirmed: testdrawing4 has 18 such cases). This module checks
all four endpoint-pairing combinations across *all* segment pairs instead.

Design notes (choices made where the plan's text is open to interpretation,
recorded here rather than silently assumed elsewhere):

- A node is formed by transitively clustering endpoints that are pairwise
  within `coincidence_tolerance_mm` of each other (standard "weld" approach).
  With the tolerance kept small relative to the smallest genuine gap between
  distinct points in the real data (empirically ~1.0mm across all four
  sample workbooks, vs. ~1e-12mm of floating-point noise between points that
  really are the same -- see PROJECT_PLAN.md), transitive chaining in
  practice never bridges two points that were meant to stay distinct.
- A node's authoritative coordinate is its first-encountered endpoint's
  point (deterministic by segment order), per the plan's "preserve the
  original shared corner coordinate" -- not an average/centroid, which
  would itself be a (tiny) invented coordinate.
- Per-node classification (right_angle_corner / straight_continuation /
  diagonal_connection / multi_member_junction / unclassified_connection)
  is a *local* property based on degree and the angle between members.
  "Closed-perimeter connection" (case F) is instead a *connected-component*
  property (whether that whole sub-graph forms a single cycle) -- a
  rectangle's four corners are still individually right_angle_corner nodes;
  closed-ness describes the loop they form together, not a fifth kind of
  corner angle. Both are reported.
- Degree-1 nodes (open ends) are not forced into one of the plan's listed
  junction categories -- they are reported as "disconnected_endpoint" per
  Phase 2's explicit instruction to report disconnected endpoints rather
  than silently close or hide them.
- Two segments sharing the same unordered pair of nodes (duplicate/
  overlapping geometry, Phase 9 test 14) are flagged separately from closed-
  loop detection, even though a 2-node "digon" is structurally cyclic.

T-junctions: confirmed against the real sample workbooks (see PROJECT_PLAN.md)
that a large fraction of genuine physical connections are a segment's
endpoint touching the *interior* of another segment's span -- not another
endpoint. The plan's literal Phase 2 text only names the four endpoint-to-
endpoint checks, but leaves most of testdrawing3's real connections
unreported as a result, so T-junction detection is included (confirmed with
the user before implementing -- see PROJECT_PLAN.md "Phase 2 Implementation").
This never changes a segment's own geometry (no splitting at the touch
point) -- a T-junction is purely a connectivity annotation; Phase 4 still
places frames along each segment's full original start-to-end length.
"""

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .models import Point3D, Segment, ValidationIssue

DEFAULT_COINCIDENCE_TOLERANCE_MM = 0.1
DEFAULT_ANGLE_TOLERANCE_DEG = 1.0
DEFAULT_NEAR_MISS_FACTOR = 10.0  # "worth a look" radius = tolerance * factor


@dataclass
class EndpointRef:
    segment_id: str
    which_end: str  # "start" or "end"
    point: Point3D


@dataclass
class Node:
    node_id: str
    point: Point3D  # authoritative/representative coordinate
    endpoints: List[EndpointRef] = field(default_factory=list)
    classification: str = "unclassified_connection"
    max_internal_deviation_mm: float = 0.0
    details: str = ""

    @property
    def degree(self) -> int:
        return len(self.endpoints)


@dataclass
class TJunction:
    """A segment's endpoint touching the interior of another segment's span
    (not splitting that segment -- purely a connectivity annotation)."""

    node_id: str
    segment_id: str          # the segment whose endpoint touches
    which_end: str
    target_segment_id: str   # the segment being touched, along its interior
    t: float                 # parametric position on the target, 0=start .. 1=end
    point: Point3D           # the touch point, on the target segment's line
    distance_mm: float


@dataclass
class ConnectivityGraph:
    nodes: List[Node]
    segment_to_nodes: Dict[str, Tuple[str, str]]  # segment_id -> (start_node_id, end_node_id)
    components: List[List[str]]  # list of node_id lists, one per connected component
    closed_components: List[bool]  # parallel to components
    issues: List[ValidationIssue]
    t_junctions: List[TJunction] = field(default_factory=list)

    def node(self, node_id: str) -> Node:
        return self._by_id[node_id]

    def __post_init__(self):
        self._by_id = {n.node_id: n for n in self.nodes}


class _UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def group_by_wall(segments: List[Segment]) -> Dict[str, List[Segment]]:
    """Group segments by Wall ID, preserving original order within each wall."""
    grouped: Dict[str, List[Segment]] = {}
    for seg in segments:
        grouped.setdefault(seg.wall_id, []).append(seg)
    return grouped


def axis_classification(segment: Segment, tol_mm: float) -> str:
    """Classify a segment's own geometry as horizontal/vertical/diagonal
    from its actual coordinates (not the reported Direction text, which may
    be absent -- and per Phase 1 spot checks, agrees with geometry anyway)."""
    dx = segment.end.x - segment.start.x
    dy = segment.end.y - segment.start.y
    dz = segment.end.z - segment.start.z
    if abs(dy) <= tol_mm and abs(dz) <= tol_mm and abs(dx) > tol_mm:
        return "horizontal"
    if abs(dx) <= tol_mm and abs(dz) <= tol_mm and abs(dy) > tol_mm:
        return "vertical"
    return "diagonal"


def _normalize(vx, vy, vz):
    length = math.sqrt(vx * vx + vy * vy + vz * vz)
    if length == 0:
        return (0.0, 0.0, 0.0)
    return (vx / length, vy / length, vz / length)


def away_from_node_vector(segment: Segment, which_end: str):
    """Unit vector pointing from the node outward along the segment,
    towards the segment's *other* endpoint."""
    if which_end == "start":
        far = segment.end
        near = segment.start
    else:
        far = segment.start
        near = segment.end
    return _normalize(far.x - near.x, far.y - near.y, far.z - near.z)


def _angle_between_deg(v1, v2) -> float:
    dot = max(-1.0, min(1.0, v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]))
    return math.degrees(math.acos(dot))


def _closest_point_on_segment(point: Point3D, segment: Segment):
    """Closest point to `point` on segment's line, clamped to [0,1].

    Returns (closest_point, t, distance_mm). If t ends up clamped to (near)
    0 or 1, the closest point is (near) one of the segment's own endpoints
    -- which, if truly within the coincidence tolerance, would already have
    been merged by the endpoint-to-endpoint pass, so this helper is only
    meaningful for finding genuine *interior* (T-junction) touches.
    """
    ax, ay, az = segment.start.x, segment.start.y, segment.start.z
    bx, by, bz = segment.end.x, segment.end.y, segment.end.z
    dx, dy, dz = bx - ax, by - ay, bz - az
    length_sq = dx * dx + dy * dy + dz * dz
    if length_sq == 0:
        return segment.start, 0.0, point.distance_to(segment.start)

    t = ((point.x - ax) * dx + (point.y - ay) * dy + (point.z - az) * dz) / length_sq
    t_clamped = max(0.0, min(1.0, t))
    closest = Point3D(ax + t_clamped * dx, ay + t_clamped * dy, az + t_clamped * dz)
    return closest, t_clamped, point.distance_to(closest)


def build_connectivity_graph(
    segments: List[Segment],
    coincidence_tolerance_mm: float = DEFAULT_COINCIDENCE_TOLERANCE_MM,
    angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    near_miss_factor: float = DEFAULT_NEAR_MISS_FACTOR,
    detect_t_junctions: bool = True,
    t_junction_tolerance_mm: Optional[float] = None,
) -> ConnectivityGraph:
    """
    Build the connectivity graph for a set of segments (typically one
    wall's segments -- see group_by_wall for multi-wall workbooks).

    Checks all four endpoint-pairing combinations (end-to-start,
    start-to-end, start-to-start, end-to-end) implicitly, by clustering
    every segment's start and end point together regardless of which
    "role" (start/end) they were recorded under -- a segment's recorded
    start/end labeling does not constrain which other segment's start or
    end it may connect to.

    If detect_t_junctions is True (default), a degree-1 node (no matching
    endpoint found) is additionally checked against every other segment's
    interior span; a touch within t_junction_tolerance_mm (defaults to
    coincidence_tolerance_mm) is recorded as a TJunction rather than left
    as a disconnected_endpoint. This does not alter either segment's own
    geometry -- it is purely a connectivity annotation.
    """
    by_id = {s.segment_id: s for s in segments}

    endpoints: List[EndpointRef] = []
    for seg in segments:
        endpoints.append(EndpointRef(seg.segment_id, "start", seg.start))
        endpoints.append(EndpointRef(seg.segment_id, "end", seg.end))

    uf = _UnionFind(range(len(endpoints)))
    near_miss_mm = coincidence_tolerance_mm * near_miss_factor
    issues: List[ValidationIssue] = []
    near_miss_pairs = []

    for i in range(len(endpoints)):
        for j in range(i + 1, len(endpoints)):
            if endpoints[i].segment_id == endpoints[j].segment_id:
                continue  # a segment's own two ends never "connect" to itself
            d = endpoints[i].point.distance_to(endpoints[j].point)
            if d <= coincidence_tolerance_mm:
                uf.union(i, j)
            elif d <= near_miss_mm:
                near_miss_pairs.append((endpoints[i], endpoints[j], d))

    clusters: Dict[int, List[int]] = {}
    for idx in range(len(endpoints)):
        clusters.setdefault(uf.find(idx), []).append(idx)

    # Deterministic node ordering: by the lowest endpoint index in each
    # cluster, which follows original segment order.
    ordered_roots = sorted(clusters.keys(), key=lambda r: min(clusters[r]))

    nodes: List[Node] = []
    segment_to_nodes: Dict[str, Dict[str, str]] = {
        s.segment_id: {} for s in segments
    }

    for i, root in enumerate(ordered_roots, start=1):
        idxs = clusters[root]
        idxs.sort()  # first-encountered endpoint is authoritative
        node_id = f"N{i}"
        refs = [endpoints[k] for k in idxs]
        representative = refs[0].point
        max_dev = max((representative.distance_to(r.point) for r in refs), default=0.0)
        node = Node(node_id=node_id, point=representative, endpoints=refs,
                    max_internal_deviation_mm=max_dev)
        nodes.append(node)
        for r in refs:
            segment_to_nodes[r.segment_id][r.which_end] = node_id

    # Classify each node.
    t_junctions: List[TJunction] = []
    t_junction_tol = (
        coincidence_tolerance_mm if t_junction_tolerance_mm is None
        else t_junction_tolerance_mm
    )

    for node in nodes:
        degree = node.degree
        if degree == 1:
            ref = node.endpoints[0]
            best = None  # (distance, target_segment_id, t, point)
            if detect_t_junctions:
                for other in segments:
                    if other.segment_id == ref.segment_id:
                        continue
                    closest, t, dist = _closest_point_on_segment(node.point, other)
                    if best is None or dist < best[0]:
                        best = (dist, other.segment_id, t, closest)

            if best is not None and best[0] <= t_junction_tol:
                dist, target_id, t, _ = best
                node.classification = "t_junction"
                node.details = (
                    f"Segment {ref.segment_id} ({ref.which_end}) touches the "
                    f"interior of segment {target_id} at t={t:.4f} "
                    f"(distance={dist:.4f}mm)."
                )
                t_junctions.append(TJunction(
                    node_id=node.node_id, segment_id=ref.segment_id,
                    which_end=ref.which_end, target_segment_id=target_id,
                    t=t, point=node.point, distance_mm=dist,
                ))
                issues.append(ValidationIssue(
                    severity="info",
                    segment_id=ref.segment_id,
                    message=(
                        f"Node {node.node_id} at {node.point.as_tuple()}: "
                        f"T-junction -- segment {ref.segment_id} "
                        f"({ref.which_end}) meets segment {target_id}'s "
                        f"interior (t={t:.4f}, distance={dist:.4f}mm)."
                    ),
                ))
            else:
                node.classification = "disconnected_endpoint"
                node.details = (
                    f"Segment {ref.segment_id} ({ref.which_end}) has no "
                    f"matching endpoint or interior touch within "
                    f"{coincidence_tolerance_mm}mm."
                )
                issues.append(ValidationIssue(
                    severity="info",
                    segment_id=ref.segment_id,
                    message=(
                        f"Node {node.node_id} at {node.point.as_tuple()}: "
                        f"disconnected endpoint (segment {ref.segment_id}, "
                        f"{ref.which_end})."
                    ),
                ))
                # Only report a *T-junction* near-miss when the nearest point
                # is genuinely interior (0 < t < 1) -- a match clamped to the
                # target's own t=0/1 endpoint is the same gap the endpoint-
                # to-endpoint near-miss pass above already reports; reporting
                # it again here would just be a duplicate of that warning.
                is_interior_match = best is not None and 0.0 < best[2] < 1.0
                if (
                    best is not None and is_interior_match
                    and coincidence_tolerance_mm < best[0] <= near_miss_mm
                ):
                    issues.append(ValidationIssue(
                        severity="warning",
                        segment_id=ref.segment_id,
                        message=(
                            f"Near miss: segment {ref.segment_id} "
                            f"({ref.which_end}) is {best[0]:.4f}mm from "
                            f"segment {best[1]}'s interior (t={best[2]:.4f}) "
                            f"-- within {near_miss_mm}mm but beyond the "
                            f"{t_junction_tol}mm tolerance, so left "
                            f"disconnected."
                        ),
                    ))
        elif degree == 2:
            a, b = node.endpoints
            seg_a, seg_b = by_id[a.segment_id], by_id[b.segment_id]
            va = away_from_node_vector(seg_a, a.which_end)
            vb = away_from_node_vector(seg_b, b.which_end)
            angle = _angle_between_deg(va, vb)

            if abs(angle - 180.0) <= angle_tolerance_deg:
                node.classification = "straight_continuation"
            elif abs(angle - 90.0) <= angle_tolerance_deg:
                node.classification = "right_angle_corner"
            elif (
                axis_classification(seg_a, coincidence_tolerance_mm) == "diagonal"
                or axis_classification(seg_b, coincidence_tolerance_mm) == "diagonal"
            ):
                node.classification = "diagonal_connection"
            else:
                node.classification = "unclassified_connection"
                detail = f"angle between members = {angle:.2f} deg"
                if angle <= angle_tolerance_deg:
                    detail += " (members overlap in the same direction -- possible duplicate geometry)"
                node.details = detail
                issues.append(ValidationIssue(
                    severity="warning",
                    segment_id=None,
                    message=(
                        f"Node {node.node_id} at {node.point.as_tuple()}: "
                        f"unclassified connection between {a.segment_id} and "
                        f"{b.segment_id} ({detail})."
                    ),
                ))
        else:
            node.classification = "multi_member_junction"
            member_ids = ", ".join(sorted({e.segment_id for e in node.endpoints}))
            node.details = f"{degree} members meet here: {member_ids}"

    # Near-miss reporting: endpoints close but not within tolerance, so they
    # were deliberately left disconnected -- surfaced in case the tolerance
    # needs revisiting, never auto-connected.
    for ref_a, ref_b, d in near_miss_pairs:
        issues.append(ValidationIssue(
            severity="warning",
            segment_id=None,
            message=(
                f"Near miss: {ref_a.segment_id} ({ref_a.which_end}) and "
                f"{ref_b.segment_id} ({ref_b.which_end}) are {d:.4f}mm apart "
                f"-- within {near_miss_mm}mm but beyond the "
                f"{coincidence_tolerance_mm}mm coincidence tolerance, so left "
                f"disconnected. Review if this should actually connect."
            ),
        ))

    # Duplicate/overlapping segment detection: two different segments
    # sharing the same unordered pair of nodes.
    node_pair_to_segments: Dict[frozenset, List[str]] = {}
    for seg in segments:
        ends = segment_to_nodes[seg.segment_id]
        if "start" not in ends or "end" not in ends:
            continue
        pair = frozenset((ends["start"], ends["end"]))
        node_pair_to_segments.setdefault(pair, []).append(seg.segment_id)
    for pair, seg_ids in node_pair_to_segments.items():
        if len(seg_ids) > 1:
            issues.append(ValidationIssue(
                severity="warning",
                segment_id=None,
                message=(
                    f"Duplicate/overlapping geometry: segments {seg_ids} all "
                    f"span the same two nodes {sorted(pair)}."
                ),
            ))

    # Connected components over nodes (via segment edges), and closed-loop
    # detection: a connected component is a closed perimeter iff every node
    # in it has degree exactly 2 (which, for a connected graph, forces it to
    # be a single simple cycle).
    node_ids = [n.node_id for n in nodes]
    comp_uf = _UnionFind(node_ids)
    for seg in segments:
        ends = segment_to_nodes[seg.segment_id]
        if "start" in ends and "end" in ends:
            comp_uf.union(ends["start"], ends["end"])
    # T-junctions also join components: a segment touching another's
    # interior is physically part of the same assembly, even though it
    # doesn't share a node with either of the target segment's own ends.
    for tj in t_junctions:
        target_ends = segment_to_nodes.get(tj.target_segment_id)
        if target_ends and "start" in target_ends:
            comp_uf.union(tj.node_id, target_ends["start"])

    comp_clusters: Dict[str, List[str]] = {}
    for nid in node_ids:
        comp_clusters.setdefault(comp_uf.find(nid), []).append(nid)

    nodes_by_id = {n.node_id: n for n in nodes}
    components = list(comp_clusters.values())
    closed_components = [
        all(nodes_by_id[nid].degree == 2 for nid in comp)
        for comp in components
    ]

    return ConnectivityGraph(
        nodes=nodes,
        segment_to_nodes={
            seg_id: (ends["start"], ends["end"])
            for seg_id, ends in segment_to_nodes.items()
            if "start" in ends and "end" in ends
        },
        components=components,
        closed_components=closed_components,
        issues=issues,
        t_junctions=t_junctions,
    )


def build_merged_connectivity_graph(
    segments: List[Segment],
    coincidence_tolerance_mm: float = DEFAULT_COINCIDENCE_TOLERANCE_MM,
    angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    near_miss_factor: float = DEFAULT_NEAR_MISS_FACTOR,
    detect_t_junctions: bool = True,
    t_junction_tolerance_mm: Optional[float] = None,
) -> ConnectivityGraph:
    """
    Multi-wall-safe entry point: groups segments by Wall ID and builds
    each wall's connectivity graph completely independently, THEN
    combines the results into a single ConnectivityGraph with globally-
    unique, wall-prefixed node IDs ("W1:N1", "W2:N1", ...).

    This matters: calling build_connectivity_graph directly on segments
    from more than one wall would happily cluster coincident endpoints
    across walls too -- e.g. two unrelated walls both anchored at a shared
    grid origin (0,0,0) would get silently merged into one fake junction.
    Nothing in the plan's sample workbooks exercises multiple walls, so
    this never surfaced in testing until reasoned through explicitly, but
    it directly violates "do not silently snap or merge disconnected
    geometry" the moment real multi-wall data shows up. Always route
    multi-wall (or possibly-multi-wall) input through this function
    instead of build_connectivity_graph directly -- it behaves
    identically to build_connectivity_graph for single-wall input (the
    common case so far), just with every node_id prefixed by its wall.

    If the same Segment ID appears in more than one wall, a warning
    ValidationIssue is added (segment_id-keyed structures elsewhere, e.g.
    the frame schedule, assume segment IDs are unique across the whole
    workbook -- rare in the data seen so far, but reported rather than
    silently producing a last-write-wins collision).
    """
    wall_groups = group_by_wall(segments)

    seen_segment_ids: Dict[str, str] = {}
    duplicate_issues: List[ValidationIssue] = []
    for wall_id, wall_segments in wall_groups.items():
        for seg in wall_segments:
            if seg.segment_id in seen_segment_ids and seen_segment_ids[seg.segment_id] != wall_id:
                duplicate_issues.append(ValidationIssue(
                    severity="warning",
                    segment_id=seg.segment_id,
                    message=(
                        f"Segment ID '{seg.segment_id}' appears in both wall "
                        f"'{seen_segment_ids[seg.segment_id]}' and wall '{wall_id}' -- "
                        f"segment IDs are assumed unique across the whole workbook; "
                        f"frame/validation lookups by segment_id may be ambiguous."
                    ),
                ))
            seen_segment_ids.setdefault(seg.segment_id, wall_id)

    all_nodes: List[Node] = []
    all_segment_to_nodes: Dict[str, Tuple[str, str]] = {}
    all_components: List[List[str]] = []
    all_closed: List[bool] = []
    all_issues: List[ValidationIssue] = list(duplicate_issues)
    all_t_junctions: List[TJunction] = []

    for wall_id, wall_segments in wall_groups.items():
        graph = build_connectivity_graph(
            wall_segments,
            coincidence_tolerance_mm=coincidence_tolerance_mm,
            angle_tolerance_deg=angle_tolerance_deg,
            near_miss_factor=near_miss_factor,
            detect_t_junctions=detect_t_junctions,
            t_junction_tolerance_mm=t_junction_tolerance_mm,
        )
        id_map = {n.node_id: f"{wall_id}:{n.node_id}" for n in graph.nodes}

        for node in graph.nodes:
            node.node_id = id_map[node.node_id]
            all_nodes.append(node)

        for seg_id, (start_id, end_id) in graph.segment_to_nodes.items():
            all_segment_to_nodes[seg_id] = (id_map[start_id], id_map[end_id])

        all_components.extend([id_map[nid] for nid in comp] for comp in graph.components)
        all_closed.extend(graph.closed_components)
        all_issues.extend(graph.issues)

        for tj in graph.t_junctions:
            tj.node_id = id_map[tj.node_id]
            all_t_junctions.append(tj)

    return ConnectivityGraph(
        nodes=all_nodes,
        segment_to_nodes=all_segment_to_nodes,
        components=all_components,
        closed_components=all_closed,
        issues=all_issues,
        t_junctions=all_t_junctions,
    )
