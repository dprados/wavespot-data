"""Tide predictor reference (Swift parity) and sanity of the extracted constituents."""
import datetime as dt
import json
import os

import numpy as np

from wavespot_pipeline import tides

ROOT = os.path.dirname(os.path.dirname(__file__))
REF = os.path.join(ROOT, "tests", "fixtures", "tide_reference.json")
STORE = os.path.join(ROOT, "data", "tides", "eot20_constituents.json")


def load(p):
    with open(p) as f:
        return json.load(f)


def test_reference_fixture_shape():
    ref = load(REF)
    assert len(ref["cases"]) == 30                      # 10 spots x 3 dates
    assert {len(c["heights"]) for c in ref["cases"]} == {144}
    assert ref["meta"]["pytmdMaxDiff"] is not None and ref["meta"]["pytmdMaxDiff"] < 0.005


def test_reference_reproduces():
    for c in load(REF)["cases"]:
        t0 = dt.datetime.fromisoformat(c["start"].replace("Z", "+00:00")).timestamp()
        h = tides.predict(c["cons"], t0 + 600 * np.arange(144), c["z0"])
        assert np.max(np.abs(h - np.array(c["heights"]))) < 1e-4, c["id"]


def test_ranges_are_plausible():
    """Spring-neap envelope over 30 days: Biscay ~3-4.5 m, Canaries ~2-2.8 m."""
    store = load(STORE)["spots"]
    t = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc).timestamp() + 600 * np.arange(30 * 144)

    def rng(sid):
        h = tides.predict(store[sid]["cons"], t)
        return h.max() - h.min()

    assert 3.0 < rng("es-zarautz") < 5.0
    assert 3.0 < rng("fr-hossegor-la-graviere") < 5.0
    assert 1.5 < rng("es-famara") < 3.0
    assert 1.2 < rng("pt-jardim-do-mar") < 2.6


def test_day_stages():
    h = np.array([0.0, 0.2, 0.5, 0.9, 1.0])
    assert tides.day_stages(h) == ["low", "low", "mid", "high", "high"]


def test_eot20_nested_zip_unpack(tmp_path):
    import zipfile

    from wavespot_pipeline.tides_extract import unpack

    inner = tmp_path / "ocean_tides.zip"
    with zipfile.ZipFile(inner, "w") as z:
        for c in ["2N2", "J1", "K1", "K2", "M2", "M4", "MF", "MM", "N2", "O1", "P1", "Q1", "S1", "S2", "SA",
                  "SSA", "T2"]:
            z.writestr(f"ocean_tides/{c}_ocean_eot20.nc", b"x")
        z.writestr("__MACOSX/ocean_tides/._M2_ocean_eot20.nc", b"x")
    outer = tmp_path / "eot20.zip"
    with zipfile.ZipFile(outer, "w") as z:
        z.write(inner, "ocean_tides.zip")
        z.writestr("load_tides.zip", b"")
    unpack(str(outer), str(tmp_path / "model"))
    files = os.listdir(tmp_path / "model" / "EOT20" / "ocean_tides")
    assert len(files) == 17 and "M2_ocean_eot20.nc" in files
