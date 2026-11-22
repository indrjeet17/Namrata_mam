"""
Tests for excel_to_cad.pipeline (Phase 8 orchestration: ties Phases 1-7
together into one call for the application to use).
"""

from pathlib import Path

import pytest

from excel_to_cad import SupportPlacementConfig, generate_drawing, run_pipeline

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_run_pipeline_end_to_end_on_real_workbooks(path):
    result = run_pipeline(path)
    assert len(result.load_result.segments) > 0
    assert len(result.frames) > 0
    assert len(result.corner_connections) == len(result.graph.nodes)
    assert len(result.segment_validations) == len(result.load_result.segments)
    assert len(result.frame_schedule_rows) == len(result.frames)
    assert result.has_errors is False


def test_run_pipeline_accepts_a_file_like_object_not_just_a_path():
    # This is what lets the Streamlit app hand it an uploaded file's
    # in-memory stream directly -- no temp file, no hardcoded path.
    with open(REPO_ROOT / "testdrawing1.xlsx", "rb") as fh:
        result = run_pipeline(fh)
    assert len(result.load_result.segments) == 29


def test_run_pipeline_testdrawing4_has_exactly_one_warning_no_errors():
    result = run_pipeline(REPO_ROOT / "testdrawing4.xlsx")
    assert result.has_errors is False
    assert result.has_warnings is True
    warnings = [r for r in result.segment_validations if r.status == "WARNING"]
    assert len(warnings) == 1
    assert warnings[0].segment_id == "S15"


def test_run_pipeline_passes_through_custom_standard_frame_length():
    result = run_pipeline(
        REPO_ROOT / "testdrawing3.xlsx", default_standard_frame_length_mm=1200,
    )
    # Every segment in this file already specifies its own
    # standard_frame_size_mm=1200 in the workbook, so this is mainly a
    # smoke test that the parameter is accepted and threaded through
    # without erroring.
    assert result.has_errors is False


def test_run_pipeline_column_overrides_are_threaded_through(tmp_path):
    import openpyxl

    path = tmp_path / "custom_columns.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Segment Report"
    ws.append(["Wall ID", "Segment ID", "Sx", "Sy", "Ex", "Ey"])
    ws.append(["W1", "S1", 0, 0, 1200, 0])
    wb.save(path)

    result = run_pipeline(
        path,
        column_overrides={"start_x": "Sx", "start_y": "Sy", "end_x": "Ex", "end_y": "Ey"},
    )
    assert len(result.load_result.segments) == 1
    assert result.load_result.segments[0].segment_id == "S1"


def test_run_pipeline_reports_sheet_not_found_clearly(tmp_path):
    import openpyxl
    from excel_to_cad import ColumnDetectionError

    path = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(path)

    with pytest.raises(ColumnDetectionError):
        run_pipeline(path, sheet_name="Nonexistent Sheet")


# ---------------------------------------------------------------------
# generate_drawing: the single entry point app.py's "Generate" button
# uses -- tested directly since Streamlit's AppTest can't simulate a
# file upload.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_generate_drawing_end_to_end_on_real_workbooks(path):
    result, doc = generate_drawing(path)
    assert result.has_errors is False
    msp_entities = list(doc.modelspace())
    assert len(msp_entities) > 0
    # Sanity: every frame has a corresponding line entity on one of the
    # two frame layers.
    frame_lines = [e for e in msp_entities if e.dxftype() == "LINE"
                   and e.dxf.layer in ("STANDARD_FRAMES", "CUSTOM_FRAMES")]
    assert len(frame_lines) == len(result.frames)


def test_generate_drawing_accepts_a_file_like_object():
    with open(REPO_ROOT / "testdrawing1.xlsx", "rb") as fh:
        result, doc = generate_drawing(fh)
    assert len(result.load_result.segments) == 29
    assert len(list(doc.modelspace())) > 0


def test_generate_drawing_respects_support_config():
    config_corners_only = SupportPlacementConfig(at_corners=True)
    config_endpoints_too = SupportPlacementConfig(at_corners=True, at_segment_endpoints=True)

    _, doc_a = generate_drawing(REPO_ROOT / "testdrawing3.xlsx", support_config=config_corners_only)
    _, doc_b = generate_drawing(REPO_ROOT / "testdrawing3.xlsx", support_config=config_endpoints_too)

    circles_a = [e for e in doc_a.modelspace() if e.dxftype() == "CIRCLE"]
    circles_b = [e for e in doc_b.modelspace() if e.dxftype() == "CIRCLE"]
    assert len(circles_b) > len(circles_a)


def test_generate_drawing_respects_dxf_kwargs():
    _, doc = generate_drawing(
        REPO_ROOT / "testdrawing1.xlsx",
        dxf_kwargs={"bracket_radius_mm": 999.0},
    )
    circles = [e for e in doc.modelspace() if e.dxftype() == "CIRCLE"
               and e.dxf.layer == "SUPPORT_SYMBOLS"]
    assert all(c.dxf.radius == 999.0 for c in circles)


def test_run_pipeline_does_not_cross_connect_two_walls_sharing_a_coordinate(tmp_path):
    # Reproduces the multi-wall bug found while reviewing Phase 9 coverage:
    # run_pipeline must route through build_merged_connectivity_graph, not
    # build_connectivity_graph directly, or two walls sharing a coordinate
    # (e.g. a common grid origin) would be silently merged into one fake
    # junction.
    import openpyxl

    path = tmp_path / "two_walls.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Segment Report"
    ws.append(["Wall ID", "Segment ID", "Start X", "Start Y", "End X", "End Y"])
    ws.append(["W1", "S1", 0, 0, 1000, 0])
    ws.append(["W2", "S2", 0, 0, 0, 1000])  # same coordinate, different wall
    wb.save(path)

    result = run_pipeline(path)
    assert len(result.graph.nodes) == 4  # not 3 -- walls must not cross-connect
    for node in result.graph.nodes:
        assert node.node_id.startswith(("W1:", "W2:"))


def test_generate_drawing_raises_clearly_for_bad_sheet(tmp_path):
    import openpyxl
    from excel_to_cad import ColumnDetectionError

    path = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(path)
    with pytest.raises(ColumnDetectionError):
        generate_drawing(path, sheet_name="Nonexistent Sheet")
