"""Buoys (§6), buoy assignment, AROME scope/overlay and model comparison (§5)."""
import datetime as dt
import os

import numpy as np

from wavespot_pipeline import blend as B
from wavespot_pipeline import buoys, config, products, validate
from wavespot_pipeline.grids import RegularGrid
from wavespot_pipeline.sources import arome
from wavespot_pipeline.sources.base import SourceData

F = os.path.join(os.path.dirname(__file__), "fixtures", "sources")
NOW = dt.datetime(2026, 11, 11, 15, tzinfo=dt.timezone.utc)


def test_index_selection():
    with open(os.path.join(F, "insitu_index_latest_sample.txt")) as f:
        sel = buoys.parse_index(f, NOW)
    assert set(sel) == {"6200024", "6200066", "Tenerife-coast-buoy"}   # no Malaga (Med), no North Sea
    assert sel["6200024"]["date"] == "20261111"


def test_read_buoy_file():
    b = buoys.read_buoy(os.path.join(F, "IR_TS_MO_6200024_20261111.nc"),
                        {"platform": "6200024", "lat": 43.6, "lon": -3.0}, NOW)
    assert b["id"] == "MO_6200024" and b["name"] == "Bilbao-Vizcaya buoy"
    assert 0.2 < b["hs"] < 8 and 4 < b["tp"] < 22 and 0 <= b["dir"] < 360
    assert b["t"].endswith("Z") and b["sst"] is not None
    stale = buoys.read_buoy(os.path.join(F, "IR_TS_MO_6200024_20261111.nc"),
                            {"platform": "6200024", "lat": 43.6, "lon": -3.0}, NOW + dt.timedelta(days=2))
    assert stale is None


def test_assignment_rules():
    reg = {"A": {"id": "A", "lat": 43.64, "lon": -3.04},      # Bilbao-Vizcaya, NW, 79 km: too far
           "B": {"id": "B", "lat": 43.56, "lon": -2.02},      # Donostia buoy, N-NE, 33 km
           "C": {"id": "C", "lat": 42.9, "lon": -2.17}}       # due south (behind the spot)
    spot = {"lat": 43.2885, "lon": -2.17, "info": {"facing": 350}}
    assert buoys.assign(spot, reg) == "B"
    assert buoys.assign({**spot, "info": {"facing": 90}}, reg) is None    # nothing within ±60° of facing
    # Land in between blocks the assignment.
    g = RegularGrid(44.0, -0.1, 20, -4.0, 0.1, 30)
    lsm = np.zeros((20, 30))
    lsm[5:7, :] = 1.0                                              # land band at 43.4-43.5 N
    assert buoys.assign(spot, reg, buoys.LandMask(g, lsm)) is None


def test_arome_scope():
    assert arome.in_scope("FR", 43.67, -1.44)
    assert arome.in_scope("ES", 43.29, -2.17)
    assert not arome.in_scope("ES", 36.03, -5.64)      # Tarifa: south of the north-Spain limit
    assert not arome.in_scope("PT", 39.34, -9.36)
    assert not arome.in_scope("FR", 55.2, -4.0)         # boundary zone


def test_arome_overlays_icon_and_fades():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from test_blend_outputs import H0, T0, make_sources

    src = make_sources()
    ta = T0 + 3600 * np.arange(0, 49)
    src.arome = SourceData("arome", ta, {"u10": np.full((2, 49), 0.0, np.float32),
                                         "v10": np.full((2, 49), -6.0, np.float32),
                                         "gust": np.full((2, 49), 9.0, np.float32)}, np.array([True, False]))
    src.arome.fields["u10"][1] = np.nan
    src.arome.fields["v10"][1] = np.nan
    bl = B.blend(src, 2, H0)
    assert bl.models[0]["wind"] == "arome" and bl.models[1]["wind"] == "ecmwf"
    assert abs(bl.h["wd"][0, 10]) < 1e-3 or abs(bl.h["wd"][0, 10] - 360) < 1e-3   # north wind from AROME
    assert abs(bl.h["wd"][0, 80] - 270) < 1e-3                                      # ICON after 48 h


def test_models_doc():
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from test_blend_outputs import H0, make_sources, spots2

    src = make_sources()
    arr = B.model_arrays(src, 2, H0)
    doc = products.models_doc(spots2()[0], arr, 0)
    assert doc["step"] == 3 and doc["n"] == config.MODELS_N and doc["start"] == "2026-11-11T00:00:00Z"
    assert set(doc["waves"]) == {"ibi", "ecmwf"} and set(doc["wind"]) == {"icon-eu", "ecmwf"}
    assert len(doc["waves"]["ibi"]["hs"]) == 40 and doc["waves"]["ibi"]["hs"][0] == 2.0
    assert validate.validate_models(doc) == []
    dakhla = products.models_doc(spots2()[1], arr, 1)
    assert "ibi" not in dakhla["waves"] and "icon-eu" not in dakhla["wind"]
