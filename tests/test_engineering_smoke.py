"""Engineering smoke tests — lightweight, no large experiments."""

import unittest, json, os, sys, math, pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
RESULTS = REPO / "data" / "results"


class TestImports(unittest.TestCase):
    """All core modules import without error."""

    def test_delta_v_budget_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import delta_v_budget
        self.assertTrue(hasattr(delta_v_budget, "qian_style_symmetric_budget"))

    def test_constants_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import constants
        self.assertTrue(constants.GM_SUN > 0)
        self.assertTrue(constants.AU_KM > 0)

    def test_lambert_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import lambert
        self.assertTrue(hasattr(lambert, "solve_lambert_universal"))

    def test_patched_conic_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import patched_conic
        self.assertTrue(hasattr(patched_conic, "compute_patched_conic"))

    def test_lunar_swingby_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import lunar_swingby
        self.assertTrue(hasattr(lunar_swingby, "compute_swingby_turn_angle"))

    def test_nbody_import(self):
        sys.path.insert(0, str(REPO / "src"))
        import nbody
        self.assertTrue(hasattr(nbody, "vv_step_nbody"))


class TestJsonResults(unittest.TestCase):
    """Existing JSON result files are valid and have no NaN/Inf."""

    def _check_json(self, rel_path):
        path = RESULTS / rel_path
        if not path.exists():
            self.skipTest(f"{rel_path} not found")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._check_finite(data, rel_path)

    def _check_finite(self, obj, path=""):
        if isinstance(obj, float):
            self.assertFalse(math.isnan(obj), f"NaN at {path}")
            self.assertFalse(math.isinf(obj), f"Inf at {path}")
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._check_finite(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                self._check_finite(v, f"{path}[{i}]")

    def test_delta_v_budget(self):
        self._check_json("delta_v_budget_unified.json")

    def test_figure_manifest(self):
        self._check_json("figure_manifest.json")

    def test_o4plus(self):
        self._check_json("../results/o4plus_powered_mga_optimizer.json")


class TestDeltaVBudgetSelfTest(unittest.TestCase):
    """delta_v_budget.py --self-test produces expected numbers."""

    def test_qian_33_67(self):
        sys.path.insert(0, str(REPO / "src"))
        from delta_v_budget import qian_style_symmetric_budget
        r = qian_style_symmetric_budget(16.8363)
        self.assertAlmostEqual(r["total_kms"], 33.6726, delta=0.01)

    def test_m1_29_41(self):
        sys.path.insert(0, str(REPO / "src"))
        from delta_v_budget import qian_style_symmetric_budget
        r = qian_style_symmetric_budget(14.7036)
        self.assertAlmostEqual(r["total_kms"], 29.4072, delta=0.01)

    def test_o4plus_43_56(self):
        sys.path.insert(0, str(REPO / "src"))
        from delta_v_budget import simplified_full_proxy_budget
        r = simplified_full_proxy_budget(
            departure_vinf_kms=10.66,
            powered_flyby_dv_kms=3.80 + 17.45,
            reentry_braking_kms=max(0, 26.65 - 15.0),
        )
        self.assertAlmostEqual(r["total_kms"], 43.56, delta=0.1)


class TestMakefileTargets(unittest.TestCase):
    """Lightweight Makefile target sanity."""

    def test_figure_manifest_target(self):
        # Run via direct python call, not make
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO / "src/experiments/generate_figure_manifest.py")],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_delta_v_self_test(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO / "src/delta_v_budget.py"), "--self-test"],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertEqual(r.returncode, 0, msg=r.stderr)

    def test_check_makefile_targets(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO / "src/experiments/check_makefile_targets.py")],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)

    def test_check_m5_fresh_reproducibility(self):
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO / "src/experiments/check_m5_fresh_reproducibility.py")],
            capture_output=True, text=True, cwd=str(REPO),
        )
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
