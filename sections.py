"""Section data for the Beam Designer.

Units: inches, in², in³, in⁴; stresses and E in the units noted per table.
Verify every value against the cited source before release.
"""

# Steel W-shapes, ASTM A992.
# Source: AISC Shapes Database v16.0 (verify before release).
# Fields: A (in²), d (in), tw (in), Ix (in⁴), Sx (in³), Zx (in³), wt (lb/ft).
W_SHAPES = [
    {"name": "W8x10",  "A": 2.96, "d": 7.89, "tw": 0.170, "Ix": 30.8, "Sx": 7.81, "Zx": 8.87, "wt": 10},
    {"name": "W8x18",  "A": 5.26, "d": 8.14, "tw": 0.230, "Ix": 61.9, "Sx": 15.2, "Zx": 17.0, "wt": 18},
    {"name": "W10x12", "A": 3.54, "d": 9.87, "tw": 0.190, "Ix": 53.8, "Sx": 10.9, "Zx": 12.6, "wt": 12},
    {"name": "W10x22", "A": 6.49, "d": 10.2, "tw": 0.240, "Ix": 118,  "Sx": 23.2, "Zx": 26.0, "wt": 22},
    {"name": "W12x14", "A": 4.16, "d": 11.9, "tw": 0.200, "Ix": 88.6, "Sx": 14.9, "Zx": 17.4, "wt": 14},
    {"name": "W12x26", "A": 7.65, "d": 12.2, "tw": 0.230, "Ix": 204,  "Sx": 33.4, "Zx": 37.2, "wt": 26},
    {"name": "W14x22", "A": 6.49, "d": 13.7, "tw": 0.230, "Ix": 199,  "Sx": 29.0, "Zx": 33.2, "wt": 22},
    {"name": "W16x26", "A": 7.68, "d": 15.7, "tw": 0.250, "Ix": 301,  "Sx": 38.4, "Zx": 44.2, "wt": 26},
    {"name": "W18x35", "A": 10.3, "d": 17.7, "tw": 0.300, "Ix": 510,  "Sx": 57.6, "Zx": 66.5, "wt": 35},
    {"name": "W21x44", "A": 13.0, "d": 20.7, "tw": 0.350, "Ix": 843,  "Sx": 81.6, "Zx": 95.4, "wt": 44},
    {"name": "W24x55", "A": 16.2, "d": 23.6, "tw": 0.395, "Ix": 1350, "Sx": 114,  "Zx": 134,  "wt": 55},
]

# Douglas Fir-Larch No. 2 lumber.
# Source: NDS Supplement, Table 4A (dimension lumber, 2x and 4x) and
# Table 4D (beams and stringers, 6x). Verify before release.
# Fields: b and d are actual dimensions (in); Fb, Fv, E in psi;
# CF is the size factor for bending. kind "dim" members can take C_r.
LUMBER = [
    {"name": "2x6",  "b": 1.5, "d": 5.5,   "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.3},
    {"name": "2x8",  "b": 1.5, "d": 7.25,  "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.2},
    {"name": "2x10", "b": 1.5, "d": 9.25,  "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.1},
    {"name": "2x12", "b": 1.5, "d": 11.25, "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.0},
    {"name": "4x6",  "b": 3.5, "d": 5.5,   "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.3},
    {"name": "4x8",  "b": 3.5, "d": 7.25,  "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.3},
    {"name": "4x10", "b": 3.5, "d": 9.25,  "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.2},
    {"name": "4x12", "b": 3.5, "d": 11.25, "kind": "dim",    "Fb": 900, "Fv": 180, "E": 1_600_000, "CF": 1.1},
    {"name": "6x10", "b": 5.5, "d": 9.5,   "kind": "timber", "Fb": 875, "Fv": 170, "E": 1_300_000, "CF": 1.0},
    {"name": "6x12", "b": 5.5, "d": 11.5,  "kind": "timber", "Fb": 875, "Fv": 170, "E": 1_300_000, "CF": 1.0},
]

# Lumber self-weight density (lb/ft³).
WOOD_DENSITY_PCF = 35

# Steel material, ASTM A992 (ksi).
STEEL = {"grade": "A992", "Fy": 50.0, "E": 29000.0}
STEEL["Fb"] = 0.66 * STEEL["Fy"]  # 33 ksi, compact and fully braced
