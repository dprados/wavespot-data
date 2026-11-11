"""Point-on-land check against OSM land polygons (© OpenStreetMap contributors, ODbL).

    python -m wavespot_pipeline.landcheck LAND_SHP [spot files...]

LAND_SHP = land-polygons-split-4326/land_polygons.shp from
https://osmdata.openstreetmap.de/data/land-polygons.html (the `spots.yml`
workflow keeps it in actions/cache). Needs shapely + pyogrio.
A point counts as "on land" when it is inside a land polygon by more than
TOLERANCE_M (coastline precision).
"""
from __future__ import annotations

import math
import sys

import numpy as np

TOLERANCE_M = 25.0
OSM_LAND_URL = "https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip"


def inland_points(shp: str, points: list[tuple[str, float, float]], tolerance_m: float = TOLERANCE_M):
    """Return [(id, metres_inland)] for points inside land by more than tolerance."""
    import pyogrio
    import shapely

    if not points:
        return []
    lats = np.array([p[1] for p in points])
    lons = np.array([p[2] for p in points])
    bbox = (lons.min() - 0.05, lats.min() - 0.05, lons.max() + 0.05, lats.max() + 0.05)
    _, _, geoms, _ = pyogrio.raw.read(shp, bbox=bbox, read_geometry=True, columns=[])
    polys = shapely.from_wkb(geoms)
    tree = shapely.STRtree(polys)
    pts = shapely.points(lons, lats)
    pi, gi = tree.query(pts, predicate="within")
    out = []
    for k in sorted(set(pi.tolist())):
        sid, lat, lon = points[k]
        poly = polys[gi[pi == k][0]]
        d_deg = shapely.distance(pts[k], poly.exterior) if hasattr(poly, "exterior") else 0.0
        metres = d_deg * 111_195 * math.cos(math.radians(lat)) ** 0.5   # rough, between lat/lon scales
        if metres > tolerance_m:
            out.append((sid, round(metres)))
    return out


def main(argv=None) -> int:
    from .spots import load_spots

    args = argv or sys.argv[1:]
    shp, files = args[0], args[1:] or ["data/spots/curated/*.json", "data/seed_spots.json"]
    spots = [s for s in load_spots(files) if s["layer"] == 2]
    bad = inland_points(shp, [(s["id"], s["lat"], s["lon"]) for s in spots])
    for sid, m in bad:
        print(f"{sid}: {m} m inland")
    print(f"{len(bad)} of {len(spots)} layer-2 points on land")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
