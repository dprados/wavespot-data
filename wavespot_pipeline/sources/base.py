"""Shared plumbing for sources: result container, HTTP, GRIB decoding."""
from __future__ import annotations

import logging
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable, Iterator

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..grids import RegularGrid

log = logging.getLogger("wavespot")

USER_AGENT = "wavespot-data-pipeline/1 (+https://github.com/dprados/wavespot-data)"


@dataclass
class SourceData:
    """Per-spot time series from one source on its native time axis.

    times: int64 UNIX seconds (nt,). fields: name -> float array (nspots, nt), NaN = missing.
    `covered`: bool (nspots,) — spots for which this source produced data.
    """
    name: str
    times: np.ndarray
    fields: dict[str, np.ndarray]
    covered: np.ndarray
    meta: dict = field(default_factory=dict)


@dataclass
class SourceStatus:
    name: str
    ok: bool
    seconds: float
    detail: str = ""
    bytes: int = 0
    run: str | None = None

    def as_json(self) -> dict:
        d = {"ok": self.ok, "seconds": round(self.seconds, 1), "detail": self.detail[:300],
             "mb": round(self.bytes / 1e6, 1)}
        if self.run:
            d["run"] = self.run
        return d


_local = threading.local()
# ecCodes and HDF5 are not reliably thread-safe: serialise decoding, keep downloads parallel.
IO_LOCK = threading.RLock()


def session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "HEAD"))
        adapter = HTTPAdapter(max_retries=retry, pool_connections=32, pool_maxsize=32)
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        s.headers["User-Agent"] = USER_AGENT
        _local.session = s
    return s


def http_get(url: str, byte_range: tuple[int, int] | None = None, timeout: float = 60.0) -> bytes:
    headers = {}
    if byte_range is not None:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    for attempt in range(3):
        try:
            r = session().get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 + 3 * attempt)
    raise RuntimeError("unreachable")


def http_exists(url: str, timeout: float = 20.0) -> bool:
    try:
        r = session().head(url, timeout=timeout, allow_redirects=True)
        return r.status_code == 200
    except requests.RequestException:
        return False


# ------------------------------------------------------------------ GRIB
def split_grib(data: bytes) -> Iterator[bytes]:
    """Split a concatenation of GRIB1/2 messages into individual messages."""
    pos = 0
    n = len(data)
    while True:
        start = data.find(b"GRIB", pos)
        if start < 0 or start + 16 > n:
            return
        edition = data[start + 7]
        if edition == 2:
            length = struct.unpack(">Q", data[start + 8:start + 16])[0]
        else:
            length = int.from_bytes(data[start + 4:start + 7], "big")
        if length <= 0 or start + length > n:
            return
        yield data[start:start + length]
        pos = start + length


@dataclass
class GribField:
    short_name: str
    level: int
    step_hours: int
    valid_time: int        # UNIX seconds
    grid: RegularGrid
    values: np.ndarray     # (nlat, nlon) float32, NaN = missing


def peek_grib(message: bytes) -> str:
    """shortName of a GRIB message without decoding its values."""
    import eccodes

    with IO_LOCK:
        h = eccodes.codes_new_from_message(message)
        try:
            return eccodes.codes_get(h, "shortName")
        finally:
            eccodes.codes_release(h)


def decode_grib(message: bytes) -> GribField:
    with IO_LOCK:
        return _decode_grib(message)


def _decode_grib(message: bytes) -> GribField:
    import eccodes

    h = eccodes.codes_new_from_message(message)
    try:
        g = lambda k: eccodes.codes_get(h, k)  # noqa: E731
        ni, nj = g("Ni"), g("Nj")
        lat0 = g("latitudeOfFirstGridPointInDegrees")
        lon0 = g("longitudeOfFirstGridPointInDegrees")
        di = g("iDirectionIncrementInDegrees")
        dj = g("jDirectionIncrementInDegrees")
        jpos = g("jScansPositively")
        dlat = dj if jpos else -dj
        global_lon = abs(ni * di - 360.0) < 1e-3
        grid = RegularGrid(float(lat0), float(dlat), int(nj), float(lon0), float(di), int(ni), global_lon)
        vals = eccodes.codes_get_values(h).astype(np.float32)
        if g("bitmapPresent"):
            miss = g("missingValue")
            vals[vals == miss] = np.nan
        try:
            level = int(g("level"))
        except Exception:  # pragma: no cover
            level = 0
        vdate, vtime = g("validityDate"), g("validityTime")
        import datetime as dt
        valid = dt.datetime(vdate // 10000, vdate // 100 % 100, vdate % 100, vtime // 100, vtime % 100,
                            tzinfo=dt.timezone.utc)
        try:
            eccodes.codes_set(h, "stepUnits", "h")
            step = int(eccodes.codes_get_long(h, "endStep"))
        except Exception:  # informative only; valid_time is what we use
            step = -1
        return GribField(g("shortName"), level, step, int(valid.timestamp()), grid,
                         vals.reshape(nj, ni))
    finally:
        eccodes.codes_release(h)


def extract(values: np.ndarray, cells: np.ndarray) -> np.ndarray:
    """values (nlat, nlon); cells (nspots, 2) int with -1 for 'no cell' -> (nspots,)."""
    out = np.full(len(cells), np.nan, dtype=np.float32)
    ok = cells[:, 0] >= 0
    if ok.any():
        out[ok] = values[cells[ok, 0], cells[ok, 1]]
    return out


def stack_times(per_time: dict[int, dict[str, np.ndarray]], names: Iterable[str], nspots: int):
    """{time: {name: (nspots,)}} -> (times, {name: (nspots, nt)})."""
    times = np.array(sorted(per_time), dtype=np.int64)
    fields = {}
    for name in names:
        arr = np.full((nspots, len(times)), np.nan, dtype=np.float32)
        for k, t in enumerate(times):
            v = per_time[int(t)].get(name)
            if v is not None:
                arr[:, k] = v
        fields[name] = arr
    return times, fields
