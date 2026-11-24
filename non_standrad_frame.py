"""
SOLIDWORKS 2026 - Native 2D Sketch Generator for NON-STANDARD EC-fence frames
(single self-contained file, same style as recreate_drawing.py)

Usage:
    python generate_fence_frame.py 550        # frame length 550 mm
    python generate_fence_frame.py            # asks for the length

Both end brackets (flange, corner fillets, 7mm bolt holes) are fixed
hardware and never change. Only the overall frame length changes: the
fin/rail lines and the overall dimension stretch or shrink to fit.
1200 mm reproduces the standard frame exactly.

No DXF import is used; native sketch entities are created through
SolidWorks COM automation. Source coordinates are millimeters.
"""

import math
import os
import glob
import sys
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

# Dimension drawn as plain sketch lines (dimension line + arrowheads).
DRAW_DIMENSION_LINES = True
DIMENSION_EXTENSION_START_Y = -78.7858
DIMENSION_ARROW_LENGTH = 2.5
DIMENSION_ARROW_HALF_WIDTH = 0.5

# Real SolidWorks driving dimension (can fail through COM; off by default).
ADD_NATIVE_DIMENSION = False


# ============================================================
# FRAME GEOMETRY (fixed hardware + length-dependent parts)
# ============================================================

OFFSET = 0.0714              # Drawing-origin offset carried over from DWG.
BRACKET_WIDTH = 40.0         # Fixed width of each end bracket.
STANDARD_LENGTH_MM = 1200.0
MIN_LENGTH_MM = 2 * BRACKET_WIDTH + 1.0   # brackets must not touch

# LEFT end bracket template (coordinates already include OFFSET).
LEFT_BRACKET_LINES = [
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
]

# (cx, cy, radius, start_angle_deg, end_angle_deg), counterclockwise
LEFT_BRACKET_ARCS = [
    (3.0514, 18.2342, 2.98, 90, 180),
    (37.0914, 18.2342, 2.98, 0, 90),
    (37.0914, -15.8058, 2.98, 270, 360),
    (3.0514, -15.8058, 2.98, 180, 270),
    (5.0714, 81.2142, 5.00, 90, 180),
    (35.0714, 81.2142, 5.00, 0, 90),
    (35.0714, -78.7858, 5.00, 270, 360),
    (5.0714, -78.7858, 5.00, 180, 270),
]

LEFT_BRACKET_CIRCLES = [
    (20.0714, 66.2142, 7.0),
    (20.0714, -63.7858, 7.0),
]

# Y positions of the 18 fin/rail lines between the brackets.
FIN_LINE_YS = [
    21.2142, 18.2142, 7.3642, 6.9142, 6.3142, 5.6420,
    2.4220, 2.0008, 1.5940, 0.8344, 0.4276, 0.0064,
    -3.2136, -3.8858, -4.4858, -4.9358, -15.7858, -18.7858,
]

BRACKET_INNER_X = BRACKET_WIDTH + OFFSET   # 40.0714
BRACKET_OUTER_X = OFFSET                   # 0.0714

LEFT_POLYLINE = [(BRACKET_OUTER_X, 21.2142), (BRACKET_OUTER_X, -18.7858)]
RIGHT_POLYLINE_Y_SPAN = (21.2142, -78.7858)

DIMENSION_Y = -58.7858
DIMENSION_LINE_Y = -108.1387


def mirror_x(x, length_mm):
    """Reflect a left-bracket X coordinate to the right-hand bracket."""
    return (length_mm + 2 * OFFSET) - x


def mirror_arc(arc, length_mm):
    """Mirror an arc about the frame's vertical centerline."""
    cx, cy, r, start, end = arc
    new_start = (180 - end) % 360
    new_end = (180 - start) % 360
    if new_end < new_start:
        new_end += 360
    return (mirror_x(cx, length_mm), cy, r, new_start, new_end)


def classify_length(length_mm, tolerance=1e-6):
    if abs(length_mm - STANDARD_LENGTH_MM) <= tolerance:
        return "standard"
    return "non-standard"


def generate_frame(length_mm):
    """Build lines/polylines/arcs/circles/dimensions for the given length."""
    length_mm = float(length_mm)
    if length_mm < MIN_LENGTH_MM:
        raise ValueError(
            f"Frame length {length_mm}mm is too short: the two end "
            f"brackets alone need at least {MIN_LENGTH_MM}mm."
        )

    right_inner_x = mirror_x(BRACKET_INNER_X, length_mm)
    right_outer_x = mirror_x(BRACKET_OUTER_X, length_mm)

    lines = list(LEFT_BRACKET_LINES)
    lines.extend(
        (mirror_x(x1, length_mm), y1, mirror_x(x2, length_mm), y2)
        for x1, y1, x2, y2 in LEFT_BRACKET_LINES
    )
    lines.extend((BRACKET_INNER_X, y, right_inner_x, y) for y in FIN_LINE_YS)

    polylines = [
        list(LEFT_POLYLINE),
        [
            (right_outer_x, RIGHT_POLYLINE_Y_SPAN[0]),
            (right_outer_x, RIGHT_POLYLINE_Y_SPAN[1]),
        ],
    ]

    arcs = list(LEFT_BRACKET_ARCS)
    arcs.extend(mirror_arc(a, length_mm) for a in LEFT_BRACKET_ARCS)

    circles = list(LEFT_BRACKET_CIRCLES)
    circles.extend(
        (mirror_x(cx, length_mm), cy, r) for cx, cy, r in LEFT_BRACKET_CIRCLES
    )

    dim_p1 = (BRACKET_OUTER_X, DIMENSION_Y)
    dim_p2 = (right_outer_x, DIMENSION_Y)
    dim_mid_x = (dim_p1[0] + dim_p2[0]) / 2
    dimensions = [(dim_p1, dim_p2, (dim_mid_x, DIMENSION_LINE_Y))]

    return {
        "length_mm": length_mm,
        "classification": classify_length(length_mm),
        "lines": lines,
        "polylines": polylines,
        "arcs": arcs,
        "circles": circles,
        "dimensions": dimensions,
    }


# ============================================================
# RUNTIME FRAME STATE (filled in by main() once length is known)
# ============================================================

LINES = []
POLYLINES = []
ARCS = []
CIRCLES = []
DIMENSIONS = []
NATIVE_DIMENSIONS = []
FRAME_LENGTH_MM = None
FRAME_CLASSIFICATION = None


def get_frame_length_mm():
    """Length from command line, else prompt. Blank = standard 1200 mm."""
    if len(sys.argv) > 1:
        return float(sys.argv[1])

    raw = input(f"Frame length in mm [{STANDARD_LENGTH_MM:g}]: ").strip()
    if not raw:
        return STANDARD_LENGTH_MM
    return float(raw)


def load_frame(length_mm):
    """Generate the frame and store it in the module-level arrays."""
    global LINES, POLYLINES, ARCS, CIRCLES, DIMENSIONS, NATIVE_DIMENSIONS
    global FRAME_LENGTH_MM, FRAME_CLASSIFICATION

    frame = generate_frame(length_mm)
    LINES = frame["lines"]
    POLYLINES = frame["polylines"]
    ARCS = frame["arcs"]
    CIRCLES = frame["circles"]
    DIMENSIONS = frame["dimensions"]
    NATIVE_DIMENSIONS = DIMENSIONS if ADD_NATIVE_DIMENSION else []
    FRAME_LENGTH_MM = frame["length_mm"]
    FRAME_CLASSIFICATION = frame["classification"]


# ============================================================
# GEOMETRY DEDUP / MERGE HELPERS
# ============================================================

def point_key(x, y, precision=6):
    return round(float(x), precision), round(float(y), precision)


def line_key(line):
    x1, y1, x2, y2 = line
    return tuple(sorted((point_key(x1, y1), point_key(x2, y2))))


def remove_duplicate_lines(lines):
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
    Merge horizontal/vertical segments that truly overlap on the same axis
    line. Segments that only touch end-to-end stay separate.
    """
    groups = {}
    other = []

    for x1, y1, x2, y2 in lines:
        if abs(y1 - y2) < tol:
            key = ("H", round(y1, 6))
            lo, hi = sorted((x1, x2))
        elif abs(x1 - x2) < tol:
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
            if lo < cur_hi - tol:
                cur_hi = max(cur_hi, hi)
            else:
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

    if len(lines) != len(result):
        print(f"Merged overlapping lines: {len(lines)} -> {len(result)}")
    return result


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def com_call(obj, name, *args):
    """Call a COM method that pywin32 may expose as a property."""
    attr = getattr(obj, name)
    if callable(attr):
        return attr(*args)
    return attr


def to_m(value):
    """Convert source drawing units (mm) to SolidWorks meters."""
    return float(value) * SCALE_TO_METERS


def get_dimension_line_segments():
    """Dimension as plain lines: 2 extension lines, dim line, 2 arrowheads."""
    segments = []
    a = DIMENSION_ARROW_LENGTH
    w = DIMENSION_ARROW_HALF_WIDTH

    for p1, p2, pos in DIMENSIONS:
        y = pos[1]
        x_left, x_right = sorted((p1[0], p2[0]))

        segments.append((x_left, DIMENSION_EXTENSION_START_Y, x_left, y))
        segments.append((x_right, DIMENSION_EXTENSION_START_Y, x_right, y))
        segments.append((x_left, y, x_right, y))

        segments.append((x_left, y, x_left + a, y + w))
        segments.append((x_left, y, x_left + a, y - w))
        segments.append((x_left + a, y + w, x_left + a, y - w))

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
    if point_key(x1, y1) == point_key(x2, y2):
        return None
    return sketch_manager.CreateLine(
        to_m(x1), to_m(y1), SKETCH_Z,
        to_m(x2), to_m(y2), SKETCH_Z,
    )


def create_arc(sketch_manager, cx, cy, radius, start_angle, end_angle):
    """Native circular sketch arc (counterclockwise)."""
    if radius <= 0:
        raise ValueError(f"Arc radius must be positive: {radius}")

    start_rad = math.radians(start_angle)
    end_rad = math.radians(end_angle)

    start_x = cx + radius * math.cos(start_rad)
    start_y = cy + radius * math.sin(start_rad)
    end_x = cx + radius * math.cos(end_rad)
    end_y = cy + radius * math.sin(end_rad)

    return sketch_manager.CreateArc(
        to_m(cx), to_m(cy), SKETCH_Z,
        to_m(start_x), to_m(start_y), SKETCH_Z,
        to_m(end_x), to_m(end_y), SKETCH_Z,
        1,
    )


def create_circle(sketch_manager, cx, cy, radius):
    if radius <= 0:
        raise ValueError(f"Circle radius must be positive: {radius}")
    return sketch_manager.CreateCircle(
        to_m(cx), to_m(cy), SKETCH_Z,
        to_m(cx + radius), to_m(cy), SKETCH_Z,
    )


def create_dimension_points(sketch_manager, p1, p2):
    pt1 = sketch_manager.CreatePoint(to_m(p1[0]), to_m(p1[1]), SKETCH_Z)
    pt2 = sketch_manager.CreatePoint(to_m(p2[0]), to_m(p2[1]), SKETCH_Z)
    if pt1 is None or pt2 is None:
        raise RuntimeError("Could not create dimension reference points.")
    return pt1, pt2


def select_dimension_points(model, pt1, pt2, p1, p2):
    model.ClearSelection2(True)

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
    """Default part template -> common folders -> manual file picker."""
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
    try:
        sw_app = win32com.client.GetActiveObject("SldWorks.Application")
        print("Connected to an existing SolidWorks instance.")
    except Exception:
        sw_app = win32com.client.Dispatch("SldWorks.Application")
        print("Started a SolidWorks instance.")

    sw_app.Visible = True
    return sw_app


def select_front_plane(model):
    model.ClearSelection2(True)

    for name in ("Front Plane", "Front", "Plane1"):
        try:
            if model.Extension.SelectByID2(
                name, "PLANE", 0.0, 0.0, 0.0, False, 0, NOTHING, 0
            ):
                return True
        except Exception:
            pass

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
        print("SOLIDWORKS 2026 - NATIVE SKETCH GENERATOR (VARIABLE LENGTH)")
        print("=" * 60)

        # 0. Length for this run -> generate geometry.
        load_frame(get_frame_length_mm())
        print(
            f"Frame length: {FRAME_LENGTH_MM:g}mm ({FRAME_CLASSIFICATION})"
        )

        # 1. Connect to SolidWorks.
        sw_app = connect_to_solidworks()

        # 2. Part template.
        template_path = find_part_template(sw_app)
        print(f"Using template: {template_path}")

        # 3. New Part document.
        model = sw_app.NewDocument(template_path, 0, 0.0, 0.0)
        if model is None:
            raise RuntimeError(
                "SolidWorks could not create the Part document. "
                "Verify that the selected template is valid."
            )

        # 4. Front Plane.
        if not select_front_plane(model):
            raise RuntimeError(
                "Could not select the Front Plane. "
                "Check the plane name in your SolidWorks installation."
            )

        # 5. New 2D sketch.
        sketch_manager = model.SketchManager
        sketch_manager.InsertSketch(True)
        sketch_started = True

        # No auto-relations / inference; much faster for many entities.
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

        # 8b. Points for native dimensions.
        for index, (p1, p2, pos) in enumerate(NATIVE_DIMENSIONS, start=1):
            try:
                pt1, pt2 = create_dimension_points(sketch_manager, p1, p2)
                dimension_points.append((pt1, pt2, p1, p2, pos))
            except Exception as exc:
                errors.append(f"Dimension points {index}: {exc}")
                print(f"ERROR creating dimension points {index}: {exc}")

        sketch_manager.AddToDB = False

        # 8c. Native dimensions (sketch must still be open).
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

        # 9. Exit sketch.
        sketch_manager.InsertSketch(True)
        sketch_started = False

        # 10. Rename the sketch.
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
        print(f"Frame length:    {FRAME_LENGTH_MM:g}mm ({FRAME_CLASSIFICATION})")
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