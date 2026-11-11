"""Build layer 1 of the spot database.

Inputs (CACHE, see README): osm/*.json (extract_osm.py), land.pkl (land.py),
wikidata_beaches.json (fetch_wikidata.py), EEA bathing sites JSON (path argument).
Outputs: data/spots/layer1.json (+ .gz), zones.json, layer1_stats.md, preview/*.png

Usage: python -I spots_build/build.py EEA_JSON [--workers N]
"""
import argparse
import collections
import glob
import gzip
import json
import math
import os
import re
import sys
import time
from multiprocessing import get_context

import numpy as np
import shapely

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import naming  # noqa: E402
import zones  # noqa: E402

KY = 110540.0

# ---------------------------------------------------------------- helpers


def dist_m(lat1, lon1, lat2, lon2):
    kx = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * kx, (lat2 - lat1) * KY)


def bearing(lat1, lon1, lat2, lon2):
    kx = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.degrees(math.atan2((lon2 - lon1) * kx, (lat2 - lat1) * KY)) % 360


class Grid:
    """Spatial hash for 'anything within r metres' queries."""

    def __init__(self, cell_m):
        self.c = cell_m
        self.cells = collections.defaultdict(list)

    def _key(self, lat, lon):
        return (int(lat * KY // self.c), int(lon * 111320.0 * math.cos(math.radians(lat)) // self.c))

    def add(self, lat, lon, item):
        self.cells[self._key(lat, lon)].append((lat, lon, item))

    def near(self, lat, lon, r):
        ky, kx = self._key(lat, lon)
        n = int(math.ceil(r / self.c))
        out = []
        for dy in range(-n, n + 1):
            for dx in range(-n - 1, n + 2):
                for la, lo, it in self.cells.get((ky + dy, kx + dx), ()):
                    d = dist_m(lat, lon, la, lo)
                    if d <= r:
                        out.append((d, it))
        out.sort(key=lambda x: x[0])
        return out


# ---------------------------------------------------------------- loading

BIZ_KEYS = ("shop", "amenity", "club", "office", "craft", "tourism", "building", "website")
BIZ_NAME = re.compile(r"(?i)school|escola|escuela|[ée]cole|eskola|shop|store|camp|rental|alquiler|"
                      r"location|club|hostel|house|lodge|academ|surf ?center|centre|centro|bar\b|"
                      r"restaurant|hotel|apartment|villa|riad")
# A place=locality is only a useful surf/beach point if its name says it is a coastal feature.
COAST_WORDS = re.compile(
    r"(?i)\b(punta|puntal|pointe|ponta|pta\.?|cabo|cap|cabezo|cala|caleta|calheta|playa|praia|plage|"
    r"hondartza|arenal|areal|areia|porto|puerto|portu|port|porz|porzh|pors|anse|baie|bahia|baía|"
    r"enseada|ensenada|concha|rada|ría|ria|furna|laxe|pedra|piedra|roca|rocher|roche|penedo|"
    r"bajo|baixa|banc|spot|point|reef|beach|mar|surf|ola|onda|vague|barra|foz|boca|desembocadura|"
    r"embouchure|plaj|shatiea|sidi|oued|cove|cueva|cova|furado|ilha|isla|ile|île|islote|ilhéu|"
    r"faro|farol|phare|dique|molhe|espig[oó]n|jetée|digue|pozo|poza|charco|piscina|praiña)\b")
SPORT_MAP = {"surfing": "surf", "surf": "surf", "kitesurfing": "kite", "windsurfing": "windsurf",
             "bodyboard": "surf", "bodyboarding": "surf"}


def load_osm():
    seen = set()
    feats = []
    for fn in sorted(glob.glob(os.path.join(config.CACHE, "osm", "*.json"))):
        for x in json.load(open(fn)):
            key = (x["t"], x["id"])
            if key in seen:
                continue
            seen.add(key)
            feats.append(x)
    return feats


def classify_osm(feats):
    """-> named candidate points, unnamed beaches, places (for naming)."""
    pts, unnamed, places = [], [], []
    for x in feats:
        t = x["tags"]
        lat, lon = x["lat"], x["lon"]
        cc = config.country_of(lat, lon)
        if cc is None:
            continue
        src = f"osm:{ {'n': 'node', 'w': 'way', 'r': 'relation'}[x['t']] }/{x['id']}".replace(" ", "")
        name, aliases = naming.pick_name(t, cc)
        nat = t.get("natural")
        sport = t.get("sport", "")
        sports = sorted({SPORT_MAP[s.strip()] for s in re.split(r"[;,]", sport) if s.strip() in SPORT_MAP})
        if t.get("place") and t.get("place") != "locality":
            if name:
                places.append({"name": name, "lat": lat, "lon": lon, "cc": cc, "place": t["place"]})
            continue
        if sports or "surfing" in t:
            brandy = nat != "beach" and re.search(r"(?i)kite|surf", name or "") and not re.search(
                r"(?i)spot|point|pointe|ponta|punta|plage|praia|playa|beach|zona|gunea|vague|ola|onda", name or "")
            if any(k in t for k in BIZ_KEYS) or not name or BIZ_NAME.search(name) or brandy:
                if nat != "beach":
                    continue
                sports = []
        if nat == "beach":
            if name:
                pts.append(dict(name=name, aliases=aliases, lat=lat, lon=lon, cc=cc, kind="beach",
                                prio=0, sources=[src], sports=sports))
            else:
                unnamed.append(dict(lat=lat, lon=lon, cc=cc, sources=[src]))
        elif sports:
            pts.append(dict(name=name, aliases=aliases, lat=lat, lon=lon, cc=cc, kind="locality",
                            prio=1, sources=[src], sports=sports, spot=True))
        elif not name:
            continue
        elif nat in ("cape", "peninsula"):
            pts.append(dict(name=name, aliases=aliases, lat=lat, lon=lon, cc=cc, kind="cape",
                            prio=3, sources=[src], sports=[]))
        elif nat == "bay":
            pts.append(dict(name=name, aliases=aliases, lat=lat, lon=lon, cc=cc, kind="bay",
                            prio=4, sources=[src], sports=[]))
        elif t.get("place") == "locality" and (COAST_WORDS.search(name) or "natural" in t):
            pts.append(dict(name=name, aliases=aliases, lat=lat, lon=lon, cc=cc, kind="locality",
                            prio=6, sources=[src], sports=[]))
            places.append({"name": name, "lat": lat, "lon": lon, "cc": cc, "place": "locality"})
    return pts, unnamed, places


def load_eea(path):
    out = []
    for x in json.load(open(path)):
        if x.get("bwWaterCategory") not in ("Coastal", "Transitional"):
            continue
        lat, lon = x["latitude"], x["longitude"]
        cc = config.country_of(lat, lon)
        if cc is None:
            continue
        nm = naming.clean_eea_name(x["bathingWaterName"])
        out.append(dict(name=nm, aliases=[], lat=lat, lon=lon, cc=cc, kind="bathing", prio=2,
                        sources=[f"eea:{x['bathingWaterIdentifier']}"], sports=[]))
    return out


WD_LANGS = {"ES": ["es", "gl", "eu", "ast", "ca", "en"], "PT": ["pt", "en", "es"],
            "FR": ["fr", "en"], "MA": ["fr", "en", "es"]}


def load_wikidata():
    fn = os.path.join(config.CACHE, "wikidata_beaches.json")
    out = []
    for x in json.load(open(fn)):
        cc = config.country_of(x["lat"], x["lon"])
        if cc is None:
            continue
        labels = [x["labels"][l] for l in WD_LANGS[cc] if l in x["labels"]]
        labels = [l for l in dict.fromkeys(labels) if naming.is_latin(l) and not re.match(r"^Q\d+$", l)]
        if not labels:
            continue
        out.append(dict(name=labels[0], aliases=labels[1:], lat=x["lat"], lon=x["lon"], cc=cc,
                        kind="wikidata", prio=5, sources=[f"wikidata:{x['qid']}"], sports=[]))
    return out


# ---------------------------------------------------------------- orientation workers

_ORIENTER = None


def _init_worker():
    global _ORIENTER
    from land import Land
    from orientation import Orienter
    _ORIENTER = Orienter(Land())


def _orient_chunk(chunk):
    out = []
    for lat, lon in chunk:
        try:
            out.append(_ORIENTER.orient(lat, lon))
        except Exception as ex:  # noqa: BLE001 - keep the batch going, report later
            out.append({"error": repr(ex)})
    return out


def orient_all(latlons, workers):
    order = sorted(range(len(latlons)), key=lambda i: (round(latlons[i][0], 1), latlons[i][1]))
    chunks = [[latlons[i] for i in order[k:k + 200]] for k in range(0, len(order), 200)]
    res = [None] * len(latlons)
    with get_context("spawn").Pool(workers, initializer=_init_worker) as pool:
        flat = [r for ch in pool.imap(_orient_chunk, chunks) for r in ch]
    for i, r in zip(order, flat):
        res[i] = r
    return res


def window_ok(r):
    return r is not None and "error" not in r and r["facing"] is not None and r["width"] >= config.MIN_WINDOW_DEG


# ---------------------------------------------------------------- main build


def merge_points(cands):
    """Greedy dedupe within DEDUPE_M; higher priority (lower prio) wins."""
    cands.sort(key=lambda p: (p["prio"], -len(p["name"] or ""), p["lat"], p["lon"]))
    grid = Grid(500)
    kept = []
    for p in cands:
        # localities/bays only where nothing better is nearby (avoid inland parajes clutter)
        extra = config.SUPPRESS_M.get(p["kind"], 0) if not p.get("spot") else 0
        near = grid.near(p["lat"], p["lon"], max(config.DEDUPE_M, extra))
        hit = None
        for d, q in near:
            if d <= config.DEDUPE_M or (extra and q["prio"] < p["prio"]):
                hit = q
                break
        if hit is not None:
            if d <= config.DEDUPE_M:
                for a in [p["name"]] + p["aliases"]:
                    if a and a != hit["name"] and a not in hit["aliases"]:
                        hit["aliases"].append(a)
                hit["sources"] += [s for s in p["sources"] if s not in hit["sources"]]
                hit["sports"] = sorted(set(hit["sports"]) | set(p["sports"]))
            continue
        kept.append(p)
        grid.add(p["lat"], p["lon"], p)
    return kept


def coast_samples(land, spacing_m=1000, min_area=0.5):
    out = []
    for g, a in zip(land.coast, land.coast_area):
        if a < min_area:
            continue
        c = shapely.get_coordinates(g)
        lat0 = c[:, 1].mean()
        kx = 111320.0 * math.cos(math.radians(lat0))
        seg = np.hypot(np.diff(c[:, 0]) * kx, np.diff(c[:, 1]) * KY)
        cum = np.concatenate([[0], np.cumsum(seg)])
        if cum[-1] < 1:
            continue
        for s in np.arange(spacing_m / 2, cum[-1], spacing_m):
            i = min(np.searchsorted(cum, s) - 1, len(seg) - 1)
            i = max(i, 0)
            f = (s - cum[i]) / seg[i] if seg[i] > 0 else 0
            lon = c[i, 0] + f * (c[i + 1, 0] - c[i, 0])
            lat = c[i, 1] + f * (c[i + 1, 1] - c[i, 1])
            cc = config.country_of(lat, lon)
            if cc:
                out.append(dict(lat=lat, lon=lon, cc=cc))
    return out


PLACE_W = {"city": 4, "town": 3, "village": 2, "suburb": 1.3, "hamlet": 1, "locality": 0.8,
           "isolated_dwelling": 0.6, "neighbourhood": 0.8, "quarter": 0.8}


def name_synthetic(points, places):
    grid = Grid(5000)
    for p in places:
        grid.add(p["lat"], p["lon"], p)
    for p in points:
        best = None
        for r in (10000, 30000, 80000):
            near = grid.near(p["lat"], p["lon"], r)
            near = [(d, q) for d, q in near if q["cc"] == p["cc"]]
            if near:
                best = min(near, key=lambda dq: max(dq[0], 300) / PLACE_W.get(dq[1]["place"], 1))
                break
        if best is None:
            p["name"] = naming.synthetic_name(p["cc"], {"MA": "Sahara", "ES": "España", "PT": "Portugal",
                                                          "FR": "France"}[p["cc"]], 0, 0)
            continue
        d, q = best
        p["name"] = naming.synthetic_name(p["cc"], q["name"], d / 1000,
                                          bearing(q["lat"], q["lon"], p["lat"], p["lon"]))
        p["near_place"] = q["name"]


def assign_ids(points):
    used = set()
    for p in sorted(points, key=lambda p: (p["kind"] == "synthetic", p["prio"], -p["lat"], p["lon"])):
        if p["kind"] == "synthetic":
            pid = naming.synthetic_id(p["cc"], p["lat"], p["lon"])
        else:
            base = f"{p['cc'].lower()}-{naming.slugify(p['name']) or 'spot'}"
            pid, k = base, 2
            while pid in used:
                pid, k = f"{base}-{k}", k + 1
        assert pid not in used, pid
        used.add(pid)
        p["id"] = pid


def licence_of(p):
    if any(s.startswith("osm:") for s in p["sources"]) or p["kind"] == "synthetic":
        return "ODbL"
    if any(s.startswith("eea:") for s in p["sources"]):
        return "CC-BY-EEA"
    return "CC0"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eea")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    args = ap.parse_args()
    t0 = time.time()
    log = lambda *a: print(f"[{time.time()-t0:6.0f}s]", *a, flush=True)  # noqa: E731

    from land import Land
    land = Land()

    feats = load_osm()
    osm_pts, unnamed, places = classify_osm(feats)
    eea = load_eea(args.eea)
    wd = load_wikidata()
    log(f"osm named {len(osm_pts)}, unnamed beaches {len(unnamed)}, places {len(places)}, "
        f"eea {len(eea)}, wikidata {len(wd)}")

    cands = osm_pts + eea + wd
    dc = land.coast_distance_m([p["lat"] for p in cands], [p["lon"] for p in cands])
    raw_counts = collections.Counter(p["kind"] for p in cands)
    cands = [p for p, d in zip(cands, dc)
             if d <= (800 if p.get("spot") else config.MAX_COAST_DIST_M[p["kind"]])]
    log(f"coastal candidates {len(cands)} {dict(collections.Counter(p['kind'] for p in cands))} "
        f"(raw {dict(raw_counts)})")

    pts = merge_points(cands)
    log(f"after dedupe {len(pts)}")

    res = orient_all([(p["lat"], p["lon"]) for p in pts], args.workers)
    errors = sum(1 for r in res if r and "error" in r)
    kept, dropped = [], collections.Counter()
    for p, r in zip(pts, res):
        lag = config.kite_lagoon(p["lat"], p["lon"])
        if window_ok(r):
            p["orient"] = r
            if lag and r["width"] < 60:
                p["sports"] = ["kite"]
                p["lagoon"] = lag
            kept.append(p)
        elif lag and r and "error" not in r and r.get("facing") is not None:
            p["orient"] = r
            p["sports"] = ["kite"]
            p["lagoon"] = lag
            kept.append(p)
        else:
            dropped[p["kind"]] += 1
    log(f"oriented real points: kept {len(kept)}, dropped narrow/none {dict(dropped)}, errors {errors}")

    # ---- gap filling with synthetic points
    unn = [p for p, d in zip(unnamed, land.coast_distance_m([u["lat"] for u in unnamed],
                                                              [u["lon"] for u in unnamed])) if d <= 500]
    samples = [dict(u, beach=True) for u in unn] + coast_samples(land)
    log(f"synthetic candidates: {len(unn)} unnamed beaches + {len(samples) - len(unn)} coast samples")
    sres = orient_all([(s["lat"], s["lon"]) for s in samples], args.workers)
    grid = Grid(2000)
    for p in kept:
        grid.add(p["lat"], p["lon"], p)
    synth = []
    for s, r in zip(samples, sres):
        if not window_ok(r):
            continue
        if grid.near(s["lat"], s["lon"], config.GAP_RADIUS_M):
            continue
        p = dict(name=None, aliases=[], lat=s["lat"], lon=s["lon"], cc=s["cc"], kind="synthetic", prio=9,
                 sources=s.get("sources", []) + ["osm:land-polygons"], sports=[], orient=r)
        lag = config.kite_lagoon(p["lat"], p["lon"])
        if lag and r["width"] < 60:
            p["sports"], p["lagoon"] = ["kite"], lag
        synth.append(p)
        grid.add(p["lat"], p["lon"], p)
    name_synthetic(synth, places)
    log(f"synthetic points: {len(synth)}")

    allp = kept + synth
    assign_ids(allp)
    for p in allp:
        p["zone"] = zones.assign_zone(p["cc"], p["lat"], p["lon"])

    out = []
    for p in sorted(allp, key=lambda p: p["id"]):
        r = p["orient"]
        rec = {
            "id": p["id"], "name": p["name"], "lat": round(p["lat"], 5), "lon": round(p["lon"], 5),
            "country": p["cc"], "zone": p["zone"], "layer": 1, "kind": p["kind"],
            "info": {"facing": r["facing"], "window": r["window"], "break": "unknown",
                     "sports": p["sports"] or ["surf"]},
            "sources": p["sources"], "licence": licence_of(p),
        }
        if p["aliases"]:
            rec["aliases"] = p["aliases"][:6]
        if p.get("lagoon"):
            rec["lagoon"] = p["lagoon"]
        out.append(rec)

    os.makedirs(config.OUT_DIR, exist_ok=True)
    fn = os.path.join(config.OUT_DIR, "layer1.json")
    with open(fn, "w") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(fn)
    if size > 20 * 2**20:
        with gzip.open(fn + ".gz", "wt", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(config.OUT_DIR, "zones.json"), "w") as f:
        json.dump({"v": 1, "zones": zones.zones_json(out)}, f, ensure_ascii=False, indent=1)
    meta = {"runtime_s": round(time.time() - t0), "real_dropped": dict(dropped), "errors": errors,
            "raw_counts": dict(raw_counts), "size_bytes": size}
    with open(os.path.join(config.CACHE, "build_meta.json"), "w") as f:
        json.dump(meta, f)
    log(f"wrote {len(out)} points, {size/2**20:.1f} MB")


if __name__ == "__main__":
    main()
