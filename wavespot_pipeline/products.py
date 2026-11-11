"""Build the published JSON documents: spots/{id}.json, index tiles, zones."""
from __future__ import annotations

import datetime as dt
import math
from zoneinfo import ZoneInfo

import numpy as np

from . import config, rating, sun, tides

DEC2 = ("hs", "s1h", "s2h", "wwh", "hb", "ws", "wg")
DEC1 = ("tp", "s1p", "s2p", "wwp", "td", "t2", "sst")
INT = ("dir", "s1d", "s2d", "wwd", "wd")
SERIES_ORDER = ["hs", "tp", "dir", "s1h", "s1p", "s1d", "s2h", "s2p", "s2d", "wwh", "wwp", "wwd",
                "hb", "td", "ws", "wg", "wd", "t2", "sst"]


def _round_list(arr: np.ndarray, field: str) -> list:
    a = np.asarray(arr, dtype=float)
    ok = np.isfinite(a)
    if field in INT:
        vals = (np.rint(np.where(ok, a, 0.0)).astype(np.int64) % 360).tolist()
    else:
        vals = np.round(np.where(ok, a, 0.0), 1 if field in DEC1 else 2).tolist()
    return [v if k else None for v, k in zip(vals, ok.tolist())]


def _exposed(series: dict, window) -> tuple[list, list]:
    hb, td = [], []
    for k in range(len(series["hs"])):
        g = lambda f: series[f][k]  # noqa: E731
        comps = rating.spot_components((g("s1h"), g("s1p"), g("s1d")), (g("s2h"), g("s2p"), g("s2d")),
                                       (g("wwh"), g("wwp"), g("wwd")), g("hs"), g("tp"), g("dir"))
        b, t = rating.effective_height(comps, window, g("tp"))
        hb.append(None if b is None else round(b, 2))
        td.append(None if t is None else round(t, 1))
    return hb, td


def series_block(fields: dict[str, np.ndarray], i: int, start: dt.datetime, step: int, window) -> dict:
    s = {f: _round_list(fields[f][i], f) for f in SERIES_ORDER if f in fields}
    s["hb"], s["td"] = _exposed(s, window)
    n = len(s["hs"])
    block = {"start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "step": step, "n": n}
    for f in SERIES_ORDER:
        block[f] = s.get(f, [None] * n)
    return block


def spot_doc(spot: dict, blended, i: int, h_start: dt.datetime, generated: str, tide: dict | None) -> dict:
    window = spot["info"].get("window")
    h3_start = h_start + dt.timedelta(hours=config.H_HOURS)
    return {
        "v": config.SCHEMA_VERSION,
        "id": spot["id"], "name": spot["name"], "aliases": spot["aliases"],
        "lat": spot["lat"], "lon": spot["lon"], "country": spot["country"], "zone": spot["zone"],
        "tz": spot["tz"], "layer": spot["layer"], "verified": spot["verified"],
        "info": spot["info"],
        "generated": generated,
        "models": blended.models[i],
        "h": series_block(blended.h, i, h_start, 1, window),
        "h3": series_block(blended.h3, i, h3_start, config.H3_STEP, window),
        "tide": tide,
        "buoy": spot.get("buoy"),
    }


def doc_is_complete(doc: dict, min_frac: float = 0.5) -> bool:
    h = doc["h"]
    n = max(h["n"], 1)
    hs_ok = sum(x is not None for x in h["hs"]) / n
    ws_ok = sum(x is not None for x in h["ws"]) / n
    return hs_ok >= min_frac and ws_ok >= min_frac


# ------------------------------------------------------------------ ratings
def _parse_t(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def local_days(doc: dict) -> list[tuple[dt.date, list[int]]]:
    """Local calendar days fully covered by `h` -> hour indices."""
    tz = ZoneInfo(doc["tz"])
    start = _parse_t(doc["h"]["start"])
    days: dict[dt.date, list[int]] = {}
    for k in range(doc["h"]["n"]):
        d = (start + dt.timedelta(hours=k)).astimezone(tz).date()
        days.setdefault(d, []).append(k)
    out = []
    for d, idx in days.items():
        midnight = dt.datetime.combine(d, dt.time(0), tz)
        nxt = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tz)
        hours = round((nxt - midnight).total_seconds() / 3600)
        if len(idx) >= hours:
            out.append((d, idx))
    return out


def tide_stages_for_day(doc: dict, d: dt.date, idx: list[int]) -> list[str | None]:
    tide = doc.get("tide")
    info = doc["info"]
    if (not tide or not tide.get("cons") or doc["layer"] != 2
            or not (info.get("bestTide") or info.get("dangerTide"))):
        return [None] * len(idx)   # T = 1 anyway (schema §3.2): skip the harmonic sum
    tz = ZoneInfo(doc["tz"])
    t0 = dt.datetime.combine(d, dt.time(0), tz).timestamp()
    t1 = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), tz).timestamp()
    fine = tides.predict(tide["cons"], np.arange(t0, t1 + 1, 600), tide.get("z0", 0.0))
    lo, hi = float(fine.min()), float(fine.max())
    start = _parse_t(doc["h"]["start"]).timestamp()
    hourly = tides.predict(tide["cons"], np.array([start + 3600 * k for k in idx]), tide.get("z0", 0.0))
    span = hi - lo
    if span <= 1e-6:
        return ["mid"] * len(idx)
    return [rating.tide_stage((float(x) - lo) / span) for x in hourly]


def day_ratings(doc: dict, d: dt.date, idx: list[int]) -> dict:
    """Hourly ratings for one local day: {'lit', 'surf': {level: [...]}, 'kite': [...] | None}."""
    info = doc["info"]
    h = doc["h"]
    start = _parse_t(h["start"])
    lat, lon = doc["lat"], doc["lon"]
    lit = [sun.is_lit(lat, lon, start + dt.timedelta(hours=k)) for k in idx]
    stages = tide_stages_for_day(doc, d, idx)
    facing = info.get("facing")
    surf = {}
    for level in rating.LEVELS:
        row = []
        for n, k in enumerate(idx):
            tf = rating.tide_factor(stages[n], doc["layer"], info.get("bestTide") or [], info.get("dangerTide") or [])
            row.append(rating.surf_rating(h["hb"][k], h["td"][k], h["ws"][k], h["wd"][k], facing, level, tf,
                                          1 if lit[n] else 0))
        surf[level] = row
    kite = None
    if {"kite", "windsurf"} & set(info.get("sports") or []):
        kite = [rating.kite_rating(h["ws"][k], h["wg"][k], h["wd"][k], facing, info.get("kiteWind"),
                                   1 if lit[n] else 0) for n, k in enumerate(idx)]
    return {"lit": lit, "surf": surf, "kite": kite, "stages": stages}


def window_strings(doc: dict, d: dt.date, idx: list[int], first: int, length: int) -> tuple[list[str], int]:
    """Local HH:MM [start, end] of a best window, clipped to civil twilight; plus minutes."""
    tz = ZoneInfo(doc["tz"])
    start = _parse_t(doc["h"]["start"])
    t_a = start + dt.timedelta(hours=idx[first])
    t_b = start + dt.timedelta(hours=idx[first + length - 1] + 1)
    dawn, dusk = sun.civil_twilight(doc["lat"], doc["lon"], t_a.date())
    day0 = dt.datetime.combine(t_a.date(), dt.time(0), dt.timezone.utc)
    t_a = max(t_a, day0 + dt.timedelta(minutes=math.ceil(dawn)))
    t_b = min(t_b, day0 + dt.timedelta(minutes=math.floor(dusk)))
    minutes = int((t_b - t_a).total_seconds() // 60)
    return [t_a.astimezone(tz).strftime("%H:%M"), t_b.astimezone(tz).strftime("%H:%M")], minutes


def today_index(doc: dict, now: dt.datetime) -> dict | None:
    """Ratings for the spot's 'today' (local date; tomorrow once past civil dusk)."""
    tz = ZoneInfo(doc["tz"])
    local = now.astimezone(tz)
    d = local.date()
    _, dusk = sun.civil_twilight(doc["lat"], doc["lon"], now.astimezone(dt.timezone.utc).date())
    now_min = now.astimezone(dt.timezone.utc).hour * 60 + now.astimezone(dt.timezone.utc).minute
    if now_min > dusk:
        d = d + dt.timedelta(days=1)
    for day, idx in local_days(doc):
        if day == d:
            return {"date": day, "idx": idx, **day_ratings(doc, day, idx)}
    return None


def index_r(doc: dict, today: dict | None) -> list[int]:
    """Best surf rating today per level [beginner, intermediate, advanced]."""
    if today is None:
        return [0, 0, 0]
    return [max([r for r in today["surf"][lv] if r is not None], default=0) for lv in rating.LEVELS]


def index_rk(doc: dict, today: dict | None) -> int | None:
    """Best kite/windsurf rating today; None for spots without kite or windsurf."""
    if not {"kite", "windsurf"} & set(doc["info"].get("sports") or []):
        return None
    if today is None or today["kite"] is None:
        return 0
    return max([r for r in today["kite"] if r is not None], default=0)


def index_entry(doc: dict, r: list[int], rk: int | None = None) -> dict:
    e = {"id": doc["id"], "n": doc["name"], "lat": doc["lat"], "lon": doc["lon"], "l": doc["layer"],
         "s": doc["info"].get("sports") or [], "z": doc["zone"], "r": r}
    if rk is not None:
        e["rk"] = rk
    return e


def zone_entries(doc: dict) -> dict[str, dict]:
    """Per local date: {'beginner': entry|None, ..., 'kite': entry|None}."""
    out = {}
    for d, idx in local_days(doc):
        rr = day_ratings(doc, d, idx)
        day = {}
        series = dict(rr["surf"]) if "surf" in (doc["info"].get("sports") or []) else {}
        if rr["kite"] is not None:
            series["kite"] = rr["kite"]
        for key, ratings in series.items():
            win = rating.best_window(ratings, rr["lit"])
            if win is None:
                continue
            best, first, length = win
            strs, minutes = window_strings(doc, d, idx, first, length)
            day[key] = {"id": doc["id"], "r": best, "win": strs, "_min": minutes}
        out[d.isoformat()] = day
    return out


def zone_doc(zone: str, per_spot: list[dict[str, dict]], generated: str, top: int = 5) -> dict:
    dates = sorted({d for entry in per_spot for d in entry})
    days = []
    for d in dates:
        levels = {}
        for lv in rating.LEVELS:
            cands = [e[d][lv] for e in per_spot if d in e and lv in e[d]]
            cands.sort(key=lambda c: (-c["r"], -c["_min"], c["id"]))
            levels[lv] = [{k: v for k, v in c.items() if k != "_min"} for c in cands[:top]]
        kc = [e[d]["kite"] for e in per_spot if d in e and "kite" in e[d]]
        kc.sort(key=lambda c: (-c["r"], -c["_min"], c["id"]))
        days.append({"date": d, "levels": levels, "kite": [{k: v for k, v in c.items() if k != "_min"} for c in kc[:top]]})
    return {"v": config.SCHEMA_VERSION, "zone": zone, "generated": generated, "days": days}
