"""
SOLIDWORKS 2026 - Native 2D Sketch Reconstruction
Creates native sketch entities through SolidWorks COM automation.
No DXF import is used.

Source coordinates are treated as millimeters and converted to meters.
"""

import math
import os
import glob
import traceback

import pythoncom
import win32com.client


# ============================================================
# CONFIGURATION
# ============================================================

SCALE_TO_METERS = 0.001
SKETCH_Z = 0.0
SKETCH_NAME = "ReconstructedSketch"

# True: remove exact duplicate line segments, regardless of direction.
REMOVE_DUPLICATE_LINES = True

# A true COM "Nothing" (null IDispatch). Plain Python None causes
# "Type mismatch" for object parameters such as SelectByID2's Callout.
NOTHING = win32com.client.VARIANT(pythoncom.VT_DISPATCH, None)


# ============================================================
# 1. LINE ENTITIES
# Format: (x1, y1, x2, y2), source units in millimeters
# ============================================================

LINES = [
    (40.0714, 21.2142, 1160.0714, 21.2142),
    (40.0714, 18.2142, 1160.0714, 18.2142),
    (40.0714, 7.3642, 1160.0714, 7.3642),
    (40.0714, 6.9142, 1160.0714, 6.9142),
    (40.0714, 6.3142, 1160.0714, 6.3142),
    (40.0714, 5.6420, 1160.0714, 5.6420),
    (40.0714, 2.4220, 1160.0714, 2.4220),
    (40.0714, 2.0008, 1160.0714, 2.0008),
    (40.0714, 1.5940, 1160.0714, 1.5940),
    (40.0714, 0.8344, 1160.0714, 0.8344),
    (40.0714, 0.4276, 1160.0714, 0.4276),
    (40.0714, 0.0064, 1160.0714, 0.0064),
    (40.0714, -3.2136, 1160.0714, -3.2136),
    (40.0714, -3.8858, 1160.0714, -3.8858),
    (40.0714, -4.4858, 1160.0714, -4.4858),
    (40.0714, -4.9358, 1160.0714, -4.9358),
    (40.0714, -15.7858, 1160.0714, -15.7858),
    (40.0714, -18.7858, 1160.0714, -18.7858),

    (35.0714, 86.2142, 5.0714, 86.2142),
    (5.0714, -83.7858, 35.0714, -83.7858),
    (40.0714, 41.2142, 0.0714, 41.2142),
    (40.0714, 31.2142, 0.0714, 31.2142),
    (0.0714, -28.7858, 40.0714, -28.7858),
    (0.0714, -38.7858, 40.0714, -38.7858),

    (3.0514, 21.2142, 37.0914, 21.2142),
    (37.0914, -18.7858, 3.0514, -18.7858),
    (40.0714, 18.2342, 40.0714, -15.8058),

    (40.0714, 21.2142, 37.0914, 21.2142),
    (40.0714, 18.2142, 40.0714, 21.2142),
    (40.0714, -18.7858, 40.0714, -15.7858),
    (37.0914, -18.7858, 40.0714, -18.7858),
    (0.0714, -18.7858, 3.0514, -18.7858),
    (3.0514, 21.2142, 0.0714, 21.2142),

    (0.0714, 41.2142, 0.0714, 81.2142),
    (0.0714, 31.2142, 0.0714, 41.2142),
    (0.0714, 21.2142, 0.0714, 31.2142),
    (40.0714, 41.2142, 40.0714, 81.2142),
    (40.0714, 31.2142, 40.0714, 41.2142),
    (40.0714, 21.2142, 40.0714, 31.2142),

    (0.0714, -18.7858, 0.0714, -28.7858),
    (0.0714, -28.7858, 0.0714, -38.7858),
    (0.0714, -38.7858, 0.0714, -78.7858),
    (40.0714, -18.7858, 40.0714, -28.7858),
    (40.0714, -28.7858, 40.0714, -38.7858),
    (40.0714, -38.7858, 40.0714, -78.7858),

    (1195.0714, 86.2142, 1165.0714, 86.2142),
    (1200.0714, 41.2142, 1160.0714, 41.2142),
    (1200.0714, 31.2142, 1160.0714, 31.2142),

    (1160.0714, -28.7858, 1200.0714, -28.7858),
    (1160.0714, -38.7858, 1200.0714, -38.7858),
    (1165.0714, -83.7858, 1195.0714, -83.7858),

    (1160.0714, -38.7858, 1160.0714, -78.7858),
    (1160.0714, -28.7858, 1160.0714, -38.7858),
    (1160.0714, -18.7858, 1160.0714, -28.7858),
    (1160.0714, 21.2142, 1160.0714, 31.2142),
    (1160.0714, 31.2142, 1160.0714, 41.2142),
    (1160.0714, 41.2142, 1160.0714, 81.2142),
    (1200.0714, 41.2142, 1200.0714, 81.2142),
    (1200.0714, 31.2142, 1200.0714, 41.2142),
    (1200.0714, 21.2142, 1200.0714, 31.2142),

    (1163.0514, 21.2142, 1197.0914, 21.2142),
    (1160.0714, 18.2142, 1160.0714, 21.2142),
    (1163.0514, 21.2142, 1160.0714, 21.2142),
    (1200.0714, 21.2142, 1197.0914, 21.2142),

    (1197.0914, -18.7858, 1163.0514, -18.7858),
    (1160.0714, -18.7858, 1163.0514, -18.7858),
    (1197.0914, -18.7858, 1200.0714, -18.7858),
    (1160.0714, -18.7858, 1160.0714, -15.7858),
    (1160.0714, -15.8058, 1160.0714, 18.2342),
]


# ============================================================
# 2. OPEN POLYLINES
# Each consecutive vertex pair becomes one sketch line.
# ============================================================

POLYLINES = [
    [
        (0.0714, 21.2142),
        (0.0714, -18.7858),
    ],
    [
        (1200.0714, 21.2142),
        (1200.0714, -78.7858),
    ],
]


# ============================================================
# 3. ARC ENTITIES
# Format: (center_x, center_y, radius, start_angle, end_angle)
# Angles are in degrees, arcs run counterclockwise start -> end.
# ============================================================

ARCS = [
    (3.0514, 18.2342, 2.98, 90, 180),
    (37.0914, 18.2342, 2.98, 0, 90),

    (37.0914, -15.8058, 2.98, 270, 360),
    (3.0514, -15.8058, 2.98, 180, 270),

    (5.0714, 81.2142, 5.00, 90, 180),
    (35.0714, 81.2142, 5.00, 0, 90),

    (35.0714, -78.7858, 5.00, 270, 360),
    (5.0714, -78.7858, 5.00, 180, 270),

    (1163.0514, -15.8058, 2.98, 180, 270),
    (1197.0914, -15.8058, 2.98, 270, 360),

    (1197.0914, 18.2342, 2.98, 0, 90),
    (1163.0514, 18.2342, 2.98, 90, 180),

    (1165.0714, -78.7858, 5.00, 180, 270),
    (1195.0714, -78.7858, 5.00, 270, 360),

    (1165.0714, 81.2142, 5.00, 90, 180),
    (1195.0714, 81.2142, 5.00, 0, 90),
]


# ============================================================
# 4. CIRCLE ENTITIES
# Format: (center_x, center_y, radius)
# ============================================================

CIRCLES = [
    (20.0714, 66.2142, 7.0),
    (20.0714, -63.7858, 7.0),
    (1180.0714, 66.2142, 7.0),
    (1180.0714, -63.7858, 7.0),
]


# ============================================================
# 5. HORIZONTAL DIMENSIONS (from the AutoCAD DIMENSION entity)
# Format: (point1, point2, dimension_line_position), millimeters
# AutoCAD: ext points (0.0714,-58.7858) and (1200.0714,-58.7858),
#          dimension line at Y = -108.1387, value = 1200
# ============================================================

DIMENSIONS = [
    (
        (0.0714, -58.7858),
        (1200.0714, -58.7858),
        (600.0714, -108.1387),
    ),
]

# Draw the dimension as plain sketch lines (dimension line + end ticks).
# This always works and looks like the AutoCAD drawing.
DRAW_DIMENSION_LINES = True
# Extension lines run from this Y down to the dimension line, continuing
# the outer plate edges (the plate edges end at Y = -78.7858).
DIMENSION_EXTENSION_START_Y = -78.7858
DIMENSION_ARROW_LENGTH = 2.5        # mm (ISO-25 arrow size)
DIMENSION_ARROW_HALF_WIDTH = 0.5    # mm

# Also try to add a real SolidWorks driving dimension (can fail through
# COM on some installs, so it is off by default).
ADD_NATIVE_DIMENSION = False
NATIVE_DIMENSIONS = DIMENSIONS if ADD_NATIVE_DIMENSION else []


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def com_call(obj, name, *args):
    """
    Call a COM method that takes no (or some) arguments.
    With pywin32 late binding, some zero-argument methods are exposed as
    properties, so obj.Method() fails with "'bool' object is not callable".
    This works either way.
    """
    attr = getattr(obj, name)
    if callable(attr):
        return attr(*args)
    return attr


def to_m(value):
    """Convert source drawing units to SolidWorks meters."""
    return float(value) * SCALE_TO_METERS


def point_key(x, y, precision=6):
    """Return a stable point key for duplicate detection."""
    return round(float(x), precision), round(float(y), precision)


def line_key(line):
    """Treat a line and its reversed direction as the same geometry."""
    x1, y1, x2, y2 = line
    return tuple(sorted((point_key(x1, y1), point_key(x2, y2))))


def remove_duplicate_lines(lines):
    """Remove exact duplicate segments without changing other geometry."""
    unique = []
    seen = set()

    for line in lines:
        if len(line) != 4:
            raise ValueError(f"Invalid line definition: {line}")

        x1, y1, x2, y2 = line

        if point_key(x1, y1) == point_key(x2, y2):
            print(f"Skipping zero-length line: {line}")
            continue

        key = line_key(line)
        if key in seen:
            print(f"Skipping duplicate line: {line}")
            continue

        seen.add(key)
        unique.append(line)

    return unique


def merge_overlapping_lines(lines, tol=1e-6):
    """
    Merge horizontal/vertical segments that overlap on the same axis line.
    Segments that only touch end-to-end are kept separate (so the vertices
    where other lines meet are preserved). Other angles pass through as-is.
    """
    groups = {}
    other = []

    for x1, y1, x2, y2 in lines:
        if abs(y1 - y2) < tol:                      # horizontal
            key = ("H", round(y1, 6))
            lo, hi = sorted((x1, x2))
        elif abs(x1 - x2) < tol:                    # vertical
            key = ("V", round(x1, 6))
            lo, hi = sorted((y1, y2))
        else:
            other.append((x1, y1, x2, y2))
            continue
        groups.setdefault(key, []).append((lo, hi))

    merged = []
    for (kind, fixed), spans in groups.items():
        spans.sort()
        cur_lo, cur_hi = spans[0]
        for lo, hi in spans[1:]:
            if lo < cur_hi - tol:                   # true overlap -> merge
                cur_hi = max(cur_hi, hi)
            else:                                   # gap or touching -> new
                merged.append((kind, fixed, cur_lo, cur_hi))
                cur_lo, cur_hi = lo, hi
        merged.append((kind, fixed, cur_lo, cur_hi))

    result = []
    for kind, fixed, lo, hi in merged:
        if kind == "H":
            result.append((lo, fixed, hi, fixed))
        else:
            result.append((fixed, lo, fixed, hi))
    result.extend(other)

    removed = len(lines) - len(result)
    if removed:
        print(f"Merged overlapping lines: {len(lines)} -> {len(result)}")
    return result


def get_dimension_line_segments():
    """
    Dimension drawn as plain lines, like the AutoCAD view:
    two extension lines, the dimension line, and an arrowhead at each end.
    """
    segments = []
    a = DIMENSION_ARROW_LENGTH
    w = DIMENSION_ARROW_HALF_WIDTH

    for p1, p2, pos in DIMENSIONS:
        y = pos[1]
        x_left, x_right = sorted((p1[0], p2[0]))

        # Extension lines (from the part down to the dimension line).
        segments.append((x_left, DIMENSION_EXTENSION_START_Y, x_left, y))
        segments.append((x_right, DIMENSION_EXTENSION_START_Y, x_right, y))

        # Dimension line.
        segments.append((x_left, y, x_right, y))

        # Left arrowhead (tip points left).
        segments.append((x_left, y, x_left + a, y + w))
        segments.append((x_left, y, x_left + a, y - w))
        segments.append((x_left + a, y + w, x_left + a, y - w))

        # Right arrowhead (tip points right).
        segments.append((x_right, y, x_right - a, y + w))
        segments.append((x_right, y, x_right - a, y - w))
        segments.append((x_right - a, y + w, x_right - a, y - w))

    return segments


def get_all_line_segments():
    """Combine explicit lines and open-polyline segments."""
    segments = list(LINES)

    for vertices in POLYLINES:
        if len(vertices) < 2:
            continue
        for i in range(len(vertices) - 1):
            x1, y1 = vertices[i]
            x2, y2 = vertices[i + 1]
            segments.append((x1, y1, x2, y2))

    if REMOVE_DUPLICATE_LINES:
        segments = remove_duplicate_lines(segments)
        segments = merge_overlapping_lines(segments)

    if DRAW_DIMENSION_LINES:
        segments.extend(get_dimension_line_segments())

    return segments


def create_line(sketch_manager, x1, y1, x2, y2):
    """Create a native SolidWorks sketch line."""
    if point_key(x1, y1) == point_key(x2, y2):
        return None

    return sketch_manager.CreateLine(
        to_m(x1), to_m(y1), SKETCH_Z,
        to_m(x2), to_m(y2), SKETCH_Z,
    )


def create_arc(sketch_manager, cx, cy, radius, start_angle, end_angle):
    """Create a native circular sketch arc (counterclockwise)."""
    if radius <= 0:
        raise ValueError(f"Arc radius must be positive: {radius}")

    start_rad = math.radians(start_angle)
    end_rad = math.radians(end_angle)

    start_x = cx + radius * math.cos(start_rad)
    start_y = cy + radius * math.sin(start_rad)
    end_x = cx + radius * math.cos(end_rad)
    end_y = cy + radius * math.sin(end_rad)

    # Direction: 1 = counterclockwise, -1 = clockwise.
    return sketch_manager.CreateArc(
        to_m(cx), to_m(cy), SKETCH_Z,
        to_m(start_x), to_m(start_y), SKETCH_Z,
        to_m(end_x), to_m(end_y), SKETCH_Z,
        1,
    )


def create_circle(sketch_manager, cx, cy, radius):
    """Create a native SolidWorks sketch circle."""
    if radius <= 0:
        raise ValueError(f"Circle radius must be positive: {radius}")

    return sketch_manager.CreateCircle(
        to_m(cx), to_m(cy), SKETCH_Z,
        to_m(cx + radius), to_m(cy), SKETCH_Z,
    )


def create_dimension_points(sketch_manager, p1, p2):
    """Create the two sketch points the dimension will measure between."""
    pt1 = sketch_manager.CreatePoint(to_m(p1[0]), to_m(p1[1]), SKETCH_Z)
    pt2 = sketch_manager.CreatePoint(to_m(p2[0]), to_m(p2[1]), SKETCH_Z)
    if pt1 is None or pt2 is None:
        raise RuntimeError("Could not create dimension reference points.")
    return pt1, pt2


def select_dimension_points(model, pt1, pt2, p1, p2):
    """Select the two sketch points (by coordinates first, then by object)."""
    model.ClearSelection2(True)

    # Method A: select by coordinates (same call that already works for
    # the Front Plane).
    try:
        ok1 = model.Extension.SelectByID2(
            "", "SKETCHPOINT", to_m(p1[0]), to_m(p1[1]), SKETCH_Z,
            False, 0, NOTHING, 0,
        )
        ok2 = model.Extension.SelectByID2(
            "", "SKETCHPOINT", to_m(p2[0]), to_m(p2[1]), SKETCH_Z,
            True, 0, NOTHING, 0,
        )
        if ok1 and ok2:
            return
        print("  Select by coordinates did not select both points.")
    except Exception as exc:
        print(f"  Select by coordinates failed: {exc}")

    # Method B: select the point objects directly.
    model.ClearSelection2(True)
    try:
        sel_data = model.SelectionManager.CreateSelectData()
    except Exception as exc:
        print(f"  CreateSelectData failed: {exc}")
        sel_data = NOTHING

    ok1 = pt1.Select4(False, sel_data)
    ok2 = pt2.Select4(True, sel_data)
    if not (ok1 and ok2):
        raise RuntimeError("Could not select the dimension points.")


def add_horizontal_dimension(model, pt1, pt2, p1, p2, line_pos):
    """
    Select two sketch points and add a native SolidWorks dimension.
    line_pos is (x, y) in source units: where the dimension line sits.
    """
    select_dimension_points(model, pt1, pt2, p1, p2)

    x, y, z = to_m(line_pos[0]), to_m(line_pos[1]), SKETCH_Z
    dim = None
    last_error = None

    for method_name in ("AddHorizontalDimension2", "AddDimension2"):
        try:
            dim = getattr(model, method_name)(x, y, z)
            if dim is not None:
                break
        except Exception as exc:
            last_error = exc
            print(f"  {method_name} failed: {exc}")

    model.ClearSelection2(True)

    if dim is None:
        raise RuntimeError(f"No dimension created. Last error: {last_error}")
    return dim


def find_part_template(sw_app):
    """
    Locate a SolidWorks part template.

    1. The default part template configured in SolidWorks.
    2. Common installation folders.
    3. A manual file picker.
    """
    # swDefaultTemplatePart = 8
    try:
        default_template = sw_app.GetUserPreferenceStringValue(8)
        if default_template and os.path.isfile(default_template):
            return default_template
    except Exception:
        pass

    candidates = [
        r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2026\templates\Part.prtdot",
        r"C:\ProgramData\SolidWorks\SOLIDWORKS 2026\templates\Part.prtdot",
        r"C:\ProgramData\SOLIDWORKS\templates\Part.prtdot",
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    patterns = [
        r"C:\ProgramData\SOLIDWORKS\*\templates\Part.prtdot",
        r"C:\ProgramData\SolidWorks\*\templates\Part.prtdot",
        r"C:\ProgramData\SOLIDWORKS\*\lang\*\Part.prtdot",
    ]
    for pattern in patterns:
        for candidate in glob.glob(pattern):
            if os.path.isfile(candidate):
                return candidate

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        template_path = filedialog.askopenfilename(
            title="Select the SolidWorks Part template",
            filetypes=[
                ("SolidWorks Part Template", "*.prtdot"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()

        if template_path and os.path.isfile(template_path):
            return template_path
    except Exception as exc:
        print(f"Template selection dialog could not open: {exc}")

    raise FileNotFoundError(
        "Could not find a SolidWorks part template (.prtdot). "
        "In SolidWorks, open Tools > Options > Default Templates "
        "to check your configured part template."
    )


def connect_to_solidworks():
    """Connect to SolidWorks if running, otherwise launch it."""
    try:
        sw_app = win32com.client.GetActiveObject("SldWorks.Application")
        print("Connected to an existing SolidWorks instance.")
    except Exception:
        sw_app = win32com.client.Dispatch("SldWorks.Application")
        print("Started a SolidWorks instance.")

    sw_app.Visible = True
    return sw_app


def select_front_plane(model):
    """Select the Front Plane (works with renamed / localized templates)."""
    model.ClearSelection2(True)

    # 1. Try by name. NOTHING (null dispatch) is required for Callout.
    for name in ("Front Plane", "Front", "Plane1"):
        try:
            if model.Extension.SelectByID2(
                name, "PLANE", 0.0, 0.0, 0.0, False, 0, NOTHING, 0
            ):
                return True
        except Exception:
            pass

    # 2. Fallback: first reference plane in the tree is Front
    #    in default SolidWorks templates.
    try:
        feat = com_call(model, "FirstFeature")
        while feat:
            if com_call(feat, "GetTypeName2") == "RefPlane":
                if feat.Select2(False, 0):
                    return True
                break
            feat = com_call(feat, "GetNextFeature")
    except Exception:
        pass

    return False


# ============================================================
# MAIN AUTOMATION
# ============================================================

def main():
    model = None
    sketch_manager = None
    sketch_started = False

    try:
        print("=" * 60)
        print("SOLIDWORKS 2026 - NATIVE SKETCH RECONSTRUCTION")
        print("=" * 60)

        # 1. Connect to SolidWorks.
        sw_app = connect_to_solidworks()

        # 2. Find a valid part template.
        template_path = find_part_template(sw_app)
        print(f"Using template: {template_path}")

        # 3. Create one new Part document.
        model = sw_app.NewDocument(template_path, 0, 0.0, 0.0)

        if model is None:
            raise RuntimeError(
                "SolidWorks could not create the Part document. "
                "Verify that the selected template is valid."
            )

        # 4. Select the Front Plane.
        if not select_front_plane(model):
            raise RuntimeError(
                "Could not select the Front Plane. "
                "Check the plane name in your SolidWorks installation."
            )

        # 5. Start a new 2D sketch.
        sketch_manager = model.SketchManager
        sketch_manager.InsertSketch(True)
        sketch_started = True

        # Create geometry exactly as defined: no auto-relations or
        # inference, and much faster for many entities.
        sketch_manager.AddToDB = True

        line_segments = get_all_line_segments()

        line_count = 0
        arc_count = 0
        circle_count = 0
        dimension_count = 0
        dimension_points = []
        errors = []

        # 6. Lines.
        print(f"\nCreating {len(line_segments)} line segments...")
        for index, line in enumerate(line_segments, start=1):
            try:
                if create_line(sketch_manager, *line) is not None:
                    line_count += 1
            except Exception as exc:
                errors.append(f"Line {index} {line}: {exc}")
                print(f"ERROR creating line {index}: {exc}")

        # 7. Arcs.
        print(f"\nCreating {len(ARCS)} arcs...")
        for index, arc in enumerate(ARCS, start=1):
            try:
                if create_arc(sketch_manager, *arc) is not None:
                    arc_count += 1
            except Exception as exc:
                errors.append(f"Arc {index} {arc}: {exc}")
                print(f"ERROR creating arc {index}: {exc}")

        # 8. Circles.
        print(f"\nCreating {len(CIRCLES)} circles...")
        for index, circle in enumerate(CIRCLES, start=1):
            try:
                if create_circle(sketch_manager, *circle) is not None:
                    circle_count += 1
            except Exception as exc:
                errors.append(f"Circle {index} {circle}: {exc}")
                print(f"ERROR creating circle {index}: {exc}")

        # 8b. Points the dimensions will attach to.
        for index, (p1, p2, pos) in enumerate(NATIVE_DIMENSIONS, start=1):
            try:
                pt1, pt2 = create_dimension_points(sketch_manager, p1, p2)
                dimension_points.append((pt1, pt2, p1, p2, pos))
            except Exception as exc:
                errors.append(f"Dimension points {index}: {exc}")
                print(f"ERROR creating dimension points {index}: {exc}")

        sketch_manager.AddToDB = False

        # 8c. Add the dimensions (must happen while the sketch is open).
        # Turn off the "Modify" popup so the script does not stall.
        prev_input_dim = None
        try:
            # swInputDimValOnCreate = 10
            prev_input_dim = sw_app.GetUserPreferenceToggle(10)
            sw_app.SetUserPreferenceToggle(10, False)
        except Exception:
            pass

        for index, (pt1, pt2, p1, p2, pos) in enumerate(dimension_points, start=1):
            try:
                add_horizontal_dimension(model, pt1, pt2, p1, p2, pos)
                dimension_count += 1
            except Exception as exc:
                errors.append(f"Dimension {index}: {exc}")
                print(f"ERROR creating dimension {index}: {exc}")

        if prev_input_dim is not None:
            try:
                sw_app.SetUserPreferenceToggle(10, prev_input_dim)
            except Exception:
                pass

        # 9. Exit sketch mode.
        sketch_manager.InsertSketch(True)
        sketch_started = False

        # 10. Rename the sketch (the most recent feature).
        try:
            sketch_feature = model.FeatureByPositionReverse(0)
            if sketch_feature is not None:
                sketch_feature.Name = SKETCH_NAME
        except Exception as exc:
            print(f"Could not rename sketch: {exc}")

        # 11. Rebuild and zoom to fit.
        com_call(model, "EditRebuild3")
        com_call(model, "ViewZoomtofit2")

        total_created = line_count + arc_count + circle_count + dimension_count

        print("\n" + "=" * 60)
        print("SKETCH CREATION SUMMARY")
        print("=" * 60)
        print(f"Lines created:   {line_count}")
        print(f"Arcs created:    {arc_count}")
        print(f"Circles created: {circle_count}")
        print(f"Dimensions:      {dimension_count}")
        print("-" * 60)
        print(f"Total entities:  {total_created}")
        print(f"Scale factor:    {SCALE_TO_METERS}")
        print(f"Errors:          {len(errors)}")
        print("=" * 60)

        if errors:
            print("\nSome entities could not be created:")
            for error in errors:
                print(f"- {error}")

        print(
            "\nReview the sketch in SolidWorks. "
            "Use File > Save As to save the part."
        )

    except Exception as exc:
        print("\nFATAL ERROR")
        print("-" * 60)
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()

        # Leave sketch mode cleanly if an error happened mid-sketch.
        if sketch_manager is not None:
            try:
                sketch_manager.AddToDB = False
            except Exception:
                pass
            if sketch_started:
                try:
                    sketch_manager.InsertSketch(True)
                except Exception:
                    pass

        print(
            "\nCheck that SolidWorks 2026 is installed, "
            "the part template is valid, and pywin32 is installed."
        )


if __name__ == "__main__":
    main()