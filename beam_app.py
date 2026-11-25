"""Beam Designer: Tkinter desktop app.

Run with:  python beam_app.py   (python3 on macOS)

All calculations come from beam_calc.py. This file handles the window, the input
widgets, drawing on Tkinter canvases, and mouse/keyboard events. index.html is
the behavior reference.
"""

from __future__ import annotations

import copy
import json
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

import beam_calc as bc
from beam_calc import fx, interp, shear_at
from sections import LUMBER, W_SHAPES

PAD_L, PAD_R = 56, 56      # shared x margins so the probe lines up on every plot
FAIL_MS = 1200             # failure animation length
DEBOUNCE_MS = 150          # wait after the last keystroke before recalculating
FACTOR_MAX = 3.0
SKETCH_MAXPX = 120         # deflected shape is clipped at this many pixels

PALETTE = {
    "bg": "#f3f5f8", "panel": "#ffffff", "ink": "#1b2430", "muted": "#5f6c7b",
    "line": "#d8dee6", "soft": "#eef2f6", "accent": "#1f5fa8", "dead": "#44515f",
    "live": "#c95f16", "pass": "#1d7a4c", "pass_bg": "#e3f3ea", "fail": "#b8322a",
    "fail_bg": "#fbe6e4", "shear": "#1f5fa8", "moment": "#7b3fa0", "defl": "#12807f",
    "beam": "#8a96a3",
}

EXAG_CHOICES = [("Auto", "auto"), ("True scale", 1), ("×10", 10), ("×50", 50), ("×200", 200)]


def _rgb(h: str):
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def blend(color: str, alpha: float, bg: str = "#ffffff") -> str:
    """Tk has no transparency, so pre-mix a color with the background."""
    c, b = _rgb(color), _rgb(bg)
    return "#%02x%02x%02x" % tuple(round(b[i] + (c[i] - b[i]) * alpha) for i in range(3))


def to_gray(color: str) -> str:
    """Washed-out gray version of a color, for stale (grayed-out) results."""
    r, g, b = _rgb(color)
    y = 0.299 * r + 0.587 * g + 0.114 * b
    y = round(150 + (y / 255) * 90)
    return "#%02x%02x%02x" % (y, y, y)


def clamp(v, a, b):
    return min(b, max(a, v))


def nice_num(v: float) -> float:
    if not (v > 0) or not math.isfinite(v):
        return 1.0
    p = 10 ** math.floor(math.log10(v))
    m = v / p
    return (1 if m < 1.5 else 2 if m < 3.5 else 5 if m < 7.5 else 10) * p


def ease_out_bounce(t: float) -> float:
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def rnd(i: int, k: int) -> float:
    s = math.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return s - math.floor(s)


def rotate_pts(pts, deg, cx, cy):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * ca - (y - cy) * sa, cy + (x - cx) * sa + (y - cy) * ca) for x, y in pts]


def flat(pts):
    return [c for p in pts for c in p]


def short_label(s: str) -> str:
    return s.split(",")[0].lower()


def parse_float(s: str) -> float:
    try:
        return float(s.strip())
    except (ValueError, AttributeError):
        return math.nan


def fmt_num(v) -> str:
    return f"{v:g}" if bc.is_num(v) else ""


# =====================================================================
class LoadDialog(tk.Toplevel):
    """Add/Edit dialog for one load."""

    def __init__(self, parent, title, kind, values):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent)
        self.resizable(False, False)
        self.result = None
        self.kind = kind
        frm = ttk.Frame(self, padding=14)
        frm.grid(sticky="nsew")
        fields = [("P", "Magnitude P (kips)"), ("x", "Position x (ft)")] if kind == "point" else \
                 [("w", "Magnitude w (kip/ft)"), ("x1", "Start (ft)"), ("x2", "End (ft)")]
        self.vars = {}
        first = None
        for r, (k, label) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            v = tk.StringVar(value=fmt_num(values.get(k)))
            e = ttk.Entry(frm, textvariable=v, width=12)
            e.grid(row=r, column=1, sticky="ew", padx=(10, 0), pady=3)
            self.vars[k] = v
            first = first or e
        r = len(fields)
        ttk.Label(frm, text="Load type").grid(row=r, column=0, sticky="w", pady=3)
        self.var_tag = tk.StringVar(value="Dead" if values.get("tag") == "D" else "Live")
        ttk.Combobox(frm, textvariable=self.var_tag, values=["Dead", "Live"], state="readonly",
                     width=10).grid(row=r, column=1, sticky="ew", padx=(10, 0), pady=3)
        self.msg = ttk.Label(frm, text="", foreground=PALETTE["fail"])
        self.msg.grid(row=r + 1, column=0, columnspan=2, sticky="w")
        btns = ttk.Frame(frm)
        btns.grid(row=r + 2, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self.ok, default="active").pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        px = parent.winfo_rootx() + parent.winfo_width() // 2 - self.winfo_reqwidth() // 2
        py = parent.winfo_rooty() + parent.winfo_height() // 3
        self.geometry(f"+{px}+{py}")
        self.deiconify()
        self.grab_set()
        first.focus_set()
        first.select_range(0, "end")
        self.wait_window()

    def ok(self):
        out = {}
        for k, v in self.vars.items():
            val = parse_float(v.get())
            if not math.isfinite(val):
                self.msg.config(text="Enter a number in every field.")
                return
            out[k] = val
        out["tag"] = "D" if self.var_tag.get() == "Dead" else "L"
        self.result = out
        self.destroy()


# =====================================================================
class BeamApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = bc.default_cfg()
        self.last: bc.Result | None = None   # last valid result
        self.stale = False                   # inputs invalid: show last results grayed out
        self.hover_x = None
        self.pin_x = None
        self.exag = "auto"
        self.plots: list[dict] = []          # per plot: y0, y1, X0, X1, sx, cursor(x)
        self.hits: list[tuple] = []          # sketch drag regions
        self.drag = None
        self.fail_was_strength = False
        self.fail_start = -math.inf
        self.anim_id = None
        self.pending_update = None
        self.pending_redraw = None
        self.file_path = None                # current .beam file
        self.saved_snapshot = self._snapshot()

        root.title("Beam Designer")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        root.geometry("1280x800")
        root.minsize(1000, 680)
        self._fonts()
        self._style()
        self._menu()
        self._layout()
        self.sync_inputs()
        self.update()
        self.render_validation()
        root.after(50, self._initial_sashes)

    # ------------------------------------------------------------ setup
    def _fonts(self):
        base = tkfont.nametofont("TkDefaultFont")
        fam = base.actual("family")
        self.f_small = tkfont.Font(family=fam, size=10)
        self.f_norm = tkfont.Font(family=fam, size=11)
        self.f_bold = tkfont.Font(family=fam, size=11, weight="bold")
        self.f_head = tkfont.Font(family=fam, size=13, weight="bold")
        self.f_fail = tkfont.Font(family=fam, size=13, weight="bold")

    def _style(self):
        st = ttk.Style(self.root)
        self.style = st
        st.configure("Head.TLabel", font=self.f_bold)
        st.configure("Muted.TLabel", foreground=PALETTE["muted"])
        st.configure("Pass.TLabel", foreground=PALETTE["pass"], font=self.f_bold)
        st.configure("Fail.TLabel", foreground=PALETTE["fail"], font=self.f_bold)
        st.configure("Over.TLabel", foreground=PALETTE["fail"], font=self.f_bold)
        st.configure("Value.TLabel", font=self.f_bold)
        st.configure("Verdict.TLabel", font=self.f_head)
        st.configure("Treeview", rowheight=22)
        self.frame_bg = st.lookup("TFrame", "background") or self.root.cget("bg")

    def _menu(self):
        mb = tk.Menu(self.root)
        mod = "Command" if self.root.tk.call("tk", "windowingsystem") == "aqua" else "Control"
        accel = "Cmd" if mod == "Command" else "Ctrl"
        fm = tk.Menu(mb, tearoff=False)
        fm.add_command(label="Open…", accelerator=f"{accel}+O", command=self.open_file)
        fm.add_command(label="Save", accelerator=f"{accel}+S", command=self.save_file)
        fm.add_command(label="Save As…", accelerator=f"{accel}+Shift+S", command=self.save_file_as)
        fm.add_separator()
        fm.add_command(label="Save Report…", command=self.save_report)
        fm.add_command(label="Save Diagrams…", command=self.save_diagrams)
        fm.add_command(label="Export Results (CSV)…", command=self.export_csv)
        fm.add_separator()
        fm.add_command(label="Quit", accelerator=f"{accel}+Q", command=self.quit)
        mb.add_cascade(label="File", menu=fm)
        hm = tk.Menu(mb, tearoff=False)
        hm.add_command(label="About", command=self.about)
        mb.add_cascade(label="Help", menu=hm)
        self.root.config(menu=mb)
        self.root.bind_all(f"<{mod}-o>", lambda e: self.open_file())
        self.root.bind_all(f"<{mod}-s>", lambda e: self.save_file())
        self.root.bind_all(f"<{mod}-S>", lambda e: self.save_file_as())
        self.root.bind_all(f"<{mod}-Shift-s>", lambda e: self.save_file_as())
        self.root.bind_all(f"<{mod}-q>", lambda e: self.quit())

    def _layout(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.paned = ttk.PanedWindow(self.root, orient="horizontal")
        self.paned.grid(row=0, column=0, sticky="nsew")

        left = ttk.Frame(self.paned)
        center = ttk.Frame(self.paned)
        right = ttk.Frame(self.paned)
        self.paned.add(left, weight=0)
        self.paned.add(center, weight=1)
        self.paned.add(right, weight=0)
        self._build_inputs(left)
        self._build_plots(center)
        self._build_notebook(right)

        status = ttk.Frame(self.root, padding=(10, 4))
        status.grid(row=1, column=0, sticky="ew")
        ttk.Separator(self.root).grid(row=1, column=0, sticky="new")
        status.columnconfigure(0, weight=1)
        self.status_msg = ttk.Label(status, text="", anchor="w")
        self.status_msg.grid(row=0, column=0, sticky="ew")
        self.status_verdict = ttk.Label(status, text="", anchor="e")
        self.status_verdict.grid(row=0, column=1, sticky="e")

    def _initial_sashes(self):
        self._last_w = None
        self._fit_panes()
        self.paned.bind("<Configure>", lambda e: self.root.after_idle(self._fit_panes), add="+")

    def _fit_panes(self):
        """Keep the side panels at a sensible width and give the plots the rest (re-run when the window width changes)."""
        w = self.paned.winfo_width()
        if w == self._last_w or w < 100:
            return
        self._last_w = w
        left = 280
        right = int(clamp(w - left - 420, 320, 400))
        try:
            self.paned.sashpos(0, left)
            self.paned.sashpos(1, w - right)
        except tk.TclError:
            pass

    # ------------------------------------------------------------ inputs panel
    def _build_inputs(self, parent):
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        cv = tk.Canvas(parent, highlightthickness=0, bg=self.frame_bg, width=270)
        sb = ttk.Scrollbar(parent, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        cv.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        f = ttk.Frame(cv, padding=(12, 10, 10, 10))
        win = cv.create_window(0, 0, window=f, anchor="nw")
        f.bind("<Configure>", lambda e: cv.configure(scrollregion=cv.bbox("all")))
        cv.bind("<Configure>", lambda e: cv.itemconfigure(win, width=e.width))
        self._wheel_target(cv, f)
        f.columnconfigure(1, weight=1)
        r = 0

        def head(text):
            nonlocal r
            ttk.Label(f, text=text, style="Head.TLabel").grid(row=r, column=0, columnspan=2, sticky="w", pady=(10 if r else 0, 3))
            r += 1

        # Support
        head("Support")
        self.var_support = tk.StringVar(value="ss")
        sf = ttk.Frame(f)
        sf.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Radiobutton(sf, text="Simply supported", value="ss", variable=self.var_support,
                        command=self.on_support).pack(side="left")
        ttk.Radiobutton(sf, text="Cantilever", value="cant", variable=self.var_support,
                        command=self.on_support).pack(side="left", padx=(10, 0))
        self.support_note = ttk.Label(f, text="", style="Muted.TLabel", font=self.f_small)
        self.support_note.grid(row=r, column=0, columnspan=2, sticky="ew"); r += 1
        self._autowrap(self.support_note)

        ttk.Label(f, text="Span L (ft)").grid(row=r, column=0, sticky="w", pady=(6, 0))
        self.var_L = tk.StringVar()
        self.box_L, ent = self._outlined_entry(f, self.var_L, 10)
        self.box_L.grid(row=r, column=1, sticky="w", pady=(6, 0)); r += 1
        self.var_L.trace_add("write", lambda *a: self.schedule_update())

        # Member
        head("Member")
        self.var_material = tk.StringVar(value="steel")
        mf = ttk.Frame(f)
        mf.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        ttk.Radiobutton(mf, text="Steel", value="steel", variable=self.var_material,
                        command=self.on_material).pack(side="left")
        ttk.Radiobutton(mf, text="Lumber", value="lumber", variable=self.var_material,
                        command=self.on_material).pack(side="left", padx=(10, 0))
        self.section_label = ttk.Label(f, text="Section")
        self.section_label.grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0)); r += 1
        self.var_section = tk.StringVar()
        self.cb_section = ttk.Combobox(f, textvariable=self.var_section, state="readonly", width=14)
        self.cb_section.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        self.cb_section.bind("<<ComboboxSelected>>", lambda e: self.on_section())

        lf = ttk.Frame(f)
        lf.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(6, 0)); r += 1
        self.lbl_CD = ttk.Label(lf, text="Load duration factor C_D")
        self.lbl_CD.grid(row=0, column=0, sticky="w")
        self.var_CD = tk.StringVar()
        self.box_CD, self.ent_CD = self._outlined_entry(lf, self.var_CD, 6)
        self.box_CD.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.var_CD.trace_add("write", lambda *a: self.schedule_update())
        self.var_rep = tk.BooleanVar()
        self.chk_rep = ttk.Checkbutton(lf, text="Repetitive member (C_r = 1.15)", variable=self.var_rep,
                                       command=self.on_simple_change)
        self.chk_rep.grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self.var_self = tk.BooleanVar()
        ttk.Checkbutton(f, text="Include self-weight (dead)", variable=self.var_self,
                        command=self.on_simple_change).grid(row=r, column=0, columnspan=2, sticky="w", pady=(6, 0)); r += 1

        # Deflection limits
        head("Deflection limits")
        df = ttk.Frame(f)
        df.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        self.var_live_lim = tk.StringVar()
        self.var_total_lim = tk.StringVar()
        self.lim_prefix = []
        for row, (label, var) in enumerate((("Live load", self.var_live_lim), ("Total load", self.var_total_lim))):
            ttk.Label(df, text=label).grid(row=row, column=0, sticky="w", pady=2)
            pre = ttk.Label(df, text="L /", width=4, anchor="e")
            pre.grid(row=row, column=1, sticky="e", padx=(8, 2))
            self.lim_prefix.append(pre)
            box, _ent = self._outlined_entry(df, var, 6)
            box.grid(row=row, column=2, sticky="w")
            var.trace_add("write", lambda *a: self.schedule_update())
            if row == 0:
                self.box_live_lim = box
            else:
                self.box_total_lim = box

        # Loads
        head("Point loads")
        self.tree_pt = self._load_table(f, r, ("P", "x", "tag"), ("P (kips)", "x (ft)", "Type"), (70, 70, 60), "point")
        r += 2
        head("Uniform loads")
        self.tree_udl = self._load_table(f, r, ("w", "x1", "x2", "tag"), ("w (k/ft)", "Start", "End", "Type"),
                                         (62, 52, 52, 50), "udl")
        r += 2

        # What-if multiplier
        head("What-if load multiplier")
        ff = ttk.Frame(f)
        ff.grid(row=r, column=0, columnspan=2, sticky="ew"); r += 1
        ff.columnconfigure(0, weight=1)
        self.var_factor = tk.DoubleVar(value=1.0)
        self.scale_factor = ttk.Scale(ff, from_=0, to=FACTOR_MAX, variable=self.var_factor, command=self.on_factor)
        self.scale_factor.grid(row=0, column=0, sticky="ew")
        self.lbl_factor = ttk.Label(ff, text="×1.00", width=6, style="Value.TLabel")
        self.lbl_factor.grid(row=0, column=1, padx=(6, 0))
        self.factor_track = tk.Canvas(ff, height=6, highlightthickness=0, bg=self.frame_bg)
        self.factor_track.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.factor_track.bind("<Configure>", lambda e: self.render_factor())
        self.lbl_reserve = ttk.Label(f, text="", font=self.f_small)
        self.lbl_reserve.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(4, 0)); r += 1
        self._autowrap(self.lbl_reserve)
        ttk.Button(f, text="Reset to 1×", command=lambda: self.set_factor(1.0)).grid(
            row=r, column=0, sticky="w", pady=(4, 0)); r += 1

        ttk.Separator(f).grid(row=r, column=0, columnspan=2, sticky="ew", pady=10); r += 1
        ttk.Button(f, text="Reset to example beam", command=self.reset).grid(row=r, column=0, columnspan=2, sticky="w")

    def _wheel_target(self, canvas, *widgets):
        """Scroll a canvas with the mouse wheel while the pointer is over it."""
        def wheel(e):
            d = e.delta
            if abs(d) >= 120:
                d //= 120
            if canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(-d, "units")
        def on(_e):
            canvas.bind_all("<MouseWheel>", wheel)
            canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-1, "units"))
            canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(1, "units"))
        def off(_e):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")
        for w in (canvas, *widgets):
            w.bind("<Enter>", on, add="+")
            w.bind("<Leave>", off, add="+")

    @staticmethod
    def _autowrap(label):
        """Wrap a label's text to whatever width the layout gives it."""
        label.bind("<Configure>", lambda e: label.configure(wraplength=max(80, e.width - 4)), add="+")

    def _outlined_entry(self, parent, var, width):
        """An entry inside a thin frame that turns red when the value is invalid."""
        box = tk.Frame(parent, bg=self.frame_bg, padx=2, pady=2)
        ent = ttk.Entry(box, textvariable=var, width=width)
        ent.pack()
        return box, ent

    def _load_table(self, f, r, cols, heads, widths, kind):
        tree = ttk.Treeview(f, columns=cols, show="headings", height=4, selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor="e" if c != "tag" else "center", stretch=True)
        tree.tag_configure("invalid", foreground=PALETTE["fail"], background=PALETTE["fail_bg"])
        tree.grid(row=r, column=0, columnspan=2, sticky="ew")
        tree.bind("<Double-1>", lambda e: self.edit_load(kind))
        tree.bind("<Delete>", lambda e: self.remove_load(kind))
        tree.bind("<BackSpace>", lambda e: self.remove_load(kind))
        bf = ttk.Frame(f)
        bf.grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Button(bf, text="Add", width=7, command=lambda: self.add_load(kind)).pack(side="left")
        ttk.Button(bf, text="Edit", width=7, command=lambda: self.edit_load(kind)).pack(side="left", padx=4)
        ttk.Button(bf, text="Remove", width=8, command=lambda: self.remove_load(kind)).pack(side="left")
        return tree

    # ------------------------------------------------------------ plots
    def _build_plots(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        tb = ttk.Frame(parent, padding=(8, 6))
        tb.grid(row=0, column=0, sticky="ew")
        ttk.Label(tb, text="Deflected shape:").pack(side="left")
        self.var_exag = tk.StringVar(value="Auto")
        cb = ttk.Combobox(tb, textvariable=self.var_exag, values=[c[0] for c in EXAG_CHOICES], state="readonly", width=10)
        cb.pack(side="left", padx=(4, 8))
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_exag())
        self.lbl_exag = ttk.Label(tb, text="", style="Muted.TLabel")
        self.lbl_exag.pack(side="left")
        self.var_animate = tk.BooleanVar(value=True)
        ttk.Checkbutton(tb, text="Animate failures", variable=self.var_animate).pack(side="right")
        ttk.Button(tb, text="Export CSV…", command=self.export_csv).pack(side="right", padx=(0, 10))
        self.btn_replay = ttk.Button(tb, text="Replay", command=self.replay)
        self.btn_replay_shown = False

        holder = ttk.Frame(parent)
        holder.grid(row=1, column=0, sticky="nsew")
        holder.columnconfigure(0, weight=1)
        holder.rowconfigure(0, weight=1)
        self.cv = tk.Canvas(holder, bg=PALETTE["panel"], highlightthickness=1,
                            highlightbackground=PALETTE["line"], highlightcolor=PALETTE["accent"], takefocus=1)
        self.cv_sb = ttk.Scrollbar(holder, orient="vertical", command=self.cv.yview)
        self.cv.configure(yscrollcommand=self.cv_sb.set)
        self.cv.grid(row=0, column=0, sticky="nsew")
        self.cv_sb.grid(row=0, column=1, sticky="ns")
        self._wheel_target(self.cv)

        ttk.Label(parent, style="Muted.TLabel", font=self.f_small, padding=(8, 4),
                  text="Drag a load to move it (drag the round handles to stretch a uniform load). "
                       "Move the mouse over any plot to read values; click to pin the probe, click again to "
                       "unpin; arrow keys move it (Shift for bigger steps).").grid(row=2, column=0, sticky="ew")

        self.cv.bind("<Configure>", lambda e: self.schedule_redraw())
        self.cv.bind("<Motion>", self.on_motion)
        self.cv.bind("<Leave>", self.on_leave, add="+")
        self.cv.bind("<ButtonPress-1>", self.on_press)
        self.cv.bind("<B1-Motion>", self.on_motion)
        self.cv.bind("<ButtonRelease-1>", self.on_release)
        for key, step in (("<Left>", -1), ("<Right>", 1), ("<Shift-Left>", -5), ("<Shift-Right>", 5)):
            self.cv.bind(key, lambda e, s=step: self.on_key_step(s))
        self.cv.bind("<Home>", lambda e: self.on_key_to(0))
        self.cv.bind("<End>", lambda e: self.on_key_to(None))

    # ------------------------------------------------------------ notebook
    def _build_notebook(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        nb = ttk.Notebook(parent)
        nb.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=6)
        self.nb = nb
        self._build_summary(nb)
        self._build_stress(nb)
        self._build_compare(nb)
        self._build_validation(nb)

    def _build_summary(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Summary")
        f.columnconfigure(0, weight=1)
        self.lbl_verdict = ttk.Label(f, text="", style="Verdict.TLabel")
        self.lbl_verdict.grid(row=0, column=0, sticky="w")
        self.lbl_note = ttk.Label(f, text="", style="Muted.TLabel")
        self.lbl_note.grid(row=1, column=0, sticky="ew", pady=(2, 8))
        self._autowrap(self.lbl_note)

        g = ttk.Frame(f)
        g.grid(row=2, column=0, sticky="ew")
        g.columnconfigure(0, weight=1)
        for c, h in enumerate(("Check", "Demand", "Capacity", "Ratio", "")):
            ttk.Label(g, text=h, style="Muted.TLabel", font=self.f_small).grid(
                row=0, column=c, sticky="w" if c == 0 else "e", padx=(0 if c == 0 else 8, 0))
        ttk.Separator(g).grid(row=1, column=0, columnspan=5, sticky="ew", pady=2)
        self.check_rows = []
        for i in range(4):
            rr = 2 + i * 2
            name = ttk.Label(g, text="", wraplength=130)
            cap_lbl = ttk.Label(g, text="", style="Muted.TLabel", font=self.f_small)
            dem = ttk.Label(g, text="")
            cap = ttk.Label(g, text="")
            rf = ttk.Frame(g)
            bar = tk.Canvas(rf, width=40, height=8, highlightthickness=0, bg=self.frame_bg)
            bar.pack(side="left", padx=(0, 4))
            rat = ttk.Label(rf, text="", width=5, anchor="e")
            rat.pack(side="left")
            res = ttk.Label(g, text="", width=5, anchor="e")
            name.grid(row=rr, column=0, sticky="w", pady=(4, 0))
            cap_lbl.grid(row=rr + 1, column=0, columnspan=3, sticky="w")
            dem.grid(row=rr, column=1, sticky="e", padx=(8, 0), pady=(4, 0))
            cap.grid(row=rr, column=2, sticky="e", padx=(8, 0), pady=(4, 0))
            rf.grid(row=rr, column=3, sticky="e", padx=(8, 0), pady=(4, 0))
            res.grid(row=rr, column=4, sticky="e", padx=(8, 0), pady=(4, 0))
            self.check_rows.append((name, cap_lbl, dem, cap, bar, rat, res))

        self.lbl_react = ttk.Label(f, text="")
        self.lbl_react.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self._autowrap(self.lbl_react)
        ttk.Separator(f).grid(row=4, column=0, sticky="ew", pady=10)
        ttk.Label(f, text="Section properties", style="Head.TLabel").grid(row=5, column=0, sticky="w")
        pf = ttk.Frame(f)
        pf.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        pf.columnconfigure(1, weight=1)
        self.prop_rows = []
        for i in range(9):
            k = ttk.Label(pf, text="", style="Muted.TLabel")
            v = ttk.Label(pf, text="")
            k.grid(row=i, column=0, sticky="w")
            v.grid(row=i, column=1, sticky="e")
            self.prop_rows.append((k, v))

    def _build_stress(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Stresses at Probe")
        f.columnconfigure(0, weight=1)
        self.lbl_xsec = ttk.Label(f, text="", style="Head.TLabel")
        self.lbl_xsec.grid(row=0, column=0, sticky="w")
        self.cv_xsec = tk.Canvas(f, height=290, bg=PALETTE["panel"], highlightthickness=1,
                                 highlightbackground=PALETTE["line"])
        self.cv_xsec.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        self.cv_xsec.bind("<Configure>", lambda e: self.draw_cursors())
        rf = ttk.Frame(f)
        rf.grid(row=2, column=0, sticky="ew")
        rf.columnconfigure(1, weight=1)
        self.read_rows = []
        for i in range(7):
            k = ttk.Label(rf, text="", style="Muted.TLabel")
            v = ttk.Label(rf, text="", style="Value.TLabel")
            k.grid(row=i, column=0, sticky="w", pady=1)
            v.grid(row=i, column=1, sticky="e", pady=1)
            self.read_rows.append((k, v))

    def _build_compare(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Section Comparison")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        hint = ttk.Label(f, text="Every section of this material under the same loads. Double-click a row to use it.",
                         style="Muted.TLabel")
        hint.grid(row=0, column=0, sticky="ew")
        self._autowrap(hint)
        self.cv_cmp = tk.Canvas(f, bg=PALETTE["panel"], highlightthickness=1, highlightbackground=PALETTE["line"])
        self.cv_cmp.grid(row=1, column=0, sticky="nsew", pady=(6, 4))
        self.cv_cmp.bind("<Configure>", lambda e: self.render_compare())
        self.cv_cmp.bind("<Double-1>", self.on_compare_dclick)
        self.cv_cmp.bind("<Motion>", self.on_compare_motion)
        self.cv_cmp.bind("<Leave>", lambda e: self.render_compare(hover=None))
        foot = ttk.Label(f, text="Bar length is the governing ratio of the four checks; the dark tick marks 1.0. "
                                 "Sorted lightest to heaviest.", style="Muted.TLabel", font=self.f_small)
        foot.grid(row=2, column=0, sticky="ew")
        self._autowrap(foot)
        self.cmp_rows = []
        self.cmp_hover = None

    def _build_validation(self, nb):
        f = ttk.Frame(nb, padding=10)
        nb.add(f, text="Validation")
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        self.lbl_valid = ttk.Label(f, text="", style="Head.TLabel")
        self.lbl_valid.grid(row=0, column=0, sticky="w")
        tv = ttk.Treeview(f, columns=("exp", "got", "diff", "ok"), show="tree headings", selectmode="browse")
        tv.heading("#0", text="Case / quantity")
        tv.heading("exp", text="Hand calc")
        tv.heading("got", text="App")
        tv.heading("diff", text="Diff")
        tv.heading("ok", text="")
        tv.column("#0", width=170, stretch=True)
        tv.column("exp", width=62, anchor="e", stretch=False)
        tv.column("got", width=62, anchor="e", stretch=False)
        tv.column("diff", width=54, anchor="e", stretch=False)
        tv.column("ok", width=28, anchor="center", stretch=False)
        tv.tag_configure("case", font=self.f_bold)
        tv.tag_configure("ok", foreground=PALETTE["pass"])
        tv.tag_configure("bad", foreground=PALETTE["fail"])
        tv.grid(row=1, column=0, sticky="nsew", pady=(6, 6))
        tv.bind("<Double-1>", lambda e: self.load_validation_case())
        self.tv_valid = tv
        ttk.Button(f, text="Load selected case", command=self.load_validation_case).grid(row=2, column=0, sticky="w")
        ttk.Label(f, text="Each case must match the hand calculation within 0.5%.", style="Muted.TLabel",
                  font=self.f_small).grid(row=3, column=0, sticky="w", pady=(6, 0))

    # ------------------------------------------------------------ colors
    def col(self, name: str, alpha: float | None = None) -> str:
        c = PALETTE[name]
        if alpha is not None:
            c = blend(c, alpha)
        return to_gray(c) if self.stale and name not in ("panel", "bg") else c

    # ------------------------------------------------------------ input events
    def sync_inputs(self):
        """Copy self.cfg into the widgets."""
        c = self.cfg
        self._syncing = True
        self.var_support.set(c["support"])
        self.var_material.set(c["material"])
        self.var_L.set(fmt_num(c["L"]))
        self.var_CD.set(fmt_num(c["CD"]))
        self.var_rep.set(c["repetitive"])
        self.var_self.set(c["self_weight"])
        self.var_live_lim.set(fmt_num(c.get("live_limit", bc.DEFAULT_LIVE_LIMIT)))
        self.var_total_lim.set(fmt_num(c.get("total_limit", bc.DEFAULT_TOTAL_LIMIT)))
        self.var_factor.set(c.get("factor", 1.0))
        self.fill_sections()
        self.render_load_tables()
        self._syncing = False

    def fill_sections(self):
        steel = self.cfg["material"] == "steel"
        lst = W_SHAPES if steel else LUMBER
        self.cb_section.configure(values=[s["name"] for s in lst])
        self.var_section.set(self.cfg["section"])
        self.section_label.config(text="W-shape (A992, Fy = 50 ksi)" if steel else "Size (Douglas Fir-Larch No. 2)")
        state = "disabled" if steel else "normal"
        self.ent_CD.configure(state=state)
        self.chk_rep.configure(state=state)
        self.lbl_CD.configure(style="Muted.TLabel" if steel else "TLabel")

    def read_inputs(self):
        """Copy the typed fields into self.cfg."""
        self.cfg["L"] = parse_float(self.var_L.get())
        self.cfg["CD"] = parse_float(self.var_CD.get())
        self.cfg["live_limit"] = parse_float(self.var_live_lim.get())
        self.cfg["total_limit"] = parse_float(self.var_total_lim.get())

    def schedule_update(self):
        if getattr(self, "_syncing", False):
            return
        if self.pending_update:
            self.root.after_cancel(self.pending_update)
        self.pending_update = self.root.after(DEBOUNCE_MS, self.update)

    def on_support(self):
        self.cfg["support"] = self.var_support.get()
        self.update()

    def on_material(self):
        m = self.var_material.get()
        if m == self.cfg["material"]:
            return
        self.cfg["material"] = m
        self.cfg["section"] = "W12x26" if m == "steel" else "2x10"
        self.fill_sections()
        self.update()

    def on_section(self):
        self.cfg["section"] = self.var_section.get()
        self.update()

    def on_simple_change(self):
        self.cfg["repetitive"] = self.var_rep.get()
        self.cfg["self_weight"] = self.var_self.get()
        self.update()

    def on_factor(self, _v=None):
        v = round(self.var_factor.get() / 0.05) * 0.05
        v = round(v, 2)
        if abs(v - self.cfg.get("factor", 1.0)) < 1e-9:
            return
        self.cfg["factor"] = v
        self.update()

    def set_factor(self, v):
        self.var_factor.set(v)
        self.cfg["factor"] = v
        self.update()

    def on_exag(self):
        label = self.var_exag.get()
        self.exag = next(v for k, v in EXAG_CHOICES if k == label)
        self.redraw()

    def reset(self):
        if not self.maybe_save():
            return
        self.load_cfg(bc.default_cfg(), None)

    def load_cfg(self, cfg, path):
        """Replace the whole design (after Open, Reset, or loading a validation case)."""
        self.cfg = cfg
        self.cfg.setdefault("factor", 1.0)
        self.cfg.setdefault("live_limit", bc.DEFAULT_LIVE_LIMIT)
        self.cfg.setdefault("total_limit", bc.DEFAULT_TOTAL_LIMIT)
        self.file_path = path
        self.pin_x = None
        self.sync_inputs()
        if self.pending_update:
            self.root.after_cancel(self.pending_update)
        self.update()
        self.saved_snapshot = self._snapshot()
        self.update_title()

    # ------------------------------------------------------------ design files
    def _snapshot(self):
        """Everything that gets saved, for spotting unsaved changes."""
        c = dict(self.cfg)
        c.pop("factor", None)
        return json.dumps(c, sort_keys=True, default=str)

    def is_dirty(self):
        return self._snapshot() != self.saved_snapshot

    def update_title(self):
        name = os.path.basename(self.file_path) if self.file_path else "Untitled"
        self.root.title(f"{'*' if self.is_dirty() else ''}{name} — Beam Designer")

    def maybe_save(self):
        """Ask to save unsaved changes. Returns False if the user cancels."""
        if self.pending_update:
            self.root.after_cancel(self.pending_update)
            self.update()
        if not self.is_dirty():
            return True
        name = os.path.basename(self.file_path) if self.file_path else "this design"
        ans = messagebox.askyesnocancel("Unsaved changes", f"Save changes to {name} first?", parent=self.root,
                                        icon="warning")
        if ans is None:
            return False
        if ans:
            return self.save_file()
        return True

    def open_file(self):
        if not self.maybe_save():
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open Design",
                                          filetypes=[("Beam designs", "*.beam"), ("JSON files", "*.json"),
                                                     ("All files", "*.*")])
        if not path:
            return
        try:
            cfg = bc.open_design(path)
        except ValueError as e:
            messagebox.showerror("Open Design", f"Could not open {os.path.basename(path)}.\n\n{e}", parent=self.root)
            return
        self.load_cfg(cfg, path)
        self.status_msg.config(text=f"Opened {path}", foreground="")

    def save_file(self):
        """Save to the current file, or ask for a name. Returns True if saved."""
        if self.file_path is None:
            return self.save_file_as()
        return self._write_design(self.file_path)

    def save_file_as(self):
        start = os.path.basename(self.file_path) if self.file_path else "beam.beam"
        path = filedialog.asksaveasfilename(parent=self.root, title="Save Design As", defaultextension=".beam",
                                            initialfile=start,
                                            filetypes=[("Beam designs", "*.beam"), ("All files", "*.*")])
        if not path:
            return False
        return self._write_design(path)

    def _write_design(self, path):
        if self.pending_update:
            self.root.after_cancel(self.pending_update)
            self.update()
        try:
            bc.save_design(self.cfg, path)
        except ValueError as e:
            messagebox.showwarning("Save Design", str(e), parent=self.root)
            return False
        except OSError as e:
            messagebox.showerror("Save Design", f"Could not save the file.\n\n{e}", parent=self.root)
            return False
        self.file_path = path
        self.saved_snapshot = self._snapshot()
        self.update_title()
        self.status_msg.config(text=f"Saved {path}", foreground="")
        return True

    def quit(self):
        if self.maybe_save():
            self.root.destroy()

    # ------------------------------------------------------------ loads
    def span_or(self, v):
        L = self.cfg["L"]
        return L if bc.is_num(L) and L > 0 else v

    def render_load_tables(self):
        bad = set()
        if self.last_errors_fields():
            bad = self.last_errors_fields()
        for tree, kind in ((self.tree_pt, "point"), (self.tree_udl, "udl")):
            sel = tree.selection()
            tree.delete(*tree.get_children())
            for i, ld in enumerate(self.cfg["loads"]):
                if ld["type"] != kind:
                    continue
                tag = "Dead" if ld["tag"] == "D" else "Live"
                vals = (fmt_num(ld["P"]), fmt_num(ld["x"]), tag) if kind == "point" else \
                       (fmt_num(ld["w"]), fmt_num(ld["x1"]), fmt_num(ld["x2"]), tag)
                tree.insert("", "end", iid=str(i), values=vals, tags=("invalid",) if f"load-{i}" in bad else ())
            keep = [s for s in sel if tree.exists(s)]
            if keep:
                tree.selection_set(keep)

    def last_errors_fields(self):
        return getattr(self, "_err_fields", set())

    def selected_index(self, kind):
        tree = self.tree_pt if kind == "point" else self.tree_udl
        sel = tree.selection()
        if not sel:
            kids = tree.get_children()
            if len(kids) == 1:
                return int(kids[0])
            return None
        return int(sel[0])

    def add_load(self, kind):
        L = self.span_or(10.0)
        if kind == "point":
            vals = {"P": 5.0, "x": round(L / 2 if self.cfg["support"] == "ss" else L, 2), "tag": "L"}
            title = "Add point load"
        else:
            vals = {"w": 0.5, "x1": 0.0, "x2": L, "tag": "D"}
            title = "Add uniform load"
        d = LoadDialog(self.root, title, kind, vals)
        if d.result:
            self.cfg["loads"].append(dict(d.result, type=kind))
            self.update()
            tree = self.tree_pt if kind == "point" else self.tree_udl
            tree.selection_set(str(len(self.cfg["loads"]) - 1))

    def edit_load(self, kind):
        i = self.selected_index(kind)
        if i is None:
            return
        ld = self.cfg["loads"][i]
        d = LoadDialog(self.root, f"Edit {bc.load_name(self.cfg['loads'], i).lower()}", kind, ld)
        if d.result:
            self.cfg["loads"][i] = dict(d.result, type=kind)
            self.update()

    def remove_load(self, kind):
        i = self.selected_index(kind)
        if i is None:
            return
        del self.cfg["loads"][i]
        self.update()

    # ------------------------------------------------------------ update
    def update(self):
        self.pending_update = None
        self.read_inputs()
        cfg = self.cfg
        res = bc.design(cfg)
        self._err_fields = {e["field"] for e in res.errors}
        self.render_load_tables()
        self.box_L.configure(bg=PALETTE["fail"] if "L" in self._err_fields else self.frame_bg)
        self.box_CD.configure(bg=PALETTE["fail"] if "CD" in self._err_fields else self.frame_bg)
        self.box_live_lim.configure(bg=PALETTE["fail"] if "live_limit" in self._err_fields else self.frame_bg)
        self.box_total_lim.configure(bg=PALETTE["fail"] if "total_limit" in self._err_fields else self.frame_bg)
        for pre in self.lim_prefix:
            pre.configure(text="L /" if cfg["support"] == "ss" else "2L /")
        self.update_title()
        self.support_note.config(text="Pin at x = 0, roller at x = L. Deflection limits use L."
                                 if cfg["support"] == "ss" else
                                 "Fixed at x = 0, free at x = L. Deflection limits use 2L.")
        self.lbl_factor.config(text=f"×{fx(cfg.get('factor', 1.0), 2)}")

        if res.errors:
            msgs = [e["msg"] for e in res.errors]
            extra = f"  (+{len(msgs) - 2} more)" if len(msgs) > 2 else ""
            self.status_msg.config(text="Fix input: " + "   •   ".join(msgs[:2]) + extra, foreground=PALETTE["fail"])
            self.status_verdict.config(text="")
            self.lbl_reserve.config(text="")
            if self.last is not None and not self.stale:
                self.stale = True
                self.render_all_results()
            return

        self.stale = False
        self.status_msg.config(text="Ready. Results update as you type.", foreground="")
        self.cfg_used = copy.deepcopy(cfg)
        self.last = res
        fs = bc.fail_state(res)
        strength = fs is not None and fs["kind"] != "deflection"
        if strength and not self.fail_was_strength:
            self.start_fail()
        self.fail_was_strength = strength
        self.render_all_results()

    def render_all_results(self):
        self.render_factor()
        self.render_summary()
        self.redraw()
        self.render_compare()

    # ------------------------------------------------------------ summary
    def render_factor(self):
        tr = self.factor_track
        tr.delete("all")
        w = max(10, tr.winfo_width())
        if self.last is None or self.stale:
            tr.create_rectangle(0, 1, w, 5, fill=PALETTE["line"], outline="")
            return
        r = bc.reserve_factor(self.cfg)
        pct = 1.0
        if r is None:
            self.lbl_reserve.config(text="")
        else:
            k, label = r
            if math.isinf(k):
                self.lbl_reserve.config(text="The entered loads do not affect any check.", foreground="")
            elif k <= 0:
                pct = 0.0
                self.lbl_reserve.config(text=f"Self-weight alone exceeds the {short_label(label)} limit.",
                                        foreground=PALETTE["fail"])
            else:
                pct = clamp(k / FACTOR_MAX, 0, 1)
                self.lbl_reserve.config(
                    text=f"First limit reached at ×{fx(k, 2)} the entered loads ({short_label(label)}). "
                         f"Slide past it to see the beam fail.", foreground="")
        tr.create_rectangle(0, 1, w * pct, 5, fill=PALETTE["pass"], outline="")
        tr.create_rectangle(w * pct, 1, w, 5, fill=PALETTE["fail"], outline="")

    def render_summary(self):
        res, cfg = self.last, self.cfg_used
        if res is None:
            return
        gray = self.stale
        c = res.checks
        lst = [c[k] for k in bc.CHECK_KEYS]
        for row, ch in zip(self.check_rows, lst):
            name, cap_lbl, dem, cap, bar, rat, out = row
            name.config(text=ch.label, foreground=PALETTE["muted"] if gray else "")
            cap_lbl.config(text=f"limit: {ch.cap_label}")
            dem.config(text=f"{fx(ch.demand, ch.dec)} {ch.unit}", foreground=PALETTE["muted"] if gray else "")
            cap.config(text=f"{fx(ch.cap, ch.dec)} {ch.unit}", foreground=PALETTE["muted"] if gray else "")
            rat.config(text=fx(ch.ratio, 2) if math.isfinite(ch.ratio) else "∞",
                       foreground=PALETTE["muted"] if gray else "")
            bar.delete("all")
            bar.create_rectangle(0, 0, 40, 8, fill=self.col("soft"), outline="")
            bar.create_rectangle(0, 0, 40 * min(ch.ratio, 1), 8,
                                 fill=self.col("pass" if ch.passed else "fail"), outline="")
            out.config(text="PASS" if ch.passed else "FAIL",
                       style="Muted.TLabel" if gray else ("Pass.TLabel" if ch.passed else "Fail.TLabel"))

        failed = [short_label(k.label) for k in lst if not k.passed]
        gk, gov = res.governing()
        if gray:
            self.lbl_verdict.config(text="Results out of date (fix the inputs)", foreground=PALETTE["muted"])
        elif failed:
            self.lbl_verdict.config(text="FAILS: " + ", ".join(failed), foreground=PALETTE["fail"])
        else:
            self.lbl_verdict.config(text="PASSES ALL CHECKS", foreground=PALETTE["pass"])
        note = f"{res.member.name}. Governing: {short_label(gov.label)} at {fx(gov.ratio, 2)}."
        if cfg["self_weight"]:
            note += f" Self-weight {fx(res.member.w_self * 1000, 1)} lb/ft included."
        if cfg.get("factor", 1) != 1:
            note += f" Entered loads × {fx(cfg['factor'], 2)} (what-if)."
        self.lbl_note.config(text=note)
        if not gray:
            self.status_verdict.config(
                text=("PASSES ALL CHECKS" if not failed else "FAILS: " + ", ".join(failed)) +
                     f"  ·  {res.member.name}, governing {short_label(gov.label)} {fx(gov.ratio, 2)}",
                style="Pass.TLabel" if not failed else "Fail.TLabel")

        t = res.total
        if cfg["support"] == "ss":
            self.lbl_react.config(text=f"Reactions (D + L): R left = {fx(t.R1, 2)} kips, R right = {fx(t.R2, 2)} kips")
        else:
            self.lbl_react.config(text=f"Reactions at fixed end (D + L): R = {fx(t.R1, 2)} kips, "
                                       f"M = {fx(abs(t.M0), 2)} kip-ft")

        m, p = res.member, res.member.props
        if m.material == "steel":
            rows = [("d", f"{p['d']} in"), ("tw", f"{p['tw']} in"), ("A", f"{p['A']} in²"), ("Ix", f"{p['Ix']} in⁴"),
                    ("Sx", f"{p['Sx']} in³"), ("Weight", f"{p['wt']} lb/ft"), ("E", "29,000 ksi"),
                    ("Fb = 0.66Fy", f"{fx(m.bend_cap, 1)} ksi"), ("Va", f"{fx(m.shear_cap, 1)} kips")]
        else:
            rows = [("b × d (actual)", f"{p['b']} × {p['d']} in"), ("A", f"{fx(p['A'], 2)} in²"),
                    ("S", f"{fx(p['S'], 2)} in³"), ("I", f"{fx(p['I'], 1)} in⁴"), ("E", f"{p['E']:,} psi"),
                    ("Fb · CD · CF · Cr", f"{p['Fb']} · {p['CD']:g} · {p['CF']} · {p['Cr']}"),
                    ("Fb'", f"{fx(p['Fbp'], 0)} psi"), ("Fv'", f"{fx(p['Fvp'], 0)} psi"),
                    ("Self-weight", f"{fx(m.w_self * 1000, 1)} lb/ft")]
        for (k, v), (kl, vl) in zip(rows, self.prop_rows):
            kl.config(text=k)
            vl.config(text=v)

    # ------------------------------------------------------------ plots: layout
    def schedule_redraw(self):
        if self.pending_redraw:
            self.root.after_cancel(self.pending_redraw)
        self.pending_redraw = self.root.after(60, self.redraw)

    def redraw(self):
        self.pending_redraw = None
        cv = self.cv
        cv.delete("all")
        self.plots = []
        self.hits = []
        if self.last is None:
            return
        W = max(320, cv.winfo_width())
        avail = max(400, cv.winfo_height())
        sketch_h = self.sketch_height(self.last)
        diag_h = clamp((avail - sketch_h - 8) / 3, 150, 230)
        self.layout = {"W": W, "sketch_h": sketch_h, "diag_h": diag_h}
        self.draw_sketch()
        y = sketch_h
        self.draw_diagrams(y, diag_h)
        total_h = y + 3 * diag_h + 4
        cv.configure(scrollregion=(0, 0, W, total_h))
        self.total_h = total_h
        if total_h <= avail + 2:
            self.cv_sb.grid_remove()
        else:
            self.cv_sb.grid()
        self.draw_cursors()

    # ------------------------------------------------------------ helpers for drawing
    def arrow(self, x, y_from, y_to, color, head=7, dash=None, tags=()):
        d = 1 if y_to > y_from else -1
        self.cv.create_line(x, y_from, x, y_to - d * head, fill=color, width=1.6, dash=dash, tags=tags)
        self.cv.create_polygon(x, y_to, x - head * 0.6, y_to - d * head, x + head * 0.6, y_to - d * head,
                               fill=color, outline="", tags=tags)

    def text(self, x, y, s, anchor="middle", color=None, font=None, tags=()):
        """SVG-style text: y is the baseline; anchor is start, middle, or end."""
        a = {"start": "sw", "middle": "s", "end": "se"}[anchor]
        self.cv.create_text(x, y + 3, text=s, anchor=a, fill=color or self.col("ink"),
                            font=font or self.f_small, tags=tags)

    def tooltip(self, cv, W, X, y, s, tags):
        tw = self.f_small.measure(s) + 14
        bx = X + 10
        if bx + tw > W - 2:
            bx = X - 10 - tw
        bx = max(2, bx)
        cv.create_rectangle(bx, y, bx + tw, y + 20, fill=PALETTE["panel"], outline=PALETTE["line"], tags=tags)
        cv.create_text(bx + 7, y + 10, text=s, anchor="w", fill=PALETTE["ink"], font=self.f_small, tags=tags)

    @staticmethod
    def beam_path(pts, jag_start=None, jag_end=None):
        """Beam as a 10 px band around a centerline, with optional jagged break edges."""
        P = [(x, y - 5) for x, y in pts]
        ex, ey = pts[-1]
        sx0, sy0 = pts[0]
        if jag_end:
            P += [(ex + dx, ey + dy) for dx, dy in jag_end]
        P += [(x, y + 5) for x, y in reversed(pts)]
        if jag_start:
            P += [(sx0 + dx, sy0 + dy) for dx, dy in reversed(jag_start)]
        return P

    def snap_targets(self, res):
        t, L = res.total, self.cfg_used["L"]
        s = [0, L, t.Vmax.x, t.Vmin.x, t.Mmax.x, t.Mmin.x, t.dX]
        for ld in res.loads:
            if ld["type"] == "point":
                s.append(ld["x"])
            else:
                s += [ld["x1"], ld["x2"]]
        return s

    # ------------------------------------------------------------ sketch
    def sketch_height(self, res):
        n_udl = sum(1 for l in res.loads if l["type"] == "udl")
        n_pt = sum(1 for l in res.loads if l["type"] == "point")
        beamY = max(90, 50 + 42 * n_udl + (40 if n_pt else 0))
        return beamY + 172

    def draw_sketch(self):
        res, cfg, cv = self.last, self.cfg_used, self.cv
        tags = ("sketch",)
        cv.delete("sketch")
        W = self.layout["W"]
        L = cfg["L"]
        loads = [dict(l, i=i) for i, l in enumerate(res.loads)]
        udls = [l for l in loads if l["type"] == "udl"]
        pts = [l for l in loads if l["type"] == "point"]
        lane_h = 42
        beamY = max(90, 50 + lane_h * len(udls) + (40 if pts else 0))
        H = beamY + 172
        X0, X1 = PAD_L, W - PAD_R
        sx = lambda x: X0 + (x / L) * (X1 - X0)
        top = beamY - 5
        t = res.total
        hits = []

        # Deflected-shape scale. Auto: the total-load limit is drawn about 36 px tall.
        px_per_in = (X1 - X0) / (L * 12)
        lim = res.checks["total"].cap
        factor = max(1.0, nice_num(36 / (lim * px_per_in))) if self.exag == "auto" else float(self.exag)
        clipped = False

        def dy_px(d):
            nonlocal clipped
            v = d * px_per_in * factor
            if abs(v) > SKETCH_MAXPX:
                clipped = True
                return math.copysign(SKETCH_MAXPX, v)
            return v

        def y_beam(x):
            return beamY + dy_px(interp(t.xs, t.D, x))

        n = len(t.xs)
        step = max(1, n // 320)
        cl = [(sx(t.xs[i]), beamY + dy_px(t.D[i])) for i in range(0, n, step)]
        if (n - 1) % step:
            cl.append((sx(t.xs[-1]), beamY + dy_px(t.D[-1])))

        fs = bc.fail_state(res)
        strength = fs is not None and fs["kind"] != "deflection"
        p = clamp((time.perf_counter() - self.fail_start) * 1000 / FAIL_MS, 0, 1) if strength else 1.0
        ink, muted = self.col("ink"), self.col("muted")
        bad = self.col("fail")

        # supports
        sup_fill = self.col("dead")
        if cfg["support"] == "ss":
            cv.create_polygon(X0, beamY + 5, X0 - 12, beamY + 27, X0 + 12, beamY + 27, fill=sup_fill, outline="", tags=tags)
            cv.create_line(X0 - 18, beamY + 28, X0 + 18, beamY + 28, fill=ink, width=1.5, tags=tags)
            cv.create_polygon(X1, beamY + 5, X1 - 11, beamY + 21, X1 + 11, beamY + 21, fill=sup_fill, outline="", tags=tags)
            for cx in (X1 - 6, X1 + 6):
                cv.create_oval(cx - 3.5, beamY + 21.5, cx + 3.5, beamY + 28.5, fill=sup_fill, outline="", tags=tags)
            cv.create_line(X1 - 18, beamY + 29, X1 + 18, beamY + 29, fill=ink, width=1.5, tags=tags)
        else:
            cv.create_line(X0, beamY - 40, X0, beamY + 40, fill=ink, width=1.5, tags=tags)
            yy = beamY - 38
            while yy <= beamY + 38:
                cv.create_line(X0, yy, X0 - 10, yy + 9, fill=ink, width=1.2, tags=tags)
                yy += 9

        # undeformed beam (ghost) and the deflection limit at the max-deflection point
        cv.create_line(X0, beamY, X1, beamY, fill=muted, dash=(4, 4), tags=tags)
        if t.dMax > 0 and not strength:
            lim_px = lim * px_per_in * factor
            if lim_px <= SKETCH_MAXPX:
                ly = beamY + lim_px + 5
                lx = sx(t.dX)
                anchor = "end" if lx > X1 - 60 else "start"
                cv.create_line(lx - 30, ly, lx + 30, ly, fill=bad, dash=(2, 3), width=1.2, tags=tags)
                self.text(lx - 34 if anchor == "end" else lx + 34, ly + 4,
                          f"{res.checks['total'].cap_label} limit", anchor, bad, tags=tags)

        # beam: intact, over-deflected, or breaking
        beam_col = self.col("beam")
        if not strength:
            cv.create_polygon(flat(self.beam_path(cl)), fill=bad if fs else beam_col, outline="", tags=tags)
        else:
            xb = clamp(fs["x"], 0.08 * L, 0.92 * L) if cfg["support"] == "ss" else clamp(fs["x"], 0.03 * L, 0.97 * L)
            q = 0 if p < 0.22 else ease_out_bounce((p - 0.22) / 0.78)
            fl = lambda c: (c[0], beamY + (c[1] - beamY) * (1 - q))  # sag straightens as the halves rotate
            xb_px = sx(xb)
            yb_px = fl((xb_px, y_beam(xb)))[1]
            jag = [(-9, -5), (-4, -2), (-5, 0.5), (2, 2.5), (8, 5)] if fs["kind"] == "shear" else \
                  [(2, -5), (-2.5, -2.5), (2, 0), (-2, 2.5), (1.5, 5)]
            left = [fl(c) for c in cl if c[0] < xb_px] + [(xb_px, yb_px)]
            right = [(xb_px, yb_px)] + [fl(c) for c in cl if c[0] > xb_px]
            if cfg["support"] == "ss":
                aL = math.degrees(math.atan2(70, max(30, xb_px - X0))) * q
                aR = math.degrees(math.atan2(70, max(30, X1 - xb_px))) * q
                cv.create_polygon(flat(rotate_pts(self.beam_path(left, None, jag), aL, X0, beamY)),
                                  fill=bad, outline="", tags=tags)
                cv.create_polygon(flat(rotate_pts(self.beam_path(right, jag, None), -aR, X1, beamY)),
                                  fill=bad, outline="", tags=tags)
            else:
                a = math.degrees(math.atan2(95, max(30, X1 - xb_px))) * q
                if len(left) > 1:
                    cv.create_polygon(flat(self.beam_path(left, None, jag)), fill=bad, outline="", tags=tags)
                rp = rotate_pts(self.beam_path(right, jag, None), a, xb_px, yb_px)
                cv.create_polygon(flat([(x, y + 14 * q) for x, y in rp]), fill=bad, outline="", tags=tags)
            if p < 0.22:
                r = 6 + 40 * p
                cv.create_oval(xb_px - r, yb_px - r, xb_px + r, yb_px + r,
                               fill=blend(PALETTE["fail"], max(0.0, 0.5 - 2 * p)), outline="", tags=tags)
                cv.tag_lower(cv.find_all()[-1], "sketch")
            if 0.22 < p < 1:
                tt = (p - 0.22) / 0.78
                for i in range(12):
                    dx = (rnd(i, 1) - 0.5) * 110 * tt
                    dy = -35 * rnd(i, 2) * tt + 170 * tt * tt
                    s = 2 + 3.5 * rnd(i, 3)
                    cx, cy = xb_px + dx, yb_px + dy
                    sq = rotate_pts([(cx - s / 2, cy - s / 2), (cx + s / 2, cy - s / 2),
                                     (cx + s / 2, cy + s / 2), (cx - s / 2, cy + s / 2)], 720 * tt * rnd(i, 4), cx, cy)
                    cv.create_polygon(flat(sq), fill=blend(PALETTE["fail"], 1 - tt), outline="", tags=tags)

        # uniform loads, stacked in lanes (draggable; handles stretch the ends)
        for k, u in enumerate(udls):
            color = self.col("dead" if u["tag"] == "D" else "live")
            dash = None if u["tag"] == "D" else (5, 3)
            yb, yt = top - k * lane_h, top - k * lane_h - 22
            a, b = sx(u["x1"]), sx(u["x2"])
            n_a = max(2, round((b - a) / 26) + 1)
            cv.create_line(a, yt if u["w"] >= 0 else yb, b, yt if u["w"] >= 0 else yb,
                           fill=color, width=1.6, dash=dash, tags=tags)
            for j in range(n_a):
                x = a + (b - a) * j / (n_a - 1)
                if u["w"] >= 0:
                    self.arrow(x, yt, yb, color, 6, dash, tags)
                else:
                    self.arrow(x, yb, yt, color, 6, dash, tags)
            label = f"{'self-wt ' if u.get('self') else ''}{fx(u['w'], 3)} k/ft {u['tag']}"
            self.text((a + b) / 2, yt - 4, label, "middle", color, tags=tags)
            if u.get("self"):
                continue
            for hx in (a, b):
                cv.create_oval(hx - 5, yt - 5, hx + 5, yt + 5, fill=PALETTE["panel"],
                               outline=self.col("accent"), width=1.5, tags=tags)
            hits.append((a - 10, yt - 10, a + 10, yt + 10, u["i"], "x1"))
            hits.append((b - 10, yt - 10, b + 10, yt + 10, u["i"], "x2"))
            hits.append((a, yt - 18, max(a + 4, b), yb + 2, u["i"], "body"))

        # point loads (draggable; arrow tips follow the deflected beam)
        pt_top = top - len(udls) * lane_h - 32
        for pl in pts:
            color = self.col("dead" if pl["tag"] == "D" else "live")
            dash = None if pl["tag"] == "D" else (5, 3)
            x = sx(pl["x"])
            tip = top if strength else y_beam(pl["x"]) - 5
            anchor = "start" if x < X0 + 30 else "end" if x > X1 - 30 else "middle"
            if pl["P"] >= 0:
                self.arrow(x, pt_top, tip, color, 8, dash, tags)
            else:
                self.arrow(x, tip, pt_top, color, 8, dash, tags)
            self.text(x, pt_top - 5, f"{fx(pl['P'], 2)} k {pl['tag']}", anchor, color, tags=tags)
            hits.insert(0, (x - 12, pt_top - 18, x + 12, tip + 2, pl["i"], "x"))

        # reactions
        acc = self.col("accent")
        rb, rt = beamY + 75, beamY + 34

        def react(x, R, extra="", anchor="middle"):
            if R >= 0:
                self.arrow(x, rb, rt, acc, 8, None, tags)
            else:
                self.arrow(x, rt, rb, acc, 8, None, tags)
            self.text(x, rb + 15, f"R = {fx(R, 2)} k{extra}", anchor, acc, self.f_bold, tags)

        if cfg["support"] == "ss":
            react(X0, t.R1, "", "start")
            react(X1, t.R2, "", "end")
        else:
            react(X0 + 22, t.R1, f", M = {fx(abs(t.M0), 2)} k-ft", "start")

        # failure label
        if fs and min(1, p * 3) > 0.3:
            lx = clamp(sx(fs["x"]), X0 + 150, X1 - 150)
            if fs["kind"] == "deflection":
                ch = fs["check"]
                msg = f"Too flexible: {short_label(ch.label)} {fx(ch.demand, 3)} in > {fx(ch.cap, 3)} in"
            else:
                msg = f"FAILED in {fs['kind']} at x = {fx(fs['x'], 2)} ft (ratio {fx(fs['ratio'], 2)})"
            self.text(lx, beamY + 140, msg, "middle", bad, self.f_fail, tags)

        # span dimension
        dy = H - 10
        cv.create_line(X0, dy, X1, dy, fill=muted, tags=tags)
        cv.create_line(X0, dy - 5, X0, dy + 5, fill=muted, tags=tags)
        cv.create_line(X1, dy - 5, X1, dy + 5, fill=muted, tags=tags)
        self.text((X0 + X1) / 2, dy - 5, f"L = {fx(L, 2)} ft", "middle", muted, tags=tags)
        cv.create_line(0, H - 0.5, W, H - 0.5, fill=PALETTE["line"], tags=tags)

        # shake while the beam breaks
        if strength and p < 0.45 and self.var_animate.get():
            cv.move("sketch", 6 * math.sin(p * 60) * (1 - p / 0.45), 0)

        f_txt = f"{round(factor)}" if factor >= 10 else fx(factor, 1)
        self.lbl_exag.config(text=f"drawn ×{f_txt}{' (clipped)' if clipped else ''}")
        self.show_replay(strength and not self.stale)
        self.hits = hits

        def cursor(x, ctags):
            X = sx(x)
            d = interp(t.xs, t.D, x)
            self._cursor_line(X, 30, H - 26, ctags)
            if not strength:
                yb = y_beam(x)
                cv.create_oval(X - 4, yb - 4, X + 4, yb + 4, fill=PALETTE["panel"], outline=self.col("ink"),
                               width=2.2, tags=ctags)
            self.tooltip(cv, W, X, 4, f"x = {fx(x, 2)} ft · Δ = {fx(abs(d), 3)} in {'↓' if d >= 0 else '↑'}", ctags)

        rec = {"kind": "sketch", "y0": 0, "y1": H, "X0": X0, "X1": X1, "sx": sx, "cursor": cursor,
               "snaps": self.snap_targets(res)}
        self.plots = [r for r in self.plots if r["kind"] != "sketch"]
        self.plots.insert(0, rec)

        if strength and p < 1:
            if self.anim_id is None:
                self.anim_id = self.root.after(16, self._anim_frame)

    def _anim_frame(self):
        self.anim_id = None
        if self.last is None or self.stale:
            return
        self.draw_sketch()
        self.cv.tag_raise("cursor")

    def show_replay(self, show):
        if show and not self.btn_replay_shown:
            self.btn_replay.pack(side="right", padx=(0, 10))
        elif not show and self.btn_replay_shown:
            self.btn_replay.pack_forget()
        self.btn_replay_shown = show

    def start_fail(self):
        self.fail_start = time.perf_counter() if self.var_animate.get() else -math.inf

    def replay(self):
        self.start_fail()
        if self.last is not None:
            self.draw_sketch()
            self.draw_cursors()

    def _cursor_line(self, X, y0, y1, ctags):
        pinned = self.pin_x is not None
        self.cv.create_line(X, y0, X, y1, fill=PALETTE["muted"] if pinned else PALETTE["ink"],
                            dash=None if pinned else (3, 3), tags=ctags)

    # ------------------------------------------------------------ diagrams
    def draw_diagrams(self, y0, h):
        res = self.last
        t = res.total
        sv, sm = max(t.Vabs, 1e-9), max(t.Mabs, 1e-9)

        v_labels = []
        if t.Vmax.v > sv * 1e-6:
            v_labels.append((t.Vmax.x, t.Vmax.v, f"{fx(t.Vmax.v, 2)} k at {fx(t.Vmax.x, 2)} ft"))
        if t.Vmin.v < -sv * 1e-6:
            v_labels.append((t.Vmin.x, t.Vmin.v, f"{fx(t.Vmin.v, 2)} k at {fx(t.Vmin.x, 2)} ft"))

        def probe_v(x):
            v = shear_at(t.shear_pts, x)
            return [(v, "shear")], f"V = {fx(v, 2)} k"
        self.draw_diagram(y0, h, [(t.shear_pts, "shear", True)], "V (kips)", v_labels, probe_v)

        m_labels = []
        if t.Mmax.v > sm * 1e-6:
            m_labels.append((t.Mmax.x, t.Mmax.v, f"{fx(t.Mmax.v, 2)} k-ft at {fx(t.Mmax.x, 2)} ft"))
        if t.Mmin.v < -sm * 1e-6:
            m_labels.append((t.Mmin.x, t.Mmin.v, f"{fx(t.Mmin.v, 2)} k-ft at {fx(t.Mmin.x, 2)} ft"))

        def probe_m(x):
            v = interp(t.xs, t.M, x)
            return [(v, "moment")], f"M = {fx(v, 2)} k-ft"
        self.draw_diagram(y0 + h, h, [(list(zip(t.xs, t.M)), "moment", True)], "M (kip-ft)", m_labels, probe_m)

        d_labels = []
        if abs(t.dMax) > 1e-9:
            d_labels.append((t.dX, -t.dMax, f"Δ = {fx(abs(t.dMax), 3)} in {'↓' if t.dMax >= 0 else '↑'} at {fx(t.dX, 2)} ft"))
        series = [([(x, -d) for x, d in zip(t.xs, t.D)], "defl", True)]
        both = any(l["tag"] == "L" for l in res.loads) and any(l["tag"] == "D" for l in res.loads)
        if both:
            series.append(([(x, -d) for x, d in zip(res.live.xs, res.live.D)], "live", False))

        def probe_d(x):
            d = interp(t.xs, t.D, x)
            dl = interp(res.live.xs, res.live.D, x)
            dots = [(-d, "defl")] + ([(-dl, "live")] if both else [])
            txt = f"Δ = {fx(abs(d), 3)} in {'↓' if d >= 0 else '↑'}" + (f" (live {fx(abs(dl), 3)})" if both else "")
            return dots, txt
        self.draw_diagram(y0 + 2 * h, h, series, "Δ (in)", d_labels, probe_d)

    def draw_diagram(self, oy, H, series, y_label, labels, probe):
        cv, W, L = self.cv, self.layout["W"], self.cfg_used["L"]
        tags = ("diagram",)
        pL, pR, pT, pB = PAD_L, PAD_R, 26, 30
        lo = hi = 0.0
        for pts, _, _ in series:
            for _, v in pts:
                lo, hi = min(lo, v), max(hi, v)
        if hi - lo < 1e-12:
            lo, hi = -1.0, 1.0
        pad = (hi - lo) * 0.2
        hi += pad
        lo -= pad
        sx = lambda x: pL + (x / L) * (W - pL - pR)
        sy = lambda v: oy + pT + (hi - v) / (hi - lo) * (H - pT - pB)
        muted, ink = self.col("muted"), self.col("ink")
        for i in range(5):
            x = L * i / 4
            X = sx(x)
            cv.create_line(X, oy + pT - 10, X, oy + H - pB, fill=PALETTE["soft"], tags=tags)
            self.text(X, oy + H - 10, f"{fx(x, 1)}{' ft' if i == 4 else ''}",
                      "start" if i == 0 else "end" if i == 4 else "middle", muted, tags=tags)
        cv.create_line(pL, sy(0), W - pR, sy(0), fill=muted, tags=tags)
        self.text(pL - 6, sy(0) + 4, "0", "end", muted, tags=tags)
        cv.create_text(16, oy + (pT + H - pB) / 2, text=y_label, angle=90, fill=muted, font=self.f_small, tags=tags)

        for pts, name, fill in series:
            line = self._thin(pts, sx, sy)
            color = self.col(name)
            if fill and len(line) >= 4:
                poly = [line[0], sy(0)] + line + [line[-2], sy(0)]
                cv.create_polygon(poly, fill=self.col(name, 0.14), outline="", tags=tags)
            if len(line) >= 4:
                cv.create_line(line, fill=color, width=1.6 if name == "live" else 2,
                               dash=(6, 4) if name == "live" else None, tags=tags)

        for x, v, s in labels:
            X, Y = sx(x), sy(v)
            anchor = "start" if X < pL + 90 else "end" if X > W - pR - 90 else "middle"
            ty = max(oy + 14, Y - 9) if v >= 0 else min(oy + H - pB - 4, Y + 19)
            dxT = 6 if anchor == "start" else -6 if anchor == "end" else 0
            cv.create_oval(X - 3.5, Y - 3.5, X + 3.5, Y + 3.5, fill=PALETTE["panel"], outline=ink, width=1.5, tags=tags)
            self.text(X + dxT, ty, s, anchor, ink, self.f_bold, tags)
        cv.create_line(0, oy + H - 0.5, W, oy + H - 0.5, fill=PALETTE["line"], tags=tags)

        def cursor(x, ctags):
            X = sx(x)
            dots, txt = probe(x)
            self._cursor_line(X, oy + pT - 10, oy + H - pB, ctags)
            for v, name in dots:
                Y = sy(v)
                cv.create_oval(X - 4, Y - 4, X + 4, Y + 4, fill=PALETTE["panel"], outline=self.col(name),
                               width=2.2, tags=ctags)
            ty = oy + 2 if sy(dots[0][0]) > oy + (pT + H - pB) / 2 else oy + H - pB - 24
            self.tooltip(cv, W, X, ty, f"x = {fx(x, 2)} ft · {txt}", ctags)

        self.plots.append({"kind": "diagram", "y0": oy, "y1": oy + H, "X0": pL, "X1": W - pR, "sx": sx,
                           "cursor": cursor, "snaps": self.snap_targets(self.last)})

    @staticmethod
    def _thin(pts, sx, sy):
        """Pixel coordinates with about one point per pixel; keeps both sides of every jump."""
        out = []
        n = len(pts)
        last_X = None
        for i, (x, v) in enumerate(pts):
            X = sx(x)
            jump = (i + 1 < n and pts[i + 1][0] == x) or (i > 0 and pts[i - 1][0] == x)
            if i == 0 or i == n - 1 or jump or X - last_X >= 1.0:
                out += [X, sy(v)]
                last_X = X
        return out

    # ------------------------------------------------------------ probe
    def cur_x(self):
        if self.last is None:
            return 0.0
        L = self.cfg_used["L"]
        if self.pin_x is not None:
            x = self.pin_x
        elif self.hover_x is not None:
            x = self.hover_x
        else:
            x = self.last.total.MabsX
        return clamp(x, 0, L)

    def draw_cursors(self):
        if self.last is None:
            return
        self.cv.delete("cursor")
        x = self.cur_x()
        for p in self.plots:
            p["cursor"](x, ("cursor",))
        self.render_section(x)

    def x_from_event(self, e, snap=True):
        if not self.plots:
            return None
        cy = self.cv.canvasy(e.y)
        plot = next((p for p in self.plots if p["y0"] <= cy < p["y1"]), self.plots[0])
        L = self.cfg_used["L"]
        X = e.x
        x = clamp((X - plot["X0"]) / (plot["X1"] - plot["X0"]) * L, 0, L)
        if snap:
            best = 7
            for s in plot["snaps"]:
                d = abs(plot["sx"](s) - X)
                if d < best:
                    best, x = d, s
        return x

    def hit_test(self, e):
        cy = self.cv.canvasy(e.y)
        if self.stale or not self.plots or cy > self.plots[0]["y1"]:
            return None
        for x0, y0, x1, y1, i, part in sorted(self.hits, key=lambda h: h[5] not in ("x1", "x2")):
            if x0 <= e.x <= x1 and y0 <= cy <= y1:
                return i, part
        return None

    def on_motion(self, e):
        if self.last is None:
            return
        if self.drag:
            self.do_drag(e)
            return
        hit = self.hit_test(e)
        self.cv.configure(cursor="sb_h_double_arrow" if hit and hit[1] in ("x1", "x2") else
                          "fleur" if hit else "")
        self.hover_x = self.x_from_event(e)
        if self.pin_x is None:
            self.draw_cursors()

    def on_leave(self, _e):
        if self.drag:
            return
        self.hover_x = None
        self.draw_cursors()

    def on_press(self, e):
        self.cv.focus_set()
        if self.last is None:
            return
        hit = self.hit_test(e)
        if hit:
            i, part = hit
            self.drag = {"i": i, "part": part, "start_x": self.x_from_event(e, False),
                         "orig": dict(self.cfg["loads"][i])}
            return
        x = self.x_from_event(e)
        if self.pin_x is None:
            self.pin_x = x
        else:
            self.pin_x = None
            self.hover_x = x
        self.draw_cursors()

    def on_release(self, _e):
        if self.drag:
            self.drag = None
            self.render_compare()

    def round_step(self, v):
        s = 0.05 if self.cfg["L"] <= 5 else 0.25
        return round(round(v / s) * s, 3)

    def do_drag(self, e):
        x = self.x_from_event(e, False)
        L = self.cfg["L"]
        d = self.drag
        o, i = d["orig"], d["i"]
        delta = x - d["start_x"]
        ld = self.cfg["loads"][i]
        if d["part"] == "x":
            ld["x"] = clamp(self.round_step(o["x"] + delta), 0, L)
        elif d["part"] == "body":
            length = o["x2"] - o["x1"]
            a = clamp(self.round_step(o["x1"] + delta), 0, L - length)
            ld["x1"], ld["x2"] = round(a, 3), round(a + length, 3)
        elif d["part"] == "x1":
            ld["x1"] = clamp(self.round_step(x), 0, o["x2"] - 0.05)
        else:
            ld["x2"] = clamp(self.round_step(x), o["x1"] + 0.05, L)
        self.hover_x = ld["x"] if d["part"] == "x" else x
        self.update()

    def on_key_step(self, steps):
        if self.last is None:
            return
        L = self.cfg_used["L"]
        self.pin_x = clamp(self.cur_x() + steps * L / 100, 0, L)
        self.draw_cursors()

    def on_key_to(self, x):
        if self.last is None:
            return
        self.pin_x = self.cfg_used["L"] if x is None else x
        self.draw_cursors()

    # ------------------------------------------------------------ stresses at the probe
    def render_section(self, x):
        res = self.last
        cv = self.cv_xsec
        cv.delete("all")
        if res is None:
            return
        m, t = res.member, res.total
        steel = m.material == "steel"
        V = shear_at(t.shear_pts, x)
        M = interp(t.xs, t.M, x)
        Dt = interp(t.xs, t.D, x)
        Dl = interp(res.live.xs, res.live.D, x)
        u, dec = m.bend_unit, (2 if steel else 0)
        fbs = M * 12 / m.S if steel else M * 12000 / m.S   # signed, sagging positive
        Fb = m.bend_cap
        fv = abs(V) / (m.props["d"] * m.props["tw"]) if steel else 1.5 * abs(V) * 1000 / m.A
        Fv = m.shear_cap / (m.props["d"] * m.props["tw"]) if steel else m.shear_cap
        rb, rv = abs(fbs) / Fb, fv / Fv

        W = max(300, cv.winfo_width())
        col = W / 3
        y0, h = 46, 150
        y1, ym = y0 + h, y0 + h / 2
        ink, muted, fail = self.col("ink"), self.col("muted"), self.col("fail")
        f = self.f_small

        def txt(xx, yy, s, anchor="center", color=None, font=None, wrap=0):
            cv.create_text(xx, yy, text=s, anchor=anchor, fill=color or ink, font=font or f,
                           width=wrap, justify="center")

        txt(col / 2, 14, "Section", font=self.f_bold)
        txt(col / 2, 30, "(schematic)" if steel else "(to scale)", color=muted)
        txt(col * 1.5, 14, "Bending stress", font=self.f_bold)
        txt(col * 2.5, 14, "Web shear" if steel else "Shear stress", font=self.f_bold)
        if steel:
            txt(col * 2.5, 30, "(average)", color=muted)
        cv.create_line(8, ym, W - 8, ym, fill=muted, dash=(5, 4))
        txt(8, ym - 8, "N.A.", "w", muted)

        # 1. section
        cx = col / 2
        soft = self.col("soft")
        if steel:
            bf, tf, tw = min(col - 30, h * 0.6), 11, 5
            l, r = cx - bf / 2, cx + bf / 2
            cv.create_polygon(l, y0, r, y0, r, y0 + tf, cx + tw / 2, y0 + tf, cx + tw / 2, y1 - tf, r, y1 - tf,
                              r, y1, l, y1, l, y1 - tf, cx - tw / 2, y1 - tf, cx - tw / 2, y0 + tf, l, y0 + tf,
                              fill=soft, outline=ink, width=1.5)
            txt(cx, y1 + 16, m.name, font=self.f_bold)
            txt(cx, y1 + 28, f"d = {m.props['d']} in, tw = {m.props['tw']} in", "n", muted, wrap=col - 8)
        else:
            bw = max(8, h * m.props["b"] / m.props["d"])
            cv.create_rectangle(cx - bw / 2, y0, cx + bw / 2, y1, fill=soft, outline=ink, width=1.5)
            txt(cx, y1 + 16, m.name, font=self.f_bold)
            txt(cx, y1 + 28, f"{m.props['b']} × {m.props['d']} in", "n", muted, wrap=col - 8)

        # 2. bending: linear; compression drawn left, tension right; dashed = allowable
        cx2, half = col * 1.5, col / 2 - 8
        a = half * 0.62
        px = lambda v: clamp(v / Fb * a, -half, half)
        s_top, s_bot = -fbs, fbs  # tension positive

        def st(s):
            if abs(s) > Fb * (1 + 1e-9):
                return self.col("fail", 0.3), fail
            return (self.col("moment", 0.28), self.col("moment")) if s < 0 else (self.col("accent", 0.22), self.col("accent"))
        if abs(fbs) > 1e-9:
            fc, oc = st(s_top)
            cv.create_polygon(cx2, y0, cx2 + px(s_top), y0, cx2, ym, fill=fc, outline=oc, width=1.5)
            fc, oc = st(s_bot)
            cv.create_polygon(cx2, ym, cx2 + px(s_bot), y1, cx2, y1, fill=fc, outline=oc, width=1.5)
        cv.create_line(cx2, y0 - 6, cx2, y1 + 6, fill=muted)
        for sgn in (-1, 1):
            cv.create_line(cx2 + sgn * a, y0 - 6, cx2 + sgn * a, y1 + 6, fill=fail, dash=(4, 3), width=1.2)
        if abs(fbs) > 1e-9:
            for s, yy in ((s_top, y0 + 8), (s_bot, y1 - 8)):
                X = cx2 + px(s)
                txt(X + (-4 if s < 0 else 4), yy, f"{'C' if s < 0 else 'T'} {fx(abs(s), dec)}",
                    "e" if s < 0 else "w", ink, self.f_bold)
        txt(cx2, y1 + 16, u)
        txt(cx2, y1 + 28, f"dashed = ±{'Fb' if steel else 'Fb' + chr(8242)} {fx(Fb, dec)}", "n", muted, wrap=col - 8)

        # 3. shear: uniform over the web (steel) or parabolic (rectangular lumber)
        cx3 = col * 2 + 10
        a3, max3 = (col - 30) * 0.62, col - 16
        pv = lambda v: min(v / Fv * a3, max3)
        if rv > 1 + 1e-9:
            vf, vo = self.col("fail", 0.3), fail
        else:
            vf, vo = self.col("shear", 0.22), self.col("shear")
        if fv > 1e-9:
            if steel:
                cv.create_rectangle(cx3, y0 + 11, cx3 + pv(fv), y1 - 11, fill=vf, outline=vo, width=1.5)
            else:
                poly = [cx3, y0]
                for i in range(31):
                    e = i / 30
                    poly += [cx3 + pv(fv * (1 - (2 * e - 1) ** 2)), y0 + e * h]
                cv.create_polygon(poly, fill=vf, outline=vo, width=1.5)
            lx = cx3 + pv(fv) + 4
            right = lx + 40 < W
            txt(lx if right else cx3 + pv(fv) - 4, ym + 14, fx(fv, 2 if steel else 1),
                "w" if right else "e", ink, self.f_bold)
        cv.create_line(cx3, y0 - 6, cx3, y1 + 6, fill=muted)
        cv.create_line(cx3 + a3, y0 - 6, cx3 + a3, y1 + 6, fill=fail, dash=(4, 3), width=1.2)
        txt(col * 2.5, y1 + 16, u)
        txt(col * 2.5, y1 + 28, f"dashed = {'0.6Fy/1.5' if steel else 'Fv' + chr(8242)} {fx(Fv, 1 if steel else 0)}",
            "n", muted, wrap=col - 8)
        txt(W / 2, y1 + 72, ("Sagging: top in compression" if M >= 0 else "Hogging: top in tension"), color=muted)

        pinned = self.pin_x is not None
        self.lbl_xsec.config(text=f"Probe at x = {fx(x, 2)} ft{' (pinned)' if pinned else ''}")
        fbn = "Fb" if steel else "Fb'"
        fvn = "Fv" if steel else "Fv'"
        rows = [
            ("Position x", f"{fx(x, 2)} ft", False),
            ("Shear V", f"{fx(V, 2)} kips", False),
            ("Moment M", f"{fx(M, 2)} kip-ft", False),
            (f"fb / {fbn}", f"{fx(abs(fbs), dec)} {u} ({fx(rb, 2)})", rb > 1),
            (f"fv / {fvn}", f"{fx(fv, 2 if steel else 1)} {u} ({fx(rv, 2)})", rv > 1),
            ("Δ total", f"{fx(abs(Dt), 3)} in {'↓' if Dt >= 0 else '↑'}", False),
            ("Δ live", f"{fx(abs(Dl), 3)} in {'↓' if Dl >= 0 else '↑'}", False),
        ]
        for (k, v, over), (kl, vl) in zip(rows, self.read_rows):
            kl.config(text=k)
            vl.config(text=v, style="Over.TLabel" if over and not self.stale else
                      ("Muted.TLabel" if self.stale else "Value.TLabel"))

    # ------------------------------------------------------------ section comparison
    def render_compare(self, hover="keep"):
        cv = self.cv_cmp
        cv.delete("all")
        if hover != "keep":
            self.cmp_hover = hover
        if self.last is None or self.drag:
            return
        if not self.stale:
            self.cmp_rows = bc.compare_sections(self.cfg)
        rows = self.cmp_rows
        W = max(260, cv.winfo_width())
        rh = 28
        best = next((r for r in rows if r["pass"]), None)
        fs, fb = self.f_small, self.f_bold
        nm_w = max([fb.measure(r["name"]) for r in rows] + [fs.measure("Section")]) + 10
        wt_w = fs.measure("55.0 lb/ft") + 10
        rt_w = fs.measure("10.00") + 8
        tag_w = fs.measure("lightest OK") + 10
        gv_w = fs.measure("Δ total") + 6 + tag_w + 6
        show_wt = W - (10 + nm_w + wt_w + rt_w + gv_w) >= 60
        cols = {"nm": 10, "wt": 10 + nm_w}
        cols["bar"] = cols["wt"] + (wt_w if show_wt else 0)
        cols["gv"] = W - gv_w
        bar_w = max(30, cols["gv"] - rt_w - 6 - cols["bar"])
        muted = self.col("muted")
        y = 8
        cv.create_text(cols["nm"], y + 8, text="Section", anchor="w", fill=muted, font=fs)
        if show_wt:
            cv.create_text(cols["wt"], y + 8, text="Weight", anchor="w", fill=muted, font=fs)
        cv.create_text(cols["bar"], y + 8, text="Governing ratio", anchor="w", fill=muted, font=fs)
        cv.create_text(cols["gv"], y + 8, text="Check", anchor="w", fill=muted, font=fs)
        y += 22
        self.cmp_y0 = y
        for i, r in enumerate(rows):
            top = y + i * rh
            current = r["name"] == self.cfg_used["section"]
            if current:
                cv.create_rectangle(2, top, W - 2, top + rh, fill=self.col("accent", 0.12), outline=self.col("accent"))
            elif i == self.cmp_hover:
                cv.create_rectangle(2, top, W - 2, top + rh, fill=PALETTE["soft"], outline="")
            mid = top + rh / 2
            ink = self.col("ink") if r["pass"] else self.col("fail")
            cv.create_text(cols["nm"], mid, text=r["name"], anchor="w", fill=ink, font=self.f_bold)
            if show_wt:
                cv.create_text(cols["wt"], mid, text=f"{fx(r['wt'], 1)} lb/ft", anchor="w", fill=muted, font=fs)
            bx = cols["bar"]
            cv.create_rectangle(bx, mid - 4, bx + bar_w, mid + 5, fill=PALETTE["soft"], outline="")
            frac = clamp(r["ratio"] / 2, 0, 1) if math.isfinite(r["ratio"]) else 1
            cv.create_rectangle(bx, mid - 4, bx + bar_w * frac, mid + 5,
                                fill=self.col("pass" if r["pass"] else "fail"), outline="")
            cv.create_line(bx + bar_w / 2, mid - 7, bx + bar_w / 2, mid + 8, fill=self.col("ink"), width=2)
            cv.create_text(bx + bar_w + rt_w + 2, mid, text=fx(r["ratio"], 2) if math.isfinite(r["ratio"]) else "∞",
                           anchor="e", fill=ink, font=self.f_small)
            cv.create_text(cols["gv"], mid, text=r["gov"], anchor="w", fill=muted, font=self.f_small)
            if r is best:
                tx = cols["gv"] + self.f_small.measure(r["gov"]) + 6
                tw = self.f_small.measure("lightest OK") + 10
                cv.create_rectangle(tx, mid - 8, tx + tw, mid + 8, fill=self.col("pass_bg"), outline="")
                cv.create_text(tx + 5, mid, text="lightest OK", anchor="w", fill=self.col("pass"), font=self.f_small)
        if not rows:
            cv.create_text(W / 2, 50, text="No sections to compare.", fill=muted, font=self.f_small)

    def _cmp_index(self, e):
        if not self.cmp_rows:
            return None
        i = int((e.y - getattr(self, "cmp_y0", 30)) // 28)
        return i if 0 <= i < len(self.cmp_rows) and e.y >= self.cmp_y0 else None

    def on_compare_motion(self, e):
        i = self._cmp_index(e)
        if i != self.cmp_hover:
            self.render_compare(hover=i)

    def on_compare_dclick(self, e):
        i = self._cmp_index(e)
        if i is None or self.stale:
            return
        self.cfg["section"] = self.cmp_rows[i]["name"]
        self.var_section.set(self.cfg["section"])
        self.update()

    # ------------------------------------------------------------ validation tab
    def render_validation(self):
        results = bc.run_validation()
        n_ok = sum(1 for r in results if r["ok"])
        self.lbl_valid.config(text=f"Validation cases: {n_ok} of {len(results)} pass",
                              foreground=PALETTE["pass"] if n_ok == len(results) else PALETTE["fail"])
        tv = self.tv_valid
        tv.delete(*tv.get_children())
        for ci, r in enumerate(results):
            parent = tv.insert("", "end", iid=f"case{ci}", text=r["name"], open=True,
                               values=("", "", "", "✓" if r["ok"] else "✗"),
                               tags=("case", "ok" if r["ok"] else "bad"))
            for row in r["rows"]:
                got = f"{row['got']:.4g}" if math.isfinite(row["got"]) else "—"
                diff = f"{row['diff'] * 100:.2f}%" if math.isfinite(row["diff"]) else "—"
                tv.insert(parent, "end", text=row["label"],
                          values=(f"{row['exp']:g}", got, diff, "✓" if row["ok"] else "✗"),
                          tags=("ok" if row["ok"] else "bad",))

    def load_validation_case(self):
        sel = self.tv_valid.selection()
        if not sel:
            return
        iid = sel[0]
        if not iid.startswith("case"):
            iid = self.tv_valid.parent(iid)
        ci = int(iid[4:])
        if not self.maybe_save():
            return
        self.load_cfg(copy.deepcopy(bc.VALIDATION[ci]["cfg"]), None)
        self.nb.select(0)

    # ------------------------------------------------------------ files
    def save_report(self):
        if self.last is None or self.stale:
            messagebox.showwarning("Save Report", "Fix the inputs first, so the report shows current results.",
                                   parent=self.root)
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Save Report", defaultextension=".txt",
                                            initialfile="beam_report.txt",
                                            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(bc.report_text(self.cfg_used, self.last))
        self.status_msg.config(text=f"Saved report to {path}", foreground="")

    def export_csv(self):
        if self.pending_update:
            self.root.after_cancel(self.pending_update)
            self.update()
        if self.last is None or self.stale:
            messagebox.showwarning("Export CSV", "Fix the inputs first, so the table shows current results.",
                                   parent=self.root)
            return
        base = os.path.splitext(os.path.basename(self.file_path))[0] if self.file_path else "beam"
        path = filedialog.asksaveasfilename(parent=self.root, title="Export Results (CSV)", defaultextension=".csv",
                                            initialfile=f"{base}_results.csv",
                                            filetypes=[("CSV (Excel)", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            n = bc.write_results_csv(self.last, path)
        except OSError as e:
            messagebox.showerror("Export CSV", f"Could not save the file.\n\n{e}", parent=self.root)
            return
        self.status_msg.config(text=f"Exported {n} rows to {path}", foreground="")

    def save_diagrams(self):
        if self.last is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="Save Diagrams", defaultextension=".eps",
                                            initialfile="beam_diagrams.eps",
                                            filetypes=[("Encapsulated PostScript", "*.eps"), ("All files", "*.*")])
        if not path:
            return
        self.cv.delete("cursor")
        self.cv.update_idletasks()
        W = self.layout["W"]
        self.cv.postscript(file=path, colormode="color", x=0, y=0, width=W, height=self.total_h,
                           pagewidth=f"{7.5}i")
        self.draw_cursors()
        self.status_msg.config(text=f"Saved diagrams to {path}", foreground="")

    def about(self):
        messagebox.showinfo(
            "About Beam Designer",
            "Beam Designer (desktop)\n\n"
            "Shear, moment, and deflection diagrams for a single-span beam, with bending, shear, and "
            "deflection checks for A992 W-shapes and DF-L No. 2 lumber.\n\n"
            "Section data must be verified against the AISC Shapes Database v16.0 and the NDS Supplement "
            "before release.",
            parent=self.root)


def main():
    root = tk.Tk()
    BeamApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
