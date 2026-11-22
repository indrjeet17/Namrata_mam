# Excel-to-CAD Engineering Drawing Automation

Reads a wall/segment Excel workbook (column layout detected dynamically, not assumed
fixed), reconstructs the wall geometry, classifies every corner/junction, calculates
standard + custom-length frame sequences, and generates an editable AutoCAD-compatible
DXF drawing — plus a frame schedule and a segment/corner validation report.

Full design rationale, phase-by-phase implementation notes, and every non-obvious
decision made along the way (with reasoning) live in **`PROJECT_PLAN.md`**. This file is
the short, practical "how do I run this" version plus a concise summary of the two
deliverables the plan specifically asks to be summarized: the algorithm, and known
assumptions/limitations.

## Setup

Requires Python 3.9+.

**macOS / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Windows (cmd.exe):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

## Running the app

```bash
streamlit run app.py
```

Opens a browser tab. Upload a workbook (the four `testdrawingN.xlsx` files in this repo
are real sample data), pick the worksheet if it isn't auto-detected, review/correct the
column mapping, configure options in the sidebar, click **Generate CAD drawing**, then
preview, zoom into corners, and download the DXF / frame schedule / validation report.

No file paths are hardcoded anywhere — the workbook comes from the upload widget as an
in-memory stream, and every output is generated in memory and offered as a download.

## Running the tests

```bash
pytest tests/ -v
```

215 tests, all passing as of this writing, including end-to-end checks against all four
real sample workbooks (every computed frame cross-checked against each workbook's own
independently-generated Frame Placement Report — zero mismatches across all 421 frames).

## Using it as a library (no UI)

Every phase is a plain, composable Python function — the UI is a thin wrapper, not where
the logic lives:

```python
from excel_to_cad import generate_drawing, write_frame_schedule, write_segment_validation_report

result, dxf_doc = generate_drawing("my_workbook.xlsx")

dxf_doc.saveas("output.dxf")
write_frame_schedule(result.frame_schedule_rows, "frame_schedule.csv")
write_segment_validation_report(result.segment_validations, "validation.csv")

print(result.has_errors, result.has_warnings)
```

## Repository layout

```
excel_to_cad/
  loader.py        Phase 1 — dynamic column detection, normalization, validation
  connectivity.py  Phase 2 — endpoint + T-junction connectivity graph
  corners.py       Phase 3 — corner-case classification (A-I, plus T)
  frames.py        Phase 4 — standard/custom frame sequencing
  dxf_export.py    Phase 5 — DXF generation (ezdxf)
  supports.py      Phase 6 — configurable support/bracket placement policy
  reports.py       Phase 7 — frame schedule + segment validation reports
  pipeline.py       Phase 8 — ties Phases 1-7 (and optionally 5/6) together
app.py              Phase 8 — Streamlit UI (thin wiring only)
tests/              Phase 9 — 215 tests covering the plan's 15 required scenarios
testdrawing1-4.xlsx  Phase 1 sample data (real, not synthetic)
PROJECT_PLAN.md      Full design log: findings, decisions, and reasoning per phase
```

## Algorithm, concisely

1. **Load** (`loader.py`): match a worksheet's actual header row against known aliases
   per field (handles `"Standard Frames"` vs. `"Standard Frame Count"` etc. without
   assuming exact names). Only Wall ID/Segment ID/Start/End X/Y are required; everything
   else is optional and its absence is recorded, not invented. Validates geometric length
   (computed from coordinates) against any reported length.
2. **Connect** (`connectivity.py`): cluster every segment's endpoints by coincidence
   (configurable tolerance, default 0.1mm — picked empirically: real coincident points
   agree to ~1e-12mm, genuine gaps start at ~1.0mm). Also detects T-junctions (an
   endpoint touching another segment's *interior* span) — common in real data but not
   named in the original plan text, added after confirming with the data. Multi-wall
   workbooks are processed one wall at a time so two walls never get silently merged
   just because they share a coordinate.
3. **Classify corners** (`corners.py`): maps each node to the plan's named cases
   (right-angle, collinear, diagonal, multi-member, closed-perimeter, plus the T-junction
   extension), assigns a placeholder bracket symbol (no real bracket data exists in any
   sample workbook), and later fills in whether a standard or custom frame terminates at
   each junction once frame sequences exist.
4. **Sequence frames** (`frames.py`): `floor(length / F)` standard frames + one custom
   remainder, placed from each segment's own start toward its end, never carrying a
   remainder into the next segment. Validated to an exact match (type, length, start,
   end) against all 421 frames across all four real workbooks' own independently-computed
   frame breakdowns.
5. **Draw** (`dxf_export.py`): real `ezdxf` DIMENSION entities (not manually-drawn fake
   lines) on the plan's exact 9 named layers, blue for per-frame dimensions / magenta for
   overall reference dimensions, custom (remainder) frames colored distinctly.
6. **Place supports** (`supports.py`): a configurable policy layer — at corners (the
   default), at segment endpoints, at frame boundaries, by explicit spacing, or at
   explicit coordinates — composable and deduplicated, not a single hardcoded rule.
7. **Report** (`reports.py`): a frame schedule and a segment validation report,
   consolidating every discrepancy found across all prior phases into one place per
   segment, with an explicit OK/WARNING/ERROR status — nothing is silently corrected.

## Assumptions and unresolved engineering details

- **No reference CAD screenshot exists for this project.** DXF styling (bracket shape,
  dimension placement side) is a reasonable generic engineering-drawing style, not a
  match to a specific drawing — confirmed acceptable with the project owner. Restyling
  against a real reference later only touches `dxf_export.py`.
- **T-junctions are a real, common pattern in the sample data** (one segment's endpoint
  touching another's interior span) that the original plan text doesn't name as a corner
  case. Added after finding that without it, one sample workbook reported 86% of its
  nodes as "disconnected," which didn't reflect the actual wall. Confirmed with the
  project owner before implementing.
- **No sample workbook contains real bracket/support block geometry, placement data, or
  component/callout numbers.** Every bracket is the same configurable placeholder shape
  (a plain circle); the `CALLOUTS` DXF layer exists (per the plan's required layer list)
  but is deliberately left empty rather than inventing numbers.
- **Corner "turn direction" (A vs. B, i.e. normal vs. reverse right angle) is local to
  each node**, not a global loop-winding direction — discovered this when a test
  incorrectly assumed a closed rectangle's four corners would all share one chirality
  label; the "closing" corner of a loop can legitimately differ. Documented in
  `corners.py` rather than building a full winding-order calculation the plan doesn't
  require.
- **Segment IDs are assumed unique across an entire workbook**, not just within one
  wall — true in every sample seen so far. If a future workbook reuses a Segment ID
  across two different walls, a warning is raised (not a silent collision), since some
  internal lookups in `frames.py`/`reports.py` key by segment ID alone. A full
  composite-key (`wall_id` + `segment_id`) refactor hasn't been done since there's no
  real data yet exercising this.
- **Multi-wall workbooks**: the connectivity graph is built one wall at a time
  specifically so two different walls sharing a coordinate (e.g. a common grid origin)
  never get silently merged — found and fixed this while reviewing test coverage, since
  none of the four real sample workbooks actually has more than one wall to catch it
  naturally.
- **PNG/PDF preview**: the Streamlit app renders a live preview and offers a PNG
  download of exactly that render; no separate PDF export path exists yet.
