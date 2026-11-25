"""Calculation sheet PDF: inputs at the top, then checks, reactions, and diagrams.

No Tkinter here. The diagrams arrive as "drawings": plain lists of shapes in
canvas pixels, which beam_app.py collects from its canvas. Each drawing is
    {"width": px, "height": px, "items": [...]}
with items
    ("line", pts, color, width, dash)
    ("poly", pts, fill, outline, width, dash)
    ("rect", x0, y0, x1, y1, fill, outline, width, dash)
    ("oval", x0, y0, x1, y1, fill, outline, width)
    ("text", x, y, text, size_px, bold, color, anchor, angle)
where pts is [(x, y), ...] and anchor is a Tk compass anchor.
"""

from __future__ import annotations

import beam_calc as bc
from beam_calc import fx
from pdf_writer import LETTER, Document, text_width

INK, MUTED, LINE = "#1b2430", "#5f6c7b", "#c9d1db"
PASS, FAIL = "#1d7a4c", "#b8322a"
MARGIN = 40.0
FOOTER_H = 44.0
MIN_ONE_PAGE_SCALE = 0.5   # below this, the V/M/Δ diagrams move to page 2


def draw_drawing(page, drawing, ox, oy, s):
    """Place a drawing with its top-left at (ox, oy), scaled by s (points per pixel)."""
    P = lambda pts: [(ox + x * s, oy + y * s) for x, y in pts]
    for it in drawing["items"]:
        kind = it[0]
        if kind == "line":
            _, pts, color, width, dash = it
            page.line(P(pts), color, width * s, [d * s for d in dash] if dash else None)
        elif kind == "poly":
            _, pts, fill, outline, width, dash = it
            page.polygon(P(pts), fill, outline, width * s, [d * s for d in dash] if dash else None)
        elif kind == "rect":
            _, x0, y0, x1, y1, fill, outline, width, dash = it
            page.rect(ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s, fill, outline, width * s,
                      [d * s for d in dash] if dash else None)
        elif kind == "oval":
            _, x0, y0, x1, y1, fill, outline, width = it
            page.ellipse(ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s, fill, outline, width * s)
        elif kind == "text":
            _, x, y, txt, size, bold, color, anchor, angle = it
            page.text(ox + x * s, oy + y * s, txt, size * s, bold, color, anchor, angle)


def wrap(text: str, width: float, size: float, bold=False) -> list[str]:
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and text_width(trial, size, bold) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    lines.append(cur)
    return lines


def input_rows(cfg: dict, res: bc.Result):
    m, p, c = res.member, res.member.props, res.checks
    rows = [("Support", "Simply supported (pin at x = 0, roller at x = L)" if cfg["support"] == "ss"
             else "Cantilever (fixed at x = 0, free at x = L)"),
            ("Span", f"L = {fx(cfg['L'], 2)} ft")]
    if m.material == "steel":
        rows += [("Member", f"{m.name}, A992 steel (Fy = 50 ksi, E = 29,000 ksi)"),
                 ("Section", f"d = {p['d']} in, tw = {p['tw']} in, A = {p['A']} in², Ix = {p['Ix']} in⁴, "
                             f"Sx = {p['Sx']} in³, {p['wt']} lb/ft"),
                 ("Allowables", f"Fb = 0.66Fy = {fx(m.bend_cap, 1)} ksi; Va = {fx(m.shear_cap, 1)} kips")]
    else:
        rows += [("Member", f"{m.name} Douglas Fir-Larch No. 2 (E = {p['E']:,} psi)"),
                 ("Section", f"b × d = {p['b']} × {p['d']} in, A = {fx(p['A'], 2)} in², S = {fx(p['S'], 2)} in³, "
                             f"I = {fx(p['I'], 1)} in⁴"),
                 ("Factors", f"C_D = {p['CD']:g}, C_F = {p['CF']}, C_r = {p['Cr']}"
                             f"{' (repetitive)' if cfg['repetitive'] else ''}"),
                 ("Allowables", f"Fb′ = {p['Fb']}·{p['CD']:g}·{p['CF']}·{p['Cr']} = {fx(p['Fbp'], 0)} psi; "
                                f"Fv′ = {fx(p['Fvp'], 0)} psi")]
    rows.append(("Self-weight", f"included, {fx(m.w_self * 1000, 1)} lb/ft (dead)" if cfg["self_weight"]
                 else "not included"))
    rows.append(("Deflection limits", f"live {c['live'].cap_label}, total {c['total'].cap_label}"))
    if cfg.get("factor", 1) != 1:
        rows.append(("What-if", f"entered loads × {fx(cfg['factor'], 2)}"))
    return rows


def load_rows(cfg: dict) -> list[str]:
    out = []
    for i, ld in enumerate(cfg["loads"]):
        tag = "Dead" if ld["tag"] == "D" else "Live"
        if ld["type"] == "point":
            out.append(f"{i + 1}. Point: P = {ld['P']:g} kips at x = {ld['x']:g} ft ({tag})")
        else:
            out.append(f"{i + 1}. Uniform: w = {ld['w']:g} kip/ft from {ld['x1']:g} to {ld['x2']:g} ft ({tag})")
    return out or ["None"]


def build_calc_sheet(cfg: dict, res: bc.Result, sketch: dict, diagrams: dict, meta: dict,
                     diagrams_tall: dict | None = None) -> bytes:
    """Return the PDF bytes. meta: {"name": design name, "date": "YYYY-MM-DD", "note": optional}.

    diagrams is drawn under the sketch on page 1 when it fits; otherwise the V/M/Δ diagrams go to
    page 2, using diagrams_tall (taller plots) when given.
    """
    doc = Document(LETTER, title=f"Beam calculation sheet - {meta.get('name', '')}", author="Beam Designer")
    W, H = LETTER
    right = W - MARGIN
    content_w = right - MARGIN
    bottom = H - MARGIN - FOOTER_H
    pages = []

    def new_page(first):
        pg = doc.new_page()
        pages.append(pg)
        pg.text(MARGIN, MARGIN, "Beam Calculation Sheet" + ("" if first else " (continued)"),
                16 if first else 12, True, INK, "nw")
        pg.text(right, MARGIN + 2, meta.get("date", ""), 9, False, MUTED, "ne")
        pg.text(right, MARGIN + 14, meta.get("name", ""), 9, True, INK, "ne")
        y = MARGIN + 28
        pg.line([(MARGIN, y), (right, y)], LINE, 0.8)
        return pg, y + 10

    page, y = new_page(True)

    def heading(text, yy):
        page.text(MARGIN, yy, text, 10, True, INK, "nw")
        return yy + 15

    # ---- inputs
    y = heading("Inputs", y)
    fs, row_h = 8.5, 11.5
    key_w, left_w = 78.0, 318.0
    col2 = MARGIN + left_w + 14
    y_left = y
    for key, val in input_rows(cfg, res):
        lines = wrap(val, left_w - key_w - 6, fs)
        page.text(MARGIN, y_left, key, fs, False, MUTED, "nw")
        for ln in lines:
            page.text(MARGIN + key_w, y_left, ln, fs, False, INK, "nw")
            y_left += row_h
    y_right = y
    page.text(col2, y_right, "Loads (as entered)", fs, True, INK, "nw")
    y_right += row_h
    for ln in load_rows(cfg):
        for part in wrap(ln, right - col2, fs):
            page.text(col2, y_right, part, fs, False, INK, "nw")
            y_right += row_h
    y = max(y_left, y_right) + 6

    # ---- checks
    page.line([(MARGIN, y), (right, y)], LINE, 0.6)
    y = heading("Checks (D + L)", y + 6)
    cols = {"chk": MARGIN, "dem": MARGIN + 250, "cap": MARGIN + 322, "lim": MARGIN + 330,
            "rat": MARGIN + 462, "res": MARGIN + 476}
    for k, label, anchor in (("chk", "Check", "nw"), ("dem", "Demand", "ne"), ("cap", "Capacity", "ne"),
                             ("lim", "Limit", "nw"), ("rat", "Ratio", "ne"), ("res", "Result", "nw")):
        page.text(cols[k], y, label, 8, True, MUTED, anchor)
    y += 11
    page.line([(MARGIN, y), (right, y)], LINE, 0.5)
    y += 4
    for key in bc.CHECK_KEYS:
        ch = res.checks[key]
        page.text(cols["chk"], y, ch.label, fs, False, INK, "nw")
        page.text(cols["dem"], y, f"{fx(ch.demand, ch.dec)} {ch.unit}", fs, False, INK, "ne")
        page.text(cols["cap"], y, f"{fx(ch.cap, ch.dec)} {ch.unit}", fs, False, INK, "ne")
        page.text(cols["lim"], y, ch.cap_label, 7.5, False, MUTED, "nw")
        page.text(cols["rat"], y, fx(ch.ratio, 2), fs, False, INK, "ne")
        page.text(cols["res"], y, "PASS" if ch.passed else "FAIL", fs, True, PASS if ch.passed else FAIL, "nw")
        y += row_h + 1
    failed = [bc.CHECK_SHORT[k] for k in bc.CHECK_KEYS if not res.checks[k].passed]
    gk, g = res.governing()
    verdict = "PASSES ALL CHECKS" if not failed else "FAILS: " + ", ".join(failed)
    y += 3
    page.text(MARGIN, y, verdict, 10, True, PASS if not failed else FAIL, "nw")
    page.text(MARGIN + text_width(verdict, 10, True) + 10, y + 1.5,
              f"Governing: {g.label.split(',')[0].lower()} at ratio {fx(g.ratio, 2)}", fs, False, MUTED, "nw")
    y += 16

    # ---- reactions and maximums
    t = res.total
    react = (f"Reactions: R left = {fx(t.R1, 2)} kips, R right = {fx(t.R2, 2)} kips" if cfg["support"] == "ss"
             else f"Reactions at the fixed end: R = {fx(t.R1, 2)} kips, M = {fx(abs(t.M0), 2)} kip-ft")
    page.text(MARGIN, y, react, fs, False, INK, "nw")
    y += row_h
    vx = t.Vmax if abs(t.Vmax.v) >= abs(t.Vmin.v) else t.Vmin
    mx = t.Mmax if abs(t.Mmax.v) >= abs(t.Mmin.v) else t.Mmin
    maxes = (f"Maximums: |V| = {fx(abs(vx.v), 2)} kips at x = {fx(vx.x, 2)} ft;  "
             f"|M| = {fx(abs(mx.v), 2)} kip-ft at x = {fx(mx.x, 2)} ft;  "
             f"Δ total = {fx(abs(t.dMax), 3)} in at x = {fx(t.dX, 2)} ft;  "
             f"Δ live = {fx(abs(res.live.dMax), 3)} in")
    for ln in wrap(maxes, content_w, fs):
        page.text(MARGIN, y, ln, fs, False, INK, "nw")
        y += row_h
    y += 4

    # ---- diagrams
    page.line([(MARGIN, y), (right, y)], LINE, 0.6)
    y = heading("Diagrams (D + L)", y + 6)
    if meta.get("note"):
        page.text(right, y - 15, meta["note"], 7.5, False, MUTED, "ne")
    Ws, Hs = sketch["width"], sketch["height"]
    Wd, Hd = diagrams["width"], diagrams["height"]
    s_full = content_w / max(Ws, Wd)
    avail = bottom - y
    s_one = min(s_full, avail / (Hs + Hd))
    if s_one >= MIN_ONE_PAGE_SCALE:
        x0 = MARGIN + (content_w - Ws * s_one) / 2
        draw_drawing(page, sketch, x0, y, s_one)
        draw_drawing(page, diagrams, x0, y + Hs * s_one, s_one)
    else:
        s1 = min(s_full, avail / Hs)
        draw_drawing(page, sketch, MARGIN + (content_w - Ws * s1) / 2, y, s1)
        page, y = new_page(False)
        y = heading("Shear, moment, and deflection (D + L)", y)
        dg = diagrams_tall or diagrams
        s2 = min(content_w / dg["width"], (bottom - y) / dg["height"])
        draw_drawing(page, dg, MARGIN + (content_w - dg["width"] * s2) / 2, y, s2)

    # ---- footers
    n = len(pages)
    for i, pg in enumerate(pages, start=1):
        fy = H - MARGIN - FOOTER_H + 10
        pg.line([(MARGIN, fy), (right, fy)], LINE, 0.6)
        sig_y = fy + 18
        x = MARGIN
        for label, blank in (("Designed by", 120), ("Checked by", 120), ("Date", 70)):
            pg.text(x, sig_y, label, 8.5, False, MUTED, "sw")
            lx = x + text_width(label, 8.5) + 4
            pg.line([(lx, sig_y), (lx + blank, sig_y)], MUTED, 0.5)
            x = lx + blank + 18
        pg.text(right, sig_y, f"Page {i} of {n}", 8.5, False, MUTED, "se")
        pg.text(MARGIN, sig_y + 12, "Section data: AISC Shapes Database v16.0 and NDS Supplement (verify before "
                "release). Generated by Beam Designer.", 7, False, MUTED, "nw")
    return doc.to_bytes()
