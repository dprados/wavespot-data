"""Rating formula — data-schema.md §3, implemented literally.

This module is the Python half of the Python <-> Swift parity contract.
Every function is scalar and side-effect free so it can be ported 1:1;
`tests/fixtures/rating_parity.json` is generated from these functions.

Conventions (shared with Swift):
- Angles in degrees, directions "coming from", arcs `[from, to]` clockwise.
- `None` means missing; a missing input yields a missing (None) output
  unless the schema defines a default.
- round_half_up(x) = floor(x + 0.5 + 1e-9): the epsilon absorbs float noise
  such as 2.4999999999 coming from products of factors.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional, Sequence

LEVELS = ("beginner", "intermediate", "advanced")

# Trapezoid (a, b, c, d) per level on effective breaking height hb (m). §3.2
SIZE_TRAPEZOID = {
    "beginner": (0.2, 0.5, 1.1, 1.8),
    "intermediate": (0.4, 0.8, 2.0, 3.0),
    "advanced": (0.7, 1.3, 3.8, 6.0),
}

KNOTS_PER_MS = 1.94384
ROUND_EPS = 1e-9


# ----------------------------------------------------------------- helpers
def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5 + ROUND_EPS))


def norm360(a: float) -> float:
    r = math.fmod(a, 360.0)
    return r + 360.0 if r < 0 else r


def ang_diff(a: float, b: float) -> float:
    """Minimum absolute angular difference in [0, 180]."""
    d = abs(norm360(a) - norm360(b))
    return 360.0 - d if d > 180.0 else d


def in_arc(d: float, arc: Sequence[float]) -> bool:
    """True if direction d lies in the clockwise arc [from, to] (inclusive)."""
    a, b = norm360(arc[0]), norm360(arc[1])
    x = norm360(d)
    if a <= b:
        return a <= x <= b
    return x >= a or x <= b


def arc_distance(d: float, arc: Sequence[float]) -> float:
    """0 inside the arc, else angular distance to the nearest edge."""
    if in_arc(d, arc):
        return 0.0
    return min(ang_diff(d, arc[0]), ang_diff(d, arc[1]))


# ------------------------------------------------------- §3.1 exposure / hb
def exposure(direction: float, window: Optional[Sequence[float]], wind_sea: bool = False) -> float:
    """e(D): 1 inside the window, linear to 0 at 30° from the nearest edge.

    window None (unknown spot geometry) -> 1. Wind sea is multiplied by 0.5.
    """
    if window is None:
        e = 1.0
    else:
        e = max(0.0, 1.0 - arc_distance(direction, window) / 30.0)
    return e * 0.5 if wind_sea else e


def g_period(t: float) -> float:
    return clamp(0.75 + 0.035 * t, 0.85, 1.35)


def effective_height(components: Iterable[tuple], window: Optional[Sequence[float]],
                     tp: Optional[float] = None) -> tuple[Optional[float], Optional[float]]:
    """Return (hb, td) from components [(H, T, D, is_wind_sea), ...].

    Components with any missing value are skipped. If no component is usable
    the result is (None, None). If the exposed energy is 0, td = tp and hb = 0.
    """
    num = 0.0   # Σ e·H²·T
    den = 0.0   # Σ e·H²
    used = 0
    for h, t, d, ww in components:
        if h is None or t is None or d is None:
            continue
        used += 1
        e = exposure(d, window, ww)
        w = e * h * h
        den += w
        num += w * t
    if used == 0:
        return None, None
    if den <= 0.0:
        td = tp
        return 0.0, td
    td = num / den
    hb = math.sqrt(den) * g_period(td)
    return hb, td


def spot_components(s1, s2, ww, hs, tp, dr) -> list[tuple]:
    """Build the component list: partitions if any partition height exists,
    otherwise the total sea (hs, tp, dir) as a single non-wind-sea component.

    s1/s2/ww are (H, T, D) tuples (values may be None).
    """
    parts = [(s1[0], s1[1], s1[2], False), (s2[0], s2[1], s2[2], False), (ww[0], ww[1], ww[2], True)]
    if any(p[0] is not None for p in parts):
        return parts
    return [(hs, tp, dr, False)]


# ------------------------------------------------------------ §3.2 factors
def size_factor(hb: float, level: str) -> float:
    a, b, c, d = SIZE_TRAPEZOID[level]
    if hb <= a or hb >= d:
        return 0.0
    if hb < b:
        return (hb - a) / (b - a)
    if hb <= c:
        return 1.0
    return (d - hb) / (d - c)


def period_q(td: float) -> float:
    return clamp((td - 6.0) / 8.0, 0.0, 1.0)


def period_factor(td: float) -> float:
    return 0.4 + 0.6 * period_q(td)


def offshore_delta(wd: float, facing: float) -> float:
    return ang_diff(wd, facing + 180.0)


def wind_factor(ws: float, wd: float, facing: float) -> float:
    v = ws
    if v < 2.0:
        return 1.0
    delta = offshore_delta(wd, facing)
    if delta <= 45.0:
        return 1.0 if v <= 8.0 else clamp(1.0 - (v - 8.0) * 0.06, 0.55, 1.0)
    if delta <= 110.0:
        return clamp(1.0 - v * 0.06, 0.3, 0.9)
    return clamp(1.0 - v * 0.1, 0.0, 0.7)


def tide_stage(normalized: float) -> str:
    """low < 0.33 <= mid <= 0.66 < high (normalized height within the day)."""
    if normalized < 0.33:
        return "low"
    if normalized > 0.66:
        return "high"
    return "mid"


def tide_factor(stage: Optional[str], layer: int, best_tide: Sequence[str],
                danger_tide: Sequence[str]) -> float:
    if layer != 2 or not best_tide or stage is None:
        return 1.0
    if stage in (danger_tide or ()):
        return 0.3
    if stage in best_tide:
        return 1.0
    return 0.6


def surf_score(hb: float, td: float, ws: float, wd: float, facing: float, level: str,
               tide_f: float = 1.0, light: int = 1) -> float:
    return 5.0 * size_factor(hb, level) * period_factor(td) * wind_factor(ws, wd, facing) * tide_f * light


def surf_rating(hb, td, ws, wd, facing, level, tide_f=1.0, light=1) -> Optional[int]:
    if hb is None or td is None or ws is None or wd is None or facing is None:
        return None
    return round_half_up(surf_score(hb, td, ws, wd, facing, level, tide_f, light))


# ---------------------------------------------------------------- kite
def kite_strength(ws: float) -> float:
    kn = ws * KNOTS_PER_MS
    if kn < 11.0:
        return 0.0
    if kn < 15.0:
        return (kn - 11.0) / 4.0
    if kn <= 28.0:
        return 1.0
    if kn < 40.0:
        return (40.0 - kn) / 12.0
    return 0.0


# Pure offshore = the same offshore sector used by W (δ ≤ 45°). Always 0.
KITE_OFFSHORE_DELTA = 45.0
KITE_DEFAULT_ARC = (60.0, 150.0)   # δ range (from offshore) when kiteWind is null
KITE_EDGE = 20.0


def kite_direction(wd: float, facing: float, kite_wind: Optional[Sequence[float]]) -> float:
    delta = offshore_delta(wd, facing)
    if delta <= KITE_OFFSHORE_DELTA:
        return 0.0
    if kite_wind is not None:
        dist = arc_distance(wd, kite_wind)
    else:
        lo, hi = KITE_DEFAULT_ARC
        dist = 0.0 if lo <= delta <= hi else min(abs(delta - lo), abs(delta - hi))
    if dist == 0.0:
        return 1.0
    if dist <= KITE_EDGE:
        return 0.5
    return 0.0


def gust_factor(ws: float, wg: Optional[float]) -> float:
    if wg is None or ws <= 0.0:
        return 1.0
    return clamp(1.0 - max(0.0, wg / ws - 1.3) * 1.2, 0.4, 1.0)


def kite_score(ws: float, wg: Optional[float], wd: float, facing: float,
               kite_wind: Optional[Sequence[float]], light: int = 1) -> float:
    return 5.0 * kite_strength(ws) * kite_direction(wd, facing, kite_wind) * gust_factor(ws, wg) * light


def kite_rating(ws, wg, wd, facing, kite_wind, light=1) -> Optional[int]:
    if ws is None or wd is None or facing is None:
        return None
    return round_half_up(kite_score(ws, wg, wd, facing, kite_wind, light))


# ------------------------------------------------------- §3.3 best window
def best_window(ratings: Sequence[Optional[int]], lit: Sequence[bool]) -> Optional[tuple[int, int, int]]:
    """Find the best window in a day of hourly ratings.

    Returns (max_rating, first_index, length_hours) or None.
    Only lit hours count. A block is a run of consecutive lit hours whose
    rating equals the day maximum; it must be >= 2 hours. Longest wins,
    ties -> earliest. Max < 2 -> None ("Día flojo").
    """
    vals = [r for r, l in zip(ratings, lit) if l and r is not None]
    if not vals:
        return None
    best = max(vals)
    if best < 2:
        return None
    found = None
    i, n = 0, len(ratings)
    while i < n:
        if lit[i] and ratings[i] == best:
            j = i
            while j + 1 < n and lit[j + 1] and ratings[j + 1] == best:
                j += 1
            length = j - i + 1
            if length >= 2 and (found is None or length > found[2]):
                found = (best, i, length)
            i = j + 1
        else:
            i += 1
    return found
