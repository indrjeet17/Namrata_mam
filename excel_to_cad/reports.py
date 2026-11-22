"""
Phase 7: frame schedule and segment/corner validation reports.

Consolidates validation signals already computed across Phases 1-6
(ValidationIssue lists from the loader, the connectivity graph, and frame
sequencing) into the two deliverables the plan asks for: a frame schedule
and a segment validation report, each writable as CSV or Excel. Adds the
explicit checks the plan names that weren't yet asserted as standalone
report lines: first/last frame alignment to the segment's own start/end,
and connected-endpoint coincidence (reusing Node.max_internal_deviation_mm,
which Phase 2 already computes for exactly this purpose).

Reports all unresolved problems rather than hiding them -- nothing here
"fixes" a discrepancy, it only surfaces it.
"""

import csv
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import openpyxl

from .connectivity import ConnectivityGraph
from .frames import DEFAULT_STANDARD_FRAME_LENGTH_MM, Frame, compute_frame_counts
from .models import Segment, ValidationIssue

DEFAULT_LENGTH_TOLERANCE_MM = 1e-3
DEFAULT_REPORTED_VALUE_TOLERANCE_MM = 0.01


def _frame_direction(start, end, tol_mm: float = 1e-6) -> str:
    dx, dy, dz = end.x - start.x, end.y - start.y, end.z - start.z
    if abs(dy) <= tol_mm and abs(dz) <= tol_mm and abs(dx) > tol_mm:
        return "Horizontal"
    if abs(dx) <= tol_mm and abs(dz) <= tol_mm and abs(dy) > tol_mm:
        return "Vertical"
    return "Diagonal"


# ---------------------------------------------------------------------
# Frame schedule
# ---------------------------------------------------------------------

FRAME_SCHEDULE_COLUMNS = [
    "Wall ID", "Segment ID", "Frame ID", "Frame Type", "Frame Length (mm)",
    "Start X", "Start Y", "Start Z", "End X", "End Y", "End Z", "Direction",
    "Cumulative Start (mm)", "Cumulative End (mm)", "Validation Status",
]


def build_frame_schedule_rows(
    frames: List[Frame],
    segments: List[Segment],
    segment_statuses: Optional[Dict[str, str]] = None,
) -> List[dict]:
    """
    One row per Frame. Frame ID is generated as "{segment_id}-F{frame_no}"
    -- globally unique, and unambiguous about which segment it belongs to
    (the source workbooks' own "Frame ID" column, e.g. "F1", "F39", is a
    single counter across the whole sheet; this is clearer for a
    reconstructed schedule that may combine segments from different
    sources). Validation Status is per-SEGMENT (from
    build_segment_validation_report), not independently computed per frame
    -- a frame's own geometry has no discrepancy of its own to report.
    """
    by_id = {s.segment_id: s for s in segments}
    segment_statuses = segment_statuses or {}
    rows = []
    for frame in frames:
        seg = by_id.get(frame.segment_id)
        rows.append({
            "Wall ID": seg.wall_id if seg else "",
            "Segment ID": frame.segment_id,
            "Frame ID": f"{frame.segment_id}-F{frame.frame_no}",
            "Frame Type": frame.frame_type,
            "Frame Length (mm)": round(frame.length_mm, 4),
            "Start X": frame.start.x, "Start Y": frame.start.y, "Start Z": frame.start.z,
            "End X": frame.end.x, "End Y": frame.end.y, "End Z": frame.end.z,
            "Direction": _frame_direction(frame.start, frame.end),
            "Cumulative Start (mm)": round(frame.cumulative_start_mm, 4),
            "Cumulative End (mm)": round(frame.cumulative_end_mm, 4),
            "Validation Status": segment_statuses.get(frame.segment_id, "OK"),
        })
    return rows


def write_frame_schedule(rows: List[dict], path: str):
    """Write to CSV or .xlsx, chosen by the path's extension."""
    if str(path).lower().endswith(".xlsx"):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Frame Schedule"
        ws.append(FRAME_SCHEDULE_COLUMNS)
        for row in rows:
            ws.append([row[c] for c in FRAME_SCHEDULE_COLUMNS])
        wb.save(path)
    else:
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FRAME_SCHEDULE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)


# ---------------------------------------------------------------------
# Segment validation report
# ---------------------------------------------------------------------

@dataclass
class SegmentValidationResult:
    wall_id: str
    segment_id: str

    geometric_length_mm: float
    reported_length_mm: Optional[float]
    length_discrepancy_mm: Optional[float]

    standard_frame_size_mm: float
    calculated_standard_count: int
    calculated_custom_remainder_mm: float
    reported_standard_count: Optional[int]
    reported_custom_remainder_mm: Optional[float]
    frame_count_matches: Optional[bool]
    custom_remainder_matches: Optional[bool]

    reconstructed_total_frame_length_mm: float
    total_length_discrepancy_mm: float

    start_matches_first_frame: bool
    start_deviation_mm: float
    end_matches_last_frame: bool
    end_deviation_mm: float

    start_corner_classification: Optional[str] = None
    start_corner_coincidence_deviation_mm: Optional[float] = None
    end_corner_classification: Optional[str] = None
    end_corner_coincidence_deviation_mm: Optional[float] = None

    issues: List[str] = field(default_factory=list)
    status: str = "OK"  # "OK" / "WARNING" / "ERROR"


def _collect_segment_issue_text(
    segments: List[Segment],
    issue_lists: List[List[ValidationIssue]],
) -> Dict[str, List[str]]:
    by_segment: Dict[str, List[str]] = {}
    segment_ids = {s.segment_id for s in segments}
    for issues in issue_lists:
        for issue in issues:
            text = f"[{issue.severity}] {issue.message}"
            if issue.segment_id:
                by_segment.setdefault(issue.segment_id, []).append(text)
            else:
                # Graph-level issues (near-miss, duplicate geometry,
                # unclassified connections) often name a segment inside
                # the message rather than the segment_id field -- attach
                # to every segment mentioned so nothing is silently
                # dropped from the per-segment report.
                for seg_id in segment_ids:
                    if seg_id in issue.message:
                        by_segment.setdefault(seg_id, []).append(text)
    return by_segment


def build_segment_validation_report(
    segments: List[Segment],
    frames: List[Frame],
    graph: Optional[ConnectivityGraph] = None,
    loader_issues: Optional[List[ValidationIssue]] = None,
    frame_issues: Optional[List[ValidationIssue]] = None,
    length_tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
    reported_value_tolerance_mm: float = DEFAULT_REPORTED_VALUE_TOLERANCE_MM,
    default_standard_frame_length_mm: float = DEFAULT_STANDARD_FRAME_LENGTH_MM,
) -> List[SegmentValidationResult]:
    loader_issues = loader_issues or []
    frame_issues = frame_issues or []
    graph_issues = list(graph.issues) if graph is not None else []

    issues_by_segment = _collect_segment_issue_text(
        segments, [loader_issues, frame_issues, graph_issues]
    )

    frames_by_segment: Dict[str, List[Frame]] = {}
    for f in frames:
        frames_by_segment.setdefault(f.segment_id, []).append(f)
    for seg_frames in frames_by_segment.values():
        seg_frames.sort(key=lambda f: f.frame_no)

    results: List[SegmentValidationResult] = []
    for seg in segments:
        seg_frames = frames_by_segment.get(seg.segment_id, [])
        frame_length = seg.standard_frame_size_mm or default_standard_frame_length_mm

        issues = list(issues_by_segment.get(seg.segment_id, []))
        has_error = any(i.startswith("[error]") for i in issues)
        has_warning = any(i.startswith("[warning]") for i in issues)

        if seg.geometric_length_mm <= length_tolerance_mm:
            # Already an error at Phase 1; nothing further to compute.
            issues.append("[error] segment has non-positive/near-zero length")
            results.append(SegmentValidationResult(
                wall_id=seg.wall_id, segment_id=seg.segment_id,
                geometric_length_mm=seg.geometric_length_mm,
                reported_length_mm=seg.reported_length_mm, length_discrepancy_mm=None,
                standard_frame_size_mm=frame_length, calculated_standard_count=0,
                calculated_custom_remainder_mm=0.0,
                reported_standard_count=seg.reported_standard_frame_count,
                reported_custom_remainder_mm=seg.reported_custom_frame_length_mm,
                frame_count_matches=None, custom_remainder_matches=None,
                reconstructed_total_frame_length_mm=0.0, total_length_discrepancy_mm=0.0,
                start_matches_first_frame=False, start_deviation_mm=-1.0,
                end_matches_last_frame=False, end_deviation_mm=-1.0,
                issues=issues, status="ERROR",
            ))
            continue

        calc_count, calc_remainder = compute_frame_counts(
            seg.geometric_length_mm, frame_length, length_tolerance_mm
        )

        length_discrepancy = (
            abs(seg.geometric_length_mm - seg.reported_length_mm)
            if seg.reported_length_mm is not None else None
        )

        frame_count_matches = (
            seg.reported_standard_frame_count == calc_count
            if seg.reported_standard_frame_count is not None else None
        )
        custom_remainder_matches = (
            abs(seg.reported_custom_frame_length_mm - calc_remainder) <= reported_value_tolerance_mm
            if seg.reported_custom_frame_length_mm is not None else None
        )
        if frame_count_matches is False:
            issues.append(
                f"[warning] standard frame count disagreement: reported "
                f"{seg.reported_standard_frame_count}, calculated {calc_count}"
            )
            has_warning = True
        if custom_remainder_matches is False:
            issues.append(
                f"[warning] custom remainder disagreement: reported "
                f"{seg.reported_custom_frame_length_mm}mm, calculated {calc_remainder:.4f}mm"
            )
            has_warning = True

        reconstructed_total = sum(f.length_mm for f in seg_frames)
        total_discrepancy = abs(reconstructed_total - seg.geometric_length_mm)
        if total_discrepancy > length_tolerance_mm:
            issues.append(
                f"[warning] reconstructed frame total {reconstructed_total:.4f}mm "
                f"disagrees with geometric length {seg.geometric_length_mm:.4f}mm "
                f"(diff={total_discrepancy:.4f}mm)"
            )
            has_warning = True

        if not seg_frames:
            issues.append("[error] no frames generated for this segment")
            start_dev = end_dev = -1.0
            start_ok = end_ok = False
            has_error = True
        else:
            start_dev = seg_frames[0].start.distance_to(seg.start)
            end_dev = seg_frames[-1].end.distance_to(seg.end)
            start_ok = start_dev <= length_tolerance_mm
            end_ok = end_dev <= length_tolerance_mm
            if not start_ok:
                issues.append(
                    f"[error] first frame does not start at segment start "
                    f"(deviation={start_dev:.6f}mm)"
                )
                has_error = True
            if not end_ok:
                issues.append(
                    f"[error] last frame does not end at segment end "
                    f"(deviation={end_dev:.6f}mm)"
                )
                has_error = True

        status = "ERROR" if has_error else "WARNING" if has_warning else "OK"

        results.append(SegmentValidationResult(
            wall_id=seg.wall_id,
            segment_id=seg.segment_id,
            geometric_length_mm=seg.geometric_length_mm,
            reported_length_mm=seg.reported_length_mm,
            length_discrepancy_mm=length_discrepancy,
            standard_frame_size_mm=frame_length,
            calculated_standard_count=calc_count,
            calculated_custom_remainder_mm=calc_remainder,
            reported_standard_count=seg.reported_standard_frame_count,
            reported_custom_remainder_mm=seg.reported_custom_frame_length_mm,
            frame_count_matches=frame_count_matches,
            custom_remainder_matches=custom_remainder_matches,
            reconstructed_total_frame_length_mm=reconstructed_total,
            total_length_discrepancy_mm=total_discrepancy,
            start_matches_first_frame=start_ok,
            start_deviation_mm=start_dev,
            end_matches_last_frame=end_ok,
            end_deviation_mm=end_dev,
            issues=issues,
            status=status,
        ))

    if graph is not None:
        _attach_corner_connectivity_info(results, graph)

    return results


def _attach_corner_connectivity_info(
    results: List[SegmentValidationResult],
    graph: ConnectivityGraph,
):
    """
    "For connected segments, verify that the relevant endpoints coincide
    within tolerance" -- reuses Node.max_internal_deviation_mm, which
    Phase 2 already computes as the max pairwise distance between every
    endpoint clustered into that node (0 if only one segment touches it).
    """
    by_segment_id = {r.segment_id: r for r in results}
    for seg_id, (start_node_id, end_node_id) in graph.segment_to_nodes.items():
        r = by_segment_id.get(seg_id)
        if r is None:
            continue
        start_node = graph.node(start_node_id)
        end_node = graph.node(end_node_id)
        r.start_corner_classification = start_node.classification
        r.start_corner_coincidence_deviation_mm = start_node.max_internal_deviation_mm
        r.end_corner_classification = end_node.classification
        r.end_corner_coincidence_deviation_mm = end_node.max_internal_deviation_mm


SEGMENT_VALIDATION_COLUMNS = [
    "Wall ID", "Segment ID",
    "Geometric Length (mm)", "Reported Length (mm)", "Length Discrepancy (mm)",
    "Standard Frame Size (mm)",
    "Calculated Standard Count", "Reported Standard Count", "Frame Count Matches",
    "Calculated Custom Remainder (mm)", "Reported Custom Remainder (mm)",
    "Custom Remainder Matches",
    "Reconstructed Total Frame Length (mm)", "Total Length Discrepancy (mm)",
    "Start Matches First Frame", "Start Deviation (mm)",
    "End Matches Last Frame", "End Deviation (mm)",
    "Start Corner Classification", "Start Corner Deviation (mm)",
    "End Corner Classification", "End Corner Deviation (mm)",
    "Status", "Issues",
]


def _validation_result_to_row(r: SegmentValidationResult) -> dict:
    return {
        "Wall ID": r.wall_id,
        "Segment ID": r.segment_id,
        "Geometric Length (mm)": round(r.geometric_length_mm, 4),
        "Reported Length (mm)": r.reported_length_mm,
        "Length Discrepancy (mm)": (
            round(r.length_discrepancy_mm, 6) if r.length_discrepancy_mm is not None else None
        ),
        "Standard Frame Size (mm)": r.standard_frame_size_mm,
        "Calculated Standard Count": r.calculated_standard_count,
        "Reported Standard Count": r.reported_standard_count,
        "Frame Count Matches": r.frame_count_matches,
        "Calculated Custom Remainder (mm)": round(r.calculated_custom_remainder_mm, 4),
        "Reported Custom Remainder (mm)": r.reported_custom_remainder_mm,
        "Custom Remainder Matches": r.custom_remainder_matches,
        "Reconstructed Total Frame Length (mm)": round(r.reconstructed_total_frame_length_mm, 4),
        "Total Length Discrepancy (mm)": round(r.total_length_discrepancy_mm, 6),
        "Start Matches First Frame": r.start_matches_first_frame,
        "Start Deviation (mm)": round(r.start_deviation_mm, 6),
        "End Matches Last Frame": r.end_matches_last_frame,
        "End Deviation (mm)": round(r.end_deviation_mm, 6),
        "Start Corner Classification": r.start_corner_classification,
        "Start Corner Deviation (mm)": r.start_corner_coincidence_deviation_mm,
        "End Corner Classification": r.end_corner_classification,
        "End Corner Deviation (mm)": r.end_corner_coincidence_deviation_mm,
        "Status": r.status,
        "Issues": "; ".join(r.issues),
    }


def build_segment_validation_rows(results: List[SegmentValidationResult]) -> List[dict]:
    """Row-dict form of a validation report, keyed by SEGMENT_VALIDATION_COLUMNS --
    the public building block behind write_segment_validation_report, also
    useful for an in-memory CSV/table (e.g. a UI) that doesn't want to
    touch disk."""
    return [_validation_result_to_row(r) for r in results]


def write_segment_validation_report(results: List[SegmentValidationResult], path: str):
    """Write to CSV or .xlsx, chosen by the path's extension."""
    rows = build_segment_validation_rows(results)
    if str(path).lower().endswith(".xlsx"):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Segment Validation"
        ws.append(SEGMENT_VALIDATION_COLUMNS)
        for row in rows:
            ws.append([row[c] for c in SEGMENT_VALIDATION_COLUMNS])
        wb.save(path)
    else:
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=SEGMENT_VALIDATION_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
