"""
Phase 8: orchestration entry point tying every phase together into one
call. The application (app.py) should contain UI code only -- this module
holds the actual logic, per the plan's "CAD generation logic separated
into reusable modules" instruction, so it's testable independent of
Streamlit and reusable by any other caller (a CLI, a notebook, etc).

Accepts a path OR a file-like object for `source` (openpyxl supports
both transparently) -- this is what lets the Streamlit app hand it an
uploaded file's in-memory stream directly, with no hardcoded or
temporary file path involved.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from .connectivity import (
    DEFAULT_ANGLE_TOLERANCE_DEG,
    DEFAULT_COINCIDENCE_TOLERANCE_MM,
    ConnectivityGraph,
    build_merged_connectivity_graph,
)
from .corners import DEFAULT_BRACKET_SYMBOL, CornerConnection, apply_frame_terminations, build_corner_connections
from .dxf_export import build_dxf_document
from .frames import DEFAULT_STANDARD_FRAME_LENGTH_MM, Frame, build_frame_schedule
from .loader import LoadResult, load_segments
from .models import ValidationIssue
from .reports import SegmentValidationResult, build_frame_schedule_rows, build_segment_validation_report
from .supports import SupportPlacementConfig


@dataclass
class PipelineResult:
    load_result: LoadResult
    graph: ConnectivityGraph
    corner_connections: List[CornerConnection]
    frames: List[Frame]
    frame_issues: List[ValidationIssue]
    segment_validations: List[SegmentValidationResult]
    frame_schedule_rows: List[dict]

    @property
    def has_errors(self) -> bool:
        return any(r.status == "ERROR" for r in self.segment_validations)

    @property
    def has_warnings(self) -> bool:
        return any(r.status == "WARNING" for r in self.segment_validations)


def run_pipeline(
    source,
    sheet_name: str = "Segment Report",
    column_overrides: Optional[Dict[str, str]] = None,
    default_standard_frame_length_mm: float = DEFAULT_STANDARD_FRAME_LENGTH_MM,
    coincidence_tolerance_mm: float = DEFAULT_COINCIDENCE_TOLERANCE_MM,
    angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    length_tolerance_mm: float = 1e-3,
    bracket_symbol: str = DEFAULT_BRACKET_SYMBOL,
) -> PipelineResult:
    """
    Run Phases 1-7 end to end for one workbook/sheet: load + validate
    segments, build the connectivity graph (with T-junctions), classify
    corners, sequence frames, cross-check reported-vs-calculated values,
    and produce the frame schedule + segment validation report. Does not
    build a DXF document -- that's a separate, optional step (see
    dxf_export.build_dxf_document), since its styling options are
    independent of whether the underlying data is even valid yet.
    """
    load_result = load_segments(
        source, sheet_name=sheet_name, column_overrides=column_overrides,
        length_tolerance_mm=length_tolerance_mm,
    )
    segments = load_result.segments

    # Multi-wall-safe: builds each wall's graph independently so two
    # different walls never get silently merged just because they share
    # a coincident coordinate (e.g. a common grid origin).
    graph = build_merged_connectivity_graph(
        segments,
        coincidence_tolerance_mm=coincidence_tolerance_mm,
        angle_tolerance_deg=angle_tolerance_deg,
    )
    corners = build_corner_connections(
        graph, segments, bracket_symbol=bracket_symbol, tolerance_mm=coincidence_tolerance_mm,
    )
    frames, frame_issues = build_frame_schedule(
        segments,
        default_standard_frame_length_mm=default_standard_frame_length_mm,
        tolerance_mm=length_tolerance_mm,
    )
    corners = apply_frame_terminations(corners, graph, frames)

    validations = build_segment_validation_report(
        segments, frames, graph=graph,
        loader_issues=load_result.issues, frame_issues=frame_issues,
        length_tolerance_mm=length_tolerance_mm,
        default_standard_frame_length_mm=default_standard_frame_length_mm,
    )
    statuses = {v.segment_id: v.status for v in validations}
    schedule_rows = build_frame_schedule_rows(frames, segments, statuses)

    return PipelineResult(
        load_result=load_result,
        graph=graph,
        corner_connections=corners,
        frames=frames,
        frame_issues=frame_issues,
        segment_validations=validations,
        frame_schedule_rows=schedule_rows,
    )


def generate_drawing(
    source,
    sheet_name: str = "Segment Report",
    column_overrides: Optional[Dict[str, str]] = None,
    default_standard_frame_length_mm: float = DEFAULT_STANDARD_FRAME_LENGTH_MM,
    coincidence_tolerance_mm: float = DEFAULT_COINCIDENCE_TOLERANCE_MM,
    angle_tolerance_deg: float = DEFAULT_ANGLE_TOLERANCE_DEG,
    length_tolerance_mm: float = 1e-3,
    bracket_symbol: str = DEFAULT_BRACKET_SYMBOL,
    support_config: Optional[SupportPlacementConfig] = None,
    dxf_kwargs: Optional[dict] = None,
):
    """
    run_pipeline() (Phases 1-7) followed by build_dxf_document() (Phase 5,
    styled per support_config/dxf_kwargs from Phase 6) in one call -- the
    single entry point app.py's "Generate" button uses, kept here (not
    inline in app.py) so it's testable with plain pytest independent of
    Streamlit, which can't simulate a file upload in automated tests.

    Returns (PipelineResult, ezdxf.Drawing).
    """
    result = run_pipeline(
        source,
        sheet_name=sheet_name,
        column_overrides=column_overrides,
        default_standard_frame_length_mm=default_standard_frame_length_mm,
        coincidence_tolerance_mm=coincidence_tolerance_mm,
        angle_tolerance_deg=angle_tolerance_deg,
        length_tolerance_mm=length_tolerance_mm,
        bracket_symbol=bracket_symbol,
    )
    doc = build_dxf_document(
        result.load_result.segments,
        result.frames,
        result.corner_connections,
        support_config=support_config,
        **(dxf_kwargs or {}),
    )
    return result, doc
