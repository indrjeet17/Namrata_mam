"""
Phase 1: dynamic column detection, normalization, and validation for
wall/segment Excel workbooks.

Column names and order are not assumed fixed (confirmed by inspecting the
four sample workbooks -- see PROJECT_PLAN.md: "Standard Frames" vs.
"Standard Frame Count", an optional "Continuity Status" column present in
some files but not others, etc.). This module matches a sheet's actual
header row against a known set of aliases per canonical field, and
reports -- rather than guesses at -- anything it cannot resolve.
"""

import re
from typing import Optional

import openpyxl

from .models import ColumnMapping, LoadResult, Point3D, Segment, ValidationIssue


class ColumnDetectionError(Exception):
    """Raised when a required column cannot be unambiguously identified."""


# A segment cannot be placed without these. Z is intentionally not
# required: a 2D wall layout with no Start/End Z columns defaults Z to
# 0.0 (reported as such, never silently assumed beyond this).
REQUIRED_FIELDS = ("wall_id", "segment_id", "start_x", "start_y", "end_x", "end_y")

# Alias lists are matched against the *normalized* header (lowercase,
# punctuation stripped to spaces, whitespace collapsed -- see
# _normalize_header), so "Length (mm)", "length_mm" and "Length mm" all
# resolve to the same alias "length mm" without needing a separate entry
# for every punctuation variant.
FIELD_ALIASES = {
    "wall_id": ["wall id", "wallid", "wall"],
    "segment_id": ["segment id", "segmentid", "segment"],
    "entity_handle": ["entity handle", "handle"],
    "entity_type": ["entity type", "type"],
    "layer": ["layer"],
    "color": ["color", "colour"],
    "start_x": ["start x", "startx", "x1"],
    "start_y": ["start y", "starty", "y1"],
    "start_z": ["start z", "startz", "z1"],
    "end_x": ["end x", "endx", "x2"],
    "end_y": ["end y", "endy", "y2"],
    "end_z": ["end z", "endz", "z2"],
    "direction": ["direction"],
    "length_mm": ["length mm", "length"],
    "standard_frame_size_mm": [
        "standard frame size mm", "standard frame size", "frame size",
        "standard length",
    ],
    "standard_frame_count": [
        "standard frames", "standard frame count", "standard frame qty",
        "no of standard frames", "number of standard frames",
    ],
    "custom_frame_length_mm": [
        "custom frame mm", "custom frame length", "custom length",
        "custom remainder",
    ],
}

_PUNCTUATION_RE = re.compile(r"[^a-z0-9]+")


def _normalize_header(name) -> str:
    if name is None:
        return ""
    text = str(name).strip().lower().replace("_", " ")
    text = _PUNCTUATION_RE.sub(" ", text)
    return " ".join(text.split())


def detect_columns(headers, overrides: Optional[dict] = None):
    """
    Match a sheet's header row against FIELD_ALIASES.

    headers: raw header cell values (row 1), in column order.
    overrides: optional {canonical_field: header_name}, forcing that field
        to a specific column and bypassing auto-detection/ambiguity checks
        for it. This is the hook for manual correction when automatic
        detection is ambiguous (see PROJECT_PLAN.md Phase 1).

    Returns (mapping, unrecognized_columns, ambiguous_fields):
        mapping: {canonical_field: column_index}
        unrecognized_columns: header names present but not mapped to any
            canonical field
        ambiguous_fields: {canonical_field: [candidate header names]} for
            fields where more than one column matched and no override
            resolved it
    """
    overrides = overrides or {}
    normalized_headers = [_normalize_header(h) for h in headers]

    alias_to_fields = {}
    for field_name, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            alias_to_fields.setdefault(alias, []).append(field_name)

    mapping = {}
    matched_columns = set()

    for field_name, header_name in overrides.items():
        norm = _normalize_header(header_name)
        if norm not in normalized_headers:
            raise ColumnDetectionError(
                f"Override for '{field_name}' names column {header_name!r}, "
                f"which is not present in this sheet's header row: {headers!r}"
            )
        idx = normalized_headers.index(norm)
        mapping[field_name] = idx
        matched_columns.add(idx)

    candidates_by_field = {}
    for idx, norm in enumerate(normalized_headers):
        if idx in matched_columns or not norm:
            continue
        for field_name in alias_to_fields.get(norm, ()):
            if field_name in mapping:
                continue
            candidates_by_field.setdefault(field_name, []).append(idx)

    ambiguous_fields = {}
    for field_name, idxs in candidates_by_field.items():
        if len(idxs) == 1:
            mapping[field_name] = idxs[0]
        else:
            ambiguous_fields[field_name] = [headers[i] for i in idxs]

    mapped_columns = set(mapping.values())
    unrecognized_columns = [
        headers[idx]
        for idx, norm in enumerate(normalized_headers)
        if idx not in mapped_columns and norm
    ]

    return mapping, unrecognized_columns, ambiguous_fields


def _as_optional_str(value):
    return None if value is None else str(value)


def _as_optional_float(value):
    return float(value) if isinstance(value, (int, float)) else None


def load_segments(
    path,
    sheet_name: str = "Segment Report",
    column_overrides: Optional[dict] = None,
    length_tolerance_mm: float = 1e-3,
) -> LoadResult:
    """
    Load and normalize segment geometry from one worksheet.

    Raises ColumnDetectionError if a required field (wall_id, segment_id,
    start/end X/Y) cannot be unambiguously mapped -- pass column_overrides
    to resolve ambiguity or name a differently-titled column instead of
    guessing.

    Per-row problems (missing coordinates, non-numeric values, zero-length
    segments, reported-vs-geometric length disagreement) are collected as
    ValidationIssue entries on the result rather than raised, so one bad
    row doesn't block loading the rest of a valid sheet.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise ColumnDetectionError(
            f"Sheet {sheet_name!r} not found. Available sheets: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ColumnDetectionError(f"Sheet {sheet_name!r} is empty.")

    headers = list(rows[0])
    mapping, unrecognized_columns, ambiguous_fields = detect_columns(
        headers, overrides=column_overrides
    )

    missing_required = [f for f in REQUIRED_FIELDS if f not in mapping]
    ambiguous_required = [f for f in REQUIRED_FIELDS if f in ambiguous_fields]
    if missing_required or ambiguous_required:
        problems = []
        if missing_required:
            problems.append(f"missing required columns: {missing_required}")
        if ambiguous_required:
            details = {f: ambiguous_fields[f] for f in ambiguous_required}
            problems.append(f"ambiguous required columns: {details}")
        raise ColumnDetectionError(
            "Cannot load segments -- " + "; ".join(problems)
            + ". Pass column_overrides to resolve."
        )

    issues = []
    for field_name, candidates in ambiguous_fields.items():
        if field_name not in REQUIRED_FIELDS:
            issues.append(ValidationIssue(
                severity="warning",
                segment_id=None,
                message=(
                    f"Optional column '{field_name}' is ambiguous "
                    f"(candidates: {candidates}); left unmapped. Pass "
                    f"column_overrides to resolve if this data is needed."
                ),
            ))

    def cell(row, field_name):
        idx = mapping.get(field_name)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    segments = []
    for row_number, row in enumerate(rows[1:], start=2):
        if row is None or all(v is None for v in row):
            continue  # skip fully blank rows

        wall_id = cell(row, "wall_id")
        segment_id = cell(row, "segment_id")
        sx, sy = cell(row, "start_x"), cell(row, "start_y")
        ex, ey = cell(row, "end_x"), cell(row, "end_y")

        row_errors = []
        if wall_id is None:
            row_errors.append("missing Wall ID")
        if segment_id is None:
            row_errors.append("missing Segment ID")
        for label, value in (
            ("Start X", sx), ("Start Y", sy), ("End X", ex), ("End Y", ey)
        ):
            if value is None:
                row_errors.append(f"missing {label}")
            elif not isinstance(value, (int, float)):
                row_errors.append(f"{label} is not numeric: {value!r}")

        if row_errors:
            issues.append(ValidationIssue(
                severity="error",
                segment_id=_as_optional_str(segment_id),
                message=f"Row {row_number}: " + "; ".join(row_errors),
            ))
            continue

        sz = _as_optional_float(cell(row, "start_z")) or 0.0
        ez = _as_optional_float(cell(row, "end_z")) or 0.0

        reported_length = _as_optional_float(cell(row, "length_mm"))
        standard_frame_size = _as_optional_float(cell(row, "standard_frame_size_mm"))
        reported_custom_len = _as_optional_float(cell(row, "custom_frame_length_mm"))

        raw_std_count = cell(row, "standard_frame_count")
        reported_std_count = (
            int(raw_std_count) if isinstance(raw_std_count, (int, float)) else None
        )

        segment = Segment(
            wall_id=str(wall_id),
            segment_id=str(segment_id),
            start=Point3D(float(sx), float(sy), sz),
            end=Point3D(float(ex), float(ey), ez),
            entity_handle=_as_optional_str(cell(row, "entity_handle")),
            entity_type=_as_optional_str(cell(row, "entity_type")),
            layer=_as_optional_str(cell(row, "layer")),
            color=cell(row, "color"),
            direction=_as_optional_str(cell(row, "direction")),
            reported_length_mm=reported_length,
            standard_frame_size_mm=standard_frame_size,
            reported_standard_frame_count=reported_std_count,
            reported_custom_frame_length_mm=reported_custom_len,
            source_row_number=row_number,
        )

        if segment.geometric_length_mm <= 0:
            issues.append(ValidationIssue(
                severity="error",
                segment_id=segment.segment_id,
                message=f"Row {row_number}: zero-length segment (start == end).",
            ))
            continue

        if reported_length is not None:
            diff = abs(segment.geometric_length_mm - reported_length)
            if diff > length_tolerance_mm:
                issues.append(ValidationIssue(
                    severity="warning",
                    segment_id=segment.segment_id,
                    message=(
                        f"Row {row_number}: reported Length (mm)="
                        f"{reported_length:.4f} disagrees with geometric "
                        f"length={segment.geometric_length_mm:.4f} "
                        f"(diff={diff:.4f} > tolerance={length_tolerance_mm})."
                    ),
                ))

        segments.append(segment)

    return LoadResult(
        sheet_name=sheet_name,
        column_mapping=ColumnMapping(
            mapping={f: headers[i] for f, i in mapping.items()}
        ),
        segments=segments,
        issues=issues,
        unrecognized_columns=unrecognized_columns,
    )
