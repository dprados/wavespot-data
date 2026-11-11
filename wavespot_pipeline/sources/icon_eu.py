"""DWD ICON-EU 0.0625° (CC BY 4.0, "Quelle: Deutscher Wetterdienst"): 10 m wind and gusts.

Domain lat 29.5–70.5: no Canaries, no Morocco south of 29.5°N (those spots
get ECMWF wind). One bz2-compressed GRIB2 file per variable and step.
"""
from __future__ import annotations

import bz2
import datetime as dt
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .. import config
from ..cells import map_cells
from .base import SourceData, SourceStatus, decode_grib, extract, http_exists, http_get, log, stack_times


def _url(run: dt.datetime, var: str, step: int) -> str:
    ymdh = run.strftime("%Y%m%d%H")
    return (f"{config.ICON_EU_BASE}/{run:%H}/{var}/icon-eu_europe_regular-lat-lon_single-level_"
            f"{ymdh}_{step:03d}_{config.ICON_EU_VARS[var]}.grib2.bz2")


def _fr_land_url(run: dt.datetime) -> str:
    return (f"{config.ICON_EU_BASE}/{run:%H}/fr_land/icon-eu_europe_regular-lat-lon_time-invariant_"
            f"{run:%Y%m%d%H}_FR_LAND.grib2.bz2")


def find_run(now: dt.datetime) -> dt.datetime | None:
    """Newest 00/06/12/18 run (120 h long) with its last file published."""
    base = now.replace(minute=0, second=0, microsecond=0, hour=(now.hour // 6) * 6)
    for k in range(5):
        run = base - dt.timedelta(hours=6 * k)
        if http_exists(_url(run, "vmax_10m", 120)) and http_exists(_url(run, "v_10m", 120)):
            return run
    return None


def in_domain(lat: float, lon: float) -> bool:
    a, b, c, d = config.ICON_EU_DOMAIN
    return a + 0.1 <= lat <= b - 0.1 and c + 0.1 <= lon <= d - 0.1


def fetch(spots: list[dict], now: dt.datetime, cache_dir: str | None, workers: int = 12):
    t0 = time.time()
    nspots = len(spots)
    inside = np.array([in_domain(s["lat"], s["lon"]) for s in spots])
    if not inside.any():
        return None, SourceStatus("icon-eu", True, 0.0, "no spot in domain")
    run = find_run(now)
    if run is None:
        return None, SourceStatus("icon-eu", False, time.time() - t0, "no complete run found")
    run_s = run.strftime("%Y-%m-%dT%HZ")
    log.info("ICON-EU run %s", run_s)
    nbytes = 0

    def get(url):
        raw = http_get(url)
        return decode_grib(bz2.decompress(raw)), len(raw)

    # Prefer the nearest sea point (FR_LAND < 0.5) within 7 km, else nearest point.
    first, n = get(_url(run, "u_10m", 0))
    nbytes += n
    grid = first.grid
    sub = [s if inside[i] else {**s, "lat": -90.0, "lon": 0.0} for i, s in enumerate(spots)]
    try:
        land, n = get(_fr_land_url(run))
        nbytes += n
        cells, _ = map_cells("icon_eu_sea", grid, [land.values < 0.5], sub, 7.0, cache_dir)
    except Exception as e:  # pragma: no cover - constant field missing
        log.warning("ICON-EU FR_LAND unavailable: %s", e)
        cells = np.full((nspots, 2), -1, dtype=np.int64)
    miss = (cells[:, 0] < 0) & inside
    if miss.any():
        anyc, _ = map_cells("icon_eu_any", grid, [np.ones((grid.nlat, grid.nlon), bool)], sub, 10.0, cache_dir)
        cells[miss] = anyc[miss]
    cells[~inside] = -1

    per_t: dict[int, dict[str, np.ndarray]] = {}
    failures = 0
    tasks = [(v, st) for v in config.ICON_EU_VARS for st in config.ICON_EU_STEPS]

    def work(var, step):
        fld, n = get(_url(run, var, step))
        return var, fld.valid_time, extract(fld.values, cells), n

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(work, *t) for t in tasks]
        for f in as_completed(futs):
            try:
                var, vt, vals, n = f.result()
            except Exception as e:
                failures += 1
                log.warning("ICON-EU field failed: %s", e)
                continue
            nbytes += n
            per_t.setdefault(vt, {})[var] = vals
    if not per_t:
        return None, SourceStatus("icon-eu", False, time.time() - t0, "no field decoded", nbytes, run_s)
    times, f = stack_times(per_t, list(config.ICON_EU_VARS), nspots)
    # VMAX_10M at step 0 is undefined (max since previous step).
    data = SourceData("icon-eu", times, {"u10": f["u_10m"], "v10": f["v_10m"], "gust": f["vmax_10m"]},
                      cells[:, 0] >= 0, {"run": run_s})
    ok = failures < len(tasks) * 0.1
    return data, SourceStatus("icon-eu", ok, time.time() - t0, f"{len(tasks) - failures}/{len(tasks)} fields",
                              nbytes, run_s)
