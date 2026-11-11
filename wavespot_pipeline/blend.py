"""Blend sources into the per-spot `h` (hourly, IBI) and `h3` (3-hourly, ECMWF) series.

Waves  h : IBI hourly -> per-hour fallback ECMWF (+ GFS-Wave partitions rescaled to ECMWF Hs)
           -> GFS-Wave alone.
Waves h3 : ECMWF (+ GFS partitions) with a 24 h ramp that carries the IBI/ECMWF Hs ratio
           of the last 12 h of `h` into `h3` (no jump at the hand-over) -> GFS alone.
Wind   h : AROME (FR + north ES, 0-48 h) > ICON-EU (0-120 h) > ECMWF, 6 h cross-fades.
Wind  h3 : ECMWF.  t2: ECMWF.  SST: IBI daily -> OISST, held constant.
"""
from __future__ import annotations

import datetime as dt
import warnings
from dataclasses import dataclass, field

import numpy as np

from . import config
from .sources.base import SourceData
from .timeseries import interp_direction, interp_scalar, persist, wind_from_uv

WAVE_FIELDS = ["hs", "tp", "dir", "s1h", "s1p", "s1d", "s2h", "s2p", "s2d", "wwh", "wwp", "wwd"]
PART_H = ["s1h", "s2h", "wwh"]
DIR_FIELDS = {"dir", "s1d", "s2d", "wwd", "wd"}  # interpolated as unit vectors
SST_MAX_AGE_H = 24 * 16


@dataclass
class Sources:
    ibi: SourceData | None = None
    ecmwf_wave: SourceData | None = None
    ecmwf_wind: SourceData | None = None
    icon: SourceData | None = None
    arome: SourceData | None = None
    gfs: SourceData | None = None
    sst_ibi: SourceData | None = None
    sst_oisst: SourceData | None = None
    buoys: list | None = None      # latest observations (not blended)


@dataclass
class Blended:
    h: dict[str, np.ndarray]          # field -> (nspots, 216)
    h3: dict[str, np.ndarray]         # field -> (nspots, 48)
    models: list[dict] = field(default_factory=list)


def target_times(h_start: dt.datetime) -> tuple[np.ndarray, np.ndarray]:
    t0 = int(h_start.timestamp())
    th = t0 + 3600 * np.arange(config.H_HOURS, dtype=np.int64)
    th3 = t0 + 3600 * (config.H_HOURS + config.H3_STEP * np.arange(config.H3_N, dtype=np.int64))
    return th, th3


def _on(src: SourceData | None, name: str, target: np.ndarray, nspots: int, max_gap_h: float) -> np.ndarray:
    if src is None or name not in src.fields:
        return np.full((nspots, len(target)), np.nan, dtype=np.float32)
    fn = interp_direction if name in DIR_FIELDS else interp_scalar
    return fn(src.times, src.fields[name], target, max_gap_h)


def _gfs_total(gfs_on: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Total sea from GFS partitions when no other total is available."""
    hs2 = np.zeros_like(gfs_on["s1h"])
    for p in PART_H:
        hs2 += np.nan_to_num(gfs_on[p]) ** 2
    hs = np.sqrt(hs2)
    stack_h = np.stack([np.nan_to_num(gfs_on[p], nan=-1) for p in PART_H])
    k = np.argmax(stack_h, axis=0)
    tp = np.choose(k, [gfs_on["s1p"], gfs_on["s2p"], gfs_on["wwp"]])
    dr = np.choose(k, [gfs_on["s1d"], gfs_on["s2d"], gfs_on["wwd"]])
    none = ~np.isfinite(gfs_on["s1h"]) & ~np.isfinite(gfs_on["wwh"])
    hs[none] = np.nan
    return {"hs": hs.astype(np.float32), "tp": tp, "dir": dr}


def _rescale_parts(parts: dict[str, np.ndarray], hs: np.ndarray) -> dict[str, np.ndarray]:
    """Scale GFS partition heights so their combined energy matches `hs`."""
    e = np.zeros_like(hs)
    for p in PART_H:
        e += np.nan_to_num(parts[p]) ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(e > 0, hs / np.sqrt(e), np.nan)
    k = np.clip(k, 0.5, 2.0)
    out = dict(parts)
    for p in PART_H:
        out[p] = parts[p] * k
    return out


def _waves(src: Sources, target: np.ndarray, nspots: int, use_ibi: bool):
    """Returns (fields, model_name per spot) for one time axis."""
    out = {f: np.full((nspots, len(target)), np.nan, dtype=np.float32) for f in WAVE_FIELDS}
    model = np.array([None] * nspots, dtype=object)
    gfs_on = {f: _on(src.gfs, f, target, nspots, 6.0) for f in WAVE_FIELDS[3:]}
    ec = {f: _on(src.ecmwf_wave, f, target, nspots, 6.0) for f in ("hs", "tp", "dir")}
    gfs_tot = _gfs_total(gfs_on) if src.gfs is not None else None

    layers = []
    if use_ibi and src.ibi is not None:
        layers.append(("ibi", {f: _on(src.ibi, f, target, nspots, 1.5) for f in WAVE_FIELDS}))
    if src.ecmwf_wave is not None:
        fb = dict(ec)
        if src.gfs is not None:
            fb.update(_rescale_parts(gfs_on, ec["hs"]))
        else:
            fb.update({f: np.full_like(ec["hs"], np.nan) for f in WAVE_FIELDS[3:]})
        layers.append(("ecmwf", fb))
    if gfs_tot is not None:
        layers.append(("gfs", {**gfs_on, **gfs_tot}))

    filled = np.zeros((nspots, len(target)), bool)
    counts = {}
    for name, fields in layers:
        take = ~filled & np.isfinite(fields["hs"])
        for f in WAVE_FIELDS:
            out[f] = np.where(take, fields[f], out[f])
        filled |= take
        counts[name] = take.sum(axis=1)
    for i in range(nspots):
        best = max(counts.items(), key=lambda kv: kv[1][i], default=(None, [0]))
        if best[0] is not None and best[1][i] > 0:
            model[i] = best[0]
    return out, model, ec


def _hs_ratio(a: np.ndarray, b: np.ndarray, cols: slice) -> np.ndarray:
    """Ratio of means a/b per spot over `cols` where both are present (NaN if none)."""
    both = np.isfinite(a[:, cols]) & np.isfinite(b[:, cols])
    sa = np.where(both, a[:, cols], 0.0).sum(axis=1)
    sb = np.where(both, b[:, cols], 0.0).sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where((both.sum(axis=1) >= 6) & (sb > 0.05), sa / sb, np.nan)


def _ramp(h: dict, h3: dict, ec_on_h: np.ndarray, model_h, model_h3):
    """Coastal correction of the ECMWF tail.

    ECMWF wet cells can sit far offshore (0.1° grid), so its Hs is biased against
    the coastal IBI cell. k_all = IBI/ECMWF Hs over the whole `h` overlap is kept
    as a persistent factor in `h3`; the first 24 h of `h3` ramp from the ratio of
    the last 12 h of `h` (no jump at the hand-over) to k_all. Both clamped to
    [0.3, 1.5]. Applied to Hs and partition heights.
    """
    k_all = _hs_ratio(h["hs"], ec_on_h, slice(0, config.H_HOURS))
    k_end = _hs_ratio(h["hs"], ec_on_h, slice(config.H_HOURS - 12, config.H_HOURS))
    k_end = np.where(np.isfinite(k_end), k_end, k_all)
    k_all = np.clip(np.nan_to_num(k_all, nan=1.0), 0.3, 1.5)
    k_end = np.clip(np.nan_to_num(k_end, nan=1.0), 0.3, 1.5)
    hours_into = config.H3_STEP * (np.arange(config.H3_N) + 1)
    w = np.clip(1.0 - hours_into / 24.0, 0.0, 1.0)
    apply = np.array([mh == "ibi" and m3 == "ecmwf" for mh, m3 in zip(model_h, model_h3)])
    factor = k_end[:, None] * w[None, :] + k_all[:, None] * (1.0 - w[None, :])
    factor[~apply] = 1.0
    for f in ["hs"] + PART_H:
        h3[f] = h3[f] * factor


def _overlay(base_u, base_v, base_g, src: SourceData, target, nspots, model, name, max_gap_h):
    """Overlay a higher-resolution wind source on (u, v, gust), cross-fading over
    6 h at both ends of its coverage so there is no jump at the hand-over."""
    iu = _on(src, "u10", target, nspots, max_gap_h)
    iv = _on(src, "v10", target, nspots, max_gap_h)
    ig = _on(src, "gust", target, nspots, max_gap_h)
    u, v, g = base_u.copy(), base_v.copy(), base_g.copy()
    for i in range(nspots):
        ok = np.isfinite(iu[i]) & np.isfinite(iv[i])
        if not ok.any():
            continue
        first = int(np.nonzero(ok)[0].min())
        last = int(np.nonzero(ok)[0].max())
        w = ok.astype(float)
        if first > 0:  # run started after h.start: fade in from the base
            fade_in = np.arange(first, min(first + 7, last + 1))
            w[fade_in] = np.minimum(w[fade_in], (fade_in - first) / 6.0)
        if last < len(target) - 1:
            fade = np.arange(max(0, last - 6), last + 1)
            w[fade] = np.minimum(w[fade], (last - fade) / 6.0)
        has_base = np.isfinite(base_u[i]) & np.isfinite(base_v[i])
        w = np.where(has_base, w, ok.astype(float))
        u[i] = np.where(ok, w * iu[i] + (1 - w) * np.nan_to_num(base_u[i]), base_u[i])
        v[i] = np.where(ok, w * iv[i] + (1 - w) * np.nan_to_num(base_v[i]), base_v[i])
        gi = np.where(np.isfinite(ig[i]), ig[i], base_g[i])
        g[i] = np.where(ok & np.isfinite(base_g[i]), w * gi + (1 - w) * base_g[i], np.where(ok, gi, base_g[i]))
        model[i] = name
    return u, v, g


def _wind(src: Sources, target: np.ndarray, nspots: int, allow_regional: bool):
    """ECMWF base, then ICON-EU, then AROME on top (each where it has data)."""
    u = _on(src.ecmwf_wind, "u10", target, nspots, 6.0)
    v = _on(src.ecmwf_wind, "v10", target, nspots, 6.0)
    g = _on(src.ecmwf_wind, "gust", target, nspots, 6.0)
    t2 = _on(src.ecmwf_wind, "t2", target, nspots, 6.0)
    model = np.array(["ecmwf" if src.ecmwf_wind is not None else None] * nspots, dtype=object)
    if allow_regional:
        for name, s, gap in (("icon-eu", src.icon, 3.5), ("arome", src.arome, 1.5)):
            if s is not None:
                u, v, g = _overlay(u, v, g, s, target, nspots, model, name, gap)
    ws, wd = wind_from_uv(u, v)
    # Gusts are "max since previous step": undefined at step 0 -> back-fill up to 3 h.
    for i in range(nspots):
        row = g[i]
        nz = np.nonzero(np.isfinite(row))[0]
        if len(nz) and 0 < nz[0] <= 3:
            row[: nz[0]] = row[nz[0]]
    g = np.where(np.isfinite(g), np.maximum(g, ws), g)
    return {"ws": ws, "wg": g.astype(np.float32), "wd": wd, "t2": t2}, model


def _sst(src: Sources, target: np.ndarray, nspots: int) -> np.ndarray:
    out = np.full((nspots, len(target)), np.nan, dtype=np.float32)
    for s in (src.sst_ibi, src.sst_oisst):
        if s is None:
            continue
        vals = persist(s.times, s.fields["sst"], target, SST_MAX_AGE_H)
        out = np.where(np.isfinite(out), out, vals)
    return out


def blend(src: Sources, nspots: int, h_start: dt.datetime) -> Blended:
    th, th3 = target_times(h_start)
    wh, model_wh, ec_on_h = _waves(src, th, nspots, use_ibi=True)
    w3, model_w3, _ = _waves(src, th3, nspots, use_ibi=False)
    _ramp(wh, w3, ec_on_h["hs"], model_wh, model_w3)
    windh, model_wind = _wind(src, th, nspots, allow_regional=True)
    wind3, model_wind3 = _wind(src, th3, nspots, allow_regional=False)
    sst_h = _sst(src, th, nspots)
    sst_3 = _sst(src, th3, nspots)
    h = {**wh, **windh, "sst": sst_h}
    h3 = {**w3, **wind3, "sst": sst_3}
    models = [{"waves": model_wh[i], "wavesLong": model_w3[i], "wind": model_wind[i], "windLong": model_wind3[i]}
              for i in range(nspots)]
    return Blended(h, h3, models)


# ------------------------------------------------------------ model comparison (§5)
MODEL_WAVES = (("ibi", "ibi", ("hs", "tp", "dir")), ("ecmwf", "ecmwf_wave", ("hs", "tp", "dir")),
               ("gfs", "gfs", ("ghs", "gtp", "gdir")))
MODEL_WIND = (("icon-eu", "icon"), ("ecmwf", "ecmwf_wind"), ("arome", "arome"))


def model_times(h_start: dt.datetime) -> np.ndarray:
    return int(h_start.timestamp()) + 3600 * config.MODELS_STEP * np.arange(config.MODELS_N, dtype=np.int64)


def model_arrays(src: Sources, nspots: int, h_start: dt.datetime) -> dict:
    """Raw per-model series on a common 3-hourly axis: {"waves": {model: {hs,tp,dir}}, "wind": {...}}."""
    t = model_times(h_start)
    waves, wind = {}, {}
    for name, attr, (fh, fp, fd) in MODEL_WAVES:
        s = getattr(src, attr)
        if s is None or not {fh, fp, fd} <= set(s.fields):
            continue
        waves[name] = {"hs": interp_scalar(s.times, s.fields[fh], t, 6.0),
                       "tp": interp_scalar(s.times, s.fields[fp], t, 6.0),
                       "dir": interp_direction(s.times, s.fields[fd], t, 6.0)}
    for name, attr in MODEL_WIND:
        s = getattr(src, attr)
        if s is None:
            continue
        u = interp_scalar(s.times, s.fields["u10"], t, 6.0)
        v = interp_scalar(s.times, s.fields["v10"], t, 6.0)
        ws, wd = wind_from_uv(u, v)
        wind[name] = {"ws": ws, "wd": wd}
    return {"start": t[0], "waves": waves, "wind": wind}
