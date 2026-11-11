"""Spot -> grid cell mapping with an on-disk cache (persisted by actions/cache)."""
from __future__ import annotations

import json
import os
from typing import Callable, Sequence

import numpy as np

from .grids import RegularGrid, nearest_cell


def map_cells(key: str, grid: RegularGrid, masks: Callable[[], list[np.ndarray]] | list[np.ndarray],
              spots: Sequence[dict], max_km: float, cache_dir: str | None) -> tuple[np.ndarray, np.ndarray]:
    """Return (cells (n,2) int, km (n,) float) for each spot; -1 when no valid cell.

    The mask list is only materialised if at least one spot is not cached.
    """
    path = os.path.join(cache_dir, f"cells_{key}.json") if cache_dir else None
    cache: dict = {}
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                blob = json.load(f)
            if blob.get("grid") == grid.signature and blob.get("max_km") == max_km:
                cache = blob.get("spots", {})
        except (OSError, ValueError):
            cache = {}
    cells = np.full((len(spots), 2), -1, dtype=np.int64)
    km = np.full(len(spots), np.nan)
    resolved_masks = None
    changed = False
    for n, s in enumerate(spots):
        c = cache.get(s["id"])
        if c and abs(c[0] - s["lat"]) < 1e-6 and abs(c[1] - s["lon"]) < 1e-6:
            cells[n] = (c[2], c[3])
            km[n] = c[4] if c[4] is not None else np.nan
            continue
        if resolved_masks is None:
            resolved_masks = masks() if callable(masks) else masks
        hit = nearest_cell(grid, resolved_masks, s["lat"], s["lon"], max_km)
        if hit is not None:
            cells[n] = hit[:2]
            km[n] = hit[2]
        cache[s["id"]] = [s["lat"], s["lon"], int(cells[n, 0]), int(cells[n, 1]),
                          None if not np.isfinite(km[n]) else round(float(km[n]), 3)]
        changed = True
    if path and changed:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path, "w") as f:
            json.dump({"grid": grid.signature, "max_km": max_km, "spots": cache}, f)
    return cells, km
