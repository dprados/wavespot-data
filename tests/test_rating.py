"""Rating formula (schema §3) and the parity fixture consumed by Swift."""
import datetime as dt
import json
import os

import pytest

from wavespot_pipeline import fixtures, rating, sun

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "rating_parity.json")


@pytest.fixture(scope="module")
def parity():
    with open(FIX) as f:
        return json.load(f)


def test_fixture_size(parity):
    n = sum(len(v) for k, v in parity.items() if k != "meta")
    assert n >= 200
    assert len(parity["surf"]) >= 200


def test_fixture_is_up_to_date(parity):
    """The committed fixture must equal what the code generates now."""
    fresh = json.loads(json.dumps(fixtures.rating_parity()))
    assert fresh == parity, "run: python -m wavespot_pipeline.fixtures"


def test_surf_cases_replay(parity):
    for c in parity["surf"]:
        i = c["in"]
        tf = rating.tide_factor(i["tideStage"], i["layer"], i["bestTide"], i["dangerTide"])
        score = rating.surf_score(i["hb"], i["td"], i["ws"], i["wd"], i["facing"], i["level"], tf, i["light"])
        assert abs(score - c["out"]["score"]) <= 1e-3
        assert rating.round_half_up(score) == c["out"]["rating"]


def test_kite_cases_replay(parity):
    for c in parity["kite"]:
        i = c["in"]
        r = rating.kite_rating(i["ws"], i["wg"], i["wd"], i["facing"], i["kiteWind"], i["light"])
        assert r == c["out"]["rating"]


def test_size_trapezoid():
    assert rating.size_factor(0.2, "beginner") == 0
    assert rating.size_factor(0.5, "beginner") == 1
    assert rating.size_factor(1.1, "beginner") == 1
    assert rating.size_factor(1.8, "beginner") == 0
    assert abs(rating.size_factor(1.45, "beginner") - 0.5) < 1e-9


def test_wind_sectors():
    # facing 0 (north-facing beach) -> offshore wind comes from 180.
    assert rating.wind_factor(1.5, 0, 0) == 1.0                 # glassy
    assert rating.wind_factor(8.0, 180, 0) == 1.0               # offshore ≤ 8 m/s
    assert abs(rating.wind_factor(10.0, 180, 0) - 0.88) < 1e-9
    assert abs(rating.wind_factor(5.0, 90, 0) - 0.7) < 1e-9     # cross
    assert abs(rating.wind_factor(5.0, 0, 0) - 0.5) < 1e-9      # onshore
    assert rating.wind_factor(20.0, 0, 0) == 0.0


def test_exposure_window():
    assert rating.exposure(300, [280, 40]) == 1.0
    assert rating.exposure(10, [280, 40]) == 1.0                # wraps through north
    assert abs(rating.exposure(265, [280, 40]) - 0.5) < 1e-9
    assert rating.exposure(200, [280, 40]) == 0.0
    assert rating.exposure(300, [280, 40], wind_sea=True) == 0.5


def test_effective_height_single_component():
    hb, td = rating.effective_height([(1.0, 10.0, 300.0, False)], [280, 40])
    assert abs(td - 12.0) < 1e-9                              # Tm01 10 s -> 12 s peak-equivalent
    assert abs(hb - 1.0 * 1.17) < 1e-9                        # g(12) = 1.17
    hb, td = rating.effective_height([(1.0, 10.0, 300.0, False)], [280, 40], tp=11.0)
    assert abs(td - 11.0) < 1e-9                              # capped at tp
    hb, td = rating.effective_height([(1.0, 4.0, 300.0, True)], [280, 40], tp=9.0)
    assert abs(td - 5.0) < 1e-9                               # wind sea x1.25


def test_round_half_up_epsilon():
    assert rating.round_half_up(2.4999999999999996) == 3
    assert rating.round_half_up(2.4999) == 2
    assert rating.round_half_up(0.5) == 1


def test_tide_factor_rules():
    assert rating.tide_factor("low", 1, ["mid"], []) == 1.0      # layer 1: ignored
    assert rating.tide_factor("low", 2, [], ["low"]) == 0.3      # danger applies without bestTide
    assert rating.tide_factor("mid", 2, [], ["low"]) == 1.0
    assert rating.tide_factor("low", 2, ["mid"], ["low"]) == 0.3
    assert rating.tide_factor("mid", 2, ["mid"], []) == 1.0
    assert rating.tide_factor("high", 2, ["mid"], []) == 0.6


def test_kite_offshore_is_zero():
    assert rating.kite_direction(180, 0, None) == 0.0
    assert rating.kite_direction(180, 0, [90, 270]) == 0.0      # even if listed in kiteWind
    assert rating.kite_direction(90, 0, None) == 1.0


def test_best_window():
    assert rating.best_window([1, 3, 3, 2, 3, 3, 3], [True] * 7) == (3, 4, 3)
    assert rating.best_window([1, 1, 1], [True] * 3) is None
    assert rating.best_window([4, 1, 4, 4, 1], [True] * 5) == (4, 2, 2)
    assert rating.best_window([4, 1, 3, 3, 1], [True] * 5) == (4, 0, 1)   # 1-h windows allowed
    assert rating.best_window([4, 4, 4], [False, False, True]) == (4, 2, 1)
    assert rating.best_window([4, 4], [False, False]) is None


def test_sun_peniche_november():
    dawn, dusk = sun.civil_twilight(39.36, -9.38, dt.date(2026, 11, 12))
    # Civil dawn ~07:00 UTC and dusk ~17:50 UTC in mid-November.
    assert 6 * 60 + 40 < dawn < 7 * 60 + 20
    assert 17 * 60 + 30 < dusk < 18 * 60 + 10
    assert sun.is_lit(39.36, -9.38, dt.datetime(2026, 11, 12, 12, tzinfo=dt.timezone.utc))
    assert not sun.is_lit(39.36, -9.38, dt.datetime(2026, 11, 12, 3, tzinfo=dt.timezone.utc))
