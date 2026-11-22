"""
Phase 4: frame sequencing.

For each segment, places standard-length frames consecutively from the
segment's original start point toward its end point, with any remainder
placed as a single custom frame at the end. Each segment is sequenced
independently -- a remainder never carries into the next segment, and a
segment's own start/end coordinates are never altered (frames are purely
a subdivision of the segment that's already there).

Works for horizontal, vertical, and diagonal segments alike: frame
boundaries are computed from the segment's actual 3D direction vector and
cumulative distance along it, not from axis-specific logic.
"""

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from .models import Point3D, Segment, ValidationIssue

DEFAULT_STANDARD_FRAME_LENGTH_MM = 1200.0
DEFAULT_LENGTH_TOLERANCE_MM = 1e-3
# Reported "Custom Frame (mm)" values in the sample workbooks are rounded
# to 2 decimal places (e.g. 400.66 for a true remainder of
# 400.664002460644) -- this tolerance is sized to absorb that rounding
# without masking a genuine discrepancy.
DEFAULT_REPORTED_VALUE_TOLERANCE_MM = 0.01


@dataclass
class Frame:
    segment_id: str
    frame_no: int  # 1-based, in placement order from the segment's start
    frame_type: str  # "standard" or "custom"
    length_mm: float
    start: Point3D
    end: Point3D
    cumulative_start_mm: float
    cumulative_end_mm: float


def compute_frame_counts(
    length_mm: float,
    standard_frame_length_mm: float,
    tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
) -> Tuple[int, float]:
    """
    standard_count = floor(length / F), remainder = length - standard_count * F.

    A segment shorter than one standard frame becomes a single custom
    frame covering its whole length (standard_count = 0) -- not an error.

    Guards against two floating-point edge cases right at an exact
    multiple of F: a length that's a hair *below* an intended exact
    multiple (naive floor() undercounts by one, leaving a near-F-length
    "remainder") or a hair *above* one (leaving a near-zero "remainder").
    Both are snapped to the exact-multiple result within `tolerance_mm`.
    """
    if length_mm <= 0:
        raise ValueError(f"length_mm must be positive, got {length_mm}")
    if standard_frame_length_mm <= 0:
        raise ValueError(
            f"standard_frame_length_mm must be positive, got {standard_frame_length_mm}"
        )

    standard_count = math.floor(length_mm / standard_frame_length_mm)
    remainder = length_mm - standard_count * standard_frame_length_mm

    if remainder < tolerance_mm:
        remainder = 0.0
    elif standard_frame_length_mm - remainder < tolerance_mm:
        standard_count += 1
        remainder = 0.0

    return standard_count, remainder


def place_frames(
    segment: Segment,
    standard_frame_length_mm: float = DEFAULT_STANDARD_FRAME_LENGTH_MM,
    tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
) -> List[Frame]:
    """
    Place standard + (optional) custom frames along one segment, from its
    original start toward its end.
    """
    length_mm = segment.geometric_length_mm
    if length_mm <= tolerance_mm:
        raise ValueError(
            f"Segment {segment.segment_id} has non-positive/near-zero "
            f"length ({length_mm}mm); cannot place frames."
        )

    standard_count, remainder = compute_frame_counts(
        length_mm, standard_frame_length_mm, tolerance_mm
    )

    ux = (segment.end.x - segment.start.x) / length_mm
    uy = (segment.end.y - segment.start.y) / length_mm
    uz = (segment.end.z - segment.start.z) / length_mm

    def point_at(distance_mm: float) -> Point3D:
        return Point3D(
            segment.start.x + ux * distance_mm,
            segment.start.y + uy * distance_mm,
            segment.start.z + uz * distance_mm,
        )

    frames: List[Frame] = []
    # Cumulative start computed by direct multiplication (idx * F), not
    # repeated addition, to avoid accumulating floating-point drift over
    # many frames.
    for idx in range(standard_count):
        cumulative_start = idx * standard_frame_length_mm
        cumulative_end = cumulative_start + standard_frame_length_mm
        frames.append(Frame(
            segment_id=segment.segment_id,
            frame_no=idx + 1,
            frame_type="standard",
            length_mm=standard_frame_length_mm,
            start=point_at(cumulative_start),
            end=point_at(cumulative_end),
            cumulative_start_mm=cumulative_start,
            cumulative_end_mm=cumulative_end,
        ))

    if remainder > 0:
        cumulative_start = standard_count * standard_frame_length_mm
        frames.append(Frame(
            segment_id=segment.segment_id,
            frame_no=standard_count + 1,
            frame_type="custom",
            length_mm=remainder,
            start=point_at(cumulative_start),
            end=segment.end,  # exact endpoint, see note below
            cumulative_start_mm=cumulative_start,
            cumulative_end_mm=length_mm,
        ))
    elif frames:
        # No remainder (exact multiple of F): the last standard frame
        # must still end exactly at the segment's actual endpoint, not a
        # recomputed point that could differ from it by floating-point
        # noise -- "ensure the final frame terminates at the actual
        # segment endpoint" (plan, Phase 4).
        frames[-1] = replace(frames[-1], end=segment.end, cumulative_end_mm=length_mm)

    return frames


def build_frame_schedule(
    segments: List[Segment],
    default_standard_frame_length_mm: float = DEFAULT_STANDARD_FRAME_LENGTH_MM,
    tolerance_mm: float = DEFAULT_LENGTH_TOLERANCE_MM,
    reported_value_tolerance_mm: float = DEFAULT_REPORTED_VALUE_TOLERANCE_MM,
) -> Tuple[List[Frame], List[ValidationIssue]]:
    """
    Place frames for every segment independently (no remainder carried
    across segments) and cross-validate against each segment's own
    reported standard-frame-count / custom-frame-length, if present --
    reporting disagreement as a warning rather than overwriting either
    value.

    Each segment uses its own `standard_frame_size_mm` if the workbook
    provided one (confirmed in Phase 1 to be given per-segment, not a
    single workbook-wide constant); `default_standard_frame_length_mm` is
    only a fallback for segments where it's absent.
    """
    all_frames: List[Frame] = []
    issues: List[ValidationIssue] = []

    for segment in segments:
        frame_length = segment.standard_frame_size_mm or default_standard_frame_length_mm
        try:
            frames = place_frames(segment, frame_length, tolerance_mm)
        except ValueError as exc:
            issues.append(ValidationIssue(
                severity="error", segment_id=segment.segment_id, message=str(exc),
            ))
            continue

        all_frames.extend(frames)

        standard_count = sum(1 for f in frames if f.frame_type == "standard")
        custom_frames = [f for f in frames if f.frame_type == "custom"]
        remainder = custom_frames[0].length_mm if custom_frames else 0.0

        if segment.reported_standard_frame_count is not None:
            if segment.reported_standard_frame_count != standard_count:
                issues.append(ValidationIssue(
                    severity="warning",
                    segment_id=segment.segment_id,
                    message=(
                        f"Standard frame count disagreement: workbook reports "
                        f"{segment.reported_standard_frame_count}, calculated "
                        f"{standard_count} (length={segment.geometric_length_mm:.4f}mm, "
                        f"frame size={frame_length}mm)."
                    ),
                ))

        if segment.reported_custom_frame_length_mm is not None:
            diff = abs(segment.reported_custom_frame_length_mm - remainder)
            if diff > reported_value_tolerance_mm:
                issues.append(ValidationIssue(
                    severity="warning",
                    segment_id=segment.segment_id,
                    message=(
                        f"Custom frame length disagreement: workbook reports "
                        f"{segment.reported_custom_frame_length_mm}mm, calculated "
                        f"{remainder:.4f}mm (diff={diff:.4f}mm > tolerance="
                        f"{reported_value_tolerance_mm}mm)."
                    ),
                ))

    return all_frames, issues


def determine_frame_terminations(frames: List[Frame]) -> Dict[Tuple[str, str], str]:
    """
    For each (segment_id, which_end) pair, the frame_type ("standard" or
    "custom") of the frame touching that end -- the segment's first frame
    for "start", its last frame for "end". Used by Phase 3 (corners.py) to
    fill in the plan's corner cases G/H ("standard/custom frame ends at
    the junction") now that frame sequences exist.
    """
    frames_by_segment: Dict[str, List[Frame]] = {}
    for f in frames:
        frames_by_segment.setdefault(f.segment_id, []).append(f)

    result: Dict[Tuple[str, str], str] = {}
    for seg_id, seg_frames in frames_by_segment.items():
        seg_frames.sort(key=lambda f: f.frame_no)
        result[(seg_id, "start")] = seg_frames[0].frame_type
        result[(seg_id, "end")] = seg_frames[-1].frame_type
    return result
