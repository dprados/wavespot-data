"""Generate the Python -> Swift parity fixtures.

    python -m wavespot_pipeline.fixtures                     # rating_parity.json
    python -m wavespot_pipeline.fixtures --tides MODEL_DIR   # + tide_reference.json (pyTMD cross-check)

Fixtures are deterministic (seeded) and committed in tests/fixtures/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import sys

import numpy as np

from . import rating, sun, tides

OUT_DIR = os.path.join("tests", "fixtures")
TIDE_SPOTS = ["es-mundaka", "es-zarautz", "es-razo", "fr-hossegor-la-graviere", "fr-la-torche",
              "pt-supertubos", "pt-arrifana", "es-famara", "pt-jardim-do-mar", "ma-anchor-point"]
TIDE_DATES = ["2026-11-12", "2027-03-21", "2027-06-21"]


def r6(x):
    return None if x is None else round(float(x), 6)


# ------------------------------------------------------------------ rating
def exposure_cases(rng: random.Random) -> list[dict]:
    cases = []
    fixed = [
        ([[1.5, 12.0, 300.0, False]], [280, 40], None),
        ([[1.5, 12.0, 250.0, False]], [280, 40], None),             # 30° outside -> 0
        ([[1.5, 12.0, 265.0, False]], [280, 40], None),             # 15° outside -> 0.5
        ([[1.5, 12.0, 55.0, False]], [280, 40], None),              # wrap-around side
        ([[1.0, 8.0, 300.0, True]], [280, 40], None),               # wind sea x0.5
        ([[2.0, 14.0, 300.0, False], [0.8, 6.0, 20.0, True]], [280, 40], None),
        ([[2.0, 14.0, 200.0, False]], [280, 40], 13.5),             # fully sheltered -> hb 0, td = tp
        ([[None, None, None, False]], [280, 40], 10.0),             # nothing usable -> null
        ([[1.2, 11.0, 90.0, False]], None, None),                   # no window -> e = 1
        ([[3.0, 16.0, 280.0, False]], [280, 40], None),             # on the edge
        ([[0.5, 25.0, 300.0, False]], [280, 40], None),             # g clamps to 1.35
        ([[0.5, 2.0, 300.0, False]], [280, 40], None),              # g clamps to 0.85
    ]
    for comps, window, tp in fixed:
        hb, td = rating.effective_height([tuple(c) for c in comps], window, tp)
        cases.append({"in": {"components": comps, "window": window, "tp": tp}, "out": {"hb": r6(hb), "td": r6(td)}})
    for _ in range(60):
        comps = []
        for k in range(rng.choice([1, 2, 3])):
            comps.append([round(rng.uniform(0.1, 4.0), 2), round(rng.uniform(4, 18), 1),
                          rng.randrange(0, 360), k == 2])
        window = rng.choice([None, [rng.randrange(0, 360), rng.randrange(0, 360)]])
        tp = round(rng.uniform(5, 16), 1)
        hb, td = rating.effective_height([tuple(c) for c in comps], window, tp)
        cases.append({"in": {"components": comps, "window": window, "tp": tp}, "out": {"hb": r6(hb), "td": r6(td)}})
    return cases


def surf_case(hb, td, ws, wd, facing, level, stage, layer, best, danger, light):
    tf = rating.tide_factor(stage, layer, best, danger)
    s = rating.size_factor(hb, level)
    q = rating.period_factor(td)
    w = rating.wind_factor(ws, wd, facing)
    score = rating.surf_score(hb, td, ws, wd, facing, level, tf, light)
    return {"in": {"hb": hb, "td": td, "ws": ws, "wd": wd, "facing": facing, "level": level, "tideStage": stage,
                   "layer": layer, "bestTide": best, "dangerTide": danger, "light": light},
            "out": {"S": r6(s), "Qf": r6(q), "W": r6(w), "T": r6(tf), "score": r6(score),
                    "rating": rating.round_half_up(score)}}


def surf_cases(rng: random.Random) -> list[dict]:
    out = []
    # Size breakpoints for every level.
    for level, (a, b, c, d) in rating.SIZE_TRAPEZOID.items():
        for hb in (0.0, a, (a + b) / 2, b, (b + c) / 2, c, (c + d) / 2, d, d + 0.5):
            out.append(surf_case(round(hb, 4), 12.0, 1.0, 0.0, 0.0, level, None, 2, [], [], 1))
    # Period breakpoints.
    for td in (4.0, 6.0, 8.0, 10.0, 14.0, 18.0):
        out.append(surf_case(1.0, td, 1.0, 0.0, 0.0, "intermediate", None, 2, [], [], 1))
    # Wind sectors / speeds, facing 300 -> offshore 120.
    for wd in (120, 165, 166, 230, 231, 300, 75, 10):
        for ws in (1.99, 2.0, 8.0, 9.0, 14.0, 20.0):
            out.append(surf_case(1.0, 12.0, ws, float(wd), 300.0, "intermediate", None, 2, [], [], 1))
    # Tide factor combinations.
    for stage in ("low", "mid", "high"):
        for best, danger, layer in (([], [], 2), (["low"], [], 2), (["mid", "high"], ["low"], 2),
                                    (["high"], [], 1), ([], ["low"], 2)):
            out.append(surf_case(1.0, 12.0, 1.0, 0.0, 0.0, "beginner", stage, layer, best, danger, 1))
    # Light off.
    out.append(surf_case(1.0, 12.0, 1.0, 0.0, 0.0, "beginner", None, 2, [], [], 0))
    # Rounding edge: 5 * 0.5 = 2.5 built from floats (S slightly below 0.5).
    out.append(surf_case(0.35, 14.0, 1.0, 0.0, 0.0, "beginner", None, 2, [], [], 1))
    out.append(surf_case(1.55, 14.0, 1.0, 0.0, 0.0, "intermediate", "low", 2, ["mid"], [], 1))
    # Random cases.
    for _ in range(220):
        best = rng.choice([[], ["low"], ["mid"], ["mid", "high"], ["low", "mid"]])
        danger = rng.choice([[], [], ["low"], ["high"]])
        out.append(surf_case(round(rng.uniform(0, 6.5), 2), round(rng.uniform(3, 20), 1),
                             round(rng.uniform(0, 22), 2), float(rng.randrange(0, 360)),
                             float(rng.randrange(0, 360)), rng.choice(rating.LEVELS),
                             rng.choice([None, "low", "mid", "high"]), rng.choice([1, 2]), best, danger,
                             rng.choice([1, 1, 1, 0])))
    return out


def kite_case(ws, wg, wd, facing, kite_wind, light):
    k = rating.kite_strength(ws)
    dk = rating.kite_direction(wd, facing, kite_wind)
    g = rating.gust_factor(ws, wg)
    score = rating.kite_score(ws, wg, wd, facing, kite_wind, light)
    return {"in": {"ws": ws, "wg": wg, "wd": wd, "facing": facing, "kiteWind": kite_wind, "light": light},
            "out": {"K": r6(k), "Dk": r6(dk), "G": r6(g), "score": r6(score), "rating": rating.round_half_up(score)}}


def kite_cases(rng: random.Random) -> list[dict]:
    out = []
    kn = rating.KNOTS_PER_MS
    for knots in (10.9, 11.0, 13.0, 15.0, 20.0, 28.0, 34.0, 40.0, 45.0):
        out.append(kite_case(round(knots / kn, 4), None, 90.0, 0.0, None, 1))
    # facing 0 -> offshore 180; δ sweep.
    for wd in (180, 225, 226, 240, 241, 250, 300, 330, 331, 350, 351, 0):
        out.append(kite_case(9.0, 11.0, float(wd), 0.0, None, 1))
    for wd in (40, 60, 90, 120, 135, 150, 200):
        out.append(kite_case(9.0, 11.0, float(wd), 0.0, [60, 120], 1))
    for wg in (9.0, 11.7, 12.0, 15.0, 25.0, None):
        out.append(kite_case(9.0, wg, 90.0, 0.0, None, 1))
    out.append(kite_case(0.0, 0.0, 90.0, 0.0, None, 1))
    out.append(kite_case(9.0, 11.0, 90.0, 0.0, None, 0))
    for _ in range(80):
        ws = round(rng.uniform(0, 24), 2)
        out.append(kite_case(ws, round(ws * rng.uniform(1.0, 2.0), 2), float(rng.randrange(0, 360)),
                             float(rng.randrange(0, 360)),
                             rng.choice([None, None, [rng.randrange(0, 360), rng.randrange(0, 360)]]),
                             rng.choice([1, 1, 0])))
    return out


def window_cases(rng: random.Random) -> list[dict]:
    fixed = [
        ([1, 2, 3, 3, 3, 2, 1, 3, 3, 0], [True] * 10),
        ([3, 3, 1, 3, 3, 1, 1, 1, 1, 1], [True] * 10),        # tie -> earliest
        ([4, 1, 4, 1, 4, 1, 1, 1, 1, 1], [True] * 10),        # max never 2 h long -> null
        ([1, 1, 1, 1, 1, 1, 1, 1, 1, 1], [True] * 10),        # max < 2 -> null
        ([5, 5, 5, 2, 2, 2, 2, 2, 2, 2], [False, True, True] + [True] * 7),
        ([None, 2, 2, None, 2, 2, 2, None, 0, 0], [True] * 10),
        ([2, 2, 2, 2], [False] * 4),
    ]
    out = [{"in": {"ratings": r, "lit": l}, "out": rating.best_window(r, l)} for r, l in fixed]
    for _ in range(30):
        n = 24
        r = [rng.choice([0, 1, 2, 3, 3, 4, 5]) for _ in range(n)]
        dawn, dusk = rng.randrange(5, 9), rng.randrange(17, 21)
        lit = [dawn <= k <= dusk for k in range(n)]
        out.append({"in": {"ratings": r, "lit": lit}, "out": rating.best_window(r, lit)})
    for c in out:
        c["out"] = None if c["out"] is None else {"rating": c["out"][0], "first": c["out"][1], "hours": c["out"][2]}
    return out


def sun_cases() -> list[dict]:
    pts = [(43.287, -2.170), (39.344, -9.364), (28.683, -14.014), (23.855, -15.79), (48.84, -3.0),
           (32.736, -17.212)]
    dates = ["2026-11-12", "2026-12-21", "2027-03-20", "2027-06-21", "2027-09-23"]
    out = []
    for lat, lon in pts:
        for d in dates:
            dawn, dusk = sun.civil_twilight(lat, lon, dt.date.fromisoformat(d))
            out.append({"in": {"lat": lat, "lon": lon, "date": d}, "out": {"dawnMin": r6(dawn), "duskMin": r6(dusk)}})
    return out


def stage_cases() -> list[dict]:
    vals = [0.0, 0.1, 0.3299, 0.33, 0.5, 0.66, 0.6601, 0.9, 1.0]
    return [{"in": v, "out": rating.tide_stage(v)} for v in vals]


def rating_parity() -> dict:
    rng = random.Random(20261111)
    doc = {
        "meta": {
            "schema": 1,
            "generator": "wavespot_pipeline.fixtures (data-schema.md §3)",
            "tolerance": 0.001,
            "rounding": "rating = floor(score + 0.5 + 1e-9)",
            "angles": "degrees, directions 'coming from', arcs [from, to] clockwise inclusive",
            "kiteOffshoreDelta": rating.KITE_OFFSHORE_DELTA,
            "kiteDefaultDelta": list(rating.KITE_DEFAULT_ARC),
            "sun": "civil twilight (zenith 96°), minutes after 00:00 UTC of the date; tolerance 1 min",
        },
        "exposure": exposure_cases(rng),
        "surf": surf_cases(rng),
        "kite": kite_cases(rng),
        "bestWindow": window_cases(rng),
        "tideStage": stage_cases(),
        "sun": sun_cases(),
    }
    return doc


# ------------------------------------------------------------------ tides
def tide_reference(store_path: str, model_dir: str | None) -> dict:
    with open(store_path) as f:
        store = json.load(f)["spots"]
    cases = []
    max_diff = None
    for sid in TIDE_SPOTS:
        s = store.get(sid)
        if not s or not s.get("cons"):
            continue
        for d in TIDE_DATES:
            t0 = dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp()
            secs = t0 + 600 * np.arange(144)
            h = tides.predict(s["cons"], secs, s.get("z0", 0.0))
            case = {"id": sid, "lat": s["lat"], "lon": s["lon"], "z0": s.get("z0", 0.0), "cons": s["cons"],
                    "start": f"{d}T00:00:00Z", "stepMinutes": 10, "heights": [round(float(x), 4) for x in h]}
            if model_dir:
                ref = _pytmd_series(model_dir, s["lat"], s["lon"], secs)
                diff = float(np.max(np.abs(ref - h)))
                case["pytmdMaxDiff"] = round(diff, 4)
                max_diff = diff if max_diff is None else max(max_diff, diff)
            cases.append(case)
    meta = {"generator": "wavespot_pipeline.tides.predict", "units": "m above mean sea level (+z0)",
            "formula": "h = z0 + Σ f·A·cos(V + u − G); see tides.py", "tolerance": 0.001,
            "pytmdCheck": "pyTMD 'FES' corrections, no minor inference, constituents interpolated at the "
                          "spot (not the rounded values)" if model_dir else None,
            "pytmdMaxDiff": None if max_diff is None else round(max_diff, 4)}
    return {"meta": meta, "cases": cases}


def _pytmd_series(model_dir: str, lat: float, lon: float, secs: np.ndarray) -> np.ndarray:
    import pyTMD.io
    import timescale
    from pyTMD.predict.ocean_load import time_series

    m = pyTMD.io.model(model_dir).from_database("EOT20")
    ds = m.open_dataset(group="z")
    x, y = ds.tmd.coords_as(np.array([lon]), np.array([lat]), type="trajectory", crs=4326)
    local = ds.tmd.interp(x, y, method="linear", extrapolate=True, cutoff=25)
    one = local.isel({local[local.tmd.constituents[0]].dims[0]: 0})
    ts = timescale.from_deltatime(secs, epoch=(1970, 1, 1, 0, 0, 0), standard="UTC")
    return np.asarray(time_series(ts.tide, one, deltat=ts.tt_ut1, corrections="FES").values, dtype=float)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--tide-store", default=os.path.join("data", "tides", "eot20_constituents.json"))
    ap.add_argument("--tides", default=None, help="EOT20 model dir: also (re)build tide_reference.json")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    rp = rating_parity()
    with open(os.path.join(args.out, "rating_parity.json"), "w") as f:
        json.dump(rp, f, indent=1, ensure_ascii=False)
    n = sum(len(v) for k, v in rp.items() if k != "meta")
    print(f"rating_parity.json: {n} cases ({len(rp['surf'])} surf, {len(rp['kite'])} kite)")
    if args.tides is not None or os.path.exists(args.tide_store):
        tr = tide_reference(args.tide_store, args.tides)
        with open(os.path.join(args.out, "tide_reference.json"), "w") as f:
            json.dump(tr, f, separators=(",", ":"))
        print(f"tide_reference.json: {len(tr['cases'])} cases, pyTMD max diff {tr['meta']['pytmdMaxDiff']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
