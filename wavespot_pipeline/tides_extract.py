"""Extract EOT20 tidal constituents per spot (run once / when spots change).

    python -m wavespot_pipeline.tides_extract --model-dir DIR --spots a.json b.json

DIR must contain `EOT20/ocean_tides/*.nc` (2.1 GB, from SEANOE; the workflow
keeps it in actions/cache so it is downloaded once). Only spots that are new or
moved (>50 m) are computed; the result is merged into
`data/tides/eot20_constituents.json` (a few hundred bytes per spot).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import shutil
import sys
import zipfile

import numpy as np

from . import config
from .spots import load_spots

log = logging.getLogger("wavespot")
DEFAULT_OUT = os.path.join("data", "tides", "eot20_constituents.json")


def load_store(path: str) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"model": "EOT20", "units": {"amp": "m", "phase": "deg Greenwich lag"},
            "reference": "Hart-Davis et al. 2021, doi:10.17882/79489 (CC BY 4.0)", "spots": {}}


def ensure_model(model_dir: str, url: str = config.EOT20_URL) -> None:
    """Download + unzip EOT20 ocean tides if missing (2.3 GB zip)."""
    target = os.path.join(model_dir, "EOT20", "ocean_tides")
    if os.path.isdir(target) and len([f for f in os.listdir(target) if f.endswith(".nc")]) >= 17:
        return
    import requests

    os.makedirs(model_dir, exist_ok=True)
    zpath = os.path.join(model_dir, "eot20.zip")
    log.info("downloading EOT20 from %s", url)
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(zpath, "wb") as f:
            for chunk in r.iter_content(1 << 22):
                f.write(chunk)
    unpack(zpath, model_dir)


def unpack(zpath: str, model_dir: str) -> None:
    target = os.path.join(model_dir, "EOT20", "ocean_tides")
    # The SEANOE archive nests two zips: ocean_tides.zip (needed) and load_tides.zip.
    os.makedirs(target, exist_ok=True)
    inner = os.path.join(model_dir, "ocean_tides.zip")
    with zipfile.ZipFile(zpath) as z:
        name = next(m for m in z.namelist() if m.endswith("ocean_tides.zip"))
        with z.open(name) as src, open(inner, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 22)
    os.remove(zpath)
    zpath = inner
    with zipfile.ZipFile(zpath) as z:
        members = [m for m in z.namelist() if m.endswith(".nc") and "__MACOSX" not in m]
        for m in members:
            with z.open(m) as src, open(os.path.join(target, os.path.basename(m)), "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 22)
    if len([f for f in os.listdir(target) if f.endswith(".nc")]) < 17:
        raise RuntimeError(f"EOT20 archive layout unexpected: {members[:5]}")
    os.remove(zpath)


def extract(model_dir: str, lats: np.ndarray, lons: np.ndarray, cutoff_km: float = 25.0) -> list[dict | None]:
    import pyTMD.io

    m = pyTMD.io.model(model_dir).from_database("EOT20")
    ds = m.open_dataset(group="z")
    x, y = ds.tmd.coords_as(lons, lats, type="trajectory", crs=4326)
    local = ds.tmd.interp(x, y, method="linear", extrapolate=True, cutoff=cutoff_km)
    out = []
    names = list(local.tmd.constituents)
    for i in range(len(lats)):
        cons = {}
        for c in names:
            da = local[c]
            hc = complex(da.values[i]) if da.ndim else complex(da.values)
            units = da.attrs.get("units", "m")
            scale = 0.01 if units == "cm" else 1.0
            amp = abs(hc) * scale
            phase = float(np.degrees(np.arctan2(-hc.imag, hc.real)) % 360.0)
            if not np.isfinite(amp):
                cons = None
                break
            cons[c.upper()] = [round(amp, 4), round(phase, 2)]
        out.append(cons)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", required=True)
    ap.add_argument("--spots", nargs="+",
                    default=["data/spots/curated/*.json", "data/seed_spots.json", "data/spots/layer1.json"])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--download", action="store_true", help="download EOT20 if missing")
    ap.add_argument("--all", action="store_true", help="recompute every spot")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if args.download:
        ensure_model(args.model_dir)
    spots = load_spots(args.spots)
    store = load_store(args.out)
    known = store["spots"]
    todo = []
    for s in spots:
        k = known.get(s["id"])
        if args.all or k is None or abs(k["lat"] - s["lat"]) > 5e-4 or abs(k["lon"] - s["lon"]) > 5e-4:
            todo.append(s)
    log.info("%d spots, %d to extract", len(spots), len(todo))
    if todo:
        lats = np.array([s["lat"] for s in todo])
        lons = np.array([s["lon"] for s in todo])
        res = extract(args.model_dir, lats, lons)
        missing = 0
        for s, cons in zip(todo, res):
            if cons is None:
                missing += 1
            known[s["id"]] = {"lat": s["lat"], "lon": s["lon"], "z0": 0.0, "cons": cons}
        log.info("extracted; %d spots without model data", missing)
    current = {s["id"] for s in spots}
    stale = [k for k in known if k not in current]
    for k in stale:          # renamed or removed spots
        del known[k]
    if stale:
        log.info("pruned %d spots no longer in the catalogue", len(stale))
    if todo or stale:
        store["updated"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    store["spots"] = dict(sorted(known.items()))
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(store, f, separators=(",", ":"), ensure_ascii=False)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
