"""Source parsers against small real fixtures saved on 2026-11-11."""
import datetime as dt
import os

import numpy as np

from wavespot_pipeline.grids import RegularGrid, erode_valid, nearest_cell
from wavespot_pipeline.sources import ecmwf, gfswave, ibi, oisst
from wavespot_pipeline.sources.base import decode_grib, extract, split_grib

F = os.path.join(os.path.dirname(__file__), "fixtures", "sources")


def read(name, mode="rb"):
    with open(os.path.join(F, name), mode) as f:
        return f.read()


def test_ecmwf_index():
    idx = ecmwf.parse_index(read("ecmwf_wave_20261111_00z_24h.index", "r"))
    assert {"swh", "mwd", "pp1d", "h1214"} <= set(idx)
    a, b = idx["swh"]
    assert a == 4601966 and b - a + 1 == 1876229


def test_ecmwf_grib_and_nearest_sea_cell():
    fld = decode_grib(read("ecmwf_swh_20261111_00z_24h_biscay.grib2"))
    assert fld.short_name == "swh"
    assert fld.valid_time == int(dt.datetime(2026, 11, 12, tzinfo=dt.timezone.utc).timestamp())
    assert fld.values.shape == (21, 31)
    valid = np.isfinite(fld.values)
    assert 0 < valid.sum() < valid.size          # land is NaN
    # Mundaka sits in a ría: the nearest grid point is land, we must find sea.
    hit = nearest_cell(fld.grid, [erode_valid(valid), valid], 43.4085, -2.6975, 40.0)
    assert hit is not None
    i, j, km = hit
    assert valid[i, j] and km < 40
    v = extract(fld.values, np.array([[i, j]]))[0]
    assert 0.2 < v < 4.0


def test_icon_eu_grib():
    fld = decode_grib(read("icon_eu_u10m_2026111106_024_biscay.grib2"))
    assert fld.short_name == "10u"
    assert np.isfinite(fld.values).all()
    assert np.abs(fld.values).max() < 40


def test_gfswave_partitions():
    blob = read("gfswave_2026111106_f024_peniche.grib2")
    msgs = list(split_grib(blob))
    assert len(msgs) == 13       # HTSGW + wind sea (3) + 3 swells x 3
    spots = [{"id": "pt-supertubos", "lat": 39.344, "lon": -9.364}]

    def cells(fld):
        valid = np.isfinite(fld.values)
        hit = nearest_cell(fld.grid, [erode_valid(valid), valid], 39.344, -9.364, 40.0)
        return np.array([hit[:2]])

    vt, vals = gfswave.decode_partitions(blob, cells)
    assert vt == int(dt.datetime(2026, 11, 12, 6, tzinfo=dt.timezone.utc).timestamp())
    raw = {k: v[:, None] for k, v in vals.items()}
    for k in gfswave.KEYS.values():
        raw.setdefault(k, np.full((1, 1), np.nan, np.float32))
    srt = gfswave.sort_swells(raw)
    assert srt["s1h"][0, 0] >= np.nan_to_num(srt["s2h"][0, 0])
    assert 0.3 < srt["s1h"][0, 0] < 8 and 5 < srt["s1p"][0, 0] < 22
    assert spots


def test_gfswave_idx():
    rows = gfswave.parse_idx(read("gfswave_2026111106_f024.idx", "r"))
    names = [r[2] for r in rows]
    assert names[:5] == ["WIND", "WDIR", "UGRD", "VGRD", "HTSGW"]
    assert rows[-1][1] == -1 and rows[0][1] == rows[1][0] - 1


def test_ibi_strip_reader():
    path = os.path.join(F, "ibi_wav_20261111_zarautz.nc")
    spots = [{"id": "es-zarautz", "lat": 43.2885, "lon": -2.17}]
    times, out, ok, km = ibi.read_strip(path, spots, [0], None, "test")
    assert len(times) == 6 and ok[0]
    hs = out["hs"][0]
    assert np.isfinite(hs).all() and (0.05 < hs).all() and (hs < 6).all()
    assert np.isfinite(out["dir"][0]).all()
    # Variables absent from the file come back as NaN, not as errors.
    assert np.isnan(out["s2p"][0]).all()


def test_ibi_strip_lookup():
    assert ibi.strip_for(39.344, -9.364) == "pt-centro"
    assert ibi.strip_for(30.545, -9.725) == "ma-agadir"
    assert ibi.strip_for(23.855, -15.79) is None
    assert not ibi.in_domain(23.855, -15.79)


def test_oisst_reader():
    blob = read("oisst_20261109_iberia.nc")
    spots = [{"id": "pt-supertubos", "lat": 39.344, "lon": -9.364},
             {"id": "es-famara", "lat": 29.116, "lon": -13.562}]
    t, sst = oisst.read_sst(blob, spots, None)
    assert t == int(dt.datetime(2026, 11, 9, 12, tzinfo=dt.timezone.utc).timestamp())
    assert 12 < sst[0] < 22 and 17 < sst[1] < 26


def test_grid_wraps_longitudes():
    g = RegularGrid(90.0, -0.1, 1801, 180.0, 0.1, 3600, True)
    fi, fj = g.fractional_index(43.0, -2.0)
    assert abs(fi - 470) < 1e-6 and abs(fj - 1780) < 1e-6
