"""Buoys: latest wave/wind observation from Copernicus Marine In Situ IBI NRT.

    python -m wavespot_pipeline.buoys --out site/v1 --work work --cache cache

Writes `buoys/latest.json` (schema §6) and keeps a registry of wave buoys
(`<cache>/buoys_registry.json`) used to assign a buoy to each spot.
Source: INSITU_IBI_PHYBGCWAV_DISCRETE_MYNRT_013_033 (moored platforms "MO"),
which aggregates Puertos del Estado, IH/IPMA, Météo-France/Cerema... under the
Copernicus Marine licence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import time

import numpy as np

from . import config
from .sources.base import IO_LOCK
from .sources.ibi import _cli

log = logging.getLogger("wavespot")
GOOD_QC = (1, 2)
NAME_RE = re.compile(r"_MO_(.+)_(\d{8})\.nc$")


# ------------------------------------------------------------------ index
def parse_index(lines, now: dt.datetime) -> dict[str, dict]:
    """index_latest.txt -> {platform: {file, lat, lon, date}} for wave buoys in our area.

    Keeps the newest daily file per platform among today and yesterday (UTC).
    """
    days = {now.strftime("%Y%m%d"), (now - dt.timedelta(days=1)).strftime("%Y%m%d")}
    la0, la1, lo0, lo1 = config.BUOY_BBOX
    out: dict[str, dict] = {}
    for line in lines:
        if line.startswith("#") or not line.strip():
            continue
        parts = line.rstrip("\n").split(",")
        if len(parts) < 12:
            continue
        path = parts[1]
        m = NAME_RE.search(path)
        if not m or "/latest/" not in path or m.group(2) not in days:
            continue
        params = set(parts[11].split())
        if not ({"VHM0", "VAVH"} & params):
            continue
        try:
            lat, lon = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if not (la0 <= lat <= la1 and lo0 <= lon <= lo1):
            continue
        if lat < 38.5 and lon > -5.55:      # Mediterranean side of the Strait
            continue
        plat = m.group(1)
        prev = out.get(plat)
        if prev is None or m.group(2) > prev["date"]:
            out[plat] = {"file": path, "name": os.path.basename(path), "lat": lat, "lon": lon, "date": m.group(2)}
    return out


def _run(cmd: list[str], timeout: int = 600) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-400:])


def fetch_index(work: str) -> str:
    d = os.path.join(work, "insitu_index")
    shutil.rmtree(d, ignore_errors=True)
    _run(_cli() + ["get", "-i", config.INSITU_DATASET, "--index-parts", "-o", d, "--log-level", "WARN"])
    found = glob.glob(os.path.join(d, "**", "index_latest.txt"), recursive=True)
    if not found:
        raise RuntimeError("index_latest.txt not downloaded")
    return found[0]


def fetch_files(names: list[str], work: str) -> str:
    d = os.path.join(work, "insitu_files")
    shutil.rmtree(d, ignore_errors=True)
    regex = ".*/(" + "|".join(re.escape(n) for n in names) + ")$"
    _run(_cli() + ["get", "-i", config.INSITU_DATASET, "--dataset-part", "latest", "--regex", regex,
                   "-o", d, "--no-directories", "--log-level", "WARN"])
    return d


# ------------------------------------------------------------------ files
def _last_valid(ds, var: str):
    """(time_index, value) of the last good sample of var over any depth, or None."""
    if var not in ds:
        return None
    vals = np.asarray(ds[var].values, dtype=float)
    if vals.ndim == 1:
        vals = vals[:, None]
    ok = np.isfinite(vals)
    qc = f"{var}_QC"
    if qc in ds:
        q = np.asarray(ds[qc].values, dtype=float)
        if q.ndim == 1:
            q = q[:, None]
        ok &= np.isin(q, GOOD_QC)
    rows = np.nonzero(ok.any(axis=1))[0]
    if len(rows) == 0:
        return None
    k = int(rows[-1])
    j = int(np.nonzero(ok[k])[0][0])
    return k, float(vals[k, j])


def read_buoy(path: str, meta: dict, now: dt.datetime) -> dict | None:
    import xarray as xr

    with xr.open_dataset(path) as ds:
        times = ds["TIME"].values.astype("datetime64[s]").astype(np.int64)
        hs = _last_valid(ds, "VHM0") or _last_valid(ds, "VAVH")
        if hs is None:
            return None
        k, hsv = hs
        t = int(times[k])
        if now.timestamp() - t > config.BUOY_MAX_AGE_H * 3600:
            return None

        def near(var, fn=float):
            r = _last_valid(ds, var)
            if r is None or abs(int(times[r[0]]) - t) > 3 * 3600:
                return None
            return fn(r[1])

        name = str(ds.attrs.get("platform_name") or "").strip() or meta["platform"]
        lat = float(np.asarray(ds["LATITUDE"].values).ravel()[-1]) if "LATITUDE" in ds else meta["lat"]
        lon = float(np.asarray(ds["LONGITUDE"].values).ravel()[-1]) if "LONGITUDE" in ds else meta["lon"]
        rnd = lambda x, n: None if x is None or not math.isfinite(x) else round(x, n)  # noqa: E731
        d = near("VMDR")
        wd = near("WDIR")
        return {
            "id": f"MO_{meta['platform']}", "name": name,
            "lat": round(lat, 4), "lon": round(lon, 4),
            "t": dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "hs": rnd(hsv, 2), "tp": rnd(near("VTPK"), 1),
            "dir": None if d is None else int(round(d)) % 360,
            "ws": rnd(near("WSPD"), 2), "wd": None if wd is None else int(round(wd)) % 360,
            "sst": rnd(near("TEMP"), 1),
        }


def collect(work: str, now: dt.datetime) -> list[dict]:
    with open(fetch_index(work)) as f:
        sel = parse_index(f, now)
    log.info("in-situ index: %d wave buoys in area", len(sel))
    if not sel:
        return []
    d = fetch_files([v["name"] for v in sel.values()], work)
    out = []
    for plat, meta in sorted(sel.items()):
        p = os.path.join(d, meta["name"])
        if not os.path.exists(p):
            continue
        try:
            with IO_LOCK:  # HDF5 is not thread-safe; the build reads other NetCDF in parallel
                b = read_buoy(p, {**meta, "platform": plat}, now)
        except Exception as e:  # one bad file must not drop the others
            log.warning("buoy %s unreadable: %s", plat, e)
            continue
        if b:
            out.append(b)
    return out


# ------------------------------------------------------------------ registry / assignment
def update_registry(cache: str | None, buoys: list[dict]) -> dict[str, dict]:
    """Known wave buoys (positions persist even when a buoy is silent for a while)."""
    reg: dict[str, dict] = {}
    path = os.path.join(cache, "buoys_registry.json") if cache else None
    if path and os.path.exists(path):
        with open(path) as f:
            reg = json.load(f)
    for b in buoys:
        reg[b["id"]] = {"id": b["id"], "name": b["name"], "lat": b["lat"], "lon": b["lon"], "seen": b["t"]}
    if path:
        os.makedirs(cache, exist_ok=True)
        with open(path, "w") as f:
            json.dump(reg, f, indent=0)
    return reg


def _bearing_km(lat1, lon1, lat2, lon2) -> tuple[float, float]:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return brg, 6371.0 * 2 * math.asin(math.sqrt(min(1.0, a)))


def assign(spot: dict, registry: dict[str, dict], land=None) -> str | None:
    """Nearest buoy ≤60 km whose bearing from the spot is within ±60° of `facing`
    and (if a land mask is given) with no land on the straight line between them."""
    facing = spot["info"].get("facing")
    if facing is None:
        return None
    best, best_km = None, config.BUOY_MAX_KM
    for b in registry.values():
        brg, km = _bearing_km(spot["lat"], spot["lon"], b["lat"], b["lon"])
        if km > best_km:
            continue
        diff = abs((brg - facing + 180) % 360 - 180)
        if diff > config.BUOY_FACING_TOL:
            continue
        if land is not None and land.blocked(spot["lat"], spot["lon"], b["lat"], b["lon"]):
            continue
        best, best_km = b["id"], km
    return best


class LandMask:
    """Coarse land test on the ECMWF 0.1° land-sea mask (cached by the build).

    The first SPOT_SKIP_KM next to the spot (it sits on the coast and 0.1° coastal
    cells are mixed land/sea) and the last 3 km next to the buoy are ignored.
    Coarse: headlands thinner than ~10 km are not seen."""

    SPOT_SKIP_KM = 8.0

    def __init__(self, grid, lsm: np.ndarray):
        self.grid, self.lsm = grid, lsm

    @classmethod
    def load(cls, path: str):
        from .grids import RegularGrid

        if not path or not os.path.exists(path):
            return None
        z = np.load(path)
        a = z["grid"]
        g = RegularGrid(float(a[0]), float(a[1]), int(a[2]), float(a[3]), float(a[4]), int(a[5]), bool(a[6]))
        return cls(g, z["lsm"])

    @staticmethod
    def save(path: str, grid, lsm: np.ndarray) -> None:
        a = np.array([grid.lat0, grid.dlat, grid.nlat, grid.lon0, grid.dlon, grid.nlon, float(grid.global_lon)])
        np.savez_compressed(path, grid=a, lsm=(lsm > 0.5).astype(np.uint8))

    def blocked(self, lat1, lon1, lat2, lon2) -> bool:
        _, km = _bearing_km(lat1, lon1, lat2, lon2)
        n = max(int(km), 2)
        for k in range(n + 1):
            f = k / n
            if f * km < self.SPOT_SKIP_KM or (1 - f) * km < 3.0:
                continue
            lat = lat1 + (lat2 - lat1) * f
            lon = lon1 + (lon2 - lon1) * f
            fi, fj = self.grid.fractional_index(lat, lon)
            i, j = int(round(fi)), int(round(fj))
            if self.grid.global_lon:
                j %= self.grid.nlon
            if 0 <= i < self.grid.nlat and 0 <= j < self.grid.nlon and self.lsm[i, j] > 0.5:
                return True
        return False


def write_latest(out: str, buoys: list[dict], generated: str) -> None:
    os.makedirs(os.path.join(out, "buoys"), exist_ok=True)
    with open(os.path.join(out, "buoys", "latest.json"), "w") as f:
        json.dump({"v": config.SCHEMA_VERSION, "generated": generated, "buoys": buoys}, f,
                  separators=(",", ":"), ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/v1")
    ap.add_argument("--work", default="work")
    ap.add_argument("--cache", default="cache")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    t0 = time.time()
    buoys = collect(args.work, now)
    update_registry(args.cache, buoys)
    write_latest(args.out, buoys, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
    log.info("%d buoys written in %.0f s", len(buoys), time.time() - t0)
    return 0 if buoys else 1


if __name__ == "__main__":
    sys.exit(main())
