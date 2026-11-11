"""Exposure-window orientation (see docs/research-raw/spots.md section 7).

For a point near the coast:
  1. candidates = coastline samples within R (default 600 m) offset CAND_OFFSET_M seaward
     (+ the point itself if it is in the water);
  2. from each candidate cast rays every RAY_STEP_DEG degrees, RAY_LEN_M long; a ray is open
     if it does not touch land (OSM land polygons, islets < MIN_ISLAND_KM2 ignored);
  3. keep the candidate with the widest contiguous open arc (the most exposed water point);
  4. window = [first, last] open bearing (clockwise) of that arc;
  5. facing = half-way between the arc centre and the local seaward coast normal (coast within
     NORMAL_RADIUS_M of the chosen origin), the normal being clamped to stay NORMAL_MARGIN_DEG
     inside the arc. The pure arc centre is biased when the coast curves within 20 km; the pure
     normal fails in rias and on headlands. The blend scored best on the reference set
     (see tests/test_orientation.py).
"""
import math
import os
import sys

import numpy as np
import shapely
from shapely.geometry import Point, box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

KY = 110540.0
BEARINGS = np.arange(0, 360, config.RAY_STEP_DEG)
_SIN = np.sin(np.radians(BEARINGS))
_COS = np.cos(np.radians(BEARINGS))


def _kx(lat):
    return 111320.0 * math.cos(math.radians(lat))


def largest_arc(open_mask):
    """(width_deg, start_idx, n_open) of the largest contiguous open arc on a circular mask."""
    n = len(open_mask)
    if open_mask.all():
        return 360, 0, n
    if not open_mask.any():
        return 0, None, 0
    # rotate so that index 0 is closed
    first_closed = int(np.argmin(open_mask))
    rot = np.roll(open_mask, -first_closed)
    best_len, best_start, cur, start = 0, None, 0, 0
    for i, v in enumerate(rot):
        if v:
            if cur == 0:
                start = i
            cur += 1
            if cur > best_len:
                best_len, best_start = cur, start
        else:
            cur = 0
    return best_len * config.RAY_STEP_DEG, (best_start + first_closed) % n, best_len


def angdiff(a, b):
    """Signed smallest difference a-b in degrees (-180, 180]."""
    return (a - b + 180) % 360 - 180


def blend_facing(centre, a0, a1, normal):
    if normal is None:
        return centre
    half = ((a1 - a0) % 360) / 2
    lim = max(half - config.NORMAL_MARGIN_DEG, 0)
    d = max(-lim, min(lim, angdiff(normal, centre)))
    return int(round(centre + config.NORMAL_WEIGHT * d)) % 360


def arc_to_facing_window(start, n_open):
    step = config.RAY_STEP_DEG
    if n_open >= len(BEARINGS):
        return None, [0, 360]
    a0 = start * step
    a1 = (start + n_open - 1) * step
    centre = (a0 + (n_open - 1) * step / 2) % 360
    return int(round(centre)) % 360, [int(a0 % 360), int(a1 % 360)]


class Orienter:
    def __init__(self, land):
        self.land = land
        shapely.prepare(land.pieces)

    def _land_near(self, lat, lon, radius_m):
        kx = _kx(lat)
        dlon, dlat = radius_m / kx, radius_m / KY
        idx = self.land.piece_tree.query(box(lon - dlon, lat - dlat, lon + dlon, lat + dlat))
        return self.land.pieces[idx]

    def _on_land(self, pieces, lons, lats):
        pts = shapely.points(lons, lats)
        res = np.zeros(len(pts), bool)
        for p in pieces:
            res |= shapely.intersects(p, pts)
        return res

    def coast_normal(self, lat, lon, r):
        """Seaward normal (deg) of the coastline within r metres (land is left of the lines)."""
        kx = _kx(lat)
        idx = self.land.coast_tree.query(
            box(lon - (r + 50) / kx, lat - (r + 50) / KY, lon + (r + 50) / kx, lat + (r + 50) / KY))
        if len(idx) == 0:
            return None
        loc = shapely.transform(self.land.coast[idx],
                                lambda c: np.column_stack(((c[:, 0] - lon) * kx, (c[:, 1] - lat) * KY)))
        clip = shapely.intersection(loc, Point(0, 0).buffer(r, 32))
        sx = sy = 0.0
        for g in shapely.get_parts(clip):
            if g.geom_type != "LineString" or g.is_empty:
                continue
            c = shapely.get_coordinates(g)
            sx += c[-1, 1] - c[0, 1]
            sy += -(c[-1, 0] - c[0, 0])
        if sx == 0 and sy == 0:
            return None
        return math.degrees(math.atan2(sx, sy)) % 360

    def candidates(self, lat, lon, radius_m=None):
        """Water candidate origins (lon, lat arrays) near the point and their distance (m)."""
        kx = _kx(lat)
        coast_idx = self.land.coast_tree.query(
            box(lon - 2000 / kx, lat - 2000 / KY, lon + 2000 / kx, lat + 2000 / KY))
        if len(coast_idx) == 0:
            return None
        lines = self.land.coast[coast_idx]
        # local metric frame
        loc = shapely.transform(lines, lambda c: np.column_stack(((c[:, 0] - lon) * kx, (c[:, 1] - lat) * KY)))
        dists = shapely.distance(loc, Point(0, 0))
        dmin = float(dists.min())
        R = radius_m or max(config.CAND_RADIUS_M, dmin + 300)
        if dmin > 1800:
            return None
        clip = shapely.intersection(loc, Point(0, 0).buffer(R, 32))
        parts = [g for g in shapely.get_parts(clip) if g.geom_type == "LineString" and g.length > 0]
        total = sum(g.length for g in parts)
        if total == 0:
            return None
        spacing = max(40.0, total / config.MAX_CANDS)
        xs, ys = [], []
        for g in parts:
            L = g.length
            n = max(1, int(L // spacing))
            ss = (np.arange(n) + 0.5) * L / n
            p = shapely.line_interpolate_point(g, ss)
            pa = shapely.line_interpolate_point(g, np.clip(ss - 75, 0, L))
            pb = shapely.line_interpolate_point(g, np.clip(ss + 75, 0, L))
            P = shapely.get_coordinates(p)
            A = shapely.get_coordinates(pa)
            B = shapely.get_coordinates(pb)
            d = B - A
            nrm = np.hypot(d[:, 0], d[:, 1])
            ok = nrm > 1
            # land on the left -> seaward normal is (dy, -dx)
            nx, ny = d[ok, 1] / nrm[ok], -d[ok, 0] / nrm[ok]
            off = config.CAND_OFFSET_M
            xs.append(np.concatenate([P[ok, 0] + nx * off, P[ok, 0] - nx * off]))
            ys.append(np.concatenate([P[ok, 1] + ny * off, P[ok, 1] - ny * off]))
        xs = np.concatenate(xs + [np.array([0.0])])
        ys = np.concatenate(ys + [np.array([0.0])])
        lons = lon + xs / kx
        lats = lat + ys / KY
        pieces = self._land_near(lat, lon, R + 500)
        water = ~self._on_land(pieces, lons, lats)
        if not water.any():
            return None
        return lons[water], lats[water], np.hypot(xs, ys)[water], dmin

    def orient(self, lat, lon, radius_m=None):
        c = self.candidates(lat, lon, radius_m)
        if c is None:
            return None
        clons, clats, cdist, dmin = c
        kx = _kx(lat)
        L = config.RAY_LEN_M
        n = len(clons)
        ex = clons[:, None] + (L * _SIN)[None, :] / kx
        ey = clats[:, None] + (L * _COS)[None, :] / KY
        coords = np.empty((n * len(BEARINGS), 2, 2))
        coords[:, 0, 0] = np.repeat(clons, len(BEARINGS))
        coords[:, 0, 1] = np.repeat(clats, len(BEARINGS))
        coords[:, 1, 0] = ex.ravel()
        coords[:, 1, 1] = ey.ravel()
        rays = shapely.linestrings(coords)
        blocked = np.zeros(len(rays), bool)
        for p in self._land_near(lat, lon, L + 2500):
            blocked |= shapely.intersects(p, rays)
        open_ = ~blocked.reshape(n, len(BEARINGS))
        best = None
        for k in range(n):
            w, s, no = largest_arc(open_[k])
            key = (w, -cdist[k])
            if best is None or key > best[0]:
                best = (key, k, s, no)
        (w, _), k, s, no = best
        if w == 0:
            return {"facing": None, "window": None, "width": 0, "coast_m": round(dmin)}
        centre, window = arc_to_facing_window(s, no)
        normal = self.coast_normal(float(clats[k]), float(clons[k]), config.NORMAL_RADIUS_M)
        if centre is None:  # fully open (islet in open sea): use the coast normal
            facing = int(round(normal or 0)) % 360
        else:
            facing = blend_facing(centre, window[0], window[1], normal)
        return {"facing": facing, "window": window, "width": w, "coast_m": round(dmin),
                "arc_centre": centre, "normal": None if normal is None else int(round(normal)) % 360,
                "origin": [round(float(clats[k]), 5), round(float(clons[k]), 5)]}
