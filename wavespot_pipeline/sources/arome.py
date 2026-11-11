"""Météo-France AROME 0.025° (Licence Ouverte Etalab 2.0, "Source : Météo-France").

10 m wind (10u, 10v) and hourly max gust (max_i10fg) for France and northern
Spain, 0–48 h. Files come from the public OVH bucket (no key), one SP1 package
per 6-hour block (~58 MB each, ~490 MB per run). Only the three needed
messages per hour are decoded. Spots within 0.5° of the grid edge are skipped
(lateral boundary zone).
"""
from __future__ import annotations

import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .. import config
from ..cells import map_cells
from .base import SourceData, SourceStatus, decode_grib, extract, http_exists, http_get, log, peek_grib, split_grib

WANTED = {"10u": "u10", "10v": "v10", "max_i10fg": "gust"}


def _url(run: dt.datetime, block: str) -> str:
    r = run.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{config.AROME_BASE}/pnt/{r}/arome/0025/SP1/arome__0025__SP1__{block}__{r}.grib2"


def find_run(now: dt.datetime) -> dt.datetime | None:
    """Newest 3-hourly run whose last needed block (43H48H) is published."""
    base = now.replace(minute=0, second=0, microsecond=0, hour=(now.hour // 3) * 3)
    for k in range(9):
        run = base - dt.timedelta(hours=3 * k)
        if http_exists(_url(run, config.AROME_BLOCKS[-1])):
            return run
    return None


def in_scope(country: str, lat: float, lon: float) -> bool:
    """France + northern Spain, away from the grid's lateral boundary zone."""
    a, b, c, d = config.AROME_DOMAIN
    m = config.AROME_EDGE_MARGIN
    if not (a + m <= lat <= b - m and c + m <= lon <= d - m):
        return False
    return country == "FR" or (country == "ES" and lat >= config.AROME_ES_MIN_LAT)


def decode_block(data: bytes, cells_for) -> dict[int, dict[str, np.ndarray]]:
    out: dict[int, dict[str, np.ndarray]] = {}
    for msg in split_grib(data):
        name = WANTED.get(peek_grib(msg))
        if name is None:
            continue
        fld = decode_grib(msg)
        out.setdefault(fld.valid_time, {})[name] = extract(fld.values, cells_for(fld))
    return out


def fetch(spots: list[dict], now: dt.datetime, cache_dir: str | None, workers: int = 4):
    t0 = time.time()
    nspots = len(spots)
    inside = np.array([in_scope(s["country"], s["lat"], s["lon"]) for s in spots])
    if not inside.any():
        return None, SourceStatus("arome", True, 0.0, "no spot in scope")
    run = find_run(now)
    if run is None:
        return None, SourceStatus("arome", False, time.time() - t0, "no complete run found")
    run_s = run.strftime("%Y-%m-%dT%HZ")
    log.info("AROME run %s", run_s)
    sub = [s if inside[i] else {**s, "lat": -90.0, "lon": 0.0} for i, s in enumerate(spots)]
    cache: dict[str, np.ndarray] = {}

    def cells_for(fld):
        key = fld.grid.signature
        if key not in cache:
            # Atmospheric field: nearest grid point (land/sea mask not in SP1).
            c, _ = map_cells("arome_v1", fld.grid, [np.ones(fld.values.shape, bool)], sub, 5.0, cache_dir)
            c[~inside] = -1
            cache[key] = c
        return cache[key]

    per_t: dict[int, dict[str, np.ndarray]] = {}
    nbytes = 0
    failed = []
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(http_get, _url(run, b), None, 300): b for b in config.AROME_BLOCKS}
        for f in as_completed(futs):
            try:
                data = f.result()
                nbytes += len(data)
                for t, vals in decode_block(data, cells_for).items():
                    per_t.setdefault(t, {}).update(vals)
            except Exception as e:
                failed.append(futs[f])
                log.warning("AROME block %s failed: %s", futs[f], e)
    if not per_t:
        return None, SourceStatus("arome", False, time.time() - t0, "no field decoded", nbytes, run_s)
    times = np.array(sorted(per_t), dtype=np.int64)
    fields = {}
    for name in WANTED.values():
        arr = np.full((nspots, len(times)), np.nan, dtype=np.float32)
        for k, t in enumerate(times):
            v = per_t[int(t)].get(name)
            if v is not None:
                arr[:, k] = v
        fields[name] = arr
    detail = f"{len(config.AROME_BLOCKS) - len(failed)}/{len(config.AROME_BLOCKS)} blocks; {int(inside.sum())} spots"
    return (SourceData("arome", times, fields, inside, {"run": run_s}),
            SourceStatus("arome", not failed, time.time() - t0, detail, nbytes, run_s))
