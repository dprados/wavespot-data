"""Civil twilight (sun 6° below the horizon) — simplified NOAA algorithm.

Ported 1:1 to Swift; parity cases live in `rating_parity.json` ("sun").
One pass, solar parameters evaluated at approximate local solar noon.
Accuracy ~1 minute for |lat| < 60°, plenty for hourly light flags.
"""
from __future__ import annotations

import datetime as dt
import math

CIVIL_ZENITH = 96.0


def _jd_from_date(d: dt.date) -> float:
    """Julian day at 00:00 UTC of a calendar date."""
    return d.toordinal() + 1721424.5


def _solar_params(jd: float) -> tuple[float, float]:
    """Return (declination_deg, equation_of_time_minutes)."""
    t = (jd - 2451545.0) / 36525.0
    l0 = math.fmod(280.46646 + t * (36000.76983 + t * 0.0003032), 360.0)
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    mr = math.radians(m)
    c = (math.sin(mr) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * mr) * (0.019993 - 0.000101 * t)
         + math.sin(3 * mr) * 0.000289)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    lam = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23.0 + (26.0 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60.0) / 60.0
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    y = math.tan(math.radians(eps) / 2.0) ** 2
    l0r = math.radians(l0)
    eot = 4.0 * math.degrees(
        y * math.sin(2 * l0r) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * l0r)
        - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * mr))
    return decl, eot


def civil_twilight(lat: float, lon: float, day: dt.date) -> tuple[float, float]:
    """Civil dawn and dusk for a UTC calendar date, in minutes after 00:00 UTC.

    Polar day/night (never happens in our area) -> (0, 1440) / (720, 720).
    """
    jd = _jd_from_date(day) + 0.5 - lon / 360.0
    decl, eot = _solar_params(jd)
    latr, declr = math.radians(lat), math.radians(decl)
    cos_h = (math.cos(math.radians(CIVIL_ZENITH)) - math.sin(latr) * math.sin(declr)) / (
        math.cos(latr) * math.cos(declr))
    noon = 720.0 - 4.0 * lon - eot
    if cos_h <= -1.0:
        return 0.0, 1440.0
    if cos_h >= 1.0:
        return noon, noon
    ha = math.degrees(math.acos(cos_h))
    return noon - 4.0 * ha, noon + 4.0 * ha


def is_lit(lat: float, lon: float, t: dt.datetime) -> bool:
    """L factor: True between civil dawn and civil dusk of t's UTC date."""
    t = t.astimezone(dt.timezone.utc)
    dawn, dusk = civil_twilight(lat, lon, t.date())
    minutes = t.hour * 60 + t.minute + t.second / 60.0
    return dawn <= minutes <= dusk
