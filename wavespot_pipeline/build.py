"""Daily forecast build: fetch sources -> blend -> write the static v1 site.

    python -m wavespot_pipeline.build --out site/v1 \
        --spots data/seed_spots.json data/spots/layer1.json

Exit code 0 when at least one spot was published with fresh data, 2 otherwise
(the workflow then skips the deploy and the previous site stays online).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import config, products
from .blend import Sources, blend
from .sources import ecmwf, gfswave, ibi, icon_eu, oisst
from .sources.base import SourceStatus
from .spots import is_named, load_spots, load_zone_registry, tile_of, zone_name
from .state import LastGood

log = logging.getLogger("wavespot")
ALL_SOURCES = ("ibi", "ibi-sst", "ecmwf", "icon-eu", "gfs-wave", "oisst")


def dumps(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def write(path: str, obj) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    raw = dumps(obj)
    with open(path, "w") as f:
        f.write(raw)
    return raw


def load_tides(path: str) -> dict:
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f).get("spots", {})
    return {}


def fetch_all(spots, now, h_start, work, cache, skip: set[str]) -> tuple[Sources, list[SourceStatus]]:
    src = Sources()
    statuses: list[SourceStatus] = []

    def guarded(name, fn):
        if name in skip:
            return None
        t0 = time.time()
        try:
            return fn()
        except Exception as e:  # a source must never take the run down
            log.exception("source %s crashed", name)
            return ("crash", SourceStatus(name, False, time.time() - t0, f"crash: {e}"))

    jobs = {
        "ibi": lambda: ibi.fetch_waves(spots, h_start, os.path.join(work, "ibi"), cache),
        "ibi-sst": lambda: ibi.fetch_sst(spots, h_start, os.path.join(work, "ibi"), cache),
        "ecmwf": lambda: ecmwf.fetch(spots, now, cache),
        "icon-eu": lambda: icon_eu.fetch(spots, now, cache),
        "gfs-wave": lambda: gfswave.fetch(spots, now, h_start, cache),
        "oisst": lambda: oisst.fetch(spots, now, cache),
    }
    with ThreadPoolExecutor(len(jobs)) as ex:
        futs = {name: ex.submit(guarded, name, fn) for name, fn in jobs.items()}
        results = {name: f.result() for name, f in futs.items()}

    def unpack(name, res):
        if res is None:
            return None
        if isinstance(res, tuple) and res and res[0] == "crash":
            statuses.append(res[1])
            return None
        return res

    r = unpack("ibi", results["ibi"])
    if r:
        src.ibi, st = r
        statuses.append(st)
    r = unpack("ibi-sst", results["ibi-sst"])
    if r:
        src.sst_ibi, st = r
        statuses.append(st)
    r = unpack("ecmwf", results["ecmwf"])
    if r:
        src.ecmwf_wave, src.ecmwf_wind, sts = r
        statuses.extend(sts)
    r = unpack("icon-eu", results["icon-eu"])
    if r:
        src.icon, st = r
        statuses.append(st)
    r = unpack("gfs-wave", results["gfs-wave"])
    if r:
        src.gfs, st = r
        statuses.append(st)
    r = unpack("oisst", results["oisst"])
    if r:
        src.sst_oisst, st = r
        statuses.append(st)
    return src, statuses


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/v1")
    ap.add_argument("--spots", nargs="+", default=["data/seed_spots.json", "data/spots/layer1.json"])
    ap.add_argument("--tides", default="data/tides/eot20_constituents.json")
    ap.add_argument("--zones", default="data/spots/zones.json", help="zone registry from the spot layer")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--work", default="work")
    ap.add_argument("--skip", nargs="*", default=[], help=f"sources to skip: {ALL_SOURCES}")
    ap.add_argument("--limit", type=int, default=0, help="only the first N spots (debug)")
    ap.add_argument("--base-url", default=config.BASE_URL, help="published site, for last-good fallback")
    ap.add_argument("--report", default="", help="write a JSON run report here")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    t_start = time.time()
    timings = {}
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    generated = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    h_start = now.replace(hour=0, minute=0, second=0)

    registry = load_zone_registry(args.zones)
    spots = load_spots(args.spots, registry)
    if args.limit:
        spots = spots[: args.limit]
    if not spots:
        log.error("no spots")
        return 2
    tides = load_tides(args.tides)
    log.info("%d spots, %d with tide constituents", len(spots), sum(1 for s in spots if s["id"] in tides))

    t = time.time()
    src, statuses = fetch_all(spots, now, h_start, args.work, args.cache, set(args.skip))
    timings["fetch"] = time.time() - t
    for st in statuses:
        log.info("source %-11s ok=%s %.0fs %.0f MB %s", st.name, st.ok, st.seconds, st.bytes / 1e6, st.detail)

    t = time.time()
    blended = blend(src, len(spots), h_start)
    timings["blend"] = time.time() - t

    t = time.time()
    last_good = LastGood(args.cache, args.base_url)
    out = args.out
    tiles: dict[str, list] = defaultdict(list)
    zones: dict[str, list] = defaultdict(list)
    zone_bbox: dict[str, list[float]] = {}
    fresh = stale = dropped = 0
    stale_ids = []
    for i, spot in enumerate(spots):
        tc = tides.get(spot["id"])
        tide = {"z0": tc.get("z0", 0.0), "cons": tc["cons"]} if tc and tc.get("cons") else None
        doc = products.spot_doc(spot, blended, i, h_start, generated, tide)
        if products.doc_is_complete(doc):
            raw = write(os.path.join(out, "spots", f"{spot['id']}.json"), doc)
            last_good.save(doc, raw)
            fresh += 1
        else:
            prev = last_good.load(spot["id"])
            if prev is not None:
                prev["info"] = spot["info"]  # metadata may have been curated meanwhile
                doc = prev
                write(os.path.join(out, "spots", f"{spot['id']}.json"), doc)
                stale += 1
                stale_ids.append(spot["id"])
            elif any(x is not None for x in doc["h"]["hs"]):
                write(os.path.join(out, "spots", f"{spot['id']}.json"), doc)
                stale += 1
                stale_ids.append(spot["id"])
            else:
                dropped += 1
                log.warning("spot %s dropped: no data and no last-good", spot["id"])
                continue
        today = products.today_index(doc, now)
        tiles[tile_of(spot["lat"], spot["lon"])].append(products.index_entry(doc, products.index_r(doc, today)))
        z = spot["zone"]
        bb = zone_bbox.setdefault(z, [spot["lat"], spot["lon"], spot["lat"], spot["lon"]])
        bb[0], bb[1] = min(bb[0], spot["lat"]), min(bb[1], spot["lon"])
        bb[2], bb[3] = max(bb[2], spot["lat"]), max(bb[3], spot["lon"])
        if spot["layer"] == 2 or is_named(spot):
            zones[z].append(products.zone_entries(doc))
    timings["spots"] = time.time() - t

    t = time.time()
    for tile, entries in tiles.items():
        entries.sort(key=lambda e: e["id"])
        write(os.path.join(out, "index", f"{tile}.json"), {"v": config.SCHEMA_VERSION, "spots": entries})
    for z, per_spot in zones.items():
        write(os.path.join(out, "zones", f"{z}.json"), products.zone_doc(z, per_spot, generated))
    zone_list = []
    for z in sorted(zone_bbox):
        bb = zone_bbox[z]
        zone_list.append({"id": z, "name": zone_name(z, registry),
                          "bbox": [round(bb[0], 3), round(bb[1], 3), round(bb[2], 3), round(bb[3], 3)]})
    status = {
        "sources": {st.name: st.as_json() for st in statuses},
        "spots": {"total": len(spots), "fresh": fresh, "stale": stale, "dropped": dropped},
        "stale": stale_ids[:50],
    }
    meta = {"v": config.SCHEMA_VERSION, "generated": generated, "tiles": sorted(tiles), "zones": zone_list,
            "attribution": config.ATTRIBUTION, "status": status}
    write(os.path.join(out, "index", "meta.json"), meta)
    timings["index"] = time.time() - t
    timings["total"] = time.time() - t_start
    log.info("published %d fresh, %d stale, %d dropped; timings %s", fresh, stale, dropped,
             {k: round(v, 1) for k, v in timings.items()})
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w") as f:
            json.dump({"generated": generated, "timings": timings, **status}, f, indent=1)
    return 0 if fresh > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
