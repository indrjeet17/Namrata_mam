"""
Tests for excel_to_cad.dxf_export (Phase 5: DXF generation).

No reference CAD screenshot exists for this project (confirmed with the
user) -- these tests check correctness (right layers, right entity counts,
dimensions measuring the right lengths, valid/round-trippable DXF), not a
specific visual appearance.
"""

from pathlib import Path

import ezdxf
import pytest

from excel_to_cad import (
    Point3D,
    Segment,
    apply_frame_terminations,
    build_connectivity_graph,
    build_corner_connections,
    build_dxf_document,
    build_frame_schedule,
    export_dxf,
    load_segments,
)
from excel_to_cad.dxf_export import LAYER_DEFINITIONS

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


def seg(segment_id, x1, y1, x2, y2):
    return Segment(
        wall_id="W1", segment_id=segment_id,
        start=Point3D(x1, y1, 0.0), end=Point3D(x2, y2, 0.0),
    )


def build_pipeline(segments):
    graph = build_connectivity_graph(segments)
    corners = build_corner_connections(graph, segments)
    frames, issues = build_frame_schedule(segments)
    enriched = apply_frame_terminations(corners, graph, frames)
    return frames, enriched, issues


def entities_by_layer_type(msp):
    from collections import Counter
    return Counter((e.dxf.layer, e.dxftype()) for e in msp)


# ---------------------------------------------------------------------
# Layer setup
# ---------------------------------------------------------------------

def test_all_plan_layers_are_created():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    expected_layers = {
        "WALL_GEOMETRY", "STANDARD_FRAMES", "CUSTOM_FRAMES",
        "CORNER_CONNECTIONS", "SUPPORT_SYMBOLS", "STANDARD_DIMENSIONS",
        "REFERENCE_DIMENSIONS", "CALLOUTS", "LABELS",
    }
    assert expected_layers == set(LAYER_DEFINITIONS.keys())
    for name in expected_layers:
        assert doc.layers.has_entry(name)


def test_standard_dimension_layer_is_blue_and_reference_is_magenta():
    assert LAYER_DEFINITIONS["STANDARD_DIMENSIONS"]["color"] == 5  # ACI blue
    assert LAYER_DEFINITIONS["REFERENCE_DIMENSIONS"]["color"] == 6  # ACI magenta


def test_callouts_layer_exists_but_is_never_populated():
    # No sample workbook has real callout/component numbers (Phase 1
    # finding) -- the plan says not to invent them.
    segments = [
        seg("S1", 0, 0, 1200, 0),
        seg("S2", 1200, 0, 1200, 1200),
        seg("S3", 1200, 1200, 0, 1200),
    ]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    msp = doc.modelspace()
    assert doc.layers.has_entry("CALLOUTS")
    assert all(e.dxf.layer != "CALLOUTS" for e in msp)


# ---------------------------------------------------------------------
# Entity counts / correctness for a simple synthetic wall
# ---------------------------------------------------------------------

def test_wall_geometry_has_one_line_per_segment():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    counts = entities_by_layer_type(doc.modelspace())
    assert counts[("WALL_GEOMETRY", "LINE")] == 2


def test_frame_lines_split_correctly_between_standard_and_custom_layers():
    segments = [seg("S1", 0, 0, 1300, 0)]  # 1 standard + 1 custom (100mm)
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    counts = entities_by_layer_type(doc.modelspace())
    assert counts[("STANDARD_FRAMES", "LINE")] == 1
    assert counts[("CUSTOM_FRAMES", "LINE")] == 1


def test_exact_multiple_segment_has_no_custom_frame_line():
    segments = [seg("S1", 0, 0, 2400, 0)]  # exact multiple of 1200
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    counts = entities_by_layer_type(doc.modelspace())
    assert counts[("CUSTOM_FRAMES", "LINE")] == 0
    assert counts[("STANDARD_FRAMES", "LINE")] == 2


def test_bracket_symbol_only_drawn_at_real_corners_not_open_ends():
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    counts = entities_by_layer_type(doc.modelspace())
    # 3 nodes total: 1 right-angle corner (gets a bracket), 2 open ends
    # (no bracket).
    assert counts[("SUPPORT_SYMBOLS", "CIRCLE")] == 1
    assert counts[("CORNER_CONNECTIONS", "LINE")] == 2  # one "+" = 2 lines


def test_segment_label_text_contains_segment_id():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    texts = [e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"
             and e.dxf.layer == "LABELS"]
    assert "S1" in texts


def test_corner_label_contains_case_letters():
    # Both segments are exactly 1200mm, so this corner gets A/B (right
    # angle) *and* G (both touching frames are "standard") -- the label
    # joins every applicable case, not just the base corner type.
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    texts = [e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"
             and e.dxf.layer == "LABELS"]
    corner_labels = [t for t in texts if t not in ("S1", "S2")]
    assert len(corner_labels) == 1
    cases = set(corner_labels[0].split("/"))
    assert cases & {"A", "B"}
    assert "G" in cases


# ---------------------------------------------------------------------
# Dimensions measure the right thing
# ---------------------------------------------------------------------

def test_frame_dimensions_measure_each_frames_actual_length():
    segments = [seg("S1", 0, 0, 2500, 0)]  # 2 standard + 1 custom (100mm)
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"
            and e.dxf.layer == "STANDARD_DIMENSIONS"]
    measurements = sorted(d.get_measurement() for d in dims)
    assert measurements == pytest.approx([100.0, 1200.0, 1200.0])


def test_reference_dimension_measures_full_segment_length():
    segments = [seg("S1", 0, 0, 3000, 4000)]  # 3-4-5 triangle, length 5000
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"
            and e.dxf.layer == "REFERENCE_DIMENSIONS"]
    assert len(dims) == 1
    assert dims[0].get_measurement() == pytest.approx(5000.0)


def test_dimension_colors_match_the_plans_blue_and_magenta_requirement():
    segments = [seg("S1", 0, 0, 1200, 0)]
    frames, corners, _ = build_pipeline(segments)
    doc = build_dxf_document(segments, frames, corners)
    for e in doc.modelspace():
        if e.dxftype() == "DIMENSION" and e.dxf.layer == "STANDARD_DIMENSIONS":
            assert e.dxf.layer in doc.layers
    standard_layer = doc.layers.get("STANDARD_DIMENSIONS")
    reference_layer = doc.layers.get("REFERENCE_DIMENSIONS")
    assert standard_layer.color == 5
    assert reference_layer.color == 6


# ---------------------------------------------------------------------
# File round-trip and real-data validation
# ---------------------------------------------------------------------

def test_export_dxf_writes_a_valid_readable_file(tmp_path):
    segments = [seg("S1", 0, 0, 1200, 0), seg("S2", 1200, 0, 1200, 1200)]
    frames, corners, _ = build_pipeline(segments)
    out_path = tmp_path / "test.dxf"
    export_dxf(segments, frames, corners, str(out_path))
    assert out_path.exists()
    reloaded = ezdxf.readfile(str(out_path))
    assert len(list(reloaded.modelspace())) > 0


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_exports_valid_dxf_with_consistent_entity_counts(path, tmp_path):
    result = load_segments(path)
    frames, corners, issues = build_pipeline(result.segments)
    assert issues == []

    out_path = tmp_path / "out.dxf"
    export_dxf(result.segments, frames, corners, str(out_path))
    reloaded = ezdxf.readfile(str(out_path))
    msp = reloaded.modelspace()
    counts = entities_by_layer_type(msp)

    standard_count = sum(1 for f in frames if f.frame_type == "standard")
    custom_count = sum(1 for f in frames if f.frame_type == "custom")
    corners_with_cases = [c for c in corners if c.corner_cases]

    assert counts[("WALL_GEOMETRY", "LINE")] == len(result.segments)
    assert counts[("STANDARD_FRAMES", "LINE")] == standard_count
    assert counts[("CUSTOM_FRAMES", "LINE")] == custom_count
    assert counts[("REFERENCE_DIMENSIONS", "DIMENSION")] == len(result.segments)
    assert counts[("STANDARD_DIMENSIONS", "DIMENSION")] == len(frames)
    assert counts[("SUPPORT_SYMBOLS", "CIRCLE")] == len(corners_with_cases)
    assert counts[("CORNER_CONNECTIONS", "LINE")] == len(corners_with_cases) * 2
    assert counts[("LABELS", "TEXT")] == len(result.segments) + len(corners_with_cases)


@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_real_workbook_every_frame_dimension_matches_its_frame_length(path):
    result = load_segments(path)
    frames, corners, _ = build_pipeline(result.segments)
    doc = build_dxf_document(result.segments, frames, corners)
    dims = [e for e in doc.modelspace() if e.dxftype() == "DIMENSION"
            and e.dxf.layer == "STANDARD_DIMENSIONS"]
    measured = sorted(round(d.get_measurement(), 2) for d in dims)
    expected = sorted(round(f.length_mm, 2) for f in frames)
    assert measured == expected
