"""Beam Designer calculation engine (no Tkinter).

Units: inputs in ft, kips, and kip/ft. Section properties in inches.
Deflection math is done internally in kips and inches.

A configuration ("cfg") is a dict:
    support      "ss" (simply supported) or "cant" (fixed at the left end)
    L            span (ft)
    material     "steel" or "lumber"
    section      section name from sections.py
    CD           load duration factor (lumber)
    repetitive   True to apply C_r = 1.15 (2x and 4x lumber only)
    self_weight  True to add the member weight as a dead uniform load
    live_limit   live-load deflection limit denominator n in L/n (default 360)
    total_limit  total-load deflection limit denominator n in L/n (default 240)
    factor       what-if multiplier on the entered loads (default 1)
    loads        list of load dicts:
                   {"type": "point", "P": kips, "x": ft, "tag": "D" or "L"}
                   {"type": "udl", "w": kip/ft, "x1": ft, "x2": ft, "tag": "D" or "L"}

Behavior matches the engine in index.html.
"""

from __future__ import annotations

import bisect
import copy
import csv
import json
import math
from dataclasses import dataclass, field

from sections import LUMBER, STEEL, W_SHAPES, WOOD_DENSITY_PCF

N_STEPS = 2000
VALID_TOL = 0.005  # validation cases must match within 0.5 %
DEFAULT_LIVE_LIMIT = 360.0
DEFAULT_TOTAL_LIMIT = 240.0


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def default_cfg() -> dict:
    """The W12x26 validation beam (case 1), which the app opens with."""
    return {
        "support": "ss", "L": 20.0, "material": "steel", "section": "W12x26",
        "CD": 1.0, "repetitive": False, "self_weight": False,
        "live_limit": DEFAULT_LIVE_LIMIT, "total_limit": DEFAULT_TOTAL_LIMIT, "factor": 1.0,
        "loads": [{"type": "udl", "w": 1.0, "x1": 0.0, "x2": 20.0, "tag": "L"}],
    }


# ---------------------------------------------------------------- member

@dataclass
class Member:
    material: str
    name: str
    props: dict
    E: float        # ksi
    I: float        # in⁴
    S: float        # in³
    A: float        # in²
    w_self: float   # kip/ft
    bend_cap: float
    bend_unit: str
    bend_dec: int
    bend_label: str
    bend_cap_label: str
    shear_cap: float
    shear_unit: str
    shear_dec: int
    shear_label: str
    shear_cap_label: str

    def bending_demand(self, M_kft: float) -> float:
        if self.material == "steel":
            return abs(M_kft) * 12 / self.S              # ksi
        return abs(M_kft) * 12000 / self.S               # psi

    def shear_demand(self, V_k: float) -> float:
        if self.material == "steel":
            return abs(V_k)                               # kips
        return 1.5 * abs(V_k) * 1000 / self.A             # psi


def get_member(cfg: dict) -> Member | None:
    """Section, stiffness, self-weight, and allowable values for the chosen member."""
    if cfg["material"] == "steel":
        s = next((r for r in W_SHAPES if r["name"] == cfg["section"]), None)
        if s is None:
            return None
        Va = 0.6 * STEEL["Fy"] * s["d"] * s["tw"] / 1.50   # kips, Cv = 1.0
        return Member(
            material="steel", name=s["name"], props=dict(s),
            E=STEEL["E"], I=s["Ix"], S=s["Sx"], A=s["A"], w_self=s["wt"] / 1000,
            bend_cap=STEEL["Fb"], bend_unit="ksi", bend_dec=1,
            bend_label="Bending, fb = M / Sx", bend_cap_label="Fb = 0.66Fy",
            shear_cap=Va, shear_unit="kips", shear_dec=2,
            shear_label="Shear, V", shear_cap_label="Va = 0.6Fy·d·tw / 1.50",
        )
    w = next((r for r in LUMBER if r["name"] == cfg["section"]), None)
    if w is None:
        return None
    A = w["b"] * w["d"]
    S = w["b"] * w["d"] ** 2 / 6
    I = w["b"] * w["d"] ** 3 / 12
    CD = cfg["CD"]
    Cr = 1.15 if (cfg["repetitive"] and w["kind"] == "dim") else 1.0
    Fbp = w["Fb"] * CD * w["CF"] * Cr
    Fvp = w["Fv"] * CD
    props = dict(w, A=A, S=S, I=I, CD=CD, Cr=Cr, Fbp=Fbp, Fvp=Fvp)
    return Member(
        material="lumber", name=w["name"], props=props,
        E=w["E"] / 1000, I=I, S=S, A=A, w_self=WOOD_DENSITY_PCF * A / 144 / 1000,
        bend_cap=Fbp, bend_unit="psi", bend_dec=0,
        bend_label="Bending, fb = M / S", bend_cap_label="Fb' = Fb·CD·CF·Cr",
        shear_cap=Fvp, shear_unit="psi", shear_dec=1,
        shear_label="Shear, fv = 1.5V / A", shear_cap_label="Fv' = Fv·CD",
    )


# ---------------------------------------------------------------- input checks

def load_name(loads: list, i: int) -> str:
    """'Point load 2' or 'Uniform load 1', numbered within its own table."""
    kind = loads[i]["type"]
    n = sum(1 for ld in loads[: i + 1] if ld["type"] == kind)
    return f"{'Point' if kind == 'point' else 'Uniform'} load {n}"


def validate_cfg(cfg: dict) -> list[dict]:
    """Input checks. Returns [{"msg": str, "field": str}].

    field is "L", "CD", "live_limit", "total_limit", "section", or "load-<i>"
    for a row in the load list.
    """
    errs = []
    L = cfg.get("L")
    if not is_num(L) or L <= 0:
        errs.append({"msg": "Span must be a number greater than 0.", "field": "L"})
    elif L > 200:
        errs.append({"msg": "Span must be 200 ft or less.", "field": "L"})
    L_ok = is_num(L) and L > 0
    if cfg["material"] == "lumber" and (not is_num(cfg.get("CD")) or cfg["CD"] <= 0):
        errs.append({"msg": "C_D must be a number greater than 0.", "field": "CD"})
    for key, name in (("live_limit", "Live-load"), ("total_limit", "Total-load")):
        v = cfg.get(key, DEFAULT_LIVE_LIMIT if key == "live_limit" else DEFAULT_TOTAL_LIMIT)
        if not is_num(v) or v <= 0:
            errs.append({"msg": f"{name} deflection limit must be a number greater than 0.", "field": key})
    loads = cfg["loads"]
    for i, ld in enumerate(loads):
        name, fld = load_name(loads, i), f"load-{i}"
        if ld["type"] == "point":
            if not is_num(ld.get("P")):
                errs.append({"msg": f"{name}: enter a magnitude P.", "field": fld})
            if not is_num(ld.get("x")):
                errs.append({"msg": f"{name}: enter a position x.", "field": fld})
            elif L_ok and not (0 <= ld["x"] <= L):
                errs.append({"msg": f"{name}: position must be between 0 and {L:g} ft.", "field": fld})
        else:
            if not is_num(ld.get("w")):
                errs.append({"msg": f"{name}: enter a magnitude w.", "field": fld})
            ok_a, ok_b = is_num(ld.get("x1")), is_num(ld.get("x2"))
            if not ok_a:
                errs.append({"msg": f"{name}: enter a start position.", "field": fld})
            if not ok_b:
                errs.append({"msg": f"{name}: enter an end position.", "field": fld})
            if ok_a and L_ok and not (0 <= ld["x1"] <= L):
                errs.append({"msg": f"{name}: start must be between 0 and {L:g} ft.", "field": fld})
            if ok_b and L_ok and not (0 <= ld["x2"] <= L):
                errs.append({"msg": f"{name}: end must be between 0 and {L:g} ft.", "field": fld})
            if ok_a and ok_b and ld["x2"] <= ld["x1"]:
                errs.append({"msg": f"{name}: end must be greater than start.", "field": fld})
    return errs


# ---------------------------------------------------------------- analysis

@dataclass
class Extreme:
    v: float
    x: float


@dataclass
class Analysis:
    xs: list
    M: list           # kip-ft at each x
    D: list           # deflection (in), downward positive
    shear_pts: list   # [(x, V)], with two points at each shear jump
    R1: float         # left (or fixed-end) vertical reaction, kips
    R2: float         # right reaction, kips (0 for a cantilever)
    M0: float         # fixed-end moment, kip-ft (0 for simply supported)
    Vmax: Extreme
    Vmin: Extreme
    Vabs: float
    Mmax: Extreme
    Mmin: Extreme
    Mabs: float
    MabsX: float
    dMax: float
    dX: float


def _load_key(ld: dict) -> tuple:
    if ld["type"] == "point":
        return ("point", ld["P"], ld["x"])
    return ("udl", ld["w"], ld["x1"], ld["x2"])


_statics_cache: dict = {}


def _statics(L: float, support: str, loads: tuple):
    """Reactions, grid, moment, and shear for one load set (cached; independent of the section)."""
    key = (L, support, loads)
    hit = _statics_cache.get(key)
    if hit is not None:
        return hit

    F = Mo = 0.0  # total load (kips) and its moment about the left end (kip-ft)
    for ld in loads:
        if ld[0] == "point":
            F += ld[1]
            Mo += ld[1] * ld[2]
        else:
            W = ld[1] * (ld[3] - ld[2])
            F += W
            Mo += W * (ld[2] + ld[3]) / 2
    if support == "ss":
        R2 = Mo / L
        R1 = F - R2
        M0 = 0.0
    else:  # fixed at left: vertical reaction and fixed-end moment
        R1, R2, M0 = F, 0.0, -Mo

    # Grid: uniform steps plus every load location and uniform-load end.
    # When a grid point and a load location nearly coincide, keep the load location.
    raw = [(L * i / N_STEPS, False) for i in range(N_STEPS + 1)]
    for ld in loads:
        if ld[0] == "point":
            raw.append((ld[2], True))
        else:
            raw.append((ld[2], True))
            raw.append((ld[3], True))
    raw.sort(key=lambda r: r[0])
    xs: list = []
    xs_is_load: list = []
    tol = 1e-9 * L
    for x, is_ld in raw:
        if xs and x - xs[-1] <= tol:
            if is_ld and not xs_is_load[-1]:
                xs[-1], xs_is_load[-1] = x, True
            continue
        xs.append(x)
        xs_is_load.append(is_ld)
    n = len(xs)

    # V just left of x, and M at x
    V = [R1] * n
    M = [M0 + R1 * x for x in xs]
    jump_at: dict = {}  # x -> total point load applied exactly there
    for ld in loads:
        if ld[0] == "point":
            P, xp = ld[1], ld[2]
            jump_at[xp] = jump_at.get(xp, 0.0) + P
            start = bisect.bisect_right(xs, xp)
            for i in range(start, n):
                V[i] -= P
                M[i] -= P * (xs[i] - xp)
        else:
            w, a, b_end = ld[1], ld[2], ld[3]
            start = bisect.bisect_right(xs, a)
            for i in range(start, n):
                x = xs[i]
                b = b_end if b_end < x else x
                Wp = w * (b - a)
                V[i] -= Wp
                M[i] -= Wp * (x - (a + b) / 2)

    shear_pts = []
    vmax = Extreme(-math.inf, 0.0)
    vmin = Extreme(math.inf, 0.0)

    def track(v, x):
        nonlocal vmax, vmin
        if v > vmax.v:
            vmax = Extreme(v, x)
        if v < vmin.v:
            vmin = Extreme(v, x)

    for i, x in enumerate(xs):
        Vl = V[i]
        if i == 0:
            Vr = Vl - jump_at.get(x, 0.0)
            shear_pts.append((x, Vr))
            track(Vr, x)
        elif i == n - 1:
            shear_pts.append((x, Vl))
            track(Vl, x)
        else:
            shear_pts.append((x, Vl))
            track(Vl, x)
            if x in jump_at:
                Vr = Vl - jump_at[x]
                shear_pts.append((x, Vr))
                track(Vr, x)

    if len(_statics_cache) > 512:
        _statics_cache.clear()
    out = (xs, M, shear_pts, R1, R2, M0, vmax, vmin)
    _statics_cache[key] = out
    return out


def analyze(L: float, support: str, loads: list, E: float, I: float) -> Analysis:
    """Statics plus numerical double integration for one set of loads."""
    xs, M, shear_pts, R1, R2, M0, vmax, vmin = _statics(L, support, tuple(_load_key(l) for l in loads))
    n = len(xs)

    mmax = Extreme(-math.inf, 0.0)
    mmin = Extreme(math.inf, 0.0)
    for i, m in enumerate(M):
        if m > mmax.v:
            mmax = Extreme(m, xs[i])
        if m < mmin.v:
            mmin = Extreme(m, xs[i])

    # Deflection: EI y'' = M, y positive up. Trapezoidal integration in inches.
    EI = E * I
    k = 12 / EI
    th = 0.0
    y = [0.0] * n
    for i in range(1, n):
        dx = (xs[i] - xs[i - 1]) * 12
        th_new = th + 0.5 * (M[i - 1] + M[i]) * k * dx
        y[i] = y[i - 1] + 0.5 * (th + th_new) * dx
        th = th_new
    if support == "ss":  # y(0) = y(L) = 0
        yL, xL = y[-1], xs[-1]
        D = [-(y[i] - yL * xs[i] / xL) for i in range(n)]
    else:                # cantilever: y(0) = 0 and slope(0) = 0 already
        D = [-v for v in y]
    d_idx = 0
    for i in range(n):
        if abs(D[i]) > abs(D[d_idx]):
            d_idx = i

    return Analysis(
        xs=xs, M=M, D=D, shear_pts=shear_pts, R1=R1, R2=R2, M0=M0,
        Vmax=vmax, Vmin=vmin, Vabs=max(abs(vmax.v), abs(vmin.v)),
        Mmax=mmax, Mmin=mmin, Mabs=max(abs(mmax.v), abs(mmin.v)),
        MabsX=mmax.x if abs(mmax.v) >= abs(mmin.v) else mmin.x,
        dMax=D[d_idx], dX=xs[d_idx],
    )


# ---------------------------------------------------------------- design

@dataclass
class Check:
    label: str
    demand: float
    cap: float
    unit: str
    dec: int
    cap_label: str
    ratio: float = field(init=False)
    passed: bool = field(init=False)

    def __post_init__(self):
        self.ratio = self.demand / self.cap if self.cap > 0 else math.inf
        self.passed = self.demand <= self.cap * (1 + 1e-9)


CHECK_KEYS = ("bending", "shear", "live", "total")


@dataclass
class Result:
    errors: list
    member: Member | None = None
    loads: list | None = None     # loads used, including self-weight and the multiplier
    total: Analysis | None = None
    live: Analysis | None = None
    dead: Analysis | None = None
    checks: dict | None = None
    Leff: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors

    def all_pass(self) -> bool:
        return all(self.checks[k].passed for k in CHECK_KEYS)

    def governing(self) -> tuple[str, Check]:
        key = max(CHECK_KEYS, key=lambda k: self.checks[k].ratio)
        return key, self.checks[key]


def design(cfg: dict) -> Result:
    """Full design: three load cases and four checks."""
    errors = validate_cfg(cfg)
    member = get_member(cfg) if not any(e["field"] == "CD" for e in errors) else None
    if member is None and not any(e["field"] == "CD" for e in errors):
        errors.append({"msg": "Choose a section.", "field": "section"})
    if errors:
        return Result(errors=errors, member=member)

    # The what-if multiplier scales the entered loads (not self-weight). Defaults to 1.
    f = cfg.get("factor", 1.0)
    if not is_num(f) or f < 0:
        f = 1.0
    loads = []
    for ld in cfg["loads"]:
        ld = dict(ld)
        if ld["type"] == "point":
            ld["P"] *= f
        else:
            ld["w"] *= f
        loads.append(ld)
    if cfg.get("self_weight"):
        loads.append({"type": "udl", "w": member.w_self, "x1": 0.0, "x2": cfg["L"], "tag": "D", "self": True})

    def run(lst):
        return analyze(cfg["L"], cfg["support"], lst, member.E, member.I)

    total = run(loads)
    live = run([l for l in loads if l["tag"] == "L"])
    dead = run([l for l in loads if l["tag"] == "D"])

    Leff = cfg["L"] if cfg["support"] == "ss" else 2 * cfg["L"]
    Lname = "L" if cfg["support"] == "ss" else "2L"
    n_live = cfg.get("live_limit", DEFAULT_LIVE_LIMIT)
    n_total = cfg.get("total_limit", DEFAULT_TOTAL_LIMIT)
    m = member
    checks = {
        "bending": Check(m.bend_label, m.bending_demand(total.Mabs), m.bend_cap, m.bend_unit, m.bend_dec, m.bend_cap_label),
        "shear": Check(m.shear_label, m.shear_demand(total.Vabs), m.shear_cap, m.shear_unit, m.shear_dec, m.shear_cap_label),
        "live": Check("Live-load deflection", abs(live.dMax), Leff * 12 / n_live, "in", 3, f"{Lname}/{n_live:g}"),
        "total": Check("Total-load deflection", abs(total.dMax), Leff * 12 / n_total, "in", 3, f"{Lname}/{n_total:g}"),
    }
    return Result(errors=[], member=member, loads=loads, total=total, live=live, dead=dead, checks=checks, Leff=Leff)


def reserve_factor(cfg: dict):
    """Multiplier on the entered loads at which the first check reaches 1.0.

    Every ratio is linear in the multiplier (self-weight stays fixed), so two runs
    give it exactly for same-sign loads. Returns (k, label), with k = inf when the
    entered loads do not affect any check, or None when the inputs are invalid.
    """
    r1 = design(dict(cfg, factor=1.0))
    if r1.errors:
        return None
    r0 = design(dict(cfg, factor=0.0))
    best_k, best_label = math.inf, ""
    for key in CHECK_KEYS:
        a = r0.checks[key].ratio
        b = r1.checks[key].ratio - a
        if a >= 1:
            return 0.0, r0.checks[key].label
        if b > 1e-12 and (1 - a) / b < best_k:
            best_k, best_label = (1 - a) / b, r1.checks[key].label
    return best_k, best_label


CHECK_SHORT = {"bending": "Bending", "shear": "Shear", "live": "Δ live", "total": "Δ total"}


def compare_sections(cfg: dict) -> list[dict]:
    """Check every section of the chosen material under the same loads, lightest first."""
    rows = []
    for s in (W_SHAPES if cfg["material"] == "steel" else LUMBER):
        r = design(dict(cfg, section=s["name"]))
        if r.errors:
            continue
        key, chk = r.governing()
        rows.append({
            "name": s["name"], "wt": r.member.w_self * 1000, "ratio": chk.ratio,
            "gov": CHECK_SHORT[key], "pass": r.all_pass(),
        })
    rows.sort(key=lambda row: row["wt"])
    return rows


# ---------------------------------------------------------------- probe helpers

def interp(xs: list, ys: list, x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    hi = bisect.bisect_right(xs, x)
    lo = hi - 1
    span = xs[hi] - xs[lo] or 1.0
    return ys[lo] + (x - xs[lo]) / span * (ys[hi] - ys[lo])


def shear_at(pts: list, x: float) -> float:
    """Shear at x from the step-aware point list; at a jump, the value just right of x."""
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    lo, hi = 0, len(pts) - 1
    while hi - lo > 1:
        m = (lo + hi) // 2
        if pts[m][0] <= x:
            lo = m
        else:
            hi = m
    a, b = pts[lo], pts[hi]
    return a[1] + (x - a[0]) / (b[0] - a[0]) * (b[1] - a[1]) if b[0] > a[0] else b[1]


def fail_state(res: Result):
    """Which failure to show: strength (bending/shear) breaks the beam; deflection only sags it."""
    c, t = res.checks, res.total
    if not c["bending"].passed or not c["shear"].passed:
        bend = not c["bending"].passed and (c["shear"].passed or c["bending"].ratio >= c["shear"].ratio)
        if bend:
            x = t.MabsX
        else:
            x = t.Vmax.x if abs(t.Vmax.v) >= abs(t.Vmin.v) else t.Vmin.x
        k = c["bending"] if bend else c["shear"]
        return {"kind": "bending" if bend else "shear", "x": x, "ratio": k.ratio, "check": k}
    if not c["live"].passed or not c["total"].passed:
        k = c["total"] if c["total"].ratio >= c["live"].ratio else c["live"]
        return {"kind": "deflection", "x": t.dX, "ratio": k.ratio, "check": k}
    return None


# ---------------------------------------------------------------- validation cases (spec.md)

_BASE = {"support": "ss", "L": 20.0, "material": "steel", "section": "W12x26",
         "CD": 1.0, "repetitive": False, "self_weight": False, "factor": 1.0}

VALIDATION = [
    {"name": "1. 20 ft SS W12x26, 1 kip/ft live",
     "cfg": dict(_BASE, loads=[{"type": "udl", "w": 1.0, "x1": 0.0, "x2": 20.0, "tag": "L"}]),
     "expect": [
         ("R left (kips)", lambda r: r.total.R1, 10.0),
         ("V max (kips)", lambda r: r.total.Vabs, 10.0),
         ("M max (kip-ft)", lambda r: r.total.Mabs, 50.0),
         ("fb (ksi)", lambda r: r.checks["bending"].demand, 18.0),
         ("Va (kips)", lambda r: r.checks["shear"].cap, 56.1),
         ("Δ live (in)", lambda r: r.checks["live"].demand, 0.609),
         ("L/360 (in)", lambda r: r.checks["live"].cap, 0.667),
     ]},
    {"name": "2. 20 ft SS W12x26, 10 kip live at midspan",
     "cfg": dict(_BASE, loads=[{"type": "point", "P": 10.0, "x": 10.0, "tag": "L"}]),
     "expect": [
         ("M max (kip-ft)", lambda r: r.total.Mabs, 50.0),
         ("Δ (in)", lambda r: r.checks["live"].demand, 0.487),
     ]},
    {"name": "3. 20 ft SS W12x26, 10 kip live at x = 5 ft",
     "cfg": dict(_BASE, loads=[{"type": "point", "P": 10.0, "x": 5.0, "tag": "L"}]),
     "expect": [
         ("R left (kips)", lambda r: r.total.R1, 7.5),
         ("R right (kips)", lambda r: r.total.R2, 2.5),
         ("M max (kip-ft)", lambda r: r.total.Mabs, 37.5),
         ("x at M max (ft)", lambda r: r.total.MabsX, 5.00),
         ("Δ max (in)", lambda r: r.checks["live"].demand, 0.340),
         ("x at Δ max (ft)", lambda r: r.total.dX, 8.82),
     ]},
    {"name": "4. 10 ft cantilever W8x18, 2 kip live at tip",
     "cfg": dict(_BASE, support="cant", L=10.0, section="W8x18",
                 loads=[{"type": "point", "P": 2.0, "x": 10.0, "tag": "L"}]),
     "expect": [
         ("M max (kip-ft)", lambda r: r.total.Mabs, 20.0),
         ("fb (ksi)", lambda r: r.checks["bending"].demand, 15.8),
         ("Δ tip (in)", lambda r: r.checks["live"].demand, 0.642),
         ("2L/360 (in)", lambda r: r.checks["live"].cap, 0.667),
     ]},
    {"name": "5. 12 ft SS 2x10 DF-L No. 2, 100 plf live, repetitive",
     "cfg": dict(_BASE, L=12.0, material="lumber", section="2x10", repetitive=True,
                 loads=[{"type": "udl", "w": 0.1, "x1": 0.0, "x2": 12.0, "tag": "L"}]),
     "expect": [
         ("M max (kip-ft)", lambda r: r.total.Mabs, 1.80),
         ("fb (psi)", lambda r: r.checks["bending"].demand, 1010),
         ("Fb' (psi)", lambda r: r.checks["bending"].cap, 1139),
         ("fv (psi)", lambda r: r.checks["shear"].demand, 64.9),
         ("Δ (in)", lambda r: r.checks["live"].demand, 0.295),
         ("L/360 (in)", lambda r: r.checks["live"].cap, 0.400),
     ]},
    {"name": "6. Case 1 with self-weight (26 plf dead)",
     "cfg": dict(_BASE, self_weight=True, loads=[{"type": "udl", "w": 1.0, "x1": 0.0, "x2": 20.0, "tag": "L"}]),
     "expect": [
         ("M max (kip-ft)", lambda r: r.total.Mabs, 51.3),
         ("Δ total (in)", lambda r: r.checks["total"].demand, 0.625),
         ("L/240 (in)", lambda r: r.checks["total"].cap, 1.00),
     ]},
]


def run_validation() -> list[dict]:
    """Run every validation case. Each row: label, expected, computed, relative diff, ok."""
    out = []
    for case in VALIDATION:
        r = design(copy.deepcopy(case["cfg"]))
        rows = []
        for label, get, exp in case["expect"]:
            got = math.nan if r.errors else get(r)
            diff = abs(got - exp) / abs(exp)
            rows.append({"label": label, "exp": exp, "got": got, "diff": diff, "ok": diff <= VALID_TOL})
        out.append({"name": case["name"], "cfg": case["cfg"], "rows": rows, "ok": all(x["ok"] for x in rows)})
    return out


# ---------------------------------------------------------------- results table (CSV)

CSV_HEADER = ("x (ft)", "V (kips)", "M (kip-ft)", "Deflection (in)")


def results_rows(res: Result) -> list[tuple]:
    """(x, V, M, deflection) along the beam for the total load case, downward deflection positive.

    One row per analysis point; at a shear jump x appears twice (V just left, then just right).
    """
    t = res.total
    rows = []
    i = 0
    n = len(t.xs)
    for x, v in t.shear_pts:
        while i < n - 1 and t.xs[i] < x:
            i += 1
        rows.append((x, v, t.M[i], t.D[i]))
    return rows


def write_results_csv(res: Result, path: str) -> int:
    """Write the results table as an Excel-friendly CSV. Returns the number of data rows."""
    rows = results_rows(res)
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(CSV_HEADER)
        for x, v, m, d in rows:
            w.writerow((fx(x, 4), fx(v, 4), fx(m, 4), fx(d, 5)))
    return len(rows)


# ---------------------------------------------------------------- design files (.beam)

FILE_APP = "Beam Designer"
FILE_VERSION = 1


def design_to_dict(cfg: dict) -> dict:
    """The saved form of a design. Raises ValueError if a value is not a number."""
    for key, label in (("L", "Span"), ("CD", "C_D"), ("live_limit", "Live-load deflection limit"),
                       ("total_limit", "Total-load deflection limit")):
        if not is_num(cfg.get(key)):
            raise ValueError(f"{label} must be a number before the design can be saved.")
    loads = []
    for ld in cfg["loads"]:
        if ld["type"] == "point":
            loads.append({"type": "point", "P_kips": ld["P"], "x_ft": ld["x"], "tag": ld["tag"]})
        else:
            loads.append({"type": "udl", "w_kip_per_ft": ld["w"], "start_ft": ld["x1"], "end_ft": ld["x2"],
                          "tag": ld["tag"]})
    return {
        "app": FILE_APP,
        "version": FILE_VERSION,
        "support": cfg["support"],
        "span_ft": cfg["L"],
        "material": cfg["material"],
        "section": cfg["section"],
        "CD": cfg["CD"],
        "repetitive": bool(cfg["repetitive"]),
        "self_weight": bool(cfg["self_weight"]),
        "deflection_limits": {"live": cfg["live_limit"], "total": cfg["total_limit"]},
        "loads": loads,
    }


def design_from_dict(d) -> dict:
    """Build a cfg from saved data. Raises ValueError with a readable message if the data is bad."""
    if not isinstance(d, dict) or d.get("app") != FILE_APP:
        raise ValueError("This is not a Beam Designer file.")
    ver = d.get("version")
    if not isinstance(ver, int) or ver < 1:
        raise ValueError("The file has no valid format version.")
    if ver > FILE_VERSION:
        raise ValueError(f"The file was made by a newer version of the app (format {ver}).")

    def num(obj, key, where):
        v = obj.get(key) if isinstance(obj, dict) else None
        if not is_num(v):
            raise ValueError(f"{where}: '{key}' is missing or not a number.")
        return float(v)

    def flag(key):
        v = d.get(key, False)
        if not isinstance(v, bool):
            raise ValueError(f"'{key}' must be true or false.")
        return v

    support = d.get("support")
    if support not in ("ss", "cant"):
        raise ValueError("'support' must be \"ss\" (simply supported) or \"cant\" (cantilever).")
    material = d.get("material")
    if material not in ("steel", "lumber"):
        raise ValueError("'material' must be \"steel\" or \"lumber\".")
    names = [r["name"] for r in (W_SHAPES if material == "steel" else LUMBER)]
    section = d.get("section")
    if section not in names:
        raise ValueError(f"Section '{section}' is not in the {material} list.")
    limits = d.get("deflection_limits", {"live": DEFAULT_LIVE_LIMIT, "total": DEFAULT_TOTAL_LIMIT})
    raw_loads = d.get("loads")
    if not isinstance(raw_loads, list):
        raise ValueError("'loads' must be a list.")
    loads = []
    for i, ld in enumerate(raw_loads, start=1):
        where = f"Load {i}"
        if not isinstance(ld, dict) or ld.get("type") not in ("point", "udl"):
            raise ValueError(f"{where}: 'type' must be \"point\" or \"udl\".")
        tag = ld.get("tag")
        if tag not in ("D", "L"):
            raise ValueError(f"{where}: 'tag' must be \"D\" (dead) or \"L\" (live).")
        if ld["type"] == "point":
            loads.append({"type": "point", "P": num(ld, "P_kips", where), "x": num(ld, "x_ft", where), "tag": tag})
        else:
            loads.append({"type": "udl", "w": num(ld, "w_kip_per_ft", where), "x1": num(ld, "start_ft", where),
                          "x2": num(ld, "end_ft", where), "tag": tag})
    return {
        "support": support,
        "L": num(d, "span_ft", "File"),
        "material": material,
        "section": section,
        "CD": num(d, "CD", "File") if "CD" in d else 1.0,
        "repetitive": flag("repetitive"),
        "self_weight": flag("self_weight"),
        "live_limit": num(limits, "live", "Deflection limits"),
        "total_limit": num(limits, "total", "Deflection limits"),
        "factor": 1.0,
        "loads": loads,
    }


def save_design(cfg: dict, path: str) -> None:
    data = design_to_dict(cfg)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def open_design(path: str) -> dict:
    """Read a .beam file. Raises ValueError with a readable message on any problem."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        raise ValueError(f"The file could not be read: {e.strerror or e}.") from e
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError("The file is not valid JSON, so it is not a Beam Designer file.") from e
    return design_from_dict(data)


# ---------------------------------------------------------------- report

def fx(v: float, d: int) -> str:
    """Fixed decimals without a negative zero."""
    s = f"{v:.{d}f}"
    return s[1:] if s.startswith("-") and float(s) == 0 else s


def report_text(cfg: dict, res: Result) -> str:
    """Plain-text report for turning in work."""
    m, t, c = res.member, res.total, res.checks
    sup = "Simply supported (pin at x = 0, roller at x = L)" if cfg["support"] == "ss" \
        else "Cantilever (fixed at x = 0, free at x = L)"
    lines = ["BEAM DESIGNER REPORT", "=" * 60, "", "INPUTS",
             f"  Support:      {sup}", f"  Span L:       {fx(cfg['L'], 2)} ft"]
    if m.material == "steel":
        lines.append(f"  Member:       {m.name}, A992 steel (Fy = 50 ksi, E = 29,000 ksi)")
    else:
        lines.append(f"  Member:       {m.name}, Douglas Fir-Larch No. 2")
        lines.append(f"  C_D:          {cfg['CD']:g}    Repetitive (C_r): {'yes' if cfg['repetitive'] else 'no'}")
    lines.append(f"  Self-weight:  {'included, ' + fx(m.w_self * 1000, 1) + ' lb/ft' if cfg['self_weight'] else 'not included'}")
    lines.append(f"  Deflection limits: live {c['live'].cap_label}, total {c['total'].cap_label}")
    if cfg.get("factor", 1) != 1:
        lines.append(f"  What-if:      entered loads × {fx(cfg['factor'], 2)}")
    lines.append("  Loads (as entered):")
    if not cfg["loads"]:
        lines.append("    none")
    for i, ld in enumerate(cfg["loads"]):
        tag = "Dead" if ld["tag"] == "D" else "Live"
        if ld["type"] == "point":
            lines.append(f"    {load_name(cfg['loads'], i)}: P = {ld['P']:g} kips at x = {ld['x']:g} ft ({tag})")
        else:
            lines.append(f"    {load_name(cfg['loads'], i)}: w = {ld['w']:g} kip/ft from {ld['x1']:g} to {ld['x2']:g} ft ({tag})")

    lines += ["", "SECTION PROPERTIES"]
    p = m.props
    if m.material == "steel":
        lines += [f"  d = {p['d']} in, tw = {p['tw']} in, A = {p['A']} in², Ix = {p['Ix']} in⁴, Sx = {p['Sx']} in³",
                  f"  Weight = {p['wt']} lb/ft, Fb = {fx(m.bend_cap, 1)} ksi, Va = {fx(m.shear_cap, 1)} kips"]
    else:
        lines += [f"  b × d = {p['b']} × {p['d']} in, A = {fx(p['A'], 2)} in², S = {fx(p['S'], 2)} in³, I = {fx(p['I'], 1)} in⁴",
                  f"  E = {p['E']:,} psi, Fb' = {p['Fb']} · {p['CD']:g} · {p['CF']} · {p['Cr']} = {fx(p['Fbp'], 0)} psi, "
                  f"Fv' = {fx(p['Fvp'], 0)} psi"]

    lines += ["", "REACTIONS (D + L)"]
    if cfg["support"] == "ss":
        lines.append(f"  R left = {fx(t.R1, 2)} kips, R right = {fx(t.R2, 2)} kips")
    else:
        lines.append(f"  R = {fx(t.R1, 2)} kips, M = {fx(abs(t.M0), 2)} kip-ft at the fixed end")

    lines += ["", "MAXIMUM VALUES (D + L)",
              f"  V max = {fx(t.Vmax.v, 2)} kips at x = {fx(t.Vmax.x, 2)} ft",
              f"  V min = {fx(t.Vmin.v, 2)} kips at x = {fx(t.Vmin.x, 2)} ft",
              f"  M max = {fx(t.Mmax.v, 2)} kip-ft at x = {fx(t.Mmax.x, 2)} ft",
              f"  M min = {fx(t.Mmin.v, 2)} kip-ft at x = {fx(t.Mmin.x, 2)} ft",
              f"  Δ total = {fx(abs(t.dMax), 3)} in at x = {fx(t.dX, 2)} ft",
              f"  Δ live  = {fx(abs(res.live.dMax), 3)} in at x = {fx(res.live.dX, 2)} ft"]

    lines += ["", "CHECKS",
              f"  {'Check':<26}{'Demand':>14}{'Capacity':>14}{'Ratio':>8}  Result",
              "  " + "-" * 70]
    for k in CHECK_KEYS:
        ch = c[k]
        lines.append(f"  {ch.label:<26}{fx(ch.demand, ch.dec) + ' ' + ch.unit:>14}"
                     f"{fx(ch.cap, ch.dec) + ' ' + ch.unit:>14}{fx(ch.ratio, 2):>8}  {'PASS' if ch.passed else 'FAIL'}")
        lines.append(f"  {'':<26}{'':>14}{'(' + ch.cap_label + ')':>14}")
    gk, g = res.governing()
    failed = [CHECK_SHORT[k] for k in CHECK_KEYS if not c[k].passed]
    lines += ["", "RESULT: " + ("PASSES ALL CHECKS" if not failed else "FAILS: " + ", ".join(failed)),
              f"Governing check: {CHECK_SHORT[gk]} at ratio {fx(g.ratio, 2)}", ""]
    return "\n".join(lines)
