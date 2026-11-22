"""
Phase 8: reusable application (Streamlit UI).

Thin wiring only -- all actual logic lives in the excel_to_cad package
(run_pipeline for Phases 1-7, dxf_export/supports for drawing). No
hardcoded file paths: the workbook comes from an upload (an in-memory
stream, handed straight to run_pipeline -- openpyxl reads file-like
objects natively, so nothing ever touches disk for the input file), and
all generated outputs are offered as in-browser downloads rather than
written to a fixed location.

Run with: streamlit run app.py
"""

import csv
import io

import matplotlib.pyplot as plt
import openpyxl
import streamlit as st
from ezdxf.addons.drawing import RenderContext
from ezdxf.addons.drawing.frontend import Frontend
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

from excel_to_cad import (
    ColumnDetectionError,
    SupportPlacementConfig,
    build_segment_validation_rows,
    detect_columns,
    generate_drawing,
)
from excel_to_cad.loader import REQUIRED_FIELDS
from excel_to_cad.reports import FRAME_SCHEDULE_COLUMNS, SEGMENT_VALIDATION_COLUMNS

st.set_page_config(page_title="Excel-to-CAD Frame Generator", layout="wide")
st.title("Excel-to-CAD Engineering Drawing Automation")

# ---------------------------------------------------------------------
# Step 1-2: upload workbook, pick worksheet
# ---------------------------------------------------------------------

uploaded = st.file_uploader("Upload a wall/segment workbook (.xlsx)", type=["xlsx"])

if uploaded is None:
    st.info("Upload a workbook to begin.")
    st.stop()

uploaded.seek(0)
workbook_bytes = uploaded.read()

wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), data_only=True)
sheet_names = wb.sheetnames
default_sheet = "Segment Report" if "Segment Report" in sheet_names else sheet_names[0]
sheet_name = st.selectbox("Worksheet", sheet_names, index=sheet_names.index(default_sheet))

headers = list(wb[sheet_name].iter_rows(min_row=1, max_row=1, values_only=True))[0]

# ---------------------------------------------------------------------
# Step 3: review / correct detected column mapping
# ---------------------------------------------------------------------

st.subheader("Column mapping")
mapping, unrecognized, ambiguous = detect_columns(list(headers))

column_overrides = {}
needs_override = sorted(set(REQUIRED_FIELDS) - set(mapping.keys())) + sorted(ambiguous.keys())
if needs_override:
    st.warning(
        f"These fields need a column assigned manually: {needs_override}"
    )
    for field_name in needs_override:
        choice = st.selectbox(
            f"Column for '{field_name}'", ["(none)"] + [str(h) for h in headers if h],
            key=f"override_{field_name}",
        )
        if choice != "(none)":
            column_overrides[field_name] = choice
else:
    st.success("All required columns detected automatically.")

with st.expander("Detected column mapping (auto)"):
    st.json({k: headers[v] for k, v in mapping.items()})
if unrecognized:
    with st.expander(f"Unrecognized columns ({len(unrecognized)}) -- ignored"):
        st.write(unrecognized)

# ---------------------------------------------------------------------
# Step 4-5: configuration
# ---------------------------------------------------------------------

st.sidebar.header("Configuration")

standard_frame_length_mm = st.sidebar.number_input(
    "Default standard frame length (mm)", min_value=1.0, value=1200.0, step=100.0,
    help="Used only when a segment doesn't specify its own Standard Frame Size.",
)
coincidence_tolerance_mm = st.sidebar.number_input(
    "Endpoint coincidence tolerance (mm)", min_value=0.0001, value=0.1, step=0.01, format="%.4f",
)
length_tolerance_mm = st.sidebar.number_input(
    "Length comparison tolerance (mm)", min_value=0.0000001, value=0.001, step=0.001, format="%.6f",
)

st.sidebar.subheader("Support placement")
at_corners = st.sidebar.checkbox("At every recognized corner", value=True)
at_segment_endpoints = st.sidebar.checkbox("At every segment endpoint", value=False)
at_frame_boundaries = st.sidebar.checkbox("At frame boundaries", value=False)
frame_boundaries_standard_only = st.sidebar.checkbox(
    "...standard-to-standard boundaries only", value=True, disabled=not at_frame_boundaries,
)
use_spacing = st.sidebar.checkbox("At regular spacing", value=False)
spacing_mm = st.sidebar.number_input(
    "Spacing (mm)", min_value=1.0, value=1200.0, step=100.0, disabled=not use_spacing,
)

st.sidebar.subheader("Drawing style")
bracket_radius_mm = st.sidebar.number_input("Bracket symbol radius (mm)", min_value=1.0, value=50.0)
frame_dim_offset_mm = st.sidebar.number_input("Frame dimension offset (mm)", min_value=1.0, value=150.0)
reference_dim_offset_mm = st.sidebar.number_input("Reference dimension offset (mm)", min_value=1.0, value=400.0)
text_height_mm = st.sidebar.number_input("Text height (mm)", min_value=1.0, value=100.0)

# ---------------------------------------------------------------------
# Step 6: generate
# ---------------------------------------------------------------------

if st.button("Generate CAD drawing", type="primary"):
    support_config = SupportPlacementConfig(
        at_corners=at_corners,
        at_segment_endpoints=at_segment_endpoints,
        at_frame_boundaries=at_frame_boundaries,
        frame_boundaries_standard_only=frame_boundaries_standard_only,
        spacing_mm=spacing_mm if use_spacing else None,
    )
    try:
        result, doc = generate_drawing(
            io.BytesIO(workbook_bytes),
            sheet_name=sheet_name,
            column_overrides=column_overrides or None,
            default_standard_frame_length_mm=standard_frame_length_mm,
            coincidence_tolerance_mm=coincidence_tolerance_mm,
            length_tolerance_mm=length_tolerance_mm,
            support_config=support_config,
            dxf_kwargs=dict(
                bracket_radius_mm=bracket_radius_mm,
                frame_dim_offset_mm=frame_dim_offset_mm,
                reference_dim_offset_mm=reference_dim_offset_mm,
                text_height_mm=text_height_mm,
            ),
        )
    except ColumnDetectionError as exc:
        st.error(f"Could not load this sheet: {exc}")
        st.stop()

    st.session_state["pipeline_result"] = result
    st.session_state["dxf_doc"] = doc

# ---------------------------------------------------------------------
# Steps 7-10: preview, zoom, downloads, validation
# ---------------------------------------------------------------------

if "pipeline_result" not in st.session_state:
    st.stop()

result = st.session_state["pipeline_result"]
doc = st.session_state["dxf_doc"]

if result.has_errors:
    st.error("Validation found unresolved ERRORs -- review before trusting this output.")
elif result.has_warnings:
    st.warning("Validation found WARNINGs -- review the report below.")
else:
    st.success("All segments validated cleanly.")


def render_figure(xlim=None, ylim=None):
    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_facecolor("#1a1a1a")
    ctx = RenderContext(doc)
    backend = MatplotlibBackend(ax)
    Frontend(ctx, backend).draw_layout(doc.modelspace(), finalize=True)
    if xlim:
        ax.set_xlim(*xlim)
    if ylim:
        ax.set_ylim(*ylim)
    return fig


st.subheader("Drawing preview")
preview_fig = render_figure()
st.pyplot(preview_fig)

png_stream = io.BytesIO()
preview_fig.savefig(png_stream, format="png", dpi=150, facecolor="#1a1a1a")
st.download_button(
    "Download preview (PNG)", png_stream.getvalue(),
    file_name="drawing_preview.png", mime="image/png",
)

st.subheader("Zoom into a corner")
corner_options = {
    f"{c.node_id} [{c.classification}] {'/'.join(sorted(c.corner_cases)) or '-'} @ "
    f"({c.point[0]:.1f}, {c.point[1]:.1f})": c
    for c in result.corner_connections
    if c.corner_cases
}
if corner_options:
    selected_label = st.selectbox("Corner", list(corner_options.keys()))
    zoom_window_mm = st.slider("Zoom window (mm)", 200, 10000, 2000)
    selected = corner_options[selected_label]
    x, y = selected.point[0], selected.point[1]
    half = zoom_window_mm / 2
    st.pyplot(render_figure(xlim=(x - half, x + half), ylim=(y - half, y + half)))
else:
    st.info("No recognized corners to zoom into.")

st.subheader("Validation report")
validation_rows = [
    {
        "Segment ID": r.segment_id,
        "Status": r.status,
        "Geometric Length (mm)": round(r.geometric_length_mm, 2),
        "Standard Count": r.calculated_standard_count,
        "Custom Remainder (mm)": round(r.calculated_custom_remainder_mm, 2),
        "Frame Count Matches": r.frame_count_matches,
        "Remainder Matches": r.custom_remainder_matches,
        "Issues": "; ".join(r.issues),
    }
    for r in result.segment_validations
]
st.dataframe(validation_rows, width="stretch")

st.subheader("Downloads")
col1, col2, col3 = st.columns(3)

dxf_stream = io.StringIO()
doc.write(dxf_stream)
col1.download_button(
    "Download DXF", dxf_stream.getvalue().encode("utf-8"),
    file_name="drawing.dxf", mime="application/dxf",
)

schedule_stream = io.StringIO()
writer = csv.DictWriter(schedule_stream, fieldnames=FRAME_SCHEDULE_COLUMNS)
writer.writeheader()
writer.writerows(result.frame_schedule_rows)
col2.download_button(
    "Download frame schedule (CSV)", schedule_stream.getvalue(),
    file_name="frame_schedule.csv", mime="text/csv",
)

validation_stream = io.StringIO()
writer = csv.DictWriter(validation_stream, fieldnames=SEGMENT_VALIDATION_COLUMNS)
writer.writeheader()
writer.writerows(build_segment_validation_rows(result.segment_validations))
col3.download_button(
    "Download validation report (CSV)", validation_stream.getvalue(),
    file_name="segment_validation.csv", mime="text/csv",
)
