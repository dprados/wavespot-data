"""Spot catalogue: load one or more spot files, normalise, assign zone/tz/tile."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from typing import Iterable

from . import config

log = logging.getLogger("wavespot")

INFO_DEFAULTS = {
    "break": "unknown",
    "sports": ["surf"],
    "facing": None,
    "window": None,
    "bestTide": [],
    "dangerTide": [],
    "bestSwell": None,
    "bestWind": None,
    "kiteWind": None,
    "level": "all",
    "hazards": [],
    "sources": [],
}
DEDUPE_KM = 0.3
SAME_POINT_KM = 0.05     # closer than this: same spot whatever the names say
STOPWORDS = {"playa", "praia", "plage", "platja", "praias", "spot", "surf", "de", "del", "la", "las", "los", "le", "les",
             "l", "d", "do", "da", "dos", "das", "du", "des", "el", "o", "a", "e", "y", "et", "the", "of", "beach",
             "cala", "cove", "anse", "port", "porto", "puerto", "baie", "bahia", "baia", "plaia", "praiaz", "sur",
             "norte", "sul", "nord", "north", "south", "este", "oeste", "est", "ouest", "grande", "grand"}


def is_curated_path(path: str) -> bool:
    return os.sep + "curated" + os.sep in os.path.abspath(path)


def expand_paths(paths: Iterable[str]) -> list[str]:
    """Expand globs (e.g. data/spots/curated/*.json), keeping the given order."""
    import glob as _glob

    out = []
    for p in paths:
        hits = sorted(_glob.glob(p)) if any(c in p for c in "*?[") else [p]
        out.extend(hits)
    return out


def _tokens(name: str) -> set[str]:
    return {t for t in slug(name).split("-") if t and t not in STOPWORDS}


def similar_names(a: dict, b: dict) -> bool:
    """Loose name match between two spots (names + aliases)."""
    from difflib import SequenceMatcher

    na = [a.get("name") or ""] + list(a.get("aliases") or [])
    nb = [b.get("name") or ""] + list(b.get("aliases") or [])
    for x in na:
        for y in nb:
            tx, ty = _tokens(x), _tokens(y)
            if not tx or not ty:
                continue
            if any(len(t) >= 4 for t in tx & ty) or tx <= ty or ty <= tx:
                return True
            if SequenceMatcher(None, "-".join(sorted(tx)), "-".join(sorted(ty))).ratio() >= 0.8:
                return True
            cx = "".join(t for t in slug(x).split("-") if t not in STOPWORDS)
            cy = "".join(t for t in slug(y).split("-") if t not in STOPWORDS)
            if cx and cy and SequenceMatcher(None, cx, cy).ratio() >= 0.8:
                return True
    return False


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def norm360(a: float) -> float:
    return a % 360.0


def default_best_wind(facing: float | None):
    if facing is None:
        return None
    off = facing + 180.0
    return [round(norm360(off - 45.0)), round(norm360(off + 45.0))]


def assign_zone(country: str, lat: float, lon: float) -> str:
    c = country.upper()
    if c == "ES" and lat < 30.0:
        if lon > -14.0 and lat > 28.8:
            return "es-lanzarote"
        if lon > -14.6:
            return "es-fuerteventura"
        if -15.9 <= lon <= -15.3:
            return "es-gran-canaria"
        if -16.95 <= lon <= -16.05:
            return "es-tenerife"
        return "es-canarias-oeste"
    if c == "PT" and lon < -15.0:
        return "pt-madeira"
    if c == "ES":
        if lat < 38.0:
            return "es-golfo-cadiz"
        if lon < -7.05:
            return "es-galicia"
        if lon < -4.52:
            return "es-asturias"
        if lon < -3.15:
            return "es-cantabria"
        return "es-costa-vasca"
    if c == "PT":
        if lat >= 40.7:
            return "pt-norte"
        if lat >= 38.9:
            return "pt-centro-oeste"
        if lat >= 38.35:
            return "pt-lisboa"
        if lat >= 37.45:
            return "pt-alentejo"
        return "pt-algarve"
    if c == "FR":
        if lat < 43.53:
            return "fr-pays-basque"
        if lat < 44.53:
            return "fr-landes"
        if lat < 45.6:
            return "fr-gironde"
        if lat < 47.2:
            return "fr-vendee-charente"
        if lon < -3.8:
            return "fr-finistere"
        if lat >= 48.3:
            return "fr-bretagne-nord"
        return "fr-bretagne-sud"
    if c == "MA":
        if lat >= 34.2:
            return "ma-nord"
        if lat >= 33.0:
            return "ma-rabat-casablanca"
        if lat >= 31.0:
            return "ma-safi-essaouira"
        if lat >= 29.9:
            return "ma-agadir"
        if lat >= 24.5:
            return "ma-sud"
        return "ma-dakhla"
    return f"{c.lower()}-other"


def assign_tz(country: str, lat: float, lon: float) -> str:
    c = country.upper()
    if c == "ES":
        return "Atlantic/Canary" if lat < 30.0 else "Europe/Madrid"
    if c == "PT":
        return "Atlantic/Madeira" if lon < -15.0 else "Europe/Lisbon"
    if c == "FR":
        return "Europe/Paris"
    if c == "MA":
        return "Africa/El_Aaiun" if lat < 27.67 else "Africa/Casablanca"
    return "UTC"


def tile_of(lat: float, lon: float) -> str:
    return f"t_{math.floor(lat)}_{math.floor(lon)}"


def is_named(spot: dict) -> bool:
    return bool(spot.get("name")) and "-p-" not in spot["id"]


def _km(a: dict, b: dict) -> float:
    dy = (a["lat"] - b["lat"]) * 111.195
    dx = (a["lon"] - b["lon"]) * 111.195 * math.cos(math.radians(a["lat"]))
    return math.hypot(dx, dy)


def load_zone_registry(path: str | None) -> dict[str, dict]:
    """Zones published by the spot layer (data/spots/zones.json): id -> {name, bbox, country}."""
    if not path or not os.path.exists(path):
        return {}
    with open(path) as f:
        blob = json.load(f)
    items = blob.get("zones", []) if isinstance(blob, dict) else blob
    return {z["id"]: z for z in items if "id" in z}


def zone_name(zone: str, registry: dict[str, dict]) -> dict:
    if zone in registry and registry[zone].get("name"):
        return registry[zone]["name"]
    return config.ZONE_NAMES.get(zone, {"en": zone})


CURATED_INFO_KEYS = ("break", "sports", "facing", "window", "bestTide", "dangerTide", "bestSwell", "bestWind",
                     "kiteWind", "level", "hazards", "sources")
INFO_ENUM_HAZARDS = {"rips", "rocks", "reef", "crowds", "currents", "shorebreak", "pollution", "localism"}


def from_curated(raw: dict) -> dict:
    """Curated layer (docs/curated-brief.md): flat attributes -> pipeline shape.

    layer 2; verified = confidence high|medium; `notes`/`confidence` are not published.
    """
    out = {k: raw[k] for k in ("id", "name", "aliases", "lat", "lon", "country", "zone", "buoy") if k in raw}
    out["info"] = {k: raw[k] for k in CURATED_INFO_KEYS if k in raw}
    out["layer"] = 2
    out["verified"] = raw.get("confidence") in ("high", "medium")
    return out


def normalise(raw: dict, default_layer: int, registry: dict | None = None) -> dict:
    lat, lon = float(raw["lat"]), float(raw["lon"])
    country = (raw.get("country") or "").upper()
    info = dict(INFO_DEFAULTS)
    info.update({k: v for k, v in (raw.get("info") or {}).items() if v is not None or k in INFO_DEFAULTS})
    for k, v in INFO_DEFAULTS.items():
        if info.get(k) is None and isinstance(v, list):
            info[k] = list(v)
    if not info.get("sources") and raw.get("sources"):
        info["sources"] = list(raw["sources"])
    if info.get("bestWind") is None:
        info["bestWind"] = default_best_wind(info.get("facing"))
    name = raw.get("name") or ""
    sid = raw.get("id") or f"{country.lower()}-{slug(name)}"
    zone = raw.get("zone")
    if zone is not None and registry and zone not in registry and zone not in config.ZONE_NAMES:
        zone = None
    zone_given = zone is not None
    return {
        "id": sid,
        "name": name,
        "aliases": list(raw.get("aliases") or []),
        "lat": round(lat, 5),
        "lon": round(lon, 5),
        "country": country,
        "zone": zone,
        "tz": raw.get("tz") or assign_tz(country, lat, lon),
        "layer": int(raw.get("layer") or default_layer),
        "verified": bool(raw.get("verified", False)),
        "info": info,
        "buoy": raw.get("buoy"),
        "_zone_given": zone_given,
    }


def _read(path: str) -> tuple[list[dict], int]:
    with open(path) as f:
        blob = json.load(f)
    if is_curated_path(path):
        return [from_curated(r) for r in (blob if isinstance(blob, list) else blob.get("spots", []))], 2
    if isinstance(blob, dict):
        items = blob.get("spots") or []
        layer = int(blob.get("layer") or (2 if "seed" in os.path.basename(path) else 1))
    else:
        items = blob
        layer = 2 if "seed" in os.path.basename(path) else 1
    return items, layer


def load_spots(paths: Iterable[str], registry: dict[str, dict] | None = None) -> list[dict]:
    """Load spot files in priority order (first file wins on id clash).

    Order used by the build: curated layer (data/spots/curated/*.json) >
    seed > automatic layer 1. A later spot is dropped when an earlier one has
    the same id, or lies ≤300 m away with a similar name ("equivalent" spot).
    Missing files are skipped; globs are expanded.
    Spots without a zone take the zone of the nearest spot (same country,
    ≤ 50 km) whose file provided one — i.e. the zone layer built with the
    spots — else the built-in assign_zone() rules.
    """
    out: list[dict] = []
    ids: set[str] = set()
    cells: dict[tuple[int, int], list[dict]] = {}
    for path in expand_paths(paths):
        if not path or not os.path.exists(path):
            log.info("spots file %s not present, skipped", path)
            continue
        items, layer = _read(path)
        added = 0
        for raw in items:
            try:
                s = normalise(raw, layer, registry)
            except (KeyError, TypeError, ValueError) as e:
                log.warning("bad spot in %s: %s (%s)", path, raw.get("id"), e)
                continue
            if s["id"] in ids:
                continue
            key = (int(s["lat"] * 100), int(s["lon"] * 100))
            near = [o for di in (-1, 0, 1) for dj in (-1, 0, 1)
                    for o in cells.get((key[0] + di, key[1] + dj), [])]
            if any(_km(s, o) < SAME_POINT_KM or (_km(s, o) < DEDUPE_KM and similar_names(s, o)) for o in near):
                continue
            ids.add(s["id"])
            cells.setdefault(key, []).append(s)
            out.append(s)
            added += 1
        log.info("loaded %d spots from %s", added, path)
    _fill_zones(out)
    for s in out:
        s.pop("_zone_given", None)
    return out


def _fill_zones(spots: list[dict]) -> None:
    given = [s for s in spots if s["_zone_given"]]
    for s in spots:
        if s["_zone_given"]:
            continue
        best, best_km = None, 50.0
        for o in given:
            if o["country"] != s["country"] or abs(o["lat"] - s["lat"]) > 0.5:
                continue
            d = _km(s, o)
            if d < best_km:
                best, best_km = o, d
        s["zone"] = best["zone"] if best else assign_zone(s["country"], s["lat"], s["lon"])
