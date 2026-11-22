"""
Phase 5: DXF generation via ezdxf.

No reference CAD screenshot is available for this project (confirmed with
the user) -- this module produces a correct, readable generic engineering-
drawing style (layers, colors, dimension chains) per the plan's explicit
textual rules, rather than guessing at a specific visual look it has no
source for. Restyling against a real reference later only needs changes
here, not to the geometry/connectivity/frame modules upstream.

Layers (exactly the plan's named set -- no extras invented):
  WALL_GEOMETRY       -- each segment's full original line, as built (thin,
                         dark gray "construction reference" -- the frame
                         divisions below are what actually carries the
                         member geometry visually).
  STANDARD_FRAMES     -- each "standard" Frame's line segment.
  CUSTOM_FRAMES       -- each "custom" (remainder) Frame's line segment,
                         colored differently so the irregular pieces are
                         easy to spot -- directly useful for the plan's
                         "inspect the generated DXF geometry at every
                         corner" instruction.
  CORNER_CONNECTIONS  -- a small marker at every node with at least one
                         corner case (Phase 3) -- the junction itself,
                         distinct from the bracket placeholder below.
  SUPPORT_SYMBOLS     -- the placeholder bracket circle (Phase 3's
                         bracket_symbol) at each such node.
  STANDARD_DIMENSIONS -- blue aligned dimension per individual Frame.
  REFERENCE_DIMENSIONS-- magenta aligned dimension per Segment (overall
                         length), offset further out so it never overlaps
                         the per-frame dimension chain.
  CALLOUTS            -- created but left EMPTY: none of the four sample
                         workbooks contain real callout/component numbers
                         (confirmed Phase 1) -- the plan explicitly says
                         not to invent these.
  LABELS              -- segment ID near each segment's midpoint (real
                         data) and each corner's case letters (derived,
                         not invented) -- useful for reviewing output.
"""

from typing import Dict, List, Optional

import ezdxf

from .corners import CornerConnection
from .frames import Frame
from .models import Segment
from .supports import SupportPlacementConfig, SupportPoint, resolve_support_points

# ACI (AutoCAD Color Index) values -- plan explicitly requires blue for
# frame dimensions and magenta for reference dimensions; the rest are this
# module's own reasonable generic choices (see module docstring).
COLOR_WALL_GEOMETRY = 8        # dark gray
COLOR_STANDARD_FRAME = 7       # white/black (the "normal" member color)
COLOR_CUSTOM_FRAME = 1         # red -- draws the eye to irregular pieces
COLOR_CORNER_MARKER = 3        # green
COLOR_SUPPORT_SYMBOL = 2       # yellow
COLOR_STANDARD_DIMENSION = 5   # blue (plan's explicit instruction)
COLOR_REFERENCE_DIMENSION = 6  # magenta (plan's explicit instruction)
COLOR_CALLOUT = 2              # yellow (layer created, left empty for now)
COLOR_LABEL = 7                # white/black

LAYER_DEFINITIONS = {
    "WALL_GEOMETRY": {"color": COLOR_WALL_GEOMETRY, "lineweight": 13},
    "STANDARD_FRAMES": {"color": COLOR_STANDARD_FRAME, "lineweight": 25},
    "CUSTOM_FRAMES": {"color": COLOR_CUSTOM_FRAME, "lineweight": 25},
    "CORNER_CONNECTIONS": {"color": COLOR_CORNER_MARKER, "lineweight": 18},
    "SUPPORT_SYMBOLS": {"color": COLOR_SUPPORT_SYMBOL, "lineweight": 18},
    "STANDARD_DIMENSIONS": {"color": COLOR_STANDARD_DIMENSION, "lineweight": 9},
    "REFERENCE_DIMENSIONS": {"color": COLOR_REFERENCE_DIMENSION, "lineweight": 9},
    "CALLOUTS": {"color": COLOR_CALLOUT, "lineweight": 9},
    "LABELS": {"color": COLOR_LABEL, "lineweight": 9},
}

DEFAULT_FRAME_DIM_OFFSET_MM = 150.0
DEFAULT_REFERENCE_DIM_OFFSET_MM = 400.0
DEFAULT_BRACKET_RADIUS_MM = 50.0
DEFAULT_TEXT_HEIGHT_MM = 100.0
DEFAULT_CORNER_MARKER_SIZE_MM = 30.0


def _setup_layers(doc):
    for name, attrs in LAYER_DEFINITIONS.items():
        doc.layers.add(name=name, color=attrs["color"], lineweight=attrs["lineweight"])


def _draw_wall_geometry(msp, segments: List[Segment]):
    for seg in segments:
        msp.add_line(
            seg.start.as_tuple(), seg.end.as_tuple(),
            dxfattribs={"layer": "WALL_GEOMETRY"},
        )


def _draw_frames(msp, frames: List[Frame]):
    for frame in frames:
        layer = "STANDARD_FRAMES" if frame.frame_type == "standard" else "CUSTOM_FRAMES"
        msp.add_line(
            frame.start.as_tuple(), frame.end.as_tuple(),
            dxfattribs={"layer": layer},
        )


def _draw_corner_markers(
    msp,
    corner_connections: List[CornerConnection],
    corner_marker_size_mm: float,
):
    """The small "+" cross marking a junction's existence -- unconditional,
    independent of Phase 6's support-placement policy below. A corner is a
    geometric fact (Phase 3); whether it *also* gets a physical support
    symbol is a separate, configurable decision (Phase 6)."""
    half = corner_marker_size_mm / 2.0
    for conn in corner_connections:
        if not conn.corner_cases:
            continue
        x, y, z = conn.point
        msp.add_line((x - half, y, z), (x + half, y, z), dxfattribs={"layer": "CORNER_CONNECTIONS"})
        msp.add_line((x, y - half, z), (x, y + half, z), dxfattribs={"layer": "CORNER_CONNECTIONS"})


def _draw_support_symbols(msp, support_points: List[SupportPoint], bracket_radius_mm: float):
    for support in support_points:
        msp.add_circle(
            support.point, radius=bracket_radius_mm,
            dxfattribs={"layer": "SUPPORT_SYMBOLS"},
        )


def _draw_labels(
    msp,
    segments: List[Segment],
    corner_connections: List[CornerConnection],
    text_height_mm: float,
):
    for seg in segments:
        mid_x = (seg.start.x + seg.end.x) / 2.0
        mid_y = (seg.start.y + seg.end.y) / 2.0
        msp.add_text(
            seg.segment_id,
            dxfattribs={"layer": "LABELS", "height": text_height_mm},
        ).set_placement((mid_x, mid_y, 0))

    for conn in corner_connections:
        if not conn.corner_cases:
            continue
        x, y, z = conn.point
        label = "/".join(sorted(conn.corner_cases))
        msp.add_text(
            label,
            dxfattribs={"layer": "LABELS", "height": text_height_mm * 0.6},
        ).set_placement((x, y, z))


def _axis_unit_normal(p1, p2):
    """Unit vector perpendicular to p1->p2, in the XY plane."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return (0.0, 1.0)
    return (-dy / length, dx / length)


def _draw_frame_dimensions(msp, frames: List[Frame], offset_mm: float, text_height_mm: float):
    for frame in frames:
        p1, p2 = frame.start.as_tuple(), frame.end.as_tuple()
        msp.add_aligned_dim(
            p1=p1, p2=p2, distance=offset_mm,
            dxfattribs={"layer": "STANDARD_DIMENSIONS"},
            override={
                "dimclrd": COLOR_STANDARD_DIMENSION,
                "dimclrt": COLOR_STANDARD_DIMENSION,
                "dimtxt": text_height_mm,
                "dimdec": 2,
            },
        ).render()


def _draw_reference_dimensions(msp, segments: List[Segment], offset_mm: float, text_height_mm: float):
    for seg in segments:
        msp.add_aligned_dim(
            p1=seg.start.as_tuple(), p2=seg.end.as_tuple(), distance=offset_mm,
            dxfattribs={"layer": "REFERENCE_DIMENSIONS"},
            override={
                "dimclrd": COLOR_REFERENCE_DIMENSION,
                "dimclrt": COLOR_REFERENCE_DIMENSION,
                "dimtxt": text_height_mm,
                "dimdec": 2,
            },
        ).render()


def build_dxf_document(
    segments: List[Segment],
    frames: List[Frame],
    corner_connections: List[CornerConnection],
    support_config: Optional[SupportPlacementConfig] = None,
    frame_dim_offset_mm: float = DEFAULT_FRAME_DIM_OFFSET_MM,
    reference_dim_offset_mm: float = DEFAULT_REFERENCE_DIM_OFFSET_MM,
    bracket_radius_mm: float = DEFAULT_BRACKET_RADIUS_MM,
    corner_marker_size_mm: float = DEFAULT_CORNER_MARKER_SIZE_MM,
    text_height_mm: float = DEFAULT_TEXT_HEIGHT_MM,
    dxfversion: str = "R2010",
):
    """
    Build (but do not save) a complete ezdxf Drawing for one wall's worth
    of segments/frames/corners. Units are left as the DXF default
    (unitless, treated as mm throughout by the rest of this application --
    coordinates are used exactly as given, no scaling).

    support_config controls WHERE support/bracket symbols are drawn (Phase
    6) -- defaults to "at every recognized corner" (SupportPlacementConfig()
    default), matching this function's original behavior before Phase 6
    made it configurable. Pass a different SupportPlacementConfig to place
    supports at segment endpoints, frame boundaries, explicit coordinates,
    or by spacing instead (or in combination).
    """
    if support_config is None:
        support_config = SupportPlacementConfig()

    doc = ezdxf.new(dxfversion=dxfversion)
    doc.header["$INSUNITS"] = 4  # 4 = millimeters
    _setup_layers(doc)
    msp = doc.modelspace()

    _draw_wall_geometry(msp, segments)
    _draw_frames(msp, frames)
    _draw_corner_markers(msp, corner_connections, corner_marker_size_mm)

    support_points = resolve_support_points(support_config, segments, frames, corner_connections)
    _draw_support_symbols(msp, support_points, bracket_radius_mm)

    _draw_labels(msp, segments, corner_connections, text_height_mm)
    _draw_frame_dimensions(msp, frames, frame_dim_offset_mm, text_height_mm)
    _draw_reference_dimensions(msp, segments, reference_dim_offset_mm, text_height_mm)

    return doc


def export_dxf(
    segments: List[Segment],
    frames: List[Frame],
    corner_connections: List[CornerConnection],
    output_path: str,
    **kwargs,
):
    """Build the DXF document (see build_dxf_document) and save it to output_path."""
    doc = build_dxf_document(segments, frames, corner_connections, **kwargs)
    doc.saveas(output_path)
    return doc
