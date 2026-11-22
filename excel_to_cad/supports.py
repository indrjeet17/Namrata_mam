"""
Phase 6: support/bracket placement policy.

Decides WHERE support symbols go -- kept deliberately separate from
Phase 3's corner connectivity (a geometric fact: these members share this
endpoint) and from Phase 5's drawing step (how a symbol looks). None of
the four sample workbooks contain real bracket/support block definitions,
placement data, or component numbers/sizes (confirmed in Phase 1
inspection) -- so there is no single "correct" default policy here; the
plan explicitly lists several placement options and says not to assume
every frame boundary needs a physical support. The caller composes
whichever policy (or policies) apply via SupportPlacementConfig.

"Preserve actual component numbers when available. Do not invent callout
numbers, bracket dimensions or physical component sizes" (plan, Phase 6):
since no such data exists in any sample workbook, nothing is invented here
-- bracket_symbol is a name, not a real component spec, and its size
(DEFAULT_BRACKET_RADIUS_MM in dxf_export.py) is an explicitly configurable
placeholder, not a claimed physical dimension.
"""

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .corners import CornerConnection, DEFAULT_BRACKET_SYMBOL
from .frames import Frame
from .models import Point3D, Segment


@dataclass
class SupportPoint:
    point: Tuple[float, float, float]
    source: str  # "corner" / "frame_boundary" / "segment_endpoint" / "explicit" / "spacing"
    symbol: str
    reference: str  # node_id, segment_id, or a short description, for traceability


def supports_at_corners(
    corner_connections: List[CornerConnection],
    symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> List[SupportPoint]:
    """One support at every recognized corner/junction (Phase 3's
    CornerConnection.corner_cases non-empty) -- genuinely open/disconnected
    ends are excluded, since those aren't junctions needing a connector."""
    return [
        SupportPoint(point=c.point, source="corner", symbol=symbol, reference=c.node_id)
        for c in corner_connections
        if c.corner_cases
    ]


def supports_at_segment_endpoints(
    segments: List[Segment],
    symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> List[SupportPoint]:
    """One support at every segment's own start and end point, regardless
    of whether that point connects to anything else."""
    points = []
    for seg in segments:
        points.append(SupportPoint(
            point=seg.start.as_tuple(), source="segment_endpoint",
            symbol=symbol, reference=f"{seg.segment_id}:start",
        ))
        points.append(SupportPoint(
            point=seg.end.as_tuple(), source="segment_endpoint",
            symbol=symbol, reference=f"{seg.segment_id}:end",
        ))
    return points


def supports_at_frame_boundaries(
    frames: List[Frame],
    standard_only: bool = True,
    symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> List[SupportPoint]:
    """
    One support at each INTERNAL boundary between two consecutive frames
    of the same segment (not at a segment's own start/end -- see
    supports_at_segment_endpoints or supports_at_corners for those).

    standard_only=True (the literal plan wording, "every standard frame
    boundary"): a boundary only counts if BOTH frames meeting there are
    "standard" -- a boundary touching a custom (remainder) frame is
    excluded. Set False for a boundary between any two frames regardless
    of type.
    """
    by_segment: dict = {}
    for f in frames:
        by_segment.setdefault(f.segment_id, []).append(f)

    points = []
    for seg_id, seg_frames in by_segment.items():
        seg_frames.sort(key=lambda f: f.frame_no)
        for prev, curr in zip(seg_frames, seg_frames[1:]):
            if standard_only and not (prev.frame_type == "standard" and curr.frame_type == "standard"):
                continue
            points.append(SupportPoint(
                point=prev.end.as_tuple(), source="frame_boundary", symbol=symbol,
                reference=f"{seg_id}:F{prev.frame_no}/F{curr.frame_no}",
            ))
    return points


def supports_by_spacing(
    segments: List[Segment],
    spacing_mm: float,
    symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> List[SupportPoint]:
    """
    One support every `spacing_mm` along each segment, starting at its
    start point, not exceeding its length. `spacing_mm` must come from
    explicit engineering/user input (the plan's "explicit support-spacing
    data") -- never guessed at by this function.

    Does not force a support exactly at the segment's end if spacing
    doesn't divide evenly; combine with supports_at_segment_endpoints if
    both are wanted.
    """
    if spacing_mm <= 0:
        raise ValueError(f"spacing_mm must be positive, got {spacing_mm}")

    points = []
    for seg in segments:
        length_mm = seg.geometric_length_mm
        if length_mm <= 0:
            continue
        ux = (seg.end.x - seg.start.x) / length_mm
        uy = (seg.end.y - seg.start.y) / length_mm
        uz = (seg.end.z - seg.start.z) / length_mm

        distance = 0.0
        index = 0
        while distance <= length_mm + 1e-9:
            point = Point3D(
                seg.start.x + ux * distance,
                seg.start.y + uy * distance,
                seg.start.z + uz * distance,
            )
            points.append(SupportPoint(
                point=point.as_tuple(), source="spacing", symbol=symbol,
                reference=f"{seg.segment_id}:{spacing_mm}mm#{index}",
            ))
            index += 1
            distance += spacing_mm
    return points


def supports_at_explicit_coordinates(
    coordinates: List[Tuple[float, float, float]],
    symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> List[SupportPoint]:
    """Pass-through for user-specified support coordinates."""
    return [
        SupportPoint(point=tuple(c), source="explicit", symbol=symbol, reference=f"explicit#{i}")
        for i, c in enumerate(coordinates)
    ]


def combine_support_points(
    *point_lists: List[SupportPoint],
    dedupe_tolerance_mm: float = 0.1,
) -> List[SupportPoint]:
    """
    Merge support points from multiple policies, collapsing any that fall
    within dedupe_tolerance_mm of an already-kept point -- "at a shared
    corner, avoid duplicated symbols" (plan, Phase 6), extended to any
    combination of policies, not just corners specifically. The first
    occurrence (in input order) wins; later near-duplicates are dropped.
    """
    kept: List[SupportPoint] = []
    for points in point_lists:
        for candidate in points:
            is_duplicate = False
            for existing in kept:
                dx = candidate.point[0] - existing.point[0]
                dy = candidate.point[1] - existing.point[1]
                dz = candidate.point[2] - existing.point[2]
                if math.sqrt(dx * dx + dy * dy + dz * dz) <= dedupe_tolerance_mm:
                    is_duplicate = True
                    break
            if not is_duplicate:
                kept.append(candidate)
    return kept


@dataclass
class SupportPlacementConfig:
    """
    Which placement policy/policies are active. Defaults to the behavior
    Phase 5 originally hard-coded (a support at every recognized corner),
    so existing callers see no change unless they opt into something else.
    """

    at_corners: bool = True
    at_segment_endpoints: bool = False
    at_frame_boundaries: bool = False
    frame_boundaries_standard_only: bool = True
    spacing_mm: Optional[float] = None
    explicit_coordinates: List[Tuple[float, float, float]] = field(default_factory=list)
    symbol: str = DEFAULT_BRACKET_SYMBOL
    dedupe_tolerance_mm: float = 0.1


def resolve_support_points(
    config: SupportPlacementConfig,
    segments: List[Segment],
    frames: List[Frame],
    corner_connections: List[CornerConnection],
) -> List[SupportPoint]:
    """Run whichever policies config enables and combine/dedupe the result."""
    policy_results: List[List[SupportPoint]] = []

    if config.at_corners:
        policy_results.append(supports_at_corners(corner_connections, config.symbol))
    if config.at_segment_endpoints:
        policy_results.append(supports_at_segment_endpoints(segments, config.symbol))
    if config.at_frame_boundaries:
        policy_results.append(supports_at_frame_boundaries(
            frames, config.frame_boundaries_standard_only, config.symbol
        ))
    if config.spacing_mm is not None:
        policy_results.append(supports_by_spacing(segments, config.spacing_mm, config.symbol))
    if config.explicit_coordinates:
        policy_results.append(
            supports_at_explicit_coordinates(config.explicit_coordinates, config.symbol)
        )

    return combine_support_points(*policy_results, dedupe_tolerance_mm=config.dedupe_tolerance_mm)
