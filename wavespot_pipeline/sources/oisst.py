"""NOAA OISST v2.1 daily 0.25° (public domain) — SST fallback (and the only SST south of 26°N)."""
from __future__ import annotations

import datetime as dt
import io
import re
import time

import numpy as np

from .. import config
from ..cells import map_cells
from ..grids import RegularGrid, erode_valid
from .base import IO_LOCK, SourceData, SourceStatus, http_get, log


def latest_file(now: dt.datetime) -> str | None:
    for back in (0, 1):
        month = (now.replace(day=1) - dt.timedelta(days=back * 2)).strftime("%Y%m") if back else now.strftime("%Y%m")
        try:
            html = http_get(f"{config.OISST_BASE}/{month}/", timeout=30).decode()
        except Exception:
            continue
        names = sorted(set(re.findall(r"oisst-avhrr-v02r01\.\d{8}(?:_preliminary)?\.nc", html)))
        if names:
            return f"{config.OISST_BASE}/{month}/{names[-1]}"
    return None


def read_sst(blob: bytes, spots: list[dict], cache_dir: str | None):
    import xarray as xr

    with IO_LOCK, xr.open_dataset(io.BytesIO(blob), engine="h5netcdf") as ds:
        da = ds["sst"].isel(time=0)
        if "zlev" in da.dims:
            da = da.isel(zlev=0)
        vals = np.asarray(da.values, dtype=np.float32)
        lats = ds["lat"].values
        lons = ds["lon"].values
        t = int(ds["time"].values[0].astype("datetime64[s]").astype(np.int64))
    grid = RegularGrid(float(lats[0]), float(lats[1] - lats[0]), len(lats), float(lons[0]),
                       float(lons[1] - lons[0]), len(lons), True)
    valid = np.isfinite(vals)
    cells, _ = map_cells("oisst", grid, lambda: [erode_valid(valid), valid], spots, 60.0, cache_dir)
    out = np.full(len(spots), np.nan, dtype=np.float32)
    ok = cells[:, 0] >= 0
    out[ok] = vals[cells[ok, 0], cells[ok, 1]]
    return t, out


def fetch(spots: list[dict], now: dt.datetime, cache_dir: str | None):
    t0 = time.time()
    url = latest_file(now)
    if url is None:
        return None, SourceStatus("oisst", False, time.time() - t0, "no file listed")
    try:
        blob = http_get(url, timeout=120)
        t, sst = read_sst(blob, spots, cache_dir)
    except Exception as e:
        log.warning("OISST failed: %s", e)
        return None, SourceStatus("oisst", False, time.time() - t0, str(e))
    # Single daily analysis (time stamp is already 12:00 UTC); persisted forward by the blender.
    data = SourceData("oisst", np.array([t], dtype=np.int64), {"sst": sst[:, None]},
                      np.isfinite(sst), {"file": url.rsplit("/", 1)[-1]})
    return data, SourceStatus("oisst", True, time.time() - t0, url.rsplit("/", 1)[-1], len(blob))
