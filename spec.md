# Beam Designer (Desktop)

## Purpose
A Python desktop app that draws shear, moment, and deflection diagrams for a
single-span beam, and checks whether a steel W-shape or lumber member is strong
enough (bending and shear) and stiff enough (deflection).

This is the desktop version of the web Beam Designer in `index.html`. Use
`index.html` as the reference for behavior: the desktop app must give the same
numbers for the same inputs and offer the same tools, adapted to Tkinter as
described below.

## Platform
- Python 3.10 or newer, with a Tkinter GUI (`tkinter` and `tkinter.ttk`).
- Use the Python standard library only, so there is nothing to install. Draw all
  plots on a Tkinter `Canvas`. Do not use matplotlib, NumPy, or Pillow.
- Runs on macOS and Windows. Start it with `python beam_app.py` (`python3` on
  macOS). Note for macOS: the python.org installer includes Tkinter. Homebrew
  Python needs the `python-tk` package.

## Files
- `beam_app.py`: the Tkinter window, input widgets, drawing, and event handling.
  It runs the app when started.
- `beam_calc.py`: the calculation engine, with no Tkinter imports. It takes the
  inputs (support, span, loads, section, options) and returns reactions; V, M,
  and deflection arrays; check results; and the reserve factor. The GUI calls
  only this module for calculations, so it can be tested without opening a
  window.
- `sections.py`: the W-shape and lumber tables below, with source citations in
  comments.
- `test_validation.py`: `unittest` tests for the six validation cases and the
  design-file format. Run them with `python -m unittest`.
- `*.beam`: saved designs (see Saving and opening designs).
- `index.html`: the web reference app. Do not change it.

## Assumptions
- Single span only: simply supported or cantilever (fixed at the left end).
- The compression flange or edge is continuously braced, so there is no lateral-torsional buckling.
- Linear elastic behavior and small deflections.
- Bending is about the strong axis only.
- Steel is A992: Fy = 50 ksi, E = 29,000 ksi.
- Lumber is Douglas Fir-Larch No. 2, dry service, normal temperature, loaded on its narrow face.
- **Sign convention:** x is measured from the left end. Downward loads are entered as positive. Positive moment means sagging. Downward deflection is shown below the beam.
- **Units:** inputs are in ft, kips, and kip/ft. Section properties are in inches. The app converts units internally.

## Inputs
All inputs sit in a panel on the left side of the window.

- **Support type:** radio buttons for simply supported or cantilever.
- **Span L** (ft): an entry field.
- **Point loads:** a table (`ttk.Treeview`) with columns P (kips), x (ft), and Dead/Live. Add, Edit, and Remove buttons sit under it. Add and Edit open a small dialog with fields for each value.
- **Uniform loads:** a second table with columns w (kip/ft), start (ft), end (ft), and Dead/Live, with the same buttons. Partial-length uniform loads are allowed.
- **Self-weight checkbox:** adds the member's own weight as a dead uniform load over the full span. It is off by default.
- **Deflection limits:** two entries for the limit denominators, shown as "L / [360]" for live load and "L / [240]" for total load. The prefix reads "2L /" for a cantilever. Defaults are 360 and 240, and each must be a number greater than 0.
- **Material and section:**
  - Material: radio buttons for Steel or Lumber.
  - Section: a read-only combobox listing the sections for the chosen material.
  - Lumber only: a C_D entry (default 1.0) and a repetitive-member checkbox (C_r). Disable these when Steel is chosen.
- **Input checks:** span must be greater than 0, and loads must lie within the span. When an input is invalid, outline the bad field in red and show a clear message in the status bar at the bottom of the window. Keep the last valid results on screen, grayed out, until the input is fixed. With no loads, show zero diagrams.

## Section data
Store the data in `sections.py`, with the source for each table in a comment.

### Steel W-shapes (AISC Shapes Database v16.0)
Fields: d, tw, A, Ix, Sx, Zx, and weight (lb/ft). Verify every value against the AISC database before release.

| Shape | A (in²) | d (in) | tw (in) | Ix (in⁴) | Sx (in³) | Zx (in³) |
|---|---|---|---|---|---|---|
| W8x10 | 2.96 | 7.89 | 0.170 | 30.8 | 7.81 | 8.87 |
| W8x18 | 5.26 | 8.14 | 0.230 | 61.9 | 15.2 | 17.0 |
| W10x12 | 3.54 | 9.87 | 0.190 | 53.8 | 10.9 | 12.6 |
| W10x22 | 6.49 | 10.2 | 0.240 | 118 | 23.2 | 26.0 |
| W12x14 | 4.16 | 11.9 | 0.200 | 88.6 | 14.9 | 17.4 |
| W12x26 | 7.65 | 12.2 | 0.230 | 204 | 33.4 | 37.2 |
| W14x22 | 6.49 | 13.7 | 0.230 | 199 | 29.0 | 33.2 |
| W16x26 | 7.68 | 15.7 | 0.250 | 301 | 38.4 | 44.2 |
| W18x35 | 10.3 | 17.7 | 0.300 | 510 | 57.6 | 66.5 |
| W21x44 | 13.0 | 20.7 | 0.350 | 843 | 81.6 | 95.4 |
| W24x55 | 16.2 | 23.6 | 0.395 | 1350 | 114 | 134 |

### Lumber, DF-L No. 2 (NDS Supplement)
Use actual dimensions b × d. Compute A = bd, S = bd²/6, and I = bd³/12.

| Size | b × d (in) | Table | Fb (psi) | Fv (psi) | E (psi) | C_F (bending) |
|---|---|---|---|---|---|---|
| 2x6 | 1.5 × 5.5 | 4A | 900 | 180 | 1,600,000 | 1.3 |
| 2x8 | 1.5 × 7.25 | 4A | 900 | 180 | 1,600,000 | 1.2 |
| 2x10 | 1.5 × 9.25 | 4A | 900 | 180 | 1,600,000 | 1.1 |
| 2x12 | 1.5 × 11.25 | 4A | 900 | 180 | 1,600,000 | 1.0 |
| 4x6 | 3.5 × 5.5 | 4A | 900 | 180 | 1,600,000 | 1.3 |
| 4x8 | 3.5 × 7.25 | 4A | 900 | 180 | 1,600,000 | 1.3 |
| 4x10 | 3.5 × 9.25 | 4A | 900 | 180 | 1,600,000 | 1.2 |
| 4x12 | 3.5 × 11.25 | 4A | 900 | 180 | 1,600,000 | 1.1 |
| 6x10 | 5.5 × 9.5 | 4D (B&S) | 875 | 170 | 1,300,000 | 1.0 |
| 6x12 | 5.5 × 11.5 | 4D (B&S) | 875 | 170 | 1,300,000 | 1.0 |

C_r = 1.15 applies only to 2x and 4x members, when the repetitive-member checkbox is on. Lumber self-weight uses 35 lb/ft³. Verify the table values against the NDS Supplement before release.

## Calculations
All calculations live in `beam_calc.py`.

1. **Reactions** from statics.
2. **Shear and moment:** step along the beam at 2000 points plus every load location, adding in each point load and uniform load.
3. **Deflection:** integrate M/EI twice numerically, then apply the boundary conditions:
   - Simply supported: y = 0 at both supports.
   - Cantilever: y = 0 and slope = 0 at the fixed end.
4. **Deflection cases:** run the analysis three times — live loads only, dead loads only, and total (dead + live).
5. **Bending check:** fb = M_max / S must not exceed the allowable stress.
   - Steel: Fb = 0.66Fy = 33 ksi.
   - Lumber: Fb′ = Fb · C_D · C_F · C_r.
6. **Shear check:**
   - Steel: Va = 0.6 · Fy · d · tw / 1.50, with Cv = 1.0. This holds for all listed shapes.
   - Lumber: fv = 1.5 V_max / A must not exceed Fv′ = Fv · C_D.
7. **Deflection check:** compare against the limits set in the inputs.
   - Live-load deflection ≤ L/n_live (default L/360).
   - Total-load deflection ≤ L/n_total (default L/240).
   - For a cantilever, use 2L in place of L.

## Window layout
- **Left:** the input panel, scrollable if the window is short.
- **Center:** four plots stacked on one `Canvas` (or four canvases with the same width and margins): the beam sketch, then shear, moment, and deflection.
- **Right:** a `ttk.Notebook` with tabs for Summary, Stresses at Probe, Section Comparison, and Validation.
- **Bottom:** a status bar for input messages and the overall PASS/FAIL result.
- **Menu bar:** File (Open, Save, Save As, Save Report, Save Diagrams, Quit) and Help (About).
- The window opens at 1280 × 800, can be resized down to 1000 × 680, and the plots redraw to fit when it is resized.

## Outputs
- **Beam sketch:** the beam with supports, loads (Dead and Live drawn in different styles), and reaction values.
- **Diagrams:** shear, moment, and deflection (total), each with its maximum value and that value's x location labeled.
- **Summary table:** for each check (bending, shear, live deflection, total deflection), show:
  - the demand
  - the capacity or limit
  - the ratio (demand ÷ capacity)
  - PASS or FAIL, colored green or red
- **Deflected shape:** the beam sketch draws the total-load deflected shape over the undeformed beam, scaled so the L/240 (or 2L/240) limit is about 36 px tall by default. A combobox sets the scale to auto, true scale, ×10, ×50, or ×200, and the legend always shows the factor in use. A short dashed line marks the limit at the max-deflection point.
- **Failure display:** if bending or shear fails, the beam turns red, cracks at the governing location (a vertical crack for bending, a diagonal crack for shear), and the two pieces fall with a short animation (driven by `after()` calls) and a label giving the failure mode, location, and ratio. A Replay button repeats the animation. A deflection-only failure shows the beam red and sagging (no break), because it is a serviceability limit. An "Animate failures" checkbox (on by default) turns the animation off and shows the final state instead.
- **Live updates:** results update as inputs change, using variable traces on the entry fields. Wait about 150 ms after the last keystroke before recalculating, so typing stays smooth.
- **Save Report:** writes a plain-text report (`.txt`) with the inputs, section properties, reactions, maximum values with locations, and the summary table, for turning in work. Use a save-file dialog.
- **Save Diagrams:** saves the plot canvas as an Encapsulated PostScript file (`.eps`) with `Canvas.postscript()`.

## Saving and opening designs
- **File format:** a design is saved as a `.beam` file, which is plain JSON. It holds the
  support type, span, material, section, C_D, repetitive-member setting, self-weight
  setting, deflection limits, and the list of loads (type, magnitude, position, Dead/Live).
  It also stores the app name and a format version number. The what-if multiplier is
  not saved; an opened design starts at 1×.
- **File menu:** Open (Ctrl+O, Cmd+O on macOS) reads a `.beam` file and loads it into
  the inputs. Save (Ctrl/Cmd+S) writes to the current file, or asks for a name if the
  design has not been saved yet. Save As (Ctrl/Cmd+Shift+S) always asks for a name.
- **Window title:** shows the file name ("Untitled" before the first save), with a `*`
  when there are unsaved changes.
- **Unsaved changes:** before Open, Reset to example beam, loading a validation case, or
  Quit throws away unsaved changes, ask whether to save them (Save, Don't Save, Cancel).
- **Bad files:** if a file cannot be read or is missing required values, show a clear
  message saying what is wrong and keep the current design. A file whose loads fall
  outside the span still opens, and the input checks mark those loads in red.
- Saving is blocked, with a message, while the span, C_D, or a deflection limit is not a
  number.

## Interactive tools
- **Probe:** moving the mouse over the sketch or any diagram moves a vertical probe line that stays lined up across all plots (they share the same x-axis margins). The Left and Right arrow keys also move it when a plot has focus. Each plot shows its value at the probe (Δ on the sketch, V, M, and Δ total/live on the diagrams). Clicking pins the probe, and clicking again unpins it. The probe snaps to load positions and max-value locations. By default it sits at the max-moment location.
- **Stresses at the probe:** the cross-section (lumber to scale, steel schematic), the linear bending-stress distribution with ±Fb (or ±Fb′) allowable lines, and the shear stress: average web shear V/(d·tw) for steel, parabolic with peak 1.5V/A for lumber. A readout lists x, V, M, fb/Fb, fv/Fv, and live and total Δ.
- **Drag loads:** point loads and uniform loads can be dragged along the beam in the sketch with the mouse, and uniform-load end handles stretch them. Positions round to 0.25 ft (0.05 ft for spans of 5 ft or less), and the load tables update to match.
- **What-if load multiplier:** a 0–3× `ttk.Scale` slider scales the entered loads (not self-weight). The app reports the multiplier at which the first check reaches 1.0. All ratios are linear in the multiplier, so this comes from two runs, at 0× and 1×. Validation cases use 1×.
- **Section comparison:** every section of the chosen material is checked under the same loads, sorted by weight, and shown in a table with its governing ratio, governing check, and a ratio bar. The lightest passing section is tagged. Double-clicking a row selects that section.

## Look and feel
Clean and professional, using the native `ttk` theme for the platform. Readable on a laptop screen. Opens with the W12x26 validation beam (case 1) already loaded.

## Validation
All cases must match within 0.5%. Self-weight is off and the deflection limits are the defaults (L/360 and L/240) unless stated otherwise. Check every case in `test_validation.py`. The Validation tab runs the same cases from inside the app and shows each case's expected value, computed value, difference, and PASS/FAIL. Results must also match `index.html` for the same inputs.

1. **20 ft simply supported W12x26, 1 kip/ft live load over the full span**
   - Reactions: R = 10.0 kips; V_max = 10.0 kips; M = 50.0 kip-ft
   - fb = 18.0 ksi (≤ 33 ksi); Va = 56.1 kips
   - Deflection: 0.609 in (≤ L/360 = 0.667 in)
   - Result: PASS on all checks
2. **20 ft simply supported W12x26, 10 kip live point load at midspan**
   - M = 50.0 kip-ft
   - Deflection: PL³/48EI = 0.487 in
3. **20 ft simply supported W12x26, 10 kip live point load at x = 5 ft**
   - Reactions: R_left = 7.5 kips, R_right = 2.5 kips
   - M_max = 37.5 kip-ft at x = 5 ft
   - Deflection: Δ_max = 0.340 in at x = 8.82 ft
4. **10 ft cantilever W8x18, 2 kip live point load at the tip**
   - M = 20.0 kip-ft; fb = 15.8 ksi
   - Deflection: PL³/3EI = 0.642 in (≤ 2L/360 = 0.667 in)
5. **12 ft simply supported 2x10 DF-L No. 2, 100 plf live load, repetitive, C_D = 1.0**
   - M = 1.80 kip-ft; fb = 1010 psi (≤ Fb′ = 1139 psi)
   - Shear: fv = 64.9 psi (≤ 180 psi)
   - Deflection: 0.295 in (≤ 0.400 in)
6. **Case 1 with self-weight on (26 plf dead)**
   - M = 51.3 kip-ft
   - Total-load deflection: 0.625 in (≤ L/240 = 1.00 in)

## Out of scope
Continuous and multi-span beams, lateral-torsional buckling and other buckling, weak-axis bending, axial loads, load combinations beyond D + L, and sections not in the lists above. Also out of scope for the desktop version: packaging as a standalone executable, printing directly from the app, and dark mode.
