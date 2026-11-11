"""Land/coastline model built from OSM land polygons (osmdata.openstreetmap.de, ODbL).

`build_land_cache(shp)` reads land-polygons-split-4326 for the scope boxes and writes
CACHE/land.pkl with:
  pieces : split land polygons (lon/lat), minus pieces belonging to islets < MIN_ISLAND_KM2
  coast  : coastline LineString chunks (lon/lat), boundaries of the merged land, clipped to
           the land boxes, <= ~60 vertices each (good for STRtree)
  parts_area_km2 / coast_part_area : area of the land part each coast chunk belongs to
"""
import math
import os
import pickle
import sys
import time

import numpy as np
import shapefile
import shapely
from shapely.geometry import box, LineString

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

LAND_PKL = os.path.join(config.CACHE, "land.pkl")


def area_km2(geoms):
    """Approximate area in km2 of lon/lat geometries (equirectangular at centroid lat)."""
    a = shapely.area(geoms)
    lat = shapely.get_coordinates(shapely.centroid(geoms))[:, 1]
    return a * 111.32 * 110.54 * np.cos(np.radians(lat))


def build_land_cache(shp):
    t0 = time.time()
    r = shapefile.Reader(shp)
    boxes = [box(w, s, e, n) for s, w, n, e in config.LAND_BOXES]
    allb = shapely.union_all(boxes)
    shapely.prepare(allb)
    pieces = []
    for sh in r.iterShapes():
        bb = sh.bbox
        if not shapely.intersects(allb, box(*bb)):
            continue
        pieces.append(shapely.geometry.shape(sh.__geo_interface__))
    pieces = np.array(pieces, dtype=object)
    print(f"land pieces: {len(pieces)} ({time.time()-t0:.0f}s)", flush=True)

    # Merge pieces into real land masses (pieces overlap slightly along the split grid).
    merged = shapely.union_all(pieces, grid_size=1e-7)
    parts = np.array(shapely.get_parts(merged), dtype=object)
    parts_area = area_km2(parts)
    print(f"land parts: {len(parts)}; merge {time.time()-t0:.0f}s", flush=True)

    # Drop pieces that lie inside tiny islets/rocks for ray casting.
    small = parts[parts_area < config.MIN_ISLAND_KM2]
    keep = np.ones(len(pieces), bool)
    if len(small):
        st = shapely.STRtree(small)
        rp = shapely.point_on_surface(pieces)
        hit = st.query(rp, predicate="intersects")
        keep[np.unique(hit[0])] = False
    pieces_ray = pieces[keep]

    # Coastline chunks, clipped to the boxes, oriented with land on the left.
    coast, coast_area = [], []
    for p, a in zip(parts, parts_area):
        p = shapely.geometry.polygon.orient(p, sign=1.0)
        rings = [p.exterior, *p.interiors]
        for ring in rings:
            ln = LineString(ring.coords)
            if not allb.intersects(ln):
                continue
            ln = shapely.intersection(ln, allb)
            for seg in shapely.get_parts(shapely.line_merge(ln) if ln.geom_type == "MultiLineString" else ln):
                cs = shapely.get_coordinates(seg)
                for i in range(0, len(cs) - 1, 60):
                    ch = cs[i:i + 61]
                    if len(ch) >= 2:
                        coast.append(LineString(ch))
                        coast_area.append(a)
    print(f"coast chunks: {len(coast)}; total {time.time()-t0:.0f}s", flush=True)
    data = {"pieces": pieces_ray, "coast": np.array(coast, dtype=object),
            "coast_area": np.array(coast_area)}
    with open(LAND_PKL, "wb") as f:
        pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)


class Land:
    """Spatial indices over land pieces and coastline (lon/lat)."""

    def __init__(self, path=LAND_PKL):
        with open(path, "rb") as f:
            d = pickle.load(f)
        self.pieces = d["pieces"]
        self.coast = d["coast"]
        self.coast_area = d["coast_area"]
        self.piece_tree = shapely.STRtree(self.pieces)
        self.coast_tree = shapely.STRtree(self.coast)

    def coast_distance_m(self, lats, lons):
        """Distance (m) from each point to the nearest coastline chunk."""
        pts = shapely.points(np.asarray(lons), np.asarray(lats))
        idx = self.coast_tree.nearest(pts)
        out = np.empty(len(pts))
        for k, (p, i) in enumerate(zip(pts, idx)):
            lat = p.y
            kx = 111320 * math.cos(math.radians(lat))
            g = self.coast[i]
            # local metric distance
            c = shapely.get_coordinates(g)
            loc = LineString(np.column_stack(((c[:, 0] - p.x) * kx, (c[:, 1] - p.y) * 110540)))
            out[k] = shapely.distance(loc, shapely.Point(0, 0))
        # nearest() is in degrees; refine by checking neighbours within a small box
        return out

    def on_land(self, lats, lons):
        pts = shapely.points(np.asarray(lons), np.asarray(lats))
        hit = self.piece_tree.query(pts, predicate="intersects")
        res = np.zeros(len(pts), bool)
        res[np.unique(hit[0])] = True
        return res


if __name__ == "__main__":
    build_land_cache(sys.argv[1])
