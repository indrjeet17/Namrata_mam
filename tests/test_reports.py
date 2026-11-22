"""
Tests for excel_to_cad.reports (Phase 7: frame schedule and segment/corner
validation reports).
"""

import csv
from pathlib import Path

import openpyxl
import pytest

from excel_to_cad import (
    Frame,
    Point3D,
    Segment,
    build_connectivity_graph,
    build_frame_schedule,
    build_frame_schedule_rows,
    build_segment_validation_report,
    load_segments,
    write_frame_schedule,
    write_segment_validation_report,
)
from excel_to_cad.reports import FRAME_SCHEDULE_COLUMNS, SEGMENT_VALIDATION_COLUMNS

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


def seg(segment_id, x1, y1, x2, y2, **kwargs):
    return Segment(
        wall_id="W1", segment_id=segment_id,
        start=Point3D(x1, y1, 0.0), end=Point3D(x2, y2, 0.0),
        **kwargs,
    )


def frame(segment_id, frame_no, frame_type, length_mm, x1, y1, x2, y2, cum_start, cum_end):
    return Frame(
        segment_id=segment_id, frame_no=frame_no, frame_type=frame_type,
        length_mm=length_mm, start=Point3D(x1, y1, 0.0), end=Point3D(x2, y2, 0.0),
        cumulative_start_mm=cum_start, cumulative_end_mm=cum_end,
    )


# ---------------------------------------------------------------------
# Frame schedule rows
# ---------------------------------------------------------------------

def test_frame_schedule_row_count_matches_frame_count():
    segments = [seg("S1", 0, 0, 2500, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    assert len(rows) == len(frames)


def test_frame_id_format_and_uniqueness():
    segments = [seg("S1", 0, 0, 2500, 0), seg("S2", 0, 0, 0, 2500)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    frame_ids = [r["Frame ID"] for r in rows]
    assert len(frame_ids) == len(set(frame_ids))  # all unique
    assert all(fid.startswith(("S1-F", "S2-F")) for fid in frame_ids)


def test_frame_direction_classification():
    segments = [
        seg("H1", 0, 0, 1200, 0), seg("V1", 0, 0, 0, 1200),
        seg("D1", 0, 0, 800, 800),
    ]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    directions = {r["Segment ID"]: r["Direction"] for r in rows}
    assert directions["H1"] == "Horizontal"
    assert directions["V1"] == "Vertical"
    assert directions["D1"] == "Diagonal"


def test_cumulative_distances_match_frame_boundaries():
    segments = [seg("S1", 0, 0, 2500, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    for row, f in zip(rows, frames):
        assert row["Cumulative Start (mm)"] == pytest.approx(f.cumulative_start_mm, abs=1e-4)
        assert row["Cumulative End (mm)"] == pytest.approx(f.cumulative_end_mm, abs=1e-4)


def test_validation_status_defaults_to_ok_without_statuses_dict():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    assert all(r["Validation Status"] == "OK" for r in rows)


def test_validation_status_uses_provided_statuses_dict():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments, segment_statuses={"S1": "WARNING"})
    assert all(r["Validation Status"] == "WARNING" for r in rows)


def test_write_frame_schedule_csv_round_trips(tmp_path):
    segments = [seg("S1", 0, 0, 2500, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    path = tmp_path / "schedule.csv"
    write_frame_schedule(rows, str(path))

    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == FRAME_SCHEDULE_COLUMNS
        read_rows = list(reader)
    assert len(read_rows) == len(rows)
    assert read_rows[0]["Segment ID"] == "S1"


def test_write_frame_schedule_xlsx_round_trips(tmp_path):
    segments = [seg("S1", 0, 0, 2500, 0)]
    frames, _ = build_frame_schedule(segments)
    rows = build_frame_schedule_rows(frames, segments)
    path = tmp_path / "schedule.xlsx"
    write_frame_schedule(rows, str(path))

    wb = openpyxl.load_workbook(path)
    ws = wb.active
    header = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    assert list(header) == FRAME_SCHEDULE_COLUMNS
    assert ws.max_row == len(rows) + 1


# ---------------------------------------------------------------------
# Segment validation report: matching / disagreeing reported values
# ---------------------------------------------------------------------

def test_matching_reported_values_give_ok_status():
    s = seg(
        "S1", 0, 0, 6550, 0,
        reported_length_mm=6550.0, reported_standard_frame_count=5,
        reported_custom_frame_length_mm=550.0,
    )
    frames, frame_issues = build_frame_schedule([s])
    results = build_segment_validation_report([s], frames, frame_issues=frame_issues)
    assert len(results) == 1
    r = results[0]
    assert r.status == "OK"
    assert r.frame_count_matches is True
    assert r.custom_remainder_matches is True
    assert r.length_discrepancy_mm == pytest.approx(0.0, abs=1e-6)


def test_disagreeing_reported_standard_count_gives_warning():
    s = seg("S1", 0, 0, 6550, 0, reported_standard_frame_count=4)  # wrong, real answer is 5
    frames, frame_issues = build_frame_schedule([s])
    results = build_segment_validation_report([s], frames, frame_issues=frame_issues)
    r = results[0]
    assert r.frame_count_matches is False
    assert r.status == "WARNING"
    assert any("standard frame count" in i for i in r.issues)


def test_disagreeing_reported_custom_remainder_gives_warning():
    s = seg("S1", 0, 0, 6550, 0, reported_custom_frame_length_mm=999.0)  # wrong
    frames, frame_issues = build_frame_schedule([s])
    results = build_segment_validation_report([s], frames, frame_issues=frame_issues)
    r = results[0]
    assert r.custom_remainder_matches is False
    assert r.status == "WARNING"


def test_reported_value_rounding_does_not_cause_false_warning():
    s = seg(
        "S1", 0, 0, 5200.664002460644, 0,
        reported_standard_frame_count=4, reported_custom_frame_length_mm=400.66,
    )
    frames, frame_issues = build_frame_schedule([s])
    results = build_segment_validation_report([s], frames, frame_issues=frame_issues)
    r = results[0]
    assert r.status == "OK"
    assert r.frame_count_matches is True
    assert r.custom_remainder_matches is True


def test_no_reported_values_leaves_match_fields_none():
    s = seg("S1", 0, 0, 1200, 0)  # no reported_* fields at all
    frames, _ = build_frame_schedule([s])
    results = build_segment_validation_report([s], frames)
    r = results[0]
    assert r.length_discrepancy_mm is None
    assert r.frame_count_matches is None
    assert r.custom_remainder_matches is None
    assert r.status == "OK"


# ---------------------------------------------------------------------
# Segment validation report: structural checks (first/last frame alignment)
# ---------------------------------------------------------------------

def test_first_frame_not_at_segment_start_is_an_error():
    s = seg("S1", 0, 0, 1200, 0)
    # Deliberately wrong: this frame starts at x=50, not the segment's x=0.
    bad_frames = [frame("S1", 1, "standard", 1200, 50, 0, 1250, 0, 0, 1200)]
    results = build_segment_validation_report([s], bad_frames)
    r = results[0]
    assert r.start_matches_first_frame is False
    assert r.status == "ERROR"
    assert any("does not start at segment start" in i for i in r.issues)


def test_last_frame_not_at_segment_end_is_an_error():
    s = seg("S1", 0, 0, 1200, 0)
    bad_frames = [frame("S1", 1, "standard", 1200, 0, 0, 1150, 0, 0, 1200)]
    results = build_segment_validation_report([s], bad_frames)
    r = results[0]
    assert r.end_matches_last_frame is False
    assert r.status == "ERROR"


def test_no_frames_for_segment_is_an_error():
    s = seg("S1", 0, 0, 1200, 0)
    results = build_segment_validation_report([s], [])  # no frames at all
    r = results[0]
    assert r.status == "ERROR"
    assert any("no frames generated" in i for i in r.issues)


def test_reconstructed_total_mismatch_is_a_warning():
    s = seg("S1", 0, 0, 1200, 0)
    # Frame total (1000mm) doesn't match the segment's actual length (1200mm).
    bad_frames = [frame("S1", 1, "standard", 1000, 0, 0, 1000, 0, 0, 1000)]
    results = build_segment_validation_report([s], bad_frames)
    r = results[0]
    assert r.total_length_discrepancy_mm == pytest.approx(200.0, abs=1e-6)
    assert r.status in ("WARNING", "ERROR")  # also trips the end-alignment check


def test_near_zero_length_segment_is_reported_as_error_not_raised():
    s = seg("S1", 5, 5, 5, 5.0000001)
    results = build_segment_validation_report([s], [])
    assert len(results) == 1
    assert results[0].status == "ERROR"


# ---------------------------------------------------------------------
# Corner connectivity info
# ---------------------------------------------------------------------

def test_corner_connectivity_info_attached_when_graph_given():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    graph = build_connectivity_graph(segments)
    frames, frame_issues = build_frame_schedule(segments)
    results = build_segment_validation_report(segments, frames, graph=graph, frame_issues=frame_issues)
    by_id = {r.segment_id: r for r in results}
    assert by_id["S1"].end_corner_classification == "right_angle_corner"
    assert by_id["S1"].end_corner_coincidence_deviation_mm == pytest.approx(0.0)
    assert by_id["S1"].start_corner_classification == "disconnected_endpoint"


def test_corner_connectivity_info_absent_without_graph():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, _ = build_frame_schedule(segments)
    results = build_segment_validation_report(segments, frames)
    assert results[0].start_corner_classification is None
    assert results[0].end_corner_classification is None


def test_write_segment_validation_report_csv_and_xlsx(tmp_path):
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, _ = build_frame_schedule(segments)
    results = build_segment_validation_report(segments, frames)

    csv_path = tmp_path / "validation.csv"
    write_segment_validation_report(results, str(csv_path))
    with open(csv_path, newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == SEGMENT_VALIDATION_COLUMNS
        rows = list(reader)
    assert len(rows) == 1

    xlsx_path = tmp_path / "validation.xlsx"
    write_segment_validation_report(results, str(xlsx_path))
    wb = openpyxl.load_workbook(xlsx_path)
    ws = wb.active
    assert ws.max_row == 2  # header + 1 segment


# ---------------------------------------------------------------------
# Real-data validation
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_validation_report_has_no_errors(path):
    result = load_segments(path)
    graph = build_connectivity_graph(result.segments)
    frames, frame_issues = build_frame_schedule(result.segments)
    results = build_segment_validation_report(
        result.segments, frames, graph=graph,
        loader_issues=result.issues, frame_issues=frame_issues,
    )
    assert len(results) == len(result.segments)
    assert all(r.status != "ERROR" for r in results)


def test_testdrawing4_has_exactly_the_known_s15_warning():
    # Confirmed in Phase 2: S15/S16 are 0.6319mm apart, beyond the strict
    # coincidence tolerance -- surfaces here as the only non-OK segment.
    result = load_segments(REPO_ROOT / "testdrawing4.xlsx")
    graph = build_connectivity_graph(result.segments)
    frames, frame_issues = build_frame_schedule(result.segments)
    results = build_segment_validation_report(
        result.segments, frames, graph=graph,
        loader_issues=result.issues, frame_issues=frame_issues,
    )
    non_ok = [r for r in results if r.status != "OK"]
    assert len(non_ok) == 1
    assert non_ok[0].segment_id == "S15"
    assert non_ok[0].status == "WARNING"


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_frame_schedule_row_count_matches_total_frames(path):
    result = load_segments(path)
    frames, _ = build_frame_schedule(result.segments)
    rows = build_frame_schedule_rows(frames, result.segments)
    assert len(rows) == len(frames)
    frame_ids = [r["Frame ID"] for r in rows]
    assert len(frame_ids) == len(set(frame_ids))
