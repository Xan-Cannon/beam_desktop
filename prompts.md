# Prompt history

- **Asked:** Set up `beam_desktop`: make the folder, initialize a git repository, copy `spec.md` and `index.html` from the first app, and write an `AGENTS.md` that keeps a prompt log and commits after every request.
  **Changed:** Created `beam_desktop` and ran `git init` on branch `main`. Copied `spec.md` and `index.html` from `beam_app`, because there is no `first_app` folder and `beam_app` is the first beam app. Added `AGENTS.md` (prompt-log and commit rules, with `index.html` as the behavior reference), this `prompts.md`, and a `.gitignore` for `.DS_Store`.
  **Worked:** Yes. The copied files match the `beam_app` originals byte for byte, and the first commit holds all five files.

- **Asked:** Make a top-level `AGENTS.md` with only two rules (log each request in `prompts.md`, and commit after each request), then commit. Build nothing else.
  **Changed:** Replaced `AGENTS.md` with the two rules. This removed the earlier note that `index.html` is the behavior reference. Added this entry.
  **Worked:** Yes. Committed.

- **Asked:** Update `spec.md` to describe a Python desktop app using Tkinter. Build nothing.
  **Changed:** Rewrote `spec.md` for a Tkinter app. Added Platform (Python 3.10+, standard library only, plots drawn on a Tkinter Canvas), Files (`beam_app.py`, `beam_calc.py` with no Tkinter, `sections.py`, `test_validation.py`), and Window layout sections. Made `index.html` the behavior reference. Replaced web-only features with desktop ones: Treeview load tables, mouse and arrow-key probe, an "Animate failures" checkbox in place of the OS reduced-motion setting, and Save Report (.txt) and Save Diagrams (.eps) in place of the print view. Kept the assumptions, section tables, calculations, and the six validation cases the same. Dropped the `01_data/` and `02_validation/` folders and moved dark mode to out of scope.
  **Worked:** Yes (spec only, no code).

- **Asked:** Read `spec.md` and build the desktop app it describes, using `index.html` as the behavior reference.
  **Changed:** Added `sections.py` (W-shape and DF-L No. 2 tables with sources), `beam_calc.py` (calculation engine with no Tkinter: statics, numerical deflection, checks, reserve factor, section comparison, validation cases, text report), `beam_app.py` (Tkinter window: input panel with load tables and Add/Edit/Remove dialogs, stacked sketch and V/M/Δ plots on a Canvas, Summary / Stresses at Probe / Section Comparison / Validation tabs, status bar, File and Help menus), and `test_validation.py` (12 `unittest` tests). Added `__pycache__/` to `.gitignore`. Started with `python3 beam_app.py`; tests run with `python3 -m unittest`.
  **Worked:** Yes. All 12 tests pass, and all 6 validation cases match the hand calculations within 0.2%. On 40 random beams the Python engine matches the `index.html` engine to about 1e-15. A scripted GUI run (hover and pin probe, arrow keys, invalid span, dragging a point load and a uniform-load handle, failure animation, lumber, cantilever, self-weight, comparison double-click, loading a validation case, no loads, resizing to 1000 × 680) raised no errors. Save Report and Save Diagrams both write files. Screenshots of the whole window were blocked (no screen-recording permission), so the canvases were checked by redrawing them to images; the ttk widgets themselves were not checked visually.
