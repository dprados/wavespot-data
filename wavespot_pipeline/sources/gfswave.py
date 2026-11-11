"""NOAA GFS-Wave (WAVEWATCH III) global 0.16° — swell/wind-sea partitions (public domain).

Primary: NOMADS grib filter with our bbox (~200 KB per step). Fallback per
step: AWS NODD byte ranges taken from the `.idx` sidecar.
Partitions are returned sorted by height: s1 = highest swell, s2 = second.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from .. import config
from ..cells import map_cells
from .base import SourceData, SourceStatus, decode_grib, extract, http_exists, http_get, log, split_grib

# (shortName, level) -> internal name
KEYS = {
    ("shww", 1): "wwh", ("mpww", 1): "wwp", ("wvdir", 1): "wwd",
    ("shts", 1): "sw1h", ("mpts", 1): "sw1p", ("swdir", 1): "sw1d",
    ("shts", 2): "sw2h", ("mpts", 2): "sw2p", ("swdir", 2): "sw2d",
    ("shts", 3): "sw3h", ("mpts", 3): "sw3p", ("swdir", 3): "sw3d",
}
IDX_NAMES = ("HTSGW", "WVHGT", "WVPER", "WVDIR", "SWELL", "SWPER", "SWDIR")


def _file(run: dt.datetime, step: int) -> str:
    return f"gfswave.t{run:%H}z.global.0p16.f{step:03d}.grib2"


def _aws(run: dt.datetime, step: int) -> str:
    return f"{config.GFSWAVE_AWS}/gfs.{run:%Y%m%d}/{run:%H}/wave/gridded/{_file(run, step)}"


def _nomads(run: dt.datetime, step: int) -> str:
    la0, la1, lo0, lo1 = config.GFSWAVE_BBOX
    vars_ = "".join(f"&var_{v}=on" for v in IDX_NAMES)
    return (f"{config.GFSWAVE_NOMADS}?dir=%2Fgfs.{run:%Y%m%d}%2F{run:%H}%2Fwave%2Fgridded&file={_file(run, step)}"
            f"{vars_}&lev_surface=on&lev_1_in_sequence=on&lev_2_in_sequence=on&lev_3_in_sequence=on"
            f"&subregion=&toplat={la1}&leftlon={lo0}&rightlon={lo1}&bottomlat={la0}")


def find_run(now: dt.datetime) -> dt.datetime | None:
    base = now.replace(minute=0, second=0, microsecond=0, hour=(now.hour // 6) * 6)
    for k in range(6):
        run = base - dt.timedelta(hours=6 * k)
        if http_exists(_aws(run, 384) + ".idx"):
            return run
    return None


def parse_idx(text: str) -> list[tuple[int, int, str, str]]:
    """NCEP `.idx` -> [(start, end_inclusive_or_-1, VAR, level)]."""
    rows = []
    lines = [l for l in text.splitlines() if l.strip()]
    for k, line in enumerate(lines):
        parts = line.split(":")
        start = int(parts[1])
        end = int(lines[k + 1].split(":")[1]) - 1 if k + 1 < len(lines) else -1
        rows.append((start, end, parts[3], parts[4]))
    return rows


def _aws_bytes(run: dt.datetime, step: int) -> bytes:
    rows = parse_idx(http_get(_aws(run, step) + ".idx").decode())
    wanted = [r for r in rows if r[2] in IDX_NAMES]
    lo = min(r[0] for r in wanted)
    hi_rows = [r[1] for r in wanted]
    hi = -1 if -1 in hi_rows else max(hi_rows)
    rng = (lo, hi) if hi >= 0 else None
    if rng is None:
        return http_get(_aws(run, step), (lo, 10**12))
    return http_get(_aws(run, step), rng)


def decode_partitions(data: bytes, cells_for_grid) -> tuple[int, dict[str, np.ndarray]]:
    """Decode a multi-message GRIB blob into {name: (nspots,)} at its valid time."""
    out: dict[str, np.ndarray] = {}
    vt = None
    fields = [decode_grib(m) for m in split_grib(data)]
    mask_field = next((f for f in fields if f.short_name == "swh"), None)
    if mask_field is None:
        raise ValueError("HTSGW (land mask) missing")
    cells = cells_for_grid(mask_field)
    for fld in fields:
        name = KEYS.get((fld.short_name, fld.level))
        if name is None:
            continue
        vt = fld.valid_time
        out[name] = extract(fld.values, cells)
    if vt is None:
        raise ValueError("no wave partition in GRIB")
    return vt, out


def sort_swells(raw: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Sort the 3 swell partitions by height (NaN last) -> s1/s2 + wind sea."""
    h = np.stack([raw[f"sw{k}h"] for k in (1, 2, 3)])        # (3, nspots, nt)
    p = np.stack([raw[f"sw{k}p"] for k in (1, 2, 3)])
    d = np.stack([raw[f"sw{k}d"] for k in (1, 2, 3)])
    key = np.where(np.isfinite(h), h, -1.0)
    order = np.argsort(-key, axis=0, kind="stable")
    take = lambda a, k: np.take_along_axis(a, order[k:k + 1], axis=0)[0]  # noqa: E731
    return {"s1h": take(h, 0), "s1p": take(p, 0), "s1d": take(d, 0),
            "s2h": take(h, 1), "s2p": take(p, 1), "s2d": take(d, 1),
            "wwh": raw["wwh"], "wwp": raw["wwp"], "wwd": raw["wwd"]}


def fetch(spots: list[dict], now: dt.datetime, h_start: dt.datetime, cache_dir: str | None, workers: int = 4):
    t0 = time.time()
    nspots = len(spots)
    run = find_run(now)
    if run is None:
        return None, SourceStatus("gfs-wave", False, time.time() - t0, "no complete run found")
    run_s = run.strftime("%Y-%m-%dT%HZ")
    log.info("GFS-Wave run %s", run_s)
    end = h_start + dt.timedelta(hours=config.H_HOURS + config.H3_STEP * config.H3_N)
    first = max(0, int((h_start - run).total_seconds() // 3600))
    first -= first % 3
    last = min(384, int((end - run).total_seconds() // 3600))
    steps = list(range(first, last + 1, 3))

    cache: dict[str, np.ndarray] = {}

    def cells_for(fld):
        key = fld.grid.signature
        if key not in cache:
            valid = np.isfinite(fld.values)   # HTSGW: defined at every sea cell
            cache[key], _ = map_cells("gfswave2_" + hashlib.md5(key.encode()).hexdigest()[:8], fld.grid,
                                      [valid], spots, 40.0, cache_dir)
        return cache[key]

    per_t: dict[int, dict[str, np.ndarray]] = {}
    nbytes = 0
    failures = 0
    nomads_fail = 0

    def work(step):
        nonlocal nomads_fail
        try:
            data = http_get(_nomads(run, step), timeout=90)
            if not data.startswith(b"GRIB"):
                raise ValueError("NOMADS returned non-GRIB")
        except Exception:
            nomads_fail += 1
            data = _aws_bytes(run, step)
        return len(data), data

    # Decode in the main thread (eccodes + shared cell cache), download in parallel.
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(work, st): st for st in steps}
        for f in as_completed(futs):
            try:
                n, data = f.result()
                vt, vals = decode_partitions(data, cells_for)
            except Exception as e:
                failures += 1
                log.warning("GFS-Wave step %s failed: %s", futs[f], e)
                continue
            nbytes += n
            per_t[vt] = vals
    if not per_t:
        return None, SourceStatus("gfs-wave", False, time.time() - t0, "no step decoded", nbytes, run_s)
    times = np.array(sorted(per_t), dtype=np.int64)
    raw = {}
    for name in KEYS.values():
        arr = np.full((nspots, len(times)), np.nan, dtype=np.float32)
        for k, t in enumerate(times):
            v = per_t[int(t)].get(name)
            if v is not None:
                arr[:, k] = v
        raw[name] = arr
    fields = sort_swells(raw)
    covered = np.isfinite(fields["wwh"]).any(axis=1) | np.isfinite(fields["s1h"]).any(axis=1)
    detail = f"{len(steps) - failures}/{len(steps)} steps, nomads fallbacks {nomads_fail}"
    return (SourceData("gfs-wave", times, fields, covered, {"run": run_s}),
            SourceStatus("gfs-wave", failures < len(steps) * 0.1, time.time() - t0, detail, nbytes, run_s))
