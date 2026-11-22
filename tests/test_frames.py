"""
Tests for excel_to_cad.frames (Phase 4: frame sequencing).

Covers the standard/custom frame math directly, placement along
horizontal/vertical/diagonal segments, cross-validation against a
workbook's own reported frame counts/lengths, and -- most importantly --
an exact cross-check of every computed frame (type, length, start, end)
against all four real workbooks' own independently-generated Frame
Placement Report sheets.
"""

import math
from pathlib import Path

import openpyxl
import pytest

from excel_to_cad import (
    Point3D,
    Segment,
    build_frame_schedule,
    compute_frame_counts,
    load_segments,
    place_frames,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_WORKBOOKS = [
    REPO_ROOT / "testdrawing1.xlsx",
    REPO_ROOT / "testdrawing2.xlsx",
    REPO_ROOT / "testdrawing3.xlsx",
    REPO_ROOT / "testdrawing4.xlsx",
]


def seg(segment_id, x1, y1, x2, y2, z1=0.0, z2=0.0, **kwargs):
    return Segment(
        wall_id="W1", segment_id=segment_id,
        start=Point3D(x1, y1, z1), end=Point3D(x2, y2, z2),
        **kwargs,
    )


# ---------------------------------------------------------------------
# compute_frame_counts
# ---------------------------------------------------------------------

def test_plan_worked_example_14587mm():
    # The plan's own worked example.
    count, remainder = compute_frame_counts(14587.44234, 1200)
    assert count == 12
    assert remainder == pytest.approx(187.44234, abs=1e-5)


def test_plan_worked_example_6550mm():
    count, remainder = compute_frame_counts(6550, 1200)
    assert count == 5
    assert remainder == pytest.approx(550, abs=1e-9)


def test_exact_multiple_has_no_remainder():
    count, remainder = compute_frame_counts(3600, 1200)
    assert count == 3
    assert remainder == 0.0


def test_segment_shorter_than_standard_length():
    count, remainder = compute_frame_counts(900, 1200)
    assert count == 0
    assert remainder == pytest.approx(900)


def test_floating_point_noise_just_below_exact_multiple_does_not_undercount():
    # Represents an intended-exact 3600mm, corrupted by float noise.
    count, remainder = compute_frame_counts(3599.9999999999995, 1200)
    assert count == 3
    assert remainder == 0.0


def test_floating_point_noise_just_above_exact_multiple_does_not_leave_tiny_remainder():
    count, remainder = compute_frame_counts(3600.0000000000005, 1200)
    assert count == 3
    assert remainder == 0.0


def test_non_positive_length_raises():
    with pytest.raises(ValueError):
        compute_frame_counts(0, 1200)
    with pytest.raises(ValueError):
        compute_frame_counts(-100, 1200)


def test_non_positive_frame_size_raises():
    with pytest.raises(ValueError):
        compute_frame_counts(1000, 0)


# ---------------------------------------------------------------------
# place_frames: orientation-agnostic placement, boundary exactness
# ---------------------------------------------------------------------

def test_horizontal_segment_frame_placement():
    s = seg("S1", 0, 0, 6550, 0)
    frames = place_frames(s, 1200)
    assert [f.frame_type for f in frames] == ["standard"] * 5 + ["custom"]
    assert frames[-1].length_mm == pytest.approx(550)
    assert frames[0].start == Point3D(0, 0, 0)
    assert frames[-1].end == s.end


def test_vertical_segment_frame_placement():
    s = seg("S1", 0, 0, 0, 2500)
    frames = place_frames(s, 1200)
    assert len(frames) == 3  # 2 standard + 1 custom (100mm)
    assert frames[-1].frame_type == "custom"
    assert frames[-1].length_mm == pytest.approx(100)
    assert frames[0].start == s.start
    assert frames[-1].end == s.end


def test_diagonal_segment_frame_placement():
    s = seg("S1", 0, 0, 3000, 4000)  # length 5000 (3-4-5 triangle)
    frames = place_frames(s, 1200)
    assert s.geometric_length_mm == pytest.approx(5000)
    total_length = sum(f.length_mm for f in frames)
    assert total_length == pytest.approx(5000)
    assert frames[0].start == s.start
    assert frames[-1].end == s.end
    # Each frame boundary must lie exactly on the line from start to end.
    for f in frames:
        for point in (f.start, f.end):
            # Cross product of (end-start) and (point-start) should be ~0
            # for colinearity in the XY plane.
            cross = (s.end.x - s.start.x) * (point.y - s.start.y) - \
                    (s.end.y - s.start.y) * (point.x - s.start.x)
            assert abs(cross) < 1e-6


def test_exact_multiple_segment_has_no_custom_frame():
    s = seg("S1", 0, 0, 3600, 0)
    frames = place_frames(s, 1200)
    assert len(frames) == 3
    assert all(f.frame_type == "standard" for f in frames)
    assert frames[-1].end == s.end  # still exact, not drifted


def test_segment_shorter_than_standard_is_single_custom_frame():
    s = seg("S1", 0, 0, 900, 0)
    frames = place_frames(s, 1200)
    assert len(frames) == 1
    assert frames[0].frame_type == "custom"
    assert frames[0].length_mm == pytest.approx(900)
    assert frames[0].start == s.start
    assert frames[0].end == s.end


def test_no_zero_length_custom_frame_created():
    s = seg("S1", 0, 0, 2400, 0)  # exact multiple of 1200
    frames = place_frames(s, 1200)
    assert all(f.length_mm > 0 for f in frames)
    assert not any(f.frame_type == "custom" for f in frames)


def test_frame_numbers_are_sequential_from_one():
    s = seg("S1", 0, 0, 6550, 0)
    frames = place_frames(s, 1200)
    assert [f.frame_no for f in frames] == list(range(1, len(frames) + 1))


def test_frames_have_no_gaps_or_overlaps():
    s = seg("S1", 0, 0, 6550, 0)
    frames = place_frames(s, 1200)
    for prev, curr in zip(frames, frames[1:]):
        assert prev.cumulative_end_mm == pytest.approx(curr.cumulative_start_mm)
        assert prev.end == curr.start


def test_near_zero_length_segment_raises():
    s = seg("S1", 0, 0, 0, 0.0001)
    with pytest.raises(ValueError):
        place_frames(s, 1200)


# ---------------------------------------------------------------------
# build_frame_schedule: per-segment independence, cross-validation
# ---------------------------------------------------------------------

def test_remainder_not_carried_across_segments():
    segments = [seg("S1", 0, 0, 1300, 0), seg("S2", 2000, 0, 2500, 0)]
    frames, issues = build_frame_schedule(segments)
    s1_frames = [f for f in frames if f.segment_id == "S1"]
    s2_frames = [f for f in frames if f.segment_id == "S2"]
    assert [f.frame_type for f in s1_frames] == ["standard", "custom"]
    assert s1_frames[-1].length_mm == pytest.approx(100)
    # S2 is only 500mm -- if the 100mm remainder had leaked in, this would
    # be wrong; it must be sequenced fresh as its own single custom frame.
    assert [f.frame_type for f in s2_frames] == ["custom"]
    assert s2_frames[0].length_mm == pytest.approx(500)


def test_segment_uses_its_own_standard_frame_size_when_given():
    s = seg("S1", 0, 0, 2000, 0, standard_frame_size_mm=1000.0)
    frames, _ = build_frame_schedule([s])
    assert [f.frame_type for f in frames] == ["standard", "standard"]
    assert all(f.length_mm == pytest.approx(1000) for f in frames)


def test_segment_falls_back_to_default_frame_size_when_absent():
    s = seg("S1", 0, 0, 2500, 0)  # no standard_frame_size_mm set
    frames, _ = build_frame_schedule([s], default_standard_frame_length_mm=1000.0)
    assert [f.frame_type for f in frames] == ["standard", "standard", "custom"]


def test_matching_reported_values_produce_no_warnings():
    s = seg(
        "S1", 0, 0, 6550, 0,
        reported_standard_frame_count=5,
        reported_custom_frame_length_mm=550.0,
    )
    _, issues = build_frame_schedule([s])
    assert issues == []


def test_reported_standard_count_disagreement_is_flagged_not_overwritten():
    s = seg(
        "S1", 0, 0, 6550, 0,
        reported_standard_frame_count=4,  # wrong on purpose -- real answer is 5
        reported_custom_frame_length_mm=550.0,
    )
    frames, issues = build_frame_schedule([s])
    standard = [f for f in frames if f.frame_type == "standard"]
    assert len(standard) == 5  # our own calculation wins, not silently "corrected" to 4
    assert len(issues) == 1
    assert "Standard frame count disagreement" in issues[0].message


def test_reported_custom_length_disagreement_is_flagged():
    s = seg(
        "S1", 0, 0, 6550, 0,
        reported_standard_frame_count=5,
        reported_custom_frame_length_mm=999.0,  # wrong on purpose
    )
    _, issues = build_frame_schedule([s])
    assert len(issues) == 1
    assert "Custom frame length disagreement" in issues[0].message


def test_reported_value_rounding_does_not_trigger_false_warning():
    # Mirrors the real data: true remainder 400.664002460644, reported
    # (rounded) as 400.66 -- must not be flagged as a disagreement.
    s = seg(
        "S1", 0, 0, 5200.664002460644, 0,
        reported_standard_frame_count=4,
        reported_custom_frame_length_mm=400.66,
    )
    _, issues = build_frame_schedule([s])
    assert issues == []


def test_zero_length_segment_is_reported_as_error_not_raised():
    s = seg("S1", 5, 5, 5, 5)
    frames, issues = build_frame_schedule([s])
    assert frames == []
    assert len(issues) == 1
    assert issues[0].severity == "error"


# ---------------------------------------------------------------------
# Real-data validation
# ---------------------------------------------------------------------

@pytest.mark.parametrize("path", REAL_WORKBOOKS)
def test_build_frame_schedule_matches_workbook_frame_placement_report_exactly(path):
    result = load_segments(path)
    frames, issues = build_frame_schedule(result.segments)
    assert issues == []

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Frame Placement Report"]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    header = list(ws.iter_rows(min_row=1, max_row=1, values_only=True))[0]
    idx = {h: i for i, h in enumerate(header)}

    assert len(rows) == len(frames)
    frames_by_key = {(f.segment_id, f.frame_no): f for f in frames}

    for row in rows:
        key = (row[idx["Segment ID"]], row[idx["Frame No"]])
        match = frames_by_key.get(key)
        assert match is not None, f"Missing computed frame for {key}"
        assert match.frame_type == row[idx["Frame Type"]].lower()
        assert match.length_mm == pytest.approx(row[idx["Frame Length"]], abs=0.01)
        for axis, reported in zip(
            match.start.as_tuple(),
            (row[idx["Start X"]], row[idx["Start Y"]], row[idx["Start Z"]]),
        ):
            assert axis == pytest.approx(reported, abs=0.01)
        for axis, reported in zip(
            match.end.as_tuple(),
            (row[idx["End X"]], row[idx["End Y"]], row[idx["End Z"]]),
        ):
            assert axis == pytest.approx(reported, abs=0.01)


def test_testdrawing4_s1_matches_plan_worked_example():
    result = load_segments(REPO_ROOT / "testdrawing4.xlsx")
    s1 = next(s for s in result.segments if s.segment_id == "S1")
    frames, issues = build_frame_schedule([s1])
    assert issues == []
    standard = [f for f in frames if f.frame_type == "standard"]
    custom = [f for f in frames if f.frame_type == "custom"]
    assert len(standard) == 12
    assert len(custom) == 1
    assert custom[0].length_mm == pytest.approx(187.44233840869128, abs=1e-6)


def test_testdrawing3_s5_shorter_than_standard_is_single_custom_frame():
    result = load_segments(REPO_ROOT / "testdrawing3.xlsx")
    s5 = next(s for s in result.segments if s.segment_id == "S5")
    frames, issues = build_frame_schedule([s5])
    assert issues == []
    assert len(frames) == 1
    assert frames[0].frame_type == "custom"
    assert frames[0].length_mm == pytest.approx(1039.015671984569, abs=1e-6)
