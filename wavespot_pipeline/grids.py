"""Regular lat/lon grid helpers and nearest-valid-cell search."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

KM_PER_DEG = 111.195


@dataclass(frozen=True)
class RegularGrid:
    """Regular lat/lon grid; row 0 is `lat0`, column 0 is `lon0`."""
    lat0: float
    dlat: float      # signed (negative when scanning north -> south)
    nlat: int
    lon0: float
    dlon: float
    nlon: int
    global_lon: bool = False   # wraps around 360°

    @property
    def signature(self) -> str:
        return f"{self.lat0:.4f}_{self.dlat:.5f}_{self.nlat}_{self.lon0:.4f}_{self.dlon:.5f}_{self.nlon}"

    def lats(self) -> np.ndarray:
        return self.lat0 + self.dlat * np.arange(self.nlat)

    def lons(self) -> np.ndarray:
        lons = self.lon0 + self.dlon * np.arange(self.nlon)
        return (lons + 180.0) % 360.0 - 180.0

    def fractional_index(self, lat: float, lon: float) -> tuple[float, float]:
        fi = (lat - self.lat0) / self.dlat
        dl = lon - self.lon0
        if self.global_lon:
            dl = dl % 360.0
        else:
            dl = (dl + 180.0) % 360.0 - 180.0 if abs(dl) > 180 else dl
        return fi, dl / self.dlon

    @classmethod
    def from_coords(cls, lats: np.ndarray, lons: np.ndarray) -> "RegularGrid":
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        dlat = float(lats[1] - lats[0]) if len(lats) > 1 else 1.0
        dlon = float(lons[1] - lons[0]) if len(lons) > 1 else 1.0
        return cls(float(lats[0]), dlat, len(lats), float(lons[0]), dlon, len(lons))


def erode_valid(valid: np.ndarray) -> np.ndarray:
    """Cells that are valid AND whose 8 neighbours are valid (≥1 cell off coast)."""
    v = valid.astype(bool)
    out = v.copy()
    padded = np.pad(v, 1, constant_values=False)
    for di in (-1, 0, 1):
        for dj in (-1, 0, 1):
            if di == 0 and dj == 0:
                continue
            out &= padded[1 + di: 1 + di + v.shape[0], 1 + dj: 1 + dj + v.shape[1]]
    return out


def nearest_cell(grid: RegularGrid, masks: list[np.ndarray], lat: float, lon: float,
                 max_km: float) -> tuple[int, int, float] | None:
    """Nearest cell (i, j, km) satisfying the first mask that has a hit within max_km.

    `masks` is an ordered preference list (e.g. [eroded_sea, sea]); each mask has
    shape (nlat, nlon). Returns None if no mask has a cell within max_km.
    """
    fi, fj = grid.fractional_index(lat, lon)
    cell_km_lat = abs(grid.dlat) * KM_PER_DEG
    cell_km_lon = abs(grid.dlon) * KM_PER_DEG * max(math.cos(math.radians(lat)), 0.1)
    ri = int(math.ceil(max_km / cell_km_lat)) + 1
    rj = int(math.ceil(max_km / cell_km_lon)) + 1
    ic, jc = int(round(fi)), int(round(fj))
    i0, i1 = max(ic - ri, 0), min(ic + ri + 1, grid.nlat)
    if i0 >= i1:
        return None
    jj = np.arange(jc - rj, jc + rj + 1)
    if grid.global_lon:
        jj = jj % grid.nlon
    else:
        jj = jj[(jj >= 0) & (jj < grid.nlon)]
    if len(jj) == 0:
        return None
    ii = np.arange(i0, i1)
    clat = grid.lat0 + grid.dlat * ii
    clon = grid.lon0 + grid.dlon * jj
    dlon = ((clon - lon + 180.0) % 360.0) - 180.0
    dy = (clat - lat)[:, None] * KM_PER_DEG
    dx = dlon[None, :] * KM_PER_DEG * math.cos(math.radians(lat))
    dist = np.hypot(dy, dx)
    for mask in masks:
        sub = mask[np.ix_(ii, jj)]
        d = np.where(sub & (dist <= max_km), dist, np.inf)
        k = int(np.argmin(d))
        if np.isfinite(d.flat[k]):
            a, b = divmod(k, len(jj))
            return int(ii[a]), int(jj[b]), float(d.flat[k])
    return None
