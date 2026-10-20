"""Regression tests for convergence-study reference states."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nbody import convergence_study


class TestConvergenceStudyDuration(unittest.TestCase):
    def test_position_error_uses_requested_duration(self) -> None:
        result = convergence_study([0.005], T=0.25)

        self.assertLess(result[0]["pos_err"], 1e-3)


if __name__ == "__main__":
    unittest.main()
