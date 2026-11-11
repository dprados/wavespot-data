"""Blending/fallback logic and schema validation of the generated documents."""
import datetime as dt
import json
import os

import numpy as np
import pytest

from wavespot_pipeline import blend as B
from wavespot_pipeline import build, config, products, validate
from wavespot_pipeline.sources.base import SourceData
from wavespot_pipeline.spots import assign_zone, load_spots, tile_of

ROOT = os.path.dirname(os.path.dirname(__file__))
H0 = dt.datetime(2026, 11, 11, tzinfo=dt.timezone.utc)
T0 = int(H0.timestamp())


def spots2():
    return [
        {"id": "es-zarautz", "name": "Zarautz", "aliases": [], "lat": 43.2885, "lon": -2.17, "country": "ES",
         "zone": "es-costa-vasca", "tz": "Europe/Madrid", "layer": 2, "verified": False, "buoy": None,
         "info": {"break": "beach", "sports": ["surf"], "facing": 350, "window": [280, 40], "bestTide": ["mid", "high"],
                  "dangerTide": [], "bestSwell": None, "bestWind": [125, 215], "kiteWind": None, "level": "all",
                  "hazards": [], "sources": []}},
        {"id": "ma-dakhla-lagoon", "name": "Dakhla", "aliases": [], "lat": 23.855, "lon": -15.79, "country": "MA",
         "zone": "ma-dakhla", "tz": "Africa/El_Aaiun", "layer": 2, "verified": False, "buoy": None,
         "info": {"break": "unknown", "sports": ["kite"], "facing": 95, "window": None, "bestTide": [],
                  "dangerTide": [], "bestSwell": None, "bestWind": [230, 320], "kiteWind": None, "level": "all",
                  "hazards": [], "sources": []}},
    ]


def const(n, nt, v):
    return np.full((n, nt), v, dtype=np.float32)


def make_sources(ibi_hours=216):
    n = 2
    th = T0 + 3600 * np.arange(216)
    ibi = None
    if ibi_hours:
        f = {k: const(n, 216, np.nan) for k in B.WAVE_FIELDS}
        for k, v in dict(hs=2.0, tp=12.0, dir=300.0, s1h=1.8, s1p=12.0, s1d=300.0, s2h=0.5, s2p=8.0, s2d=330.0,
                         wwh=0.6, wwp=5.0, wwd=0.0).items():
            f[k][0, :ibi_hours] = v      # spot 0 covered; spot 1 (Dakhla) outside IBI
        ibi = SourceData("ibi", th, f, np.array([True, False]))
    te = T0 + 3600 * np.array(list(range(0, 145, 3)) + list(range(150, 361, 6)))
    ecw = SourceData("ecmwf", te, {"hs": const(n, len(te), 1.6), "tp": const(n, len(te), 11.0),
                                   "dir": const(n, len(te), 310.0)}, np.array([True, True]))
    ecwind = SourceData("ecmwf", te, {"u10": const(n, len(te), 0.0), "v10": const(n, len(te), 5.0),
                                      "gust": const(n, len(te), 7.0), "t2": const(n, len(te), 15.0)},
                        np.array([True, True]))
    tg = T0 + 3600 * np.arange(0, 385, 3)
    g = {k: const(n, len(tg), np.nan) for k in B.WAVE_FIELDS[3:]}
    for k, v in dict(s1h=1.0, s1p=13.0, s1d=290.0, s2h=0.4, s2p=9.0, s2d=200.0, wwh=0.3, wwp=4.0, wwd=20.0).items():
        g[k][:] = v
    gfs = SourceData("gfs-wave", tg, g, np.array([True, True]))
    ti = T0 + 3600 * np.array(list(range(0, 79)) + list(range(81, 121, 3)))
    icon = SourceData("icon-eu", ti, {"u10": const(n, len(ti), 3.0), "v10": const(n, len(ti), 0.0),
                                      "gust": const(n, len(ti), 4.0)}, np.array([True, False]))
    icon.fields["u10"][1] = np.nan
    icon.fields["v10"][1] = np.nan
    sst = SourceData("ibi-sst", T0 + 43200 + 86400 * np.arange(10), {"sst": const(n, 10, 17.0)},
                     np.array([True, False]))
    sst.fields["sst"][1] = np.nan
    ois = SourceData("oisst", np.array([T0 - 86400]), {"sst": np.array([[16.0], [21.0]], np.float32)},
                     np.array([True, True]))
    return B.Sources(ibi=ibi, ecmwf_wave=ecw, ecmwf_wind=ecwind, icon=icon, gfs=gfs, sst_ibi=sst, sst_oisst=ois)


def test_blend_priorities():
    bl = B.blend(make_sources(), 2, H0)
    m0, m1 = bl.models
    assert m0 == {"waves": "ibi", "wavesLong": "ecmwf", "wind": "icon-eu", "windLong": "ecmwf"}
    assert m1["waves"] == "ecmwf" and m1["wind"] == "ecmwf"
    assert np.allclose(bl.h["hs"][0], 2.0)
    assert np.allclose(bl.h["hs"][1], 1.6)
    # GFS partitions rescaled to the ECMWF Hs: energy preserved.
    e = bl.h["s1h"][1] ** 2 + bl.h["s2h"][1] ** 2 + bl.h["wwh"][1] ** 2
    assert np.allclose(np.sqrt(e), 1.6, atol=1e-4)
    # ICON wind from the west (u=3) early, ECMWF from the south (v=5) after ICON ends.
    assert abs(bl.h["wd"][0, 10] - 270) < 1e-3 and abs(bl.h["ws"][0, 10] - 3.0) < 1e-4
    assert abs(bl.h["wd"][0, 150] - 180) < 1e-3
    assert abs(bl.h["wd"][1, 10] - 180) < 1e-3
    # SST: IBI where available, OISST otherwise, held to day 15.
    assert np.allclose(bl.h["sst"][0], 17.0) and np.allclose(bl.h3["sst"][1], 21.0)


def test_ramp_from_ibi_into_ecmwf():
    bl = B.blend(make_sources(), 2, H0)
    hs3 = bl.h3["hs"][0]
    # IBI is 25 % above ECMWF over the whole overlap: the tail keeps that coastal factor.
    assert abs(hs3[0] - 2.0) < 1e-4 and abs(hs3[-1] - 2.0) < 1e-4
    # Different end-of-h ratio: ramps from it to the persistent one in 24 h.
    src = make_sources()
    src.ibi.fields["hs"][0, 204:] = 1.6
    bl = B.blend(src, 2, H0)
    k_all = (2.0 * 204 + 1.6 * 12) / (1.6 * 216)
    hs3 = bl.h3["hs"][0]
    assert abs(hs3[0] - 1.6 * (1.0 * (1 - 3 / 24) + k_all * 3 / 24)) < 1e-4
    assert abs(hs3[-1] - 1.6 * k_all) < 1e-4


def test_ibi_gap_falls_back_per_hour():
    bl = B.blend(make_sources(ibi_hours=100), 2, H0)
    assert np.allclose(bl.h["hs"][0, :100], 2.0) and np.allclose(bl.h["hs"][0, 100:], 1.6)
    assert bl.models[0]["waves"] == "ecmwf"         # majority of hours


def test_all_wave_sources_down_gives_incomplete_doc():
    src = make_sources()
    src.ibi = src.ecmwf_wave = src.gfs = None
    bl = B.blend(src, 2, H0)
    doc = products.spot_doc(spots2()[0], bl, 0, H0, "2026-11-11T10:00:00Z", None)
    assert not products.doc_is_complete(doc)


def test_spot_doc_validates_and_rates():
    bl = B.blend(make_sources(), 2, H0)
    for i, s in enumerate(spots2()):
        doc = products.spot_doc(s, bl, i, H0, "2026-11-11T10:00:00Z",
                                {"z0": 0.0, "cons": {"M2": [1.3, 95.0], "S2": [0.45, 128.0]}})
        assert validate.validate_spot(doc) == []
        assert products.doc_is_complete(doc)
        assert doc["h"]["n"] == 216 and doc["h3"]["n"] == 48
        assert doc["h3"]["start"] == "2026-11-20T00:00:00Z"
        today = products.today_index(doc, dt.datetime(2026, 11, 11, 10, tzinfo=dt.timezone.utc))
        r = products.index_r(doc, today)
        assert len(r) == 3 and all(0 <= x <= 5 for x in r)
        rk = products.index_rk(doc, today)
        entry = products.index_entry(doc, r, rk)
        assert ("rk" in entry) == ("kite" in s["info"]["sports"])
        assert validate.validate_tile({"v": 1, "spots": [entry]}) == []
        z = products.zone_doc(s["zone"], [products.zone_entries(doc)], "2026-11-11T10:00:00Z")
        assert validate.validate_zone(z) == []


def test_build_end_to_end_with_stubbed_sources(tmp_path, monkeypatch):
    def fake_fetch_all(spots, now, h_start, work, cache, skip):
        return make_sources(), []
    monkeypatch.setattr(build, "fetch_all", fake_fetch_all)
    spots_file = tmp_path / "s.json"
    spots_file.write_text(json.dumps({"layer": 2, "spots": spots2()}))
    out = tmp_path / "site" / "v1"
    rc = build.main(["--out", str(out), "--spots", str(spots_file), "--cache", str(tmp_path / "c"),
                     "--work", str(tmp_path / "w"), "--base-url", "", "--tides", "none",
                     "--published", str(tmp_path / "pub.txt"), "--aliases", str(tmp_path / "al.json")])
    assert rc == 0
    assert validate.validate_site(str(out)) == []
    meta = json.loads((out / "index" / "meta.json").read_text())
    assert meta["status"]["spots"]["fresh"] == 2
    assert tile_of(43.2885, -2.17) in meta["tiles"]


def test_last_good_reused_when_sources_fail(tmp_path, monkeypatch):
    spots_file = tmp_path / "s.json"
    spots_file.write_text(json.dumps({"layer": 2, "spots": spots2()}))
    args = ["--spots", str(spots_file), "--cache", str(tmp_path / "c"), "--work", str(tmp_path / "w"),
            "--base-url", "", "--tides", "none", "--published", str(tmp_path / "pub.txt"),
            "--aliases", str(tmp_path / "al.json")]
    monkeypatch.setattr(build, "fetch_all", lambda *a: (make_sources(), []))
    assert build.main(["--out", str(tmp_path / "a")] + args) == 0
    first = json.loads((tmp_path / "a" / "spots" / "es-zarautz.json").read_text())

    def broken(*a):
        s = make_sources()
        s.ibi = s.ecmwf_wave = s.gfs = None
        return s, []
    monkeypatch.setattr(build, "fetch_all", broken)
    rc = build.main(["--out", str(tmp_path / "b")] + args)
    assert rc == 2                       # nothing fresh -> workflow must not deploy
    again = json.loads((tmp_path / "b" / "spots" / "es-zarautz.json").read_text())
    assert again["generated"] == first["generated"] and again["h"]["hs"] == first["h"]["hs"]


def test_seed_spots_file():
    spots = load_spots([os.path.join(ROOT, "data", "seed_spots.json"), os.path.join(ROOT, "nope.json")])
    assert len(spots) >= 40
    ids = [s["id"] for s in spots]
    assert len(ids) == len(set(ids))
    for s in spots:
        assert s["layer"] == 2 and s["verified"] is False
        assert s["zone"] in config.ZONE_NAMES, s
        assert s["info"]["facing"] is not None
    for must in ("ma-anchor-point", "ma-killer-point", "ma-imsouane-bay", "ma-safi", "ma-dakhla-lagoon",
                 "es-el-cotillo", "es-la-santa-el-quemao", "es-el-medano", "pt-jardim-do-mar",
                 "es-tarifa-los-lances"):
        assert must in ids


@pytest.mark.parametrize("cc,lat,lon,zone", [
    ("ES", 43.29, -2.17, "es-costa-vasca"), ("ES", 28.68, -14.01, "es-fuerteventura"),
    ("ES", 29.11, -13.56, "es-lanzarote"), ("PT", 39.34, -9.36, "pt-centro-oeste"),
    ("PT", 32.74, -17.21, "pt-madeira"), ("FR", 43.67, -1.44, "fr-landes"), ("MA", 30.54, -9.72, "ma-agadir"),
    ("MA", 23.85, -15.79, "ma-dakhla"),
])
def test_zone_assignment(cc, lat, lon, zone):
    assert assign_zone(cc, lat, lon) == zone
