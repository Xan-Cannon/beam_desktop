"""Validation tests for the Beam Designer engine. Run with: python -m unittest

Hand-calculated values come from spec.md. Each must match within 0.5 %.
"""

import copy
import math
import unittest

import beam_calc as bc


class ValidationCases(unittest.TestCase):
    """The six hand-checked cases from spec.md."""

    def test_cases(self):
        for case in bc.VALIDATION:
            res = bc.design(copy.deepcopy(case["cfg"]))
            self.assertEqual(res.errors, [], case["name"])
            for label, get, exp in case["expect"]:
                with self.subTest(case=case["name"], quantity=label):
                    got = get(res)
                    diff = abs(got - exp) / abs(exp)
                    self.assertLessEqual(diff, bc.VALID_TOL,
                                         f"{label}: expected {exp}, got {got:.4g} ({diff:.2%} off)")

    def test_case1_passes_all_checks(self):
        res = bc.design(copy.deepcopy(bc.VALIDATION[0]["cfg"]))
        self.assertTrue(res.all_pass())

    def test_run_validation_all_ok(self):
        self.assertTrue(all(c["ok"] for c in bc.run_validation()))


class ClosedForm(unittest.TestCase):
    """Extra checks against closed-form answers."""

    def cfg(self, **kw):
        c = bc.default_cfg()
        c.update(kw)
        return c

    def test_partial_udl_reactions(self):
        # 2 kip/ft from 0 to 10 ft on a 20 ft simple span: W = 20 k at 5 ft.
        res = bc.design(self.cfg(loads=[{"type": "udl", "w": 2.0, "x1": 0.0, "x2": 10.0, "tag": "D"}]))
        self.assertAlmostEqual(res.total.R1, 15.0, places=9)
        self.assertAlmostEqual(res.total.R2, 5.0, places=9)
        # Max moment where V = 0: x = 7.5 ft, M = 15·7.5 − 2·7.5²/2 = 56.25 kip-ft.
        self.assertAlmostEqual(res.total.Mabs, 56.25, delta=0.01)

    def test_cantilever_udl(self):
        # wL⁴/8EI for a 10 ft W8x18 cantilever with 0.5 kip/ft.
        res = bc.design(self.cfg(support="cant", L=10.0, section="W8x18",
                                 loads=[{"type": "udl", "w": 0.5, "x1": 0.0, "x2": 10.0, "tag": "L"}]))
        exact = 0.5 / 12 * (120 ** 4) / (8 * 29000 * 61.9)
        self.assertAlmostEqual(res.checks["live"].demand, exact, delta=exact * 0.001)
        self.assertAlmostEqual(res.total.Mabs, 25.0, places=6)

    def test_shear_jump_at_point_load(self):
        res = bc.design(self.cfg(loads=[{"type": "point", "P": 10.0, "x": 5.0, "tag": "L"}]))
        self.assertAlmostEqual(bc.shear_at(res.total.shear_pts, 4.0), 7.5, places=9)
        self.assertAlmostEqual(bc.shear_at(res.total.shear_pts, 5.0), -2.5, places=9)
        self.assertAlmostEqual(res.total.Vmax.v, 7.5, places=9)
        self.assertAlmostEqual(res.total.Vmin.v, -2.5, places=9)

    def test_no_loads_gives_zero(self):
        res = bc.design(self.cfg(loads=[]))
        self.assertEqual(res.errors, [])
        self.assertEqual(res.total.Mabs, 0)
        self.assertEqual(res.total.dMax, 0)
        self.assertTrue(res.all_pass())

    def test_reserve_factor_reaches_one(self):
        cfg = self.cfg()
        k, label = bc.reserve_factor(cfg)
        res = bc.design(dict(cfg, factor=k))
        self.assertAlmostEqual(max(c.ratio for c in res.checks.values()), 1.0, places=6)
        self.assertEqual(label, "Live-load deflection")

    def test_compare_sorted_and_tags_lightest(self):
        rows = bc.compare_sections(self.cfg())
        weights = [r["wt"] for r in rows]
        self.assertEqual(weights, sorted(weights))
        self.assertEqual(len(rows), len(bc.W_SHAPES))
        self.assertTrue(any(r["pass"] for r in rows))


class InputChecks(unittest.TestCase):
    def test_bad_span(self):
        for L in (0, -5, math.nan, None):
            cfg = bc.default_cfg()
            cfg["L"] = L
            errs = bc.validate_cfg(cfg)
            self.assertTrue(any(e["field"] == "L" for e in errs), L)

    def test_load_outside_span(self):
        cfg = bc.default_cfg()
        cfg["loads"] = [{"type": "point", "P": 5.0, "x": 25.0, "tag": "L"}]
        errs = bc.validate_cfg(cfg)
        self.assertEqual(errs[0]["field"], "load-0")
        self.assertIn("Point load 1", errs[0]["msg"])

    def test_udl_end_before_start(self):
        cfg = bc.default_cfg()
        cfg["loads"] = [{"type": "udl", "w": 1.0, "x1": 8.0, "x2": 4.0, "tag": "D"}]
        errs = bc.validate_cfg(cfg)
        self.assertTrue(any("end must be greater than start" in e["msg"] for e in errs))


if __name__ == "__main__":
    unittest.main()
