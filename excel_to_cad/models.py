"""
Normalized data structures produced by the Phase 1 loader.

These are the common internal representation every later phase (geometry
reconstruction, corner connectivity, frame sequencing, DXF generation)
builds on, regardless of which workbook or column layout it came from.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Point3D:
    x: float
    y: float
    z: float = 0.0

    def as_tuple(self):
        return (self.x, self.y, self.z)

    def distance_to(self, other: "Point3D") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )


@dataclass
class Segment:
    """One wall/frame segment, exactly as given (no straightening, no
    reordering, no invented values)."""

    wall_id: str
    segment_id: str
    start: Point3D
    end: Point3D

    entity_handle: Optional[str] = None
    entity_type: Optional[str] = None
    layer: Optional[str] = None
    color: Optional[object] = None
    direction: Optional[str] = None

    # As reported in the workbook -- kept separate from anything this
    # application calculates itself, so disagreements can be surfaced
    # (see Phase 1/4 validation) instead of silently overwritten.
    reported_length_mm: Optional[float] = None
    standard_frame_size_mm: Optional[float] = None
    reported_standard_frame_count: Optional[int] = None
    reported_custom_frame_length_mm: Optional[float] = None

    source_row_number: int = -1

    @property
    def geometric_length_mm(self) -> float:
        return self.start.distance_to(self.end)


@dataclass
class ColumnMapping:
    """canonical_field -> actual header name found in the sheet."""

    mapping: dict = field(default_factory=dict)


@dataclass
class ValidationIssue:
    severity: str  # "error" or "warning"
    segment_id: Optional[str]
    message: str


@dataclass
class LoadResult:
    sheet_name: str
    column_mapping: ColumnMapping
    segments: list  # list[Segment]
    issues: list  # list[ValidationIssue]
    unrecognized_columns: list  # list[str], header names present but unmapped

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self):
        return [i for i in self.issues if i.severity == "warning"]
