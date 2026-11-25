"""Minimal PDF writer (standard library only) for the calculation sheet.

Coordinates are in points with the origin at the TOP-LEFT of the page and y
pointing down, like a Tkinter canvas. Text uses the built-in PDF fonts
Helvetica, Helvetica-Bold, and Symbol (for Δ, arrows, and similar), so no font
files are embedded.
"""

from __future__ import annotations

import math
import zlib

LETTER = (612.0, 792.0)

# Helvetica and Helvetica-Bold advance widths (per 1000 em) for ASCII 32–126 (Adobe AFM).
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_HELV_B = [
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
    975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
    333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
    611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584,
]
# Widths of the non-ASCII WinAnsi characters the app uses.
_EXTRA = {"×": 584, "·": 278, "±": 584, "²": 333, "³": 333, "°": 400, "—": 1000, "–": 556,
          "’": 222, "‘": 222, "“": 333, "”": 333, "•": 350, "µ": 556}
# Characters drawn with the Symbol font: (byte in Symbol encoding, width).
_SYMBOL = {"Δ": (0x44, 612), "↓": (0xAF, 603), "↑": (0xAD, 603), "′": (0xA2, 247),
           "≤": (0xA3, 549), "≥": (0xB3, 549), "∞": (0xA5, 713), "→": (0xAE, 987)}
# Superscripts not in WinAnsi: drawn as a smaller, raised digit.
_SUPER = {"⁴": "4", "⁰": "0", "¹": "1", "⁵": "5"}

ASCENT, DESCENT = 0.718, 0.207   # Helvetica, per em


def _hex(color) -> tuple[float, float, float] | None:
    if color is None or color == "":
        return None
    if isinstance(color, tuple):
        return color
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _num(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _escape(b: bytes) -> bytes:
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _runs(text: str, bold: bool):
    """Split text into (font, bytes, width_per_em, size_factor, rise_per_em) runs."""
    base = "F2" if bold else "F1"
    table = _HELV_B if bold else _HELV
    runs = []
    for ch in text:
        if ch in _SYMBOL:
            code, w = _SYMBOL[ch]
            item = ("F3", bytes([code]), w / 1000, 1.0, 0.0)
        elif ch in _SUPER:
            d = _SUPER[ch]
            item = (base, d.encode("ascii"), table[ord(d) - 32] / 1000 * 0.65, 0.65, 0.33)
        else:
            o = ord(ch)
            if 32 <= o <= 126:
                w = table[o - 32]
            else:
                w = _EXTRA.get(ch, 556)
            try:
                b = ch.encode("cp1252")
            except UnicodeEncodeError:
                b, w = b"?", table[ord("?") - 32]
            item = (base, b, w / 1000, 1.0, 0.0)
        if runs and runs[-1][0] == item[0] and runs[-1][3] == item[3] and runs[-1][4] == item[4]:
            f, bb, ww, sf, rise = runs[-1]
            runs[-1] = (f, bb + item[1], ww + item[2], sf, rise)
        else:
            runs.append(item)
    return runs


def text_width(text: str, size: float, bold: bool = False) -> float:
    return sum(r[2] for r in _runs(text, bold)) * size


class Page:
    def __init__(self, width: float, height: float):
        self.w, self.h = width, height
        self.ops: list[str] = []

    # -- state helpers
    def _y(self, y):
        return self.h - y

    def _stroke_state(self, color, width, dash):
        r, g, b = _hex(color)
        self.ops.append(f"{_num(r)} {_num(g)} {_num(b)} RG {_num(width)} w")
        self.ops.append(f"[{' '.join(_num(d) for d in dash)}] 0 d" if dash else "[] 0 d")

    def _fill_state(self, color):
        r, g, b = _hex(color)
        self.ops.append(f"{_num(r)} {_num(g)} {_num(b)} rg")

    def _path(self, pts, close):
        x0, y0 = pts[0]
        seg = [f"{_num(x0)} {_num(self._y(y0))} m"]
        seg += [f"{_num(x)} {_num(self._y(y))} l" for x, y in pts[1:]]
        if close:
            seg.append("h")
        self.ops.append(" ".join(seg))

    def _paint(self, fill, stroke):
        if fill is not None and stroke is not None:
            self.ops.append("B")
        elif fill is not None:
            self.ops.append("f")
        elif stroke is not None:
            self.ops.append("S")
        else:
            self.ops.append("n")

    # -- drawing
    def line(self, pts, color="#000000", width=1.0, dash=None):
        if len(pts) < 2:
            return
        self.ops.append("q 1 J 1 j")
        self._stroke_state(color, width, dash)
        self._path(pts, False)
        self.ops.append("S Q")

    def polygon(self, pts, fill=None, stroke=None, width=1.0, dash=None):
        if len(pts) < 3 or (fill in (None, "") and stroke in (None, "")):
            return
        fill = None if fill in (None, "") else fill
        stroke = None if stroke in (None, "") else stroke
        self.ops.append("q 1 j")
        if fill is not None:
            self._fill_state(fill)
        if stroke is not None:
            self._stroke_state(stroke, width, dash)
        self._path(pts, True)
        self._paint(fill, stroke)
        self.ops.append("Q")

    def rect(self, x0, y0, x1, y1, fill=None, stroke=None, width=1.0, dash=None):
        self.polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill, stroke, width, dash)

    def ellipse(self, x0, y0, x1, y1, fill=None, stroke=None, width=1.0):
        fill = None if fill in (None, "") else fill
        stroke = None if stroke in (None, "") else stroke
        if fill is None and stroke is None:
            return
        cx, cy = (x0 + x1) / 2, self._y((y0 + y1) / 2)
        rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
        k = 0.5523
        self.ops.append("q")
        if fill is not None:
            self._fill_state(fill)
        if stroke is not None:
            self._stroke_state(stroke, width, None)
        p = [
            f"{_num(cx + rx)} {_num(cy)} m",
            f"{_num(cx + rx)} {_num(cy + k * ry)} {_num(cx + k * rx)} {_num(cy + ry)} {_num(cx)} {_num(cy + ry)} c",
            f"{_num(cx - k * rx)} {_num(cy + ry)} {_num(cx - rx)} {_num(cy + k * ry)} {_num(cx - rx)} {_num(cy)} c",
            f"{_num(cx - rx)} {_num(cy - k * ry)} {_num(cx - k * rx)} {_num(cy - ry)} {_num(cx)} {_num(cy - ry)} c",
            f"{_num(cx + k * rx)} {_num(cy - ry)} {_num(cx + rx)} {_num(cy - k * ry)} {_num(cx + rx)} {_num(cy)} c h",
        ]
        self.ops.append(" ".join(p))
        self._paint(fill, stroke)
        self.ops.append("Q")

    def text(self, x, y, s, size=10.0, bold=False, color="#000000", anchor="sw", angle=0.0):
        """Draw text. (x, y) is the point given by a Tk-style compass anchor:
        n/s = top/bottom of the text box, e/w = right/left, center = middle.
        "baseline" anchors use the baseline at the left edge."""
        if not s:
            return
        runs = _runs(s, bold)
        w = sum(r[2] for r in runs) * size
        asc, desc = ASCENT * size, DESCENT * size
        if anchor == "baseline":
            ax, ay = 0.0, 0.0
        else:
            ax = 0.0 if "w" in anchor else w if "e" in anchor else w / 2
            ay = asc if "n" in anchor else -desc if "s" in anchor else (asc - desc) / 2
        # local origin offset (text space: x right, y up), rotated by angle (counterclockwise)
        a = math.radians(angle)
        ca, sa = math.cos(a), math.sin(a)
        ox, oy = -ax, -ay
        px = x + (ox * ca - oy * sa)
        py = self._y(y) + (ox * sa + oy * ca)
        r, g, b = _hex(color)
        out = [f"BT {_num(r)} {_num(g)} {_num(b)} rg",
               f"{_num(ca)} {_num(sa)} {_num(-sa)} {_num(ca)} {_num(px)} {_num(py)} Tm"]
        for font, data, _wpe, sf, rise in runs:
            out.append(f"/{font} {_num(size * sf)} Tf {_num(rise * size)} Ts "
                       f"({_escape(data).decode('latin-1')}) Tj")
        out.append("ET")
        self.ops.append(" ".join(out))


class Document:
    def __init__(self, page_size=LETTER, title="", author=""):
        self.page_size = page_size
        self.pages: list[Page] = []
        self.title = title
        self.author = author

    def new_page(self) -> Page:
        p = Page(*self.page_size)
        self.pages.append(p)
        return p

    def to_bytes(self) -> bytes:
        objs: list[bytes] = []

        def add(b: bytes) -> int:
            objs.append(b)
            return len(objs)

        def info_str(s):
            return b"(" + _escape(s.encode("cp1252", "replace")) + b")"

        catalog = add(b"")           # filled in below
        pages_id = add(b"")
        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        f3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Symbol >>")
        kids = []
        W, H = self.page_size
        for p in self.pages:
            data = zlib.compress("\n".join(p.ops).encode("latin-1"))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
            page = add((f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {_num(W)} {_num(H)}] "
                        f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R /F3 {f3} 0 R >> >> "
                        f"/Contents {content} 0 R >>").encode("ascii"))
            kids.append(page)
        objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
        objs[pages_id - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                              f"/Count {len(kids)} >>").encode("ascii")
        info = add(b"<< /Title " + info_str(self.title) + b" /Author " + info_str(self.author) +
                   b" /Producer (Beam Designer) >>")

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, b in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode("ascii") + b + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode("ascii")
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode("ascii")
        out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode("ascii")
        return bytes(out)
