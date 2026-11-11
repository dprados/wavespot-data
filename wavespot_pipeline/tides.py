"""Harmonic tide prediction from EOT20 constituents (reference for Swift).

    h(t) = z0 + Σ_k f_k(t) · A_k · cos(V_k(t) + u_k(t) − G_k)

- A_k (m) and G_k (° Greenwich phase lag) come from `spot.tide.cons`.
- V_k: equilibrium argument from Doodson numbers on (τ, s, h, p, N', p1)
  plus a multiple of 90°. τ = 15·UT_hours − s + h.
- f_k, u_k: nodal corrections (Doodson/Schureman polynomials in N).
- Mean longitudes: Meeus (1998) polynomials in Julian centuries from J2000,
  evaluated on UT (ΔT ignored; ~1 min, < 1 mm effect).
No minor-constituent inference: the app sums exactly the 17 constituents.
Validated against pyTMD (corrections="FES", infer_minor=False): see
`tests/fixtures/tide_reference.json` (max difference stored in `meta`).
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Mapping, Sequence

import numpy as np

# Doodson numbers (τ, s, h, p, N', p1) and the extra phase in degrees.
# N' = −N (Doodson convention), so the N column multiplies −N.
DOODSON: dict[str, tuple[tuple[int, int, int, int, int, int], float]] = {
    "SA": ((0, 0, 1, 0, 0, -1), 0.0),
    "SSA": ((0, 0, 2, 0, 0, 0), 0.0),
    "MM": ((0, 1, 0, -1, 0, 0), 0.0),
    "MF": ((0, 2, 0, 0, 0, 0), 0.0),
    "Q1": ((1, -2, 0, 1, 0, 0), -90.0),
    "O1": ((1, -1, 0, 0, 0, 0), -90.0),
    "P1": ((1, 1, -2, 0, 0, 0), -90.0),
    "S1": ((1, 1, -1, 0, 0, 0), 180.0),
    "K1": ((1, 1, 0, 0, 0, 0), 90.0),
    "J1": ((1, 2, 0, -1, 0, 0), 90.0),
    "2N2": ((2, -2, 0, 2, 0, 0), 0.0),
    "N2": ((2, -1, 0, 1, 0, 0), 0.0),
    "M2": ((2, 0, 0, 0, 0, 0), 0.0),
    "T2": ((2, 2, -3, 0, 0, 1), 0.0),
    "S2": ((2, 2, -2, 0, 0, 0), 0.0),
    "K2": ((2, 2, 0, 0, 0, 0), 0.0),
    "M4": ((4, 0, 0, 0, 0, 0), 0.0),
}

MJD_J2000 = 51544.5  # 2000-01-01T12:00 UTC
UNIX_EPOCH_MJD = 40587.0


def mean_longitudes(mjd):
    """s, h, p, N, p1 in degrees (Meeus 1998), mjd on UT."""
    t = (np.asarray(mjd, dtype=float) - MJD_J2000) / 36525.0
    s = 218.3164477 + 481267.88123421 * t - 0.0015786 * t**2 + t**3 / 538841.0
    h = 280.46646 + 36000.76983 * t + 0.0003032 * t**2
    p = 83.3532465 + 4069.0137287 * t - 0.0103200 * t**2 - t**3 / 80053.0
    n = 125.04452 - 1934.136261 * t + 0.0020708 * t**2 + t**3 / 450000.0
    p1 = 282.93735 + 1.71946 * t + 0.00046 * t**2
    return s, h, p, n, p1


def nodal(name: str, n_deg):
    """Nodal factor f and angle u (degrees) for constituent `name`."""
    n = np.radians(n_deg)
    c1, c2, c3 = np.cos(n), np.cos(2 * n), np.cos(3 * n)
    s1, s2, s3 = np.sin(n), np.sin(2 * n), np.sin(3 * n)
    one = np.ones_like(n)
    zero = np.zeros_like(n)
    if name in ("M2", "N2", "2N2"):
        return 1.0004 - 0.0373 * c1 + 0.0002 * c2, -2.14 * s1
    if name == "M4":
        f, u = nodal("M2", n_deg)
        return f * f, 2 * u
    if name == "K1":
        return 1.0060 + 0.1150 * c1 - 0.0088 * c2 + 0.0006 * c3, -8.86 * s1 + 0.68 * s2 - 0.07 * s3
    if name in ("O1", "Q1"):
        return 1.0089 + 0.1871 * c1 - 0.0147 * c2 + 0.0014 * c3, 10.80 * s1 - 1.34 * s2 + 0.19 * s3
    if name == "J1":
        return 1.0129 + 0.1676 * c1 - 0.0170 * c2 + 0.0016 * c3, -12.94 * s1 + 1.34 * s2 - 0.19 * s3
    if name == "K2":
        return (1.0241 + 0.2863 * c1 + 0.0083 * c2 - 0.0015 * c3,
                -17.74 * s1 + 0.68 * s2 - 0.04 * s3)
    if name == "MM":
        return 1.0 - 0.1300 * c1 + 0.0013 * c2, zero
    if name == "MF":
        return 1.0429 + 0.4135 * c1 - 0.004 * c2, -23.74 * s1 + 2.68 * s2 - 0.38 * s3
    # S2, P1, S1, T2, SA, SSA: purely solar, no nodal modulation.
    return one, zero


def equilibrium_argument(name: str, mjd, longitudes=None):
    s, h, p, n, p1 = mean_longitudes(mjd) if longitudes is None else longitudes
    hours = 24.0 * np.mod(np.asarray(mjd, dtype=float), 1.0)
    tau = 15.0 * hours - s + h
    (a, b, c, d, e, g), k = DOODSON[name]
    return a * tau + b * s + c * h + d * p + e * (-n) + g * p1 + k


def mjd_from_unix(seconds):
    return np.asarray(seconds, dtype=float) / 86400.0 + UNIX_EPOCH_MJD


def predict(cons: Mapping[str, Sequence[float]], unix_seconds, z0: float = 0.0) -> np.ndarray:
    """Tide height (m, relative to mean sea level + z0) at UNIX times."""
    mjd = mjd_from_unix(unix_seconds)
    lon = mean_longitudes(mjd)
    n = lon[3]
    out = np.full(np.shape(mjd), float(z0))
    for name, (amp, phase) in cons.items():
        if name not in DOODSON:
            continue
        f, u = nodal(name, n)
        v = equilibrium_argument(name, mjd, lon)
        out = out + f * amp * np.cos(np.radians(v + u - phase))
    return out


def unix(t: dt.datetime) -> float:
    return t.replace(tzinfo=dt.timezone.utc).timestamp() if t.tzinfo is None else t.timestamp()


def day_stages(heights: np.ndarray) -> list[str]:
    """Tide stage per sample using the day's own min/max (schema §2)."""
    from .rating import tide_stage
    lo, hi = float(np.nanmin(heights)), float(np.nanmax(heights))
    span = hi - lo
    if not np.isfinite(span) or span <= 1e-6:
        return ["mid"] * len(heights)
    return [tide_stage((float(x) - lo) / span) for x in heights]
