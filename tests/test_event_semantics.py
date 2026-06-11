"""
test_event_semantics.py
=======================
Tests for event_semantics module.
"""

import unittest
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from event_semantics import compute_earth_return_vinf, classify_event


class TestEventSemantics(unittest.TestCase):
    def test_deep_space_returns_none(self):
        """At 1e8 km from Earth, return_vinf must be None."""
        r_sc = np.array([1e8, 0])
        v_sc = np.array([30, 0])
        r_earth = np.array([0, 0])
        v_earth = np.array([0, 30])
        result = compute_earth_return_vinf(r_sc, v_sc, r_earth, v_earth)
        self.assertFalse(result["valid_return_event"])
        self.assertIsNone(result["return_vinf_kms"])

    def test_near_earth_allows_vinf(self):
        """At 1e5 km from Earth, return_vinf must be computed."""
        r_sc = np.array([1e5, 0])
        v_sc = np.array([10, 0])
        r_earth = np.array([0, 0])
        v_earth = np.array([-5, 0])
        result = compute_earth_return_vinf(r_sc, v_sc, r_earth, v_earth)
        self.assertTrue(result["valid_return_event"])
        self.assertIsNotNone(result["return_vinf_kms"])

    def test_classify_deep_space(self):
        """Far from Earth and Sun should be deep_space."""
        r_sc = np.array([1e9, 0])
        r_earth = np.array([0, 0])
        r_sun = np.array([0, 0])
        event = classify_event(r_sc, r_earth, r_sun)
        self.assertEqual(event, "deep_space")

    def test_classify_near_earth(self):
        """Near Earth should be earth_return."""
        r_sc = np.array([1e5, 0])
        r_earth = np.array([0, 0])
        event = classify_event(r_sc, r_earth)
        self.assertEqual(event, "earth_return")

    def test_result_has_valid_return_field(self):
        """Result must contain valid_return_event."""
        r_sc = np.array([1e8, 0])
        v_sc = np.array([30, 0])
        r_earth = np.array([0, 0])
        v_earth = np.array([0, 30])
        result = compute_earth_return_vinf(r_sc, v_sc, r_earth, v_earth)
        self.assertIn("valid_return_event", result)
        self.assertIn("return_vinf_kms", result)
        self.assertIn("reason", result)

    def test_reentry_speed_computed(self):
        """When valid, reentry_speed must be > return_vinf."""
        r_sc = np.array([1e5, 0])
        v_sc = np.array([10, 0])
        r_earth = np.array([0, 0])
        v_earth = np.array([0, 0])
        result = compute_earth_return_vinf(r_sc, v_sc, r_earth, v_earth)
        self.assertTrue(result["valid_return_event"])
        self.assertIsNotNone(result["reentry_speed_kms"])
        self.assertGreater(result["reentry_speed_kms"], result["return_vinf_kms"])


if __name__ == "__main__":
    unittest.main()
