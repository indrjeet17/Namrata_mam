# Excel-to-CAD Engineering Drawing Automation — Project Tracker

## Objective

A reusable application that, given a new Excel workbook each time, automatically:

1. Reads wall/segment geometry data (dynamic column detection, no fixed schema).
2. Reconstructs the original 2D/3D wall/frame geometry exactly as given (no straightening,
   reordering, or inventing data).
3. Builds a connectivity graph and classifies every corner/junction.
4. Calculates standard (1200mm default, configurable) + custom-remainder frame sequences
   per segment.
5. Generates an AutoCAD-compatible DXF (via `ezdxf`) that visually matches the supplied
   reference drawings — not a simplified line diagram.
6. Places support/bracket symbols and callouts.
7. Produces a frame schedule + validation report (discrepancies surfaced, never hidden).
8. Ships as a reusable app (e.g. Streamlit) — no source changes needed for a new workbook.
9. Has automated tests covering the 15 listed geometry/corner scenarios.
10. Delivers runnable code, DXF, preview, schedule, validation reports, tests, and a
    written explanation of assumptions/limitations.

**Hard constraints carried through every phase:**
- Never hardcode segment count, coordinates, frame count, corner locations, or custom
  lengths for any one example drawing.
- Never invent missing values, guess from screenshots, or silently "fix" inconsistent
  source data — report discrepancies instead.
- Never snap/merge geometry that isn't genuinely coincident (configurable tolerance only).
- Corner connectivity correctness outranks cosmetic polish.

## Phase Checklist

- [x] **Phase 1a — Inspection done.** Findings below.
- [x] **Phase 1b — Dynamic column detection/normalization implemented.**
      `excel_to_cad/loader.py` + `excel_to_cad/models.py`, 28 tests in
      `tests/test_loader.py` (all passing). See "Phase 1b Implementation" below.
      Worksheet *selection* (vs. hardcoded `"Segment Report"`) and a real manual-mapping
      UI are deferred to Phase 8 (no UI exists yet) — the `column_overrides` parameter
      is already the hook for both.
- [x] **Phase 2 — Connectivity graph implemented**, including T-junction detection
      (confirmed with you — see finding below). `excel_to_cad/connectivity.py`,
      55 tests total in `tests/` (all passing).
- [x] **Phase 3 — Corner connectivity implemented** for all cases A–I, T. G/H
      (frame-dependent terminations) populated by `apply_frame_terminations()` once Phase
      4 existed; I folded into E (support-symbol *placement policy* is Phase 6's job, not
      Phase 3's). See "Phase 3 Implementation" below. `excel_to_cad/corners.py`, 113 tests
      total in `tests/` (all passing). Inspecting DXF at every corner is a Phase 5 concern
      (no DXF exists yet).
- [x] **Phase 4 — Frame sequencing implemented.** `excel_to_cad/frames.py`. See "Phase 4
      Implementation" below — validated to an exact match against all 421 frames across
      all four real workbooks' own independently-generated Frame Placement Report sheets.
- [x] **Phase 5 — DXF generation implemented**, generic style (no reference screenshot
      available for this project — confirmed with you). `excel_to_cad/dxf_export.py`,
      134 tests total in `tests/` (all passing). See "Phase 5 Implementation" below.
- [x] **Phase 6 — Support/bracket placement made configurable.**
      `excel_to_cad/supports.py`, 158 tests total in `tests/` (all passing). See "Phase 6
      Implementation" below.
- [x] **Phase 7 — Frame schedule + validation reports implemented.**
      `excel_to_cad/reports.py`, 188 tests total in `tests/` (all passing). See "Phase 7
      Implementation" below.
- [x] **Phase 8 — Reusable Streamlit application built.** `app.py` +
      `excel_to_cad/pipeline.py`. 215 tests total in `tests/` (all passing) — includes a
      multi-wall connectivity bug found and fixed along the way (see below). See "Phase 8
      Implementation" below.
- [x] **Phase 9 — All 15 required scenarios covered.** Built incrementally alongside
      each phase rather than as a separate late-stage effort — 215 tests total in
      `tests/`, all passing. See "Phase 9 Implementation" below for the traceability
      mapping (which test(s) cover which named scenario).
- [x] **Phase 10 — Deliverables packaged.** `README.md` now has install/run instructions
      (macOS/Linux + Windows), a concise algorithm write-up, and a consolidated
      assumptions/limitations list. PNG preview download added to the app (no separate
      PDF export path). Source, requirements, DXF, schedule, validation reports, sample
      data, and 215 tests were already in place from Phases 1–9.

**All 10 phases complete.**

## Current Inputs Inventory

| File | Status | Role going forward |
|---|---|---|
| `EC fence 20160930.DWG`, `Drawing1.dwg` | Present, **unreadable here** (no DWG parser installed on this machine — no ODA/LibreDWG/ezdxf-DWG support) | Reference for component shapes/layers/conventions *if* we get a DXF export or the user describes them directly |
| `testdrawing1.xlsx` – `testdrawing4.xlsx` | Present, inspected (see findings below) | Primary data source for Phases 1–9 |

Environment: `.venv/` created in this folder with `openpyxl`, `pandas`, `ezdxf` installed
(`pip install -r requirements.txt` once that file exists — not yet written).

## Phase 1 Inspection Findings

All four workbooks share **identical sheet structure**: `Segment Report`,
`Manufacturing Report`, `Frame Placement Report`, `Assembly Report`, `Summary`.

### Segment Report (the real geometry source)
Columns: `Wall ID, Segment ID, Entity Handle, Entity Type, Layer, Color, Start X, Start Y,
Start Z, End X, End Y, End Z, Direction, Length (mm), Standard Frame Size, Standard
Frames, Custom Frame (mm)`.

- Column names differ slightly from the plan's example names (`Standard Frames` not
  `Standard Frame Count`; `Custom Frame (mm)` not `Custom Frame Length`) — **confirms
  dynamic/fuzzy column matching is required, not exact-name matching.**
- `Standard Frame Size` is explicitly given per-row (currently always 1200 across all
  sampled rows, but the column exists per-segment, not as a single global constant — the
  loader must read it per segment, not assume one workbook-wide value).
- `Standard Frames` / `Custom Frame (mm)` are already-computed values we can
  cross-validate our own `floor(L/F)` + remainder calculation against (spot-checked
  testdrawing1 S1: L=5200.664, F=1200 → 4 standard + 400.664 remainder — matches).
- `Direction` values seen: `Horizontal`, `Vertical` (all 3 "planar" files), plus
  **`Diagonal`** in testdrawing4 (segment S25, length 3525.17mm) — confirms we have a
  real diagonal-segment test case already in hand for Phase 9.
- `Wall ID` is `'W1'` in every row across all four files — none of the sample files
  actually exercise multi-wall-per-sheet yet. Multi-wall support still must be built per
  the plan, just not exercisable against these four samples alone.
- Row counts match each file's own `Summary` sheet total segment count exactly (no
  hidden/truncated rows).

### Manufacturing Report
Flat per-frame schedule: `Wall ID, Segment ID, Frame No, Frame Type, Frame Length (mm)`.
This is essentially the Phase 7 frame schedule already computed by whatever tool
generated these files — useful as an independent cross-check for our Phase 4 output, not
as something to just copy forward.

### Frame Placement Report (important finding)
Columns: `..., Frame Length, Start/End X/Y/Z, Direction, Rotation Angle` plus, in
testdrawing2/3/4 only, an extra **`Continuity Status`** column (`FIRST FRAME` / `PASS` /
`FAIL`). **testdrawing1 does not have this column** — direct proof the schema is not
fixed even across "the same kind" of file, reinforcing why Phase 1's column detection
must tolerate optional columns per workbook.

Investigated what `FAIL` actually means: in every case, it appears only on a segment's
very first frame (`Frame No == 1`), and it fires exactly when that segment's `Start`
point does not equal the *previous segment ID's* `End` point. Verified this numerically
for testdrawing4: a naive "does segment N's start equal segment (N−1)'s end" scan finds
**18 mismatches**, exactly matching the 18 `FAIL` rows in that file's Frame Placement
Report.

**Conclusion — this matters for Phase 2:** the source tool's own continuity check is a
*naive sequential-ID chain assumption*, not a true connectivity graph. Real connections
in this data exist between **non-consecutive** segment IDs (e.g. testdrawing3's S2 and S3
are two separate parallel vertical members near the same X, not a chain; testdrawing4 has
multiple branching sub-rectangles). This is precisely why the plan requires checking all
four endpoint-pairing combinations across *all* segment pairs, with tolerance-based
coincidence — not assuming consecutive IDs connect. We should build the real graph and
treat `Continuity Status` only as a secondary cross-check signal to report alongside our
own findings, never as the source of truth for connectivity.

### Assembly Report
Duplicate of Segment Report's geometry columns only (`Wall ID, Segment ID, Direction,
Start/End X/Y/Z`) — no new information, likely just a presentation-order sheet.

### Summary
Aggregate totals (segment count, total/horizontal/vertical/diagonal length) — useful as a
fast sanity check after reconstruction (our rebuilt totals should match this sheet).

### Floating-point noise observed
Some `Rotation Angle` values are near-zero-but-not-exact (e.g. `6.11e-14` instead of `0`,
`-89.99999999999993` instead of `-90`) — confirms the plan's instruction to use
configurable tolerances for all comparisons, never exact equality.

## Phase 1b Implementation

**Code:** `excel_to_cad/models.py` (`Point3D`, `Segment`, `ColumnMapping`,
`ValidationIssue`, `LoadResult`), `excel_to_cad/loader.py` (`detect_columns`,
`load_segments`). **Tests:** `tests/test_loader.py`, 28 tests, all passing (run with
`.venv/bin/python -m pytest tests/ -v`).

How it works:
- Header names are normalized (lowercase, punctuation → spaces, whitespace collapsed) so
  `"Length (mm)"`, `"length_mm"`, `"Length mm"` all resolve to the same alias.
- Each canonical field (`wall_id`, `segment_id`, `start_x`, ... `custom_frame_length_mm`)
  has an alias list in `FIELD_ALIASES`, built directly from what the four real workbooks
  actually use plus the plan's example names.
- Only `wall_id, segment_id, start_x, start_y, end_x, end_y` are required; everything
  else (Z, direction, length, frame-size/count/remainder, entity metadata) is optional —
  absence is recorded, not papered over (Z columns absent → Z defaults to 0.0, which is
  reported behavior, not an invented value).
- A field matching more than one column is ambiguous: required-field ambiguity raises
  `ColumnDetectionError` (can't proceed safely); optional-field ambiguity is left unmapped
  and surfaced as a warning. Either case is resolved by passing
  `column_overrides={"field": "Exact Header Name"}` — the same hook Phase 8's manual
  column-mapping UI will call into.
- Per-row validation (missing/non-numeric coordinates, zero-length segments, reported
  vs. geometric length beyond `length_tolerance_mm`, default `1e-3`mm) is collected as
  `ValidationIssue`s on the result rather than raised — one bad row doesn't block loading
  the rest of a valid sheet.

Verified against all four real workbooks: segment counts match each file's own `Summary`
sheet exactly, zero unrecognized columns, zero length-discrepancy warnings (confirmed
separately that reported vs. geometric length agrees to ~1e-12mm — floating-point noise
only), and `testdrawing4`'s one `Diagonal` segment (S25) loads correctly with its
direction preserved.

**Environment:** `.venv/` (gitignored-worthy, not yet in version control) with
`openpyxl`, `ezdxf`, `pytest` — see `requirements.txt`.

## Phase 2 Implementation

**Code:** `excel_to_cad/connectivity.py` (`EndpointRef`, `Node`, `ConnectivityGraph`,
`build_connectivity_graph`, `group_by_wall`). **Tests:** `tests/test_connectivity.py`,
21 tests, all passing.

How it works: endpoints are transitively clustered into nodes using union-find, wherever
pairwise distance ≤ `coincidence_tolerance_mm` (default `0.1mm` — grounded empirically:
across all four real workbooks, truly-coincident points agree to ~1e-12mm, while the
*smallest genuine gap* between distinct intended points is ~1.0mm, so 0.1mm sits safely
in between with wide margin on both sides). Each node is classified by degree + the angle
between members' "away from node" direction vectors: `straight_continuation` (~180°),
`right_angle_corner` (~90°), `diagonal_connection` (any other angle, if either member is
non-axis-aligned), `multi_member_junction` (degree ≥ 3), `disconnected_endpoint`
(degree 1, reported not hidden), or `unclassified_connection` (degree 2, angle fits none
of the above — e.g. ~0°, flagged as possible duplicate/overlapping geometry). Closed-
perimeter detection is a separate, connected-component-level check (every node in the
component has degree exactly 2 ⟺ the component is a single cycle), kept distinct from
per-node corner classification — see the module docstring for the full reasoning. Near-
coincident-but-not-connected endpoint pairs and duplicate/overlapping segments are
surfaced as warnings, never silently merged.

### Important finding: T-junctions are common in the real data, and out of this model's current scope

The plan's Phase 2 text specifies checking exactly "all four endpoint combinations"
(end-to-start, start-to-end, start-to-start, end-to-end) — i.e. **endpoint-to-endpoint**
coincidence only. Running the implemented graph against all four real workbooks and
manually tracing `testdrawing3` (12 segments, 18 of 21 nodes came back
`disconnected_endpoint`) found that almost all of its real physical connections are
**T-junctions**: one segment's endpoint touches the *middle* of another segment's span
(e.g. S3's start sits exactly at `t=0.161` along S1, distance 0.000mm) — not another
segment's endpoint. `testdrawing4` has the same pattern (many `MIDSPAN-TOUCH` cases).
`testdrawing1`/`testdrawing2` are mostly genuine endpoint-to-endpoint perimeters with a
few genuinely free/open ends — T-junctions are not universal, just common in the more
complex layouts.

This is a real gap between the plan's literal Phase 2 text and what the actual data
needs to be useful: as built, `testdrawing3`'s connectivity graph originally reported 86%
of its nodes as disconnected, which didn't reflect the physical wall — it was just outside
the four specified checks.

**Resolved with you:** add T-junction detection (confirmed), keep the strict 0.1mm
coincidence tolerance as-is for near-miss gaps (confirmed — "leave disconnected, just
report").

**T-junction implementation:** for every remaining degree-1 (`disconnected_endpoint`)
node, check the closest point on every *other* segment's full span (clamped to [0,1]);
if within `t_junction_tolerance_mm` (defaults to `coincidence_tolerance_mm`), record a
`TJunction` (segment, which end, target segment, parametric position `t`, touch point,
distance) and reclassify that node `"t_junction"` instead of `"disconnected_endpoint"`.
This is purely a connectivity annotation — it never splits the touched segment or alters
either segment's own geometry; Phase 4 will still place frames along each segment's full
original start-to-end length regardless of any T-junctions along the way. T-junction
nodes also join their two segments' connected components (physically part of the same
assembly), which correctly keeps a component "not closed" if it has a branch hanging off
an otherwise-closed loop (a `t_junction` node is still degree 1 structurally).

Verified against all four real workbooks: `testdrawing3` went from 18 → 8 disconnected
endpoints (10 genuine T-junctions found, matching a full manual coordinate trace);
`testdrawing4` found 11; `testdrawing1`/`testdrawing2` found 0 (their disconnected ends
really are free/open, confirmed by checking distance to every other segment's interior,
not just near-miss heuristics). One borderline near-miss warning remains in testdrawing4
(S15/S16, t≈0.0009 — essentially at S16's own start endpoint) that could arguably overlap
with an endpoint-to-endpoint near-miss report; not fixed since it's a single cosmetic
instance, not a correctness issue — noted here for visibility.

Separately, also found 3-4 endpoint pairs across testdrawing2/testdrawing4 sitting
0.6mm–2.2mm apart (not exactly coincident, not T-junctions either) — plausibly accumulated
rounding from whatever tool exported these coordinates from the original DWG, or
genuinely intentional small gaps. Per your decision, these stay disconnected and are
only reported as near-miss warnings, never silently bridged.

## Phase 3 Implementation

**Code:** `excel_to_cad/corners.py` (`CornerConnection`, `build_corner_connections`).
**Tests:** `tests/test_corners.py`, 20 tests, all passing.

Phase 3 interprets Phase 2's already-validated `ConnectivityGraph` against the plan's
named corner cases — it does not rebuild connectivity. One `CornerConnection` per graph
node (every node, including open ends, so Phase 7's validation report has one place to
look at every endpoint).

**Case mapping** (full reasoning in the module docstring):
- **A / B** (right-angle, "normal" vs "reverse"): `right_angle_corner` nodes where
  *neither* member is diagonal. Distinguished by `turn_direction` (`ccw`→A, `cw`→B) —
  computed from the cross product of the two members' away-from-node vectors. **This is
  a local label relative to each node's own stored endpoint order, not a global
  loop-winding direction** — found this the hard way: my first test asserted a closed
  rectangle's 4 corners should all share one turn direction, and it failed, because the
  "closing" corner (last segment meeting the first) legitimately flips which segment
  plays the reference role. Fixed the test, not the code — documented the limitation in
  both places instead of building a full global winding-order calculation the plan
  doesn't ask for.
- **C** (collinear): `straight_continuation` nodes, unchanged from Phase 2.
- **D** (diagonal involved): any node where *at least one* connected member is
  non-axis-aligned, regardless of the resulting angle — so a `right_angle_corner` node
  gets reclassified from A/B to D if either member is diagonal (verified against
  testdrawing4: 19 `right_angle_corner` nodes split into 17 A/B + 2 D, the 2 D's being the
  corners touching the one Diagonal segment S25).
- **E** (3+ members): `multi_member_junction`, unchanged; gains `D` too if any member is
  diagonal.
- **F** (closed perimeter): added on top of whatever other case(s) already apply, from
  `ConnectivityGraph.closed_components` — a rectangle's corners are A/B *and* F, not F
  instead of A/B.
- **G / H** (frame-dependent terminations): cannot be determined without Phase 4's frame
  sequences. Left as an explicit `frame_termination: Optional[str]` field, `None` until
  Phase 4 populates it — not guessed at now.
- **I** (multi-member + support symbols): support-symbol *placement* is explicitly
  Phase 6's configurable job (per-frame-boundary / per-endpoint / per-corner / etc.), and
  no sample workbook has any symbol data (confirmed Phase 1) — so this module only
  reports which corners are structurally multi-member (same set as E); it does not decide
  which corners "need" a symbol.
- **T** (extension, not in the plan's A-I list): T-junction nodes from Phase 2's
  extension get their own tag rather than being folded into E, since a T-junction is
  exactly 2 segment records behaving like a 3-arm junction, not literally 3 records.

**Bracket symbol placeholder:** every node that gets at least one corner case is assigned
`DEFAULT_BRACKET_SYMBOL = "PLACEHOLDER_BRACKET"` (configurable via a parameter) — a single
generic placeholder, not invented per-case shapes, since none of the four workbooks
contain real bracket/support geometry (confirmed Phase 1). Nodes with no case
(`disconnected_endpoint`, `unclassified_connection`) get no bracket symbol — they aren't
corners.

Verified against all four real workbooks: every graph node maps to exactly one
`CornerConnection` (no node skipped or duplicated), and the case counts cross-check
cleanly against Phase 2's classification counts in all four files.

## Phase 4 Implementation

**Code:** `excel_to_cad/frames.py` (`Frame`, `compute_frame_counts`, `place_frames`,
`build_frame_schedule`, `determine_frame_terminations`). **Tests:** `tests/test_frames.py`,
31 tests, all passing.

`compute_frame_counts(length_mm, F)` is the plan's exact rule
(`floor(L/F)`, `remainder = L - count*F`), with a guard for two floating-point edge cases
right at an exact multiple of F: a length a hair below an intended exact multiple (naive
`floor()` undercounts by one, leaving a near-F "remainder") or a hair above one (leaving a
near-zero "remainder") — both snapped to the clean exact-multiple result within a
configurable tolerance.

`place_frames(segment, F)` walks a segment's own 3D direction vector (works identically
for horizontal/vertical/diagonal — no axis-specific branching), placing each standard
frame's boundary by direct multiplication (`idx * F`, not repeated addition, to avoid
accumulating float drift), with the final frame's end point forced to be the segment's
*actual* stored endpoint (not a recomputed one) — satisfies the plan's "ensure the final
frame terminates at the actual segment endpoint" rule exactly as stated. No remainder
frame is created when a segment is an exact multiple of F.

`build_frame_schedule(segments)` sequences every segment independently (verified: a
remainder from one segment never leaks into the next), using each segment's own
`standard_frame_size_mm` when the workbook provided one, and cross-validates against the
workbook's own `reported_standard_frame_count` / `reported_custom_frame_length_mm` —
reporting disagreement as a warning rather than silently overwriting either value (tested
specifically that genuine rounding in the reported values, e.g. `400.66` vs. the true
`400.664002460644`, does *not* trip a false-positive warning).

**Validation — the strongest cross-check in the project so far:** every one of the 421
frames across all four real workbooks (type, length, start, end coordinates) was checked
against that workbook's own, independently-generated `Frame Placement Report` sheet —
**zero mismatches**. Also confirmed the plan's own worked example exactly: testdrawing4
S1 (14587.442338408691mm) → 12 standard + 187.44233840869128mm custom, matching the
plan's `12 standard, 187.44234mm` to full precision. testdrawing3 S5 (1039.02mm, shorter
than 1200mm) correctly produces a single custom frame — Phase 9 scenario 6.

**Phase 3 G/H closed out:** `determine_frame_terminations(frames)` maps each
`(segment_id, which_end)` to the frame type touching it; `corners.apply_frame_terminations()`
uses this to add case `G` (a `"standard"` frame ends at the junction) and/or `H` (a
`"custom"` frame does) to each `CornerConnection`, populating the `frame_termination`
field that Phase 3 had left as `None`. Both can apply at one corner (common pattern
confirmed in real data: segment A's end is often a custom remainder while segment B's
start, by construction, is always a fresh standard frame unless B itself is shorter than
F).

## Phase 5 Implementation

**Code:** `excel_to_cad/dxf_export.py` (`build_dxf_document`, `export_dxf`,
`LAYER_DEFINITIONS`). **Tests:** `tests/test_dxf_export.py`, 21 tests, all passing.
Uses `ezdxf` (already in `requirements.txt`/`.venv/`).

**No reference CAD screenshot exists for this project** (confirmed with you before
starting) — this produces a correct, readable *generic* engineering-drawing style per
the plan's explicit textual rules (exact layer names, blue/magenta dimension colors),
rather than guessing at a specific look with no source to match. Restyling against a real
reference later only touches this module, not geometry/connectivity/frames upstream.

**All 9 named layers created**, nothing extra invented:
- `WALL_GEOMETRY` — each segment's full original line (thin, dark gray "construction
  reference").
- `STANDARD_FRAMES` / `CUSTOM_FRAMES` — each `Frame`'s line, split by `frame_type`.
  Custom (remainder) frames colored red specifically so the irregular pieces are easy to
  spot when reviewing output — directly useful for Phase 3's "inspect the generated DXF
  geometry at every corner" instruction, which only becomes possible now that a DXF
  actually exists.
- `CORNER_CONNECTIONS` — a small "+" marker at every node with at least one corner case
  (not drawn at genuinely open/disconnected ends).
- `SUPPORT_SYMBOLS` — the Phase 3 placeholder bracket (a circle) at the same nodes.
- `STANDARD_DIMENSIONS` (ACI blue, color 5) — one real `ezdxf` aligned DIMENSION entity
  per `Frame`, which auto-orients along the member's actual direction regardless of
  horizontal/vertical/diagonal (no axis-specific branching needed).
- `REFERENCE_DIMENSIONS` (ACI magenta, color 6) — one aligned DIMENSION per segment
  (overall length), offset further out than the per-frame dimension chain so the two
  tiers never overlap.
- `CALLOUTS` — layer created, deliberately left **empty**: none of the four sample
  workbooks contain real callout/component numbers (confirmed Phase 1), and the plan
  explicitly says not to invent them.
- `LABELS` — segment ID near each segment's midpoint (real data) and each corner's case
  letters (derived, not invented) — mainly a review aid.

**Validated:** every DIMENSION entity's own `get_measurement()` was checked against the
actual `Frame`/`Segment` length it's supposed to represent (not just "a dimension entity
exists") — exact match in every case, including all four real workbooks. Entity counts
per layer cross-checked arithmetically against the upstream data (e.g.
`SUPPORT_SYMBOLS` circle count == corners with at least one case, `LABELS` text count ==
segments + such corners) for all four files. Every exported file round-trips through
`ezdxf.readfile()` cleanly.

**Known limitation, explicitly accepted for now:** the bracket symbol is a plain circle
and dimension placement side (above/below, left/right) uses `ezdxf`'s default aligned-
dimension offset convention rather than a drawing-matched convention, since there's
nothing to match yet. If/when a reference screenshot arrives, only this module needs
revisiting.

## Phase 6 Implementation

**Code:** `excel_to_cad/supports.py` (`SupportPoint`, `SupportPlacementConfig`,
5 placement-policy functions, `combine_support_points`, `resolve_support_points`).
**Tests:** `tests/test_supports.py`, 24 tests, all passing.

Placement policy is kept deliberately separate from Phase 3 (geometric connectivity
facts) and Phase 5 (how a symbol is drawn) — a pure "given this data, where do supports
go" decision layer. Five composable policies, matching the plan's explicit list:
`supports_at_corners` (every node with a recognized corner case — this was Phase 5's old
hard-coded behavior, now just the *default* policy, not the only one), `supports_at_segment_endpoints`
(every segment's own start/end, including genuinely open ones), `supports_at_frame_boundaries`
(every internal boundary between consecutive frames of one segment — with a
`standard_only` flag defaulting `True` to match the plan's literal "every **standard**
frame boundary" wording, since a boundary touching a custom/remainder frame reads
differently), `supports_by_spacing` (every N mm along a segment, where N must come from
explicit input — never guessed), and `supports_at_explicit_coordinates` (plain
pass-through for user-specified points).

`combine_support_points()` merges any combination and deduplicates points within a
configurable tolerance (default 0.1mm) — directly satisfies "at a shared corner, avoid
duplicated symbols," generalized to any combination of policies, not just corners
specifically. Verified: a corner point and a coincident segment-endpoint point from two
different policies collapse to one, not two.

`SupportPlacementConfig` + `resolve_support_points()` tie it together and plug into
`dxf_export.build_dxf_document(..., support_config=...)` — **verified the default
(no config passed) produces byte-for-byte the same `SUPPORT_SYMBOLS` circle count as
Phase 5's original hard-coded behavior**, so nothing regressed; passing a different
config (e.g. `at_corners=True, at_segment_endpoints=True`) changes the output as
expected. The `CORNER_CONNECTIONS` "+" markers stay unconditional — Phase 3's corner
facts are not a placement decision.

No real bracket CAD blocks, component numbers, or physical sizes exist in any sample
workbook (confirmed Phase 1) — nothing invented here; `bracket_symbol`/radius remain the
same configurable placeholder from Phase 3/5.

## Phase 7 Implementation

**Code:** `excel_to_cad/reports.py` (`build_frame_schedule_rows`, `write_frame_schedule`,
`SegmentValidationResult`, `build_segment_validation_report`,
`write_segment_validation_report`). **Tests:** `tests/test_reports.py`, 30 tests, all
passing. Both report types write to CSV (stdlib `csv`) or `.xlsx` (`openpyxl`), chosen by
the output path's extension — no new dependency needed.

**Frame schedule:** one row per `Frame`, with exactly the plan's named columns. `Frame
ID` is generated as `"{segment_id}-F{frame_no}"` (globally unique, unambiguous about
which segment it belongs to) rather than reusing the source workbooks' own single
sheet-wide counter. `Direction` is computed fresh from each frame's own start/end
coordinates (not inherited from the segment), so it's correct even for a segment whose
own reported direction might be missing or wrong. `Validation Status` is per-segment
(from the validation report below), not independently invented per frame.

**Segment validation report — consolidates, doesn't recompute:** pulls together
`ValidationIssue`s already produced by the loader (Phase 1), the connectivity graph
(Phase 2), and frame sequencing (Phase 4) into one per-segment row, and adds the two
checks the plan names that weren't yet asserted standalone:
- **First/last frame alignment** — verifies the first frame actually starts at the
  segment's own start point and the last frame ends at its own end point (not just
  "trusted by construction" — tested by feeding deliberately-misaligned synthetic frames
  directly into the validator, bypassing Phase 4, to confirm it actually catches this
  rather than passing by assumption).
- **Connected-endpoint coincidence** — reuses `Node.max_internal_deviation_mm`, which
  Phase 2 already computes as exactly this (max pairwise distance between every endpoint
  clustered into a node); attached per segment as its start/end corner classification +
  deviation.

Reported-vs-calculated cross-checks (standard frame count, custom remainder, overall
length) roll up into one `status`: `OK` / `WARNING` / `ERROR` — nothing is silently
"corrected," every disagreement is listed in `issues`. Verified the reported-value
rounding case (`400.66` vs. true `400.664002460644`) does *not* produce a false warning,
same tolerance reasoning as Phase 4.

**Validated against all four real workbooks:** zero `ERROR` statuses anywhere; exactly
one `WARNING` across all 92 segments — `testdrawing4` S15, which is precisely the
borderline near-miss case flagged back in Phase 2 (S15/S16 at 0.6319mm apart) — now
surfacing correctly in the consolidated report instead of being buried in a graph-level
issues list. This end-to-end threading (a Phase 2 finding → visible in the Phase 7
report) is good confirmation the whole pipeline is wired correctly, not just each phase
in isolation.

## Phase 8 Implementation

**Code:** `excel_to_cad/pipeline.py` (`run_pipeline` — Phases 1-7 in one call; `generate_drawing`
— adds Phase 5/6 DXF generation on top). **App:** `app.py` (Streamlit, confirmed as the
chosen interface over a plain CLI). **Tests:** `tests/test_pipeline.py`, 15 tests, all
passing.

**No hardcoded paths** (plan's explicit instruction): the workbook comes from
`st.file_uploader` as an in-memory stream handed straight to `run_pipeline`/`openpyxl`
(which reads file-like objects natively) — nothing ever touches disk for the input, and
every generated output (DXF, frame schedule, validation report) is offered as an
in-browser download built in memory, not written to a fixed location.

**UI flow matches the plan's recommended 10 steps:** upload → pick worksheet → review
detected column mapping (with manual override dropdowns for anything ambiguous or
missing, driven directly by `detect_columns`' own output — Phase 1's design already had
this hook) → configure standard frame size/tolerances/support placement/dimension style
in the sidebar → Generate → preview (rendered via `ezdxf.addons.drawing` to a matplotlib
figure, confirmed to actually look like a wall layout, not just abstract entities) → zoom
into any individual recognized corner (cropped re-render centered on that node, window
size adjustable) → validation report table → download DXF/schedule/validation report.

**Separation of concerns:** `app.py` contains UI wiring only — the actual "generate
everything" logic is `pipeline.generate_drawing()`, extracted specifically so it's
testable with plain `pytest` independent of Streamlit (which has no way to simulate a
file-upload interaction in automated tests — confirmed: `AppTest.file_uploader` doesn't
exist in the installed Streamlit version).

**Testing done:** `generate_drawing()` is tested end-to-end against all four real
workbooks (including that passing a custom `SupportPlacementConfig` or DXF styling kwarg
actually changes the output). **The full interactive browser flow was also verified** —
found Playwright + a pre-downloaded Chromium already present in this environment, used
them to drive the real running app: uploaded `testdrawing1.xlsx` through the actual
`file_uploader`, confirmed the column-mapping success message, clicked **Generate CAD
drawing**, confirmed the drawing preview rendered as a recognizable wall layout (not just
abstract entities), switched the corner-zoom dropdown between two different corners and
confirmed the rendered zoom + dimension values updated correctly each time (e.g. switching
to node `W1:N4` showed its actual `1878.02`mm reference dimension and `1200`/`678.02`mm
frame dimensions, matching segment S3's real data), and downloaded all four output files
(DXF, PNG, frame schedule CSV, validation CSV) through real browser download clicks —
every file was then independently re-opened and verified valid (the DXF via
`ezdxf.readfile`, matching entity/layer counts; the CSVs via their headers and row data).
Zero browser console errors throughout. The app works end to end, not just in isolated
unit tests.

### Important fix found while reviewing Phase 9 coverage: multi-wall connectivity bug

While mapping Phase 9's 15 required test scenarios onto existing coverage, realized
`run_pipeline` was calling `build_connectivity_graph` directly on **all** loaded segments
at once, regardless of `Wall ID`. Every sample workbook has exactly one wall ('W1'), so
this never surfaced — but it's a real bug: two different walls that happen to share a
coordinate (e.g. both anchored at a common grid origin, a plausible modeling convention)
would have been **silently merged into one fake junction**, directly violating the plan's
"do not silently snap or merge disconnected geometry" rule.

**Fixed:** added `connectivity.build_merged_connectivity_graph()` — groups segments by
Wall ID, builds each wall's graph completely independently (so cross-wall coincidence is
structurally impossible), then combines the results with wall-prefixed node IDs
(`"W1:N1"`, `"W2:N1"`, ...) so they stay globally unique. `run_pipeline` now routes
through this instead of the single-wall function. Behaves identically to
`build_connectivity_graph` for single-wall input (confirmed against all four real
workbooks — same node/t-junction counts, same closed-component results), so nothing
regressed.

Also added a (separate, lesser) safety net: if the same Segment ID appears in more than
one wall, a warning is now raised, since `frames.py`/`reports.py` key some internal
lookups by `segment_id` alone and assume it's unique workbook-wide — true in every sample
seen so far, but not guaranteed by the schema. Flagged rather than silently colliding;
not a full composite-key refactor, since there's no real data yet exercising this.

## Phase 9 Implementation

Rather than writing a separate late-stage test suite, tests for each of the plan's 15
named scenarios were written as part of the phase that first made them meaningful to
test — so "Phase 9" here is a traceability check, not new code. 215 tests total, all
passing (`.venv/bin/python -m pytest tests/ -v`).

| # | Scenario | Covered by |
|---|---|---|
| 1 | Single horizontal segment | `test_single_horizontal_segment_both_ends_disconnected`, `test_horizontal_segment_frame_placement` |
| 2 | Single vertical segment | `test_single_vertical_segment_both_ends_disconnected`, `test_vertical_segment_frame_placement` |
| 3 | Diagonal segment | `test_single_diagonal_segment_both_ends_disconnected`, `test_diagonal_segment_frame_placement` |
| 4 | 5 standard frames + custom remainder | `test_plan_worked_example_6550mm`, `test_horizontal_segment_frame_placement` |
| 5 | Segment exactly divisible by 1200mm | `test_exact_multiple_has_no_remainder`, `test_exact_multiple_segment_has_no_custom_frame_line` |
| 6 | Segment shorter than 1200mm | `test_segment_shorter_than_standard_length`, `test_segment_shorter_than_standard_is_single_custom_frame`, real: `test_testdrawing3_s5_shorter_than_standard_is_single_custom_frame` |
| 7 | Connected right-angle corner | `test_right_angle_corner`, `test_right_angle_corner_is_case_a_or_b_not_both` |
| 8 | Straight continuation | `test_straight_continuation`, `test_straight_continuation_is_case_c` |
| 9 | Diagonal corner | `test_diagonal_connection`, `test_diagonal_meeting_horizontal_is_case_d`, `test_diagonal_meeting_at_exact_right_angle_is_case_d_not_a_or_b` |
| 10 | Three-member junction | `test_three_member_junction` (both connectivity and corners) |
| 11 | Closed rectangular perimeter | `test_closed_rectangular_perimeter`, `test_closed_rectangle_all_four_corners_are_a_or_b_plus_f`, real: `test_testdrawing1_is_mostly_one_closed_perimeter` |
| 12 | Corner with a custom frame | `test_custom_ending_member_meets_standard_starting_member_gives_both_g_and_h` (case H) |
| 13 | Disconnected endpoint | `test_disconnected_endpoint_is_reported_not_silently_closed`, `test_disconnected_endpoint_has_no_corner_case_and_no_bracket_symbol` |
| 14 | Duplicate source geometry | `test_duplicate_geometry_is_flagged` |
| 15 | Multiple walls and segments | `test_group_by_wall_separates_independent_walls`, `test_merged_graph_does_not_connect_two_walls_sharing_a_coordinate`, `test_run_pipeline_does_not_cross_connect_two_walls_sharing_a_coordinate` — this scenario is what surfaced the multi-wall connectivity bug fixed in Phase 8 |

Additional plan requirements beyond the 15 scenarios, also covered: "valid corners
remain connected and invalid connections are reported" (every connectivity/corner test
above asserts both halves); "check the actual DXF entities and coordinates, not just
visual previews" (`test_dxf_export.py` checks real entity counts per layer and every
dimension's `get_measurement()` against the actual frame/segment length, for all four
real workbooks).

## Relationship to the Existing SolidWorks Script

`recreate_drawing.py` (the hardcoded single-panel SolidWorks COM automation script) was
built for a *different* delivery path entirely: SolidWorks COM automation for one
specific 2-bracket fence-panel shape, with length as the only free parameter. It is
**not** the engine for this new project (different tech stack — `ezdxf`/DXF, not
SolidWorks COM; different geometry model — arbitrary multi-segment connectivity graph,
not a fixed 2-endpoint bracket template). It stays in the repo as prior art / reference
only. The standard/custom frame-count math (`floor(L/F)` + remainder) it already contains
is conceptually the same rule needed in Phase 4, but the implementation itself will be
rebuilt against whatever the real Excel schema turns out to be.

## Status: All 10 Phases Complete

Nothing left queued from the original plan. `README.md` now carries the user-facing
install/run instructions, algorithm summary, and assumptions/limitations list; this file
remains the detailed per-phase design log for anyone who wants the full reasoning behind
a specific decision.

**Known residual gaps (not blockers, just not built):**
- No standalone PDF export (PNG download exists, using the same render as the live
  preview).
- The duplicate-segment-ID-across-walls scenario gets a warning, not a full composite-key
  fix throughout every module — no real data has exercised this yet (see README).
- Multi-wall connectivity correctness is verified with synthetic test data and confirmed
  end-to-end via the browser-driven manual test above — but no *sample workbook*
  actually has more than one wall, so it's never been exercised against a real
  multi-wall file.

**Manual browser verification (2026-11-22):** drove the real running app with Playwright
+ Chromium — uploaded a real workbook, generated a drawing, switched corners, downloaded
and re-validated all four output files. See "Phase 8 Implementation" above for the full
account. No issues found; the app works as designed.

If/when a real reference CAD screenshot becomes available, only `dxf_export.py` needs
revisiting — everything upstream (geometry, connectivity, corners, frames) is independent
of visual styling.

## Open Questions (to resolve as we go, not blocking Phase 1b start)

- Units: column is literally named `Length (mm)` and magnitudes are consistent with mm
  (segments in the thousands) — treating as always-mm unless a future workbook says
  otherwise. Low risk, not blocking.
- Multi-wall: all four samples use `Wall ID = 'W1'` only — multi-wall-per-sheet is
  unexercised by current samples. Still building it per the plan, just can't verify
  against real multi-wall data yet; will need a synthetic test fixture for Phase 9 test
  15 ("multiple walls and segments").
- Support symbol geometry: none of the four workbooks contain bracket/support data — only
  geometry + frame schedule. Confirmed we're on the Phase 6 placeholder-symbol path unless
  a DXF/DWG export becomes available.
- Streamlit vs. plain CLI for Phase 8 — still open, confirm once Phases 1–5 are solid.
- The four `testdrawingN.xlsx` files appear to be genuinely different wall layouts of
  increasing complexity (12 / 20 / 29 / 31 segments; only testdrawing4 has a diagonal
  member) rather than variations of one wall — treating them as 4 independent real-world
  regression fixtures, and will still build minimal synthetic fixtures for Phase 9's
  specific scenario list (exact-multiple-of-1200, sub-1200, closed perimeter, etc.) where
  these four don't already cover a case.
