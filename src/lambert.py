"""
lambert.py
==========
Universal-variable Lambert solver (Gooding's method).
Finds the velocity vectors for an orbit connecting r1 to r2 in time tof.
Pure numpy, no scipy dependency.
"""

import numpy as np
import math


def _norm(v):
    return float(np.linalg.norm(v))


def solve_lambert_universal(r1, r2, tof_s, mu, prograde=True, long_way=False, tol=1e-10, max_iter=100):
    """Universal-variable Lambert solver.

    Parameters
    ----------
    r1, r2 : (2,) or (3,) ndarray
        Initial and final position vectors (km).
    tof_s : float
        Time of flight (s).
    mu : float
        Gravitational parameter (km³/s²).
    prograde : bool
        True for prograde transfer, False for retrograde.
    long_way : bool
        True for the long (>180°) transfer, False for short (<180°).
    tol : float
        Convergence tolerance on universal anomaly.
    max_iter : int

    Returns
    -------
    v1, v2 : (2,) ndarray
        Initial and final velocity vectors (km/s).
    (z, alpha) : diagnostics.
    """
    r1n = _norm(r1)
    r2n = _norm(r2)

    # Cross product determines transfer angle
    cos_dnu = np.dot(r1, r2) / (r1n * r2n + 1e-30)
    sin_dnu_sign = 1 if prograde else -1
    if long_way:
        sin_dnu_sign = -sin_dnu_sign

    # Compute transfer angle
    dnu = math.acos(np.clip(cos_dnu, -1.0, 1.0))
    if long_way:
        dnu = 2.0 * math.pi - dnu
    if not prograde:
        dnu = -dnu

    # Stumpff functions via series
    def stumpff(z):
        if z > 0:
            sqrt_z = math.sqrt(z)
            c2 = (1 - math.cos(sqrt_z)) / z
            c3 = (sqrt_z - math.sin(sqrt_z)) / (sqrt_z**3)
        elif z < 0:
            sqrt_negz = math.sqrt(-z)
            c2 = (1 - math.cosh(sqrt_negz)) / z
            c3 = (math.sinh(sqrt_negz) - sqrt_negz) / ((-z)**1.5)
        else:
            c2 = 0.5
            c3 = 1.0 / 6.0
        return c2, c3

    A = sin_dnu_sign * math.sqrt(r1n * r2n * (1 + cos_dnu) / (1 - cos_dnu + 1e-30) + 1e-15)

    # Initial guess for z
    z = 0.0
    for iteration in range(max_iter):
        c2, c3 = stumpff(z)
        y = r1n + r2n + A * (z * c3 - 1) / math.sqrt(c2 + 1e-30) if c2 > 0 else r1n + r2n
        if y < 0:
            # Divergent, reduce z
            z = z * 0.5
            continue

        chi = math.sqrt(y / c2) if c2 > 1e-15 else math.sqrt(y)
        dt = (chi**3 * c3 + A * math.sqrt(y)) / math.sqrt(mu)

        if abs(dt - tof_s) < tol:
            break

        # Derivative
        if c2 > 1e-15:
            dz = 4 * (dt - tof_s) * math.sqrt(mu) * c2**2 / (chi * (chi * c3 - 3 * c2 * (chi * c3 - 1)) + A * math.sqrt(y) / (2 * y))
        else:
            dz = (dt - tof_s) * math.sqrt(mu) / (chi * (chi - 3) / 6 + A * math.sqrt(y) / (2 * y))
        z = z - dz
        if abs(dz) < tol:
            break

    c2, c3 = stumpff(z)
    y = r1n + r2n + A * (z * c3 - 1) / math.sqrt(c2 + 1e-30) if c2 > 0 else r1n + r2n
    f = 1 - y / r1n
    g = A * math.sqrt(y / mu)
    gdot = 1 - y / r2n

    v1 = (r2 - f * r1) / (g + 1e-30)
    v2 = (gdot * r2 - r1) / (g + 1e-30)

    return v1, v2, (z, y, f, g, gdot)


def orbital_elements_from_state(r, v, mu):
    """Compute orbital elements from heliocentric state.

    Returns (a, e, rp, energy, h_scalar).
    """
    rn = _norm(r)
    vn = _norm(v)
    eps = 0.5 * vn**2 - mu / rn
    a = -mu / (2 * eps) if abs(eps) > 1e-15 else 1e15
    h_scalar = r[0] * v[1] - r[1] * v[0]  # 2D angular momentum
    # eccentricity: e^2 = 1 - h^2 / (mu * a)
    if a > 0:
        e = math.sqrt(max(0, 1 - h_scalar**2 / (mu * a)))
    else:
        e = math.sqrt(max(0, 1 + h_scalar**2 / (mu * abs(a))))
    rp = abs(a) * (1 - e) if e < 1 else abs(a) * (e - 1)
    return a, e, rp, eps, h_scalar
