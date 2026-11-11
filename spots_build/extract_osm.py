"""Extract candidate features from Geofabrik .osm.pbf extracts (pyosmium).

Writes one JSON per extract into CACHE/osm/: list of
{"t": "n|w|r", "id", "lat", "lon", "tags": {...}} for
  natural=beach|cape|bay|peninsula, place=*, sport=surf/kite/windsurf.
Only features inside the scope boxes (padded) are kept.

Usage: python -I spots_build/extract_osm.py PBF_DIR [name ...]
"""
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

import osmium  # noqa: E402

SPORT = re.compile(r"surf|kite|windsurf|bodyboard")
PLACES = {"locality", "village", "hamlet", "town", "city", "suburb", "isolated_dwelling",
          "neighbourhood", "quarter"}
KEEP_TAGS = re.compile(r"^(name(:(es|pt|fr|en|ast|gl|eu|ca|de|br|latin|ar))?|alt_name|"
                       r"natural|place|sport|surfing|leisure|shop|amenity|club|office|craft|"
                       r"tourism|building|website|wikidata|population|surface)$")


def want(t):
    nat = t.get("natural")
    if nat == "beach":
        return True
    if nat in ("cape", "bay", "peninsula") and "name" in t:
        return True
    if t.get("place") in PLACES and ("name" in t):
        return True
    if SPORT.search(t.get("sport", "")) or "surfing" in t:
        return True
    return False


def in_boxes(la, lo, pad=0.15):
    for s, w, n, e in config.LAND_BOXES:
        if s - pad <= la <= n + pad and w - pad <= lo <= e + pad:
            return True
    return False


def slim(tags):
    return {k: v for k, v in dict(tags).items() if KEEP_TAGS.match(k)}


def run(path):
    out = []
    fp = (osmium.FileProcessor(path)
          .with_locations()
          .with_areas(osmium.filter.KeyFilter("natural")))
    for o in fp:
        if not o.tags or not want(o.tags):
            continue
        if o.is_node():
            la, lo, t = o.location.lat, o.location.lon, "n"
        elif o.is_way():
            pts = [(nd.location.lat, nd.location.lon) for nd in o.nodes if nd.location.valid()]
            if not pts:
                continue
            if len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            la = sum(p[0] for p in pts) / len(pts)
            lo = sum(p[1] for p in pts) / len(pts)
            t = "w"
        elif o.is_area() and not o.from_way():
            pts = [(nr.lat, nr.lon) for ring in o.outer_rings() for nr in ring]
            if not pts:
                continue
            la = sum(p[0] for p in pts) / len(pts)
            lo = sum(p[1] for p in pts) / len(pts)
            t = "r"
        else:
            continue
        if not in_boxes(la, lo):
            continue
        oid = o.orig_id() if t == "r" else o.id
        out.append({"t": t, "id": oid, "lat": round(la, 6), "lon": round(lo, 6),
                    "tags": slim(o.tags)})
    return path, out


def main():
    pbf_dir = sys.argv[1]
    names = sys.argv[2:] or [p.split("/")[-1] for p in config.PBF_FILES]
    os.makedirs(os.path.join(config.CACHE, "osm"), exist_ok=True)
    paths = [os.path.join(pbf_dir, f"{n}.osm.pbf") for n in names]
    with ProcessPoolExecutor(4) as ex:
        for path, out in ex.map(run, paths):
            name = os.path.basename(path).split(".")[0]
            with open(os.path.join(config.CACHE, "osm", f"{name}.json"), "w") as f:
                json.dump(out, f, ensure_ascii=False)
            print(name, len(out), flush=True)


if __name__ == "__main__":
    main()
