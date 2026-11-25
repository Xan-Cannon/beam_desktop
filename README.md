# Beam Designer (Desktop)

A Python desktop app for checking a single-span beam. You enter a simply supported or cantilever beam, its loads, and a steel W-shape or Douglas Fir-Larch lumber size. The app then:

- draws the shear, moment, and deflection diagrams
- checks bending, shear, and live- and total-load deflection, with PASS/FAIL for each
- lets you save and open designs (`.beam` files)
- exports the results along the beam to a CSV file for Excel
- saves a PDF calculation sheet to hand in with a design

## What to install

Install Python 3.10 or newer, with Tkinter. There are no other packages to install: the app uses only Python's standard library.

- **Windows and macOS:** the installer from [python.org](https://www.python.org/downloads/) includes Tkinter.
- **macOS with Homebrew Python:** also install Tkinter with `brew install python-tk`.
- **Linux:** install your distribution's Tkinter package, for example `sudo apt install python3-tk`.

## Start the app

From this folder, run:

```
python beam_app.py
```

On macOS, use `python3 beam_app.py`.

To run the tests, including the six hand-calculated validation cases:

```
python -m unittest
```
