"""
Tests for excel_to_cad.loader (Phase 1: dynamic column detection,
normalization, and validation).

Covers both the real sample workbooks (testdrawing1-4.xlsx) and small
synthetic workbooks built on the fly for edge cases the samples don't
happen to exercise (missing required column, ambiguous column, zero-
length segment, non-numeric coordinate, length mismatch).
"""

import math
from pathlib import Path

import openpyxl
import pytest

from excel_to_cad import ColumnDetectionError, Point3D, detect_columns, load_segments

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


def _read_summary_total_segments(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Summary"]
    for param, value in ws.iter_rows(min_row=2, values_only=True):
        if param == "Total Segments":
            return int(value)
    raise AssertionError("Total Segments not found in Summary sheet")


def _write_workbook(path, headers, rows, sheet_name="Segment Report"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(path)


# ---------------------------------------------------------------------
# detect_columns
# ---------------------------------------------------------------------

def test_detect_columns_matches_known_header_variants():
    headers = [
        "Wall ID", "Segment ID", "Start X", "Start Y", "Start Z",
        "End X", "End Y", "End Z", "Length (mm)", "Standard Frame Size",
        "Standard Frames", "Custom Frame (mm)",
    ]
    mapping, unrecognized, ambiguous = detect_columns(headers)

    assert mapping["wall_id"] == 0
    assert mapping["segment_id"] == 1
    assert mapping["length_mm"] == headers.index("Length (mm)")
    assert mapping["standard_frame_size_mm"] == headers.index("Standard Frame Size")
    assert mapping["standard_frame_count"] == headers.index("Standard Frames")
    assert mapping["custom_frame_length_mm"] == headers.index("Custom Frame (mm)")
    assert not unrecognized
    assert not ambiguous


def test_detect_columns_is_case_and_punctuation_insensitive():
    headers = ["wall_id", "SEGMENT-ID", "start x", "Start_Y", "end x", "END Y"]
    mapping, _, _ = detect_columns(headers)
    assert mapping["wall_id"] == 0
    assert mapping["segment_id"] == 1
    assert mapping["start_x"] == 2
    assert mapping["start_y"] == 3
    assert mapping["end_x"] == 4
    assert mapping["end_y"] == 5


def test_detect_columns_flags_unrecognized_columns():
    headers = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y", "Notes"]
    _, unrecognized, _ = detect_columns(headers)
    assert unrecognized == ["Notes"]


def test_detect_columns_flags_ambiguous_field():
    # Two columns both alias to "length_mm".
    headers = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y",
               "Length", "Length (mm)"]
    _, _, ambiguous = detect_columns(headers)
    assert "length_mm" in ambiguous
    assert set(ambiguous["length_mm"]) == {"Length", "Length (mm)"}


def test_detect_columns_override_resolves_ambiguity():
    headers = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y",
               "Length", "Length (mm)"]
    mapping, _, ambiguous = detect_columns(
        headers, overrides={"length_mm": "Length (mm)"}
    )
    assert mapping["length_mm"] == headers.index("Length (mm)")
    assert "length_mm" not in ambiguous


def test_detect_columns_override_unknown_header_raises():
    headers = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y"]
    with pytest.raises(ColumnDetectionError):
        detect_columns(headers, overrides={"length_mm": "Does Not Exist"})


# ---------------------------------------------------------------------
# load_segments against the real sample workbooks
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_load_segments_real_workbook_matches_summary_count(path):
    expected_count = _read_summary_total_segments(path)
    result = load_segments(path)
    assert len(result.segments) == expected_count
    assert result.errors == []


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_load_segments_real_workbook_has_no_length_discrepancies(path):
    # Verified separately that reported Length (mm) vs. geometric length
    # agrees to ~1e-12mm across all four sample files (floating-point
    # noise only) -- so with the default 1e-3mm tolerance, no warnings
    # should fire here.
    result = load_segments(path)
    length_warnings = [
        w for w in result.warnings if "disagrees with geometric length" in w.message
    ]
    assert length_warnings == []


def test_load_segments_testdrawing4_has_diagonal_segment():
    result = load_segments(REPO_ROOT / "testdrawing4.xlsx")
    diagonal_segments = [s for s in result.segments if s.direction == "Diagonal"]
    assert len(diagonal_segments) == 1
    assert diagonal_segments[0].segment_id == "S25"


def test_load_segments_real_workbook_carries_reported_frame_fields():
    result = load_segments(REPO_ROOT / "testdrawing1.xlsx")
    s1 = next(s for s in result.segments if s.segment_id == "S1")
    assert s1.wall_id == "W1"
    assert s1.standard_frame_size_mm == 1200
    assert s1.reported_standard_frame_count == 4
    assert math.isclose(s1.reported_custom_frame_length_mm, 400.66, rel_tol=1e-6)
    assert math.isclose(s1.geometric_length_mm, 5200.664002460644, rel_tol=1e-9)


def test_load_segments_testdrawing1_has_no_continuity_status_column():
    # testdrawing1's Frame Placement Report lacks this column, but the
    # Segment Report loader shouldn't care -- it only reads Segment Report.
    result = load_segments(REPO_ROOT / "testdrawing1.xlsx")
    assert "standard_frame_count" in result.column_mapping.mapping


# ---------------------------------------------------------------------
# load_segments edge cases (synthetic workbooks)
# ---------------------------------------------------------------------

MINIMAL_HEADERS = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y"]


def test_load_segments_missing_required_column_raises(tmp_path):
    path = tmp_path / "missing_col.xlsx"
    _write_workbook(path, ["Wall ID", "Segment ID", "Start X", "End X", "End Y"], [])
    with pytest.raises(ColumnDetectionError):
        load_segments(path)


def test_load_segments_ambiguous_required_column_raises(tmp_path):
    path = tmp_path / "ambiguous_required.xlsx"
    headers = ["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y", "End Y "]
    _write_workbook(path, headers, [("W1", "S1", 0, 0, 10, 0, 0)])
    # Two columns both normalize to "end y" -> ambiguous required field.
    with pytest.raises(ColumnDetectionError):
        load_segments(path)


def test_load_segments_missing_required_column_resolved_by_override(tmp_path):
    path = tmp_path / "renamed_col.xlsx"
    headers = ["Wall ID", "Segment ID", "Sx", "Sy", "Ex", "Ey"]
    _write_workbook(path, headers, [("W1", "S1", 0, 0, 10, 0)])
    with pytest.raises(ColumnDetectionError):
        load_segments(path)  # "Sx" etc. don't match any alias
    result = load_segments(
        path,
        column_overrides={
            "start_x": "Sx", "start_y": "Sy", "end_x": "Ex", "end_y": "Ey",
        },
    )
    assert len(result.segments) == 1
    assert result.segments[0].start == Point3D(0, 0, 0)
    assert result.segments[0].end == Point3D(10, 0, 0)


def test_load_segments_zero_length_segment_is_flagged_not_dropped_silently(tmp_path):
    path = tmp_path / "zero_length.xlsx"
    rows = [("W1", "S1", 5, 5, 5, 5), ("W1", "S2", 0, 0, 10, 0)]
    _write_workbook(path, MINIMAL_HEADERS, rows)
    result = load_segments(path)
    assert len(result.segments) == 1  # only S2 survives
    assert len(result.errors) == 1
    assert "zero-length" in result.errors[0].message
    assert result.errors[0].segment_id == "S1"


def test_load_segments_non_numeric_coordinate_is_flagged(tmp_path):
    path = tmp_path / "bad_coord.xlsx"
    rows = [("W1", "S1", "not-a-number", 0, 10, 0)]
    _write_workbook(path, MINIMAL_HEADERS, rows)
    result = load_segments(path)
    assert result.segments == []
    assert len(result.errors) == 1
    assert "not numeric" in result.errors[0].message


def test_load_segments_missing_coordinate_value_is_flagged(tmp_path):
    path = tmp_path / "missing_value.xlsx"
    rows = [("W1", "S1", None, 0, 10, 0)]
    _write_workbook(path, MINIMAL_HEADERS, rows)
    result = load_segments(path)
    assert result.segments == []
    assert "missing Start X" in result.errors[0].message


def test_load_segments_blank_row_is_skipped_without_error(tmp_path):
    path = tmp_path / "blank_row.xlsx"
    rows = [("W1", "S1", 0, 0, 10, 0), (None, None, None, None, None, None)]
    _write_workbook(path, MINIMAL_HEADERS, rows)
    result = load_segments(path)
    assert len(result.segments) == 1
    assert result.errors == []


def test_load_segments_length_mismatch_is_flagged(tmp_path):
    path = tmp_path / "length_mismatch.xlsx"
    headers = MINIMAL_HEADERS + ["Length (mm)"]
    # Geometric length is 10, reported is wildly different.
    rows = [("W1", "S1", 0, 0, 10, 0, 999)]
    _write_workbook(path, headers, rows)
    result = load_segments(path)
    assert len(result.segments) == 1
    assert len(result.warnings) == 1
    assert "disagrees with geometric length" in result.warnings[0].message


def test_load_segments_z_defaults_to_zero_when_column_absent(tmp_path):
    path = tmp_path / "no_z.xlsx"
    rows = [("W1", "S1", 1, 2, 3, 4)]
    _write_workbook(path, MINIMAL_HEADERS, rows)
    result = load_segments(path)
    seg = result.segments[0]
    assert seg.start.z == 0.0
    assert seg.end.z == 0.0


def test_load_segments_color_preserved_as_native_type(tmp_path):
    path = tmp_path / "color.xlsx"
    headers = MINIMAL_HEADERS + ["Color"]
    rows = [("W1", "S1", 0, 0, 10, 0, 5)]
    _write_workbook(path, headers, rows)
    result = load_segments(path)
    assert result.segments[0].color == 5  # stays an int, not "5"


def test_load_segments_optional_ambiguous_column_warns_but_does_not_raise(tmp_path):
    path = tmp_path / "optional_ambiguous.xlsx"
    headers = MINIMAL_HEADERS + ["Length", "Length (mm)"]
    rows = [("W1", "S1", 0, 0, 10, 0, 10, 10)]
    _write_workbook(path, headers, rows)
    result = load_segments(path)
    assert len(result.segments) == 1
    assert result.segments[0].reported_length_mm is None  # left unmapped
    ambiguous_warnings = [w for w in result.warnings if "ambiguous" in w.message]
    assert len(ambiguous_warnings) == 1
