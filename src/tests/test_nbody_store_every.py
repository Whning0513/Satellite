"""Regression tests for sampled Velocity-Verlet output."""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nbody import vv_integrate


class TestStoreEvery(unittest.TestCase):
    def test_states_match_reported_times(self) -> None:
        result = vv_integrate(
            np.array([0.0]),
            np.array([1.0]),
            dt=0.1,
            n_steps=5,
            accel_fn=lambda position: np.zeros_like(position),
            store_every=2,
        )

        np.testing.assert_allclose(result["t"], [0.0, 0.2, 0.4])
        np.testing.assert_allclose(result["r"][:, 0], [0.0, 0.2, 0.4])
        np.testing.assert_allclose(result["v"][:, 0], [1.0, 1.0, 1.0])
