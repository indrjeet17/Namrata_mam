"""
Excel-to-CAD engineering drawing automation.

Phase 1 (this package so far): read a wall/segment Excel workbook with an
unknown-in-advance column layout, detect and normalize its columns, and
validate the geometry it describes.
"""

from .connectivity import (
    ConnectivityGraph,
    EndpointRef,
    Node,
    TJunction,
    axis_classification,
    away_from_node_vector,
    build_connectivity_graph,
    build_merged_connectivity_graph,
    group_by_wall,
)
from .corners import CornerConnection, apply_frame_terminations, build_corner_connections
from .dxf_export import LAYER_DEFINITIONS, build_dxf_document, export_dxf
from .frames import Frame, build_frame_schedule, compute_frame_counts, place_frames
from .loader import ColumnDetectionError, detect_columns, load_segments
from .models import ColumnMapping, LoadResult, Point3D, Segment, ValidationIssue
from .pipeline import PipelineResult, generate_drawing, run_pipeline
from .reports import (
    FRAME_SCHEDULE_COLUMNS,
    SEGMENT_VALIDATION_COLUMNS,
    SegmentValidationResult,
    build_frame_schedule_rows,
    build_segment_validation_report,
    build_segment_validation_rows,
    write_frame_schedule,
    write_segment_validation_report,
)
from .supports import (
    SupportPlacementConfig,
    SupportPoint,
    combine_support_points,
    resolve_support_points,
    supports_at_corners,
    supports_at_explicit_coordinates,
    supports_at_frame_boundaries,
    supports_at_segment_endpoints,
    supports_by_spacing,
)

__all__ = [
    "ColumnDetectionError",
    "ColumnMapping",
    "ConnectivityGraph",
    "CornerConnection",
    "EndpointRef",
    "Frame",
    "LoadResult",
    "Node",
    "PipelineResult",
    "Point3D",
    "Segment",
    "SegmentValidationResult",
    "SupportPlacementConfig",
    "SupportPoint",
    "TJunction",
    "ValidationIssue",
    "FRAME_SCHEDULE_COLUMNS",
    "LAYER_DEFINITIONS",
    "SEGMENT_VALIDATION_COLUMNS",
    "apply_frame_terminations",
    "axis_classification",
    "away_from_node_vector",
    "build_connectivity_graph",
    "build_corner_connections",
    "build_merged_connectivity_graph",
    "build_dxf_document",
    "build_frame_schedule",
    "build_frame_schedule_rows",
    "build_segment_validation_report",
    "build_segment_validation_rows",
    "combine_support_points",
    "compute_frame_counts",
    "detect_columns",
    "export_dxf",
    "generate_drawing",
    "group_by_wall",
    "load_segments",
    "place_frames",
    "run_pipeline",
    "resolve_support_points",
    "supports_at_corners",
    "supports_at_explicit_coordinates",
    "supports_at_frame_boundaries",
    "supports_at_segment_endpoints",
    "supports_by_spacing",
    "write_frame_schedule",
    "write_segment_validation_report",
]
