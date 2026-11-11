"""ECMWF IFS 0.1° open data (CC BY 4.0): waves (swh, mwd, pp1d) and wind (10u, 10v, 10fg, 2t).

Only the needed GRIB messages are fetched with HTTP byte ranges read from the
`.index` sidecar files. Mirrors: AWS (eu-central-1) first, data.ecmwf.int next.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .. import config
from ..cells import map_cells
from ..grids import erode_valid
from .base import SourceData, SourceStatus, decode_grib, extract, http_exists, http_get, log, stack_times


def _url(mirror: str, run: dt.datetime, stream: str, step: int, ext: str) -> str:
    d = run.strftime("%Y%m%d")
    hh = run.strftime("%H")
    kind = "wave-fc-sfc" if stream == "wave" else "oper-fc-sfc"
    folder = "wave" if stream == "wave" else "oper"
    return f"{mirror}/{d}/{hh}z/ifs/{config.ECMWF_RESOL}/{folder}/{d}{hh}0000-{step}h-{kind}.{ext}"


def find_run(now: dt.datetime, mirrors=None) -> tuple[dt.datetime, str] | None:
    """Newest 00z/12z run whose last step (360 h) is published for both streams."""
    mirrors = mirrors or config.ECMWF_MIRRORS
    base = now.replace(minute=0, second=0, microsecond=0, hour=12 if now.hour >= 12 else 0)
    for k in range(5):
        run = base - dt.timedelta(hours=12 * k)
        for m in mirrors:
            if http_exists(_url(m, run, "wave", 360, "index")) and http_exists(_url(m, run, "oper", 360, "index")):
                return run, m
    return None


def parse_index(text: str) -> dict[str, tuple[int, int]]:
    """ECMWF `.index` (JSON lines) -> {param: (offset, last_byte)}."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        e = json.loads(line)
        if e.get("levtype", "sfc") != "sfc":
            continue
        out[e["param"]] = (int(e["_offset"]), int(e["_offset"]) + int(e["_length"]) - 1)
    return out


def fetch(spots: list[dict], now: dt.datetime, cache_dir: str | None, workers: int = 12):
    """Return (wave SourceData|None, wind SourceData|None, [SourceStatus...])."""
    t0 = time.time()
    found = find_run(now)
    if found is None:
        st = SourceStatus("ecmwf", False, time.time() - t0, "no complete 00z/12z run found")
        return None, None, [st]
    run, mirror = found
    run_s = run.strftime("%Y-%m-%dT%HZ")
    log.info("ECMWF run %s from %s", run_s, mirror)
    nspots = len(spots)
    nbytes = 0

    # Indexes for every step of both streams.
    def get_index(stream, step):
        return stream, step, parse_index(http_get(_url(mirror, run, stream, step, "index")).decode())

    indexes: dict[tuple[str, int], dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(get_index, s, st) for s in ("wave", "oper") for st in config.ECMWF_STEPS]
        for f in as_completed(futs):
            try:
                s, st, idx = f.result()
                indexes[(s, st)] = idx
            except Exception as e:  # missing step -> gap, interpolated later
                log.warning("ECMWF index failed: %s", e)

    def get_field(stream, step, param):
        idx = indexes.get((stream, step), {})
        if param not in idx:
            return None
        data = http_get(_url(mirror, run, stream, step, "grib2"), idx[param])
        return decode_grib(data), len(data)

    # Masks from step 0: wave validity and land-sea mask for wind.
    swh0, n1 = get_field("wave", 0, "swh")
    lsm0, n2 = get_field("oper", 0, "lsm") or (None, 0)
    nbytes += n1 + n2
    wave_valid = np.isfinite(swh0.values)
    wave_cells, wave_km = map_cells("ecmwf_wave", swh0.grid, lambda: [erode_valid(wave_valid), wave_valid],
                                    spots, 40.0, cache_dir)
    if lsm0 is not None:
        sea = lsm0.values < 0.5
        wind_grid = lsm0.grid
        wind_cells, _ = map_cells("ecmwf_wind_sea", wind_grid, [sea], spots, 10.0, cache_dir)
    else:
        wind_grid = swh0.grid
        wind_cells = np.full((nspots, 2), -1, dtype=np.int64)
    if (wind_cells[:, 0] < 0).any():
        any_cell = np.ones((wind_grid.nlat, wind_grid.nlon), bool)
        fallback, _ = map_cells("ecmwf_wind_any", wind_grid, [any_cell], spots, 20.0, cache_dir)
        miss = wind_cells[:, 0] < 0
        wind_cells[miss] = fallback[miss]

    tasks = [("wave", st, p) for st in config.ECMWF_STEPS for p in config.ECMWF_WAVE_PARAMS]
    tasks += [("oper", st, p) for st in config.ECMWF_STEPS for p in config.ECMWF_OPER_PARAMS]
    wave_t: dict[int, dict[str, np.ndarray]] = {}
    wind_t: dict[int, dict[str, np.ndarray]] = {}
    failures = 0

    def work(stream, step, param):
        r = get_field(stream, step, param)
        if r is None:
            return stream, step, param, None, None, 0
        fld, n = r
        if param == "10fg" and step == 0:
            return stream, step, param, None, None, n  # gust undefined at analysis time (all zeros)
        cells = wave_cells if stream == "wave" else wind_cells
        return stream, step, param, fld.valid_time, extract(fld.values, cells), n

    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(work, *t) for t in tasks]
        for f in as_completed(futs):
            try:
                stream, step, param, vt, vals, n = f.result()
            except Exception as e:
                failures += 1
                log.warning("ECMWF field failed: %s", e)
                continue
            if vals is None:
                if not (param == "10fg" and step == 0):
                    failures += 1
                continue
            nbytes += n
            (wave_t if stream == "wave" else wind_t).setdefault(vt, {})[param] = vals

    elapsed = time.time() - t0
    statuses = []
    wave = wind = None
    if wave_t:
        times, f = stack_times(wave_t, config.ECMWF_WAVE_PARAMS, nspots)
        wave = SourceData("ecmwf", times, {"hs": f["swh"], "tp": f["pp1d"], "dir": f["mwd"]},
                          wave_cells[:, 0] >= 0, {"run": run_s, "km": wave_km})
    if wind_t:
        times, f = stack_times(wind_t, config.ECMWF_OPER_PARAMS, nspots)
        t2 = f["2t"] - 273.15
        wind = SourceData("ecmwf", times, {"u10": f["10u"], "v10": f["10v"], "gust": f["10fg"], "t2": t2},
                          wind_cells[:, 0] >= 0, {"run": run_s})
    total = len(tasks)
    detail = f"{total - failures}/{total} fields"
    statuses.append(SourceStatus("ecmwf-wave", wave is not None and failures < total * 0.1, elapsed, detail,
                                 nbytes, run_s))
    statuses.append(SourceStatus("ecmwf-wind", wind is not None and failures < total * 0.1, elapsed, detail,
                                 0, run_s))
    return wave, wind, statuses
