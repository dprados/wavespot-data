"""Copernicus Marine IBI (Iberia-Biscay-Ireland) waves 0.027° hourly + daily SST.

Waves are downloaded per coastal strip (config.IBI_STRIPS) with the official
`copernicusmarine` toolbox; each spot then uses the nearest valid sea cell that
is at least one cell off the coast (8 sea neighbours), cached on disk.
Attribution: "Generated using E.U. Copernicus Marine Service Information".
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .. import config
from ..cells import map_cells
from ..grids import RegularGrid, erode_valid
from .base import IO_LOCK, SourceData, SourceStatus, log

FIELD_MAP = {
    "VHM0": "hs", "VTPK": "tp", "VMDR": "dir",
    "VHM0_SW1": "s1h", "VTM01_SW1": "s1p", "VMDR_SW1": "s1d",
    "VHM0_SW2": "s2h", "VTM01_SW2": "s2p", "VMDR_SW2": "s2d",
    "VHM0_WW": "wwh", "VTM01_WW": "wwp", "VMDR_WW": "wwd",
}
MARGIN = 0.02


def strip_for(lat: float, lon: float) -> str | None:
    for name, (a, b, c, d) in config.IBI_STRIPS.items():
        if a + MARGIN <= lat <= b - MARGIN and c + MARGIN <= lon <= d - MARGIN:
            return name
    return None


def in_domain(lat: float, lon: float) -> bool:
    a, b, c, d = config.IBI_DOMAIN
    return a <= lat <= b and c <= lon <= d


def _cli() -> list[str]:
    exe = os.path.join(os.path.dirname(sys.executable), "copernicusmarine")
    if os.path.exists(exe):
        return [exe]
    found = shutil.which("copernicusmarine")
    if found:
        return [found]
    return [sys.executable, "-c", "from copernicusmarine.command_line_interface.copernicus_marine import "
            "command_line_interface as c; c()"]


def _subset(dataset: str, variables: list[str], box, start: dt.datetime, end: dt.datetime,
            out_dir: str, name: str, depth: tuple[float, float] | None = None, timeout: int = 900) -> str:
    """Run `copernicusmarine subset` in a subprocess (isolates HDF5 from our threads).

    Credentials come from COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD.
    """
    cmd = _cli() + [
        "subset", "--dataset-id", dataset,
        "--minimum-latitude", str(box[0]), "--maximum-latitude", str(box[1]),
        "--minimum-longitude", str(box[2]), "--maximum-longitude", str(box[3]),
        "--start-datetime", start.strftime("%Y-%m-%dT%H:%M:%S"),
        "--end-datetime", end.strftime("%Y-%m-%dT%H:%M:%S"),
        "--output-directory", out_dir, "--output-filename", name,
        "--overwrite", "--disable-progress-bar", "--log-level", "WARN",
    ]
    for v in variables:
        cmd += ["--variable", v]
    if depth is not None:
        cmd += ["--minimum-depth", str(depth[0]), "--maximum-depth", str(depth[1])]
    last = ""
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            path = os.path.join(out_dir, name)
            if r.returncode == 0 and os.path.exists(path):
                return path
            last = (r.stderr or r.stdout)[-400:]
        except subprocess.TimeoutExpired:
            last = "timeout"
        time.sleep(5 + 10 * attempt)
    raise RuntimeError(f"IBI subset {name} failed: {last}")


def read_strip(path: str, spots: list[dict], idx: list[int], cache_dir: str | None, key: str):
    """Open one strip file and extract every variable at the spots' cells."""
    import xarray as xr

    with xr.open_dataset(path) as ds:
        lats = ds["latitude"].values
        lons = ds["longitude"].values
        grid = RegularGrid.from_coords(lats, lons)
        hs0 = ds["VHM0"].isel(time=0).values
        valid = np.isfinite(hs0)
        sub = [spots[i] for i in idx]
        cells, km = map_cells(f"ibi_{key}", grid, lambda: [erode_valid(valid), valid], sub, 12.0, cache_dir)
        times = (ds["time"].values.astype("datetime64[s]").astype(np.int64))
        out = {}
        ok = cells[:, 0] >= 0
        for var, name in FIELD_MAP.items():
            arr = np.full((len(idx), len(times)), np.nan, dtype=np.float32)
            if var in ds and ok.any():
                data = ds[var].values  # (time, lat, lon)
                arr[ok] = data[:, cells[ok, 0], cells[ok, 1]].T
            out[name] = arr
    return times, out, ok, km


def fetch_waves(spots: list[dict], h_start: dt.datetime, work_dir: str, cache_dir: str | None, workers: int = 4):
    t0 = time.time()
    nspots = len(spots)
    groups: dict[str, list[int]] = {}
    uncovered = 0
    for i, s in enumerate(spots):
        if not in_domain(s["lat"], s["lon"]):
            continue
        st = strip_for(s["lat"], s["lon"])
        if st is None:
            uncovered += 1
            continue
        groups.setdefault(st, []).append(i)
    if not groups:
        return None, SourceStatus("ibi-wave", False, 0.0, "no spot inside a strip")
    end = h_start + dt.timedelta(hours=config.H_HOURS - 1)
    os.makedirs(work_dir, exist_ok=True)

    times_ref = None
    fields = {n: None for n in FIELD_MAP.values()}
    covered = np.zeros(nspots, bool)
    failed = []
    nbytes = 0

    def work(name):
        return _subset(config.IBI_WAV_DATASET, config.IBI_WAV_VARS, config.IBI_STRIPS[name], h_start, end,
                       work_dir, f"ibi_{name}.nc")

    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(work, n): n for n in groups}
        for f in as_completed(futs):
            name = futs[f]
            try:
                path = f.result()
                size = os.path.getsize(path)
                with IO_LOCK:
                    times, out, ok, _km = read_strip(path, spots, groups[name], cache_dir, name)
                os.remove(path)
            except Exception as e:
                failed.append(name)
                log.warning("IBI strip %s failed: %s", name, e)
                continue
            nbytes += size
            if times_ref is None:
                times_ref = times
                for n in fields:
                    fields[n] = np.full((nspots, len(times)), np.nan, dtype=np.float32)
            if len(times) != len(times_ref) or (times != times_ref).any():
                # Align on the common axis (should not happen: same request window).
                common, ia, ib = np.intersect1d(times_ref, times, return_indices=True)
                for n in fields:
                    tmp = np.full((len(groups[name]), len(times_ref)), np.nan, dtype=np.float32)
                    tmp[:, ia] = out[n][:, ib]
                    out[n] = tmp
            gi = np.array(groups[name])
            for n in fields:
                fields[n][gi] = out[n]
            covered[gi[ok]] = True
    elapsed = time.time() - t0
    if times_ref is None:
        return None, SourceStatus("ibi-wave", False, elapsed, f"all {len(groups)} strips failed", nbytes)
    detail = f"{len(groups) - len(failed)}/{len(groups)} strips; {int(covered.sum())} spots; uncovered {uncovered}"
    if failed:
        detail += "; failed " + ",".join(sorted(failed))
    return (SourceData("ibi", times_ref, fields, covered, {"failed": failed}),
            SourceStatus("ibi-wave", not failed, elapsed, detail, nbytes))


def fetch_sst(spots: list[dict], h_start: dt.datetime, work_dir: str, cache_dir: str | None):
    """Daily surface temperature (°C) from IBI PHY over the bbox of all IBI spots."""
    t0 = time.time()
    idx = [i for i, s in enumerate(spots) if in_domain(s["lat"], s["lon"])]
    if not idx:
        return None, SourceStatus("ibi-sst", False, 0.0, "no spot in domain")
    lats = [spots[i]["lat"] for i in idx]
    lons = [spots[i]["lon"] for i in idx]
    box = (max(min(lats) - 0.3, config.IBI_DOMAIN[0]), min(max(lats) + 0.3, config.IBI_DOMAIN[1]),
           max(min(lons) - 0.3, config.IBI_DOMAIN[2]), min(max(lons) + 0.3, config.IBI_DOMAIN[3]))
    end = h_start + dt.timedelta(days=9)
    os.makedirs(work_dir, exist_ok=True)
    try:
        path = _subset(config.IBI_PHY_DAILY_DATASET, ["thetao"], box, h_start, end, work_dir, "ibi_sst.nc",
                       depth=(0.0, 1.0))
    except Exception as e:
        return None, SourceStatus("ibi-sst", False, time.time() - t0, str(e))
    import xarray as xr

    size = os.path.getsize(path)
    with IO_LOCK, xr.open_dataset(path) as ds:
        da = ds["thetao"]
        if "depth" in da.dims:
            da = da.isel(depth=0)
        grid = RegularGrid.from_coords(ds["latitude"].values, ds["longitude"].values)
        vals = da.values  # (time, lat, lon)
        times = ds["time"].values.astype("datetime64[s]").astype(np.int64)
    os.remove(path)
    valid = np.isfinite(vals[0])
    sub = [spots[i] for i in idx]
    cells, _ = map_cells("ibi_sst_" + grid.signature.replace(".", "")[:40], grid,
                         lambda: [erode_valid(valid), valid], sub, 15.0, cache_dir)
    sst = np.full((len(spots), len(times)), np.nan, dtype=np.float32)
    ok = cells[:, 0] >= 0
    gi = np.array(idx)
    sst[gi[ok]] = vals[:, cells[ok, 0], cells[ok, 1]].T
    # Daily means are stamped at 00:00; centre them at 12:00 for interpolation.
    times = times + 12 * 3600
    covered = np.isfinite(sst).any(axis=1)
    return (SourceData("ibi-sst", times, {"sst": sst}, covered),
            SourceStatus("ibi-sst", True, time.time() - t0, f"{int(covered.sum())} spots", size))
