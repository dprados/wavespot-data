"""Time interpolation helpers on (nspots, nt) arrays; NaN = missing."""
from __future__ import annotations

import numpy as np


def _bracket(src: np.ndarray, target: np.ndarray, max_gap: float):
    src = np.asarray(src, dtype=np.int64)
    target = np.asarray(target, dtype=np.int64)
    k = np.searchsorted(src, target, side="right") - 1
    exact = (k >= 0) & (k < len(src)) & (src[np.clip(k, 0, len(src) - 1)] == target)
    valid = (k >= 0) & (k < len(src) - 1)
    k0 = np.clip(k, 0, len(src) - 1)
    k1 = np.clip(k + 1, 0, len(src) - 1)
    span = (src[k1] - src[k0]).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(span > 0, (target - src[k0]) / span, 0.0)
    valid &= span <= max_gap
    valid |= exact
    w = np.where(exact, 0.0, w)
    return k0, k1, w, valid


def interp_scalar(src_t, values, target_t, max_gap_h: float = 6.0) -> np.ndarray:
    if values is None or len(src_t) == 0:
        return np.full((0 if values is None else values.shape[0], len(target_t)), np.nan, dtype=np.float32)
    k0, k1, w, valid = _bracket(src_t, target_t, max_gap_h * 3600)
    a = values[:, k0]
    b = values[:, k1]
    out = a + (b - a) * w[None, :]
    exact = valid & (w == 0)
    out = np.where(exact[None, :], a, out)
    out[:, ~valid] = np.nan
    return out.astype(np.float32)


def interp_direction(src_t, deg, target_t, max_gap_h: float = 6.0) -> np.ndarray:
    r = np.radians(deg)
    s = interp_scalar(src_t, np.sin(r), target_t, max_gap_h)
    c = interp_scalar(src_t, np.cos(r), target_t, max_gap_h)
    out = np.degrees(np.arctan2(s, c)) % 360.0
    out[~np.isfinite(s) | ~np.isfinite(c)] = np.nan
    return out.astype(np.float32)


def persist(src_t, values, target_t, max_age_h: float = 96.0) -> np.ndarray:
    """Step-wise: nearest available sample (previous or next), within max_age."""
    out = np.full((values.shape[0], len(target_t)), np.nan, dtype=np.float32)
    src_t = np.asarray(src_t, dtype=np.int64)
    for j, t in enumerate(np.asarray(target_t, dtype=np.int64)):
        d = np.abs(src_t - t)
        order = np.argsort(d, kind="stable")
        for k in order:
            if d[k] > max_age_h * 3600:
                break
            col = values[:, k]
            fill = np.isnan(out[:, j]) & np.isfinite(col)
            out[fill, j] = col[fill]
            if not np.isnan(out[:, j]).any():
                break
    return out


def wind_from_uv(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Speed (m/s) and meteorological direction (° coming from)."""
    ws = np.hypot(u, v)
    wd = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0
    return ws.astype(np.float32), wd.astype(np.float32)
