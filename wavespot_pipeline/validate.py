"""Structural validation of the published v1 documents (data-schema.md).

    python -m wavespot_pipeline.validate site/v1     # exit 1 on any error
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import config

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
HHMM = re.compile(r"^\d{2}:\d{2}$")
SERIES = ["hs", "tp", "dir", "s1h", "s1p", "s1d", "s2h", "s2p", "s2d", "wwh", "wwp", "wwd",
          "hb", "td", "ws", "wg", "wd", "t2", "sst"]
DIRS = {"dir", "s1d", "s2d", "wwd", "wd"}
INFO_KEYS = {"break", "sports", "facing", "window", "bestTide", "dangerTide", "bestSwell", "bestWind",
             "kiteWind", "level", "hazards", "sources"}
BREAKS = {"beach", "reef", "point", "rivermouth", "unknown"}
SPORTS = {"surf", "kite", "windsurf"}
TIDES = {"low", "mid", "high"}
LEVELS = {"beginner", "intermediate", "advanced", "all"}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _arc(x) -> bool:
    return x is None or (isinstance(x, list) and len(x) == 2 and all(_num(v) for v in x))


def validate_series(block: dict, n: int, step: int, where: str) -> list[str]:
    errs = []
    if not ISO.match(str(block.get("start"))):
        errs.append(f"{where}.start not ISO")
    if block.get("step") != step or block.get("n") != n:
        errs.append(f"{where} step/n = {block.get('step')}/{block.get('n')}, expected {step}/{n}")
    for f in SERIES:
        arr = block.get(f)
        if not isinstance(arr, list) or len(arr) != n:
            errs.append(f"{where}.{f} length {None if arr is None else len(arr)} != {n}")
            continue
        for v in arr:
            if v is None:
                continue
            if not _num(v):
                errs.append(f"{where}.{f} non-numeric {v!r}")
                break
            if f in DIRS and not (isinstance(v, int) and 0 <= v < 360):
                errs.append(f"{where}.{f} bad direction {v}")
                break
            if f in ("hs", "s1h", "s2h", "wwh", "hb", "ws", "wg") and not (0 <= v < 40):
                errs.append(f"{where}.{f} out of range {v}")
                break
    return errs


def validate_spot(doc: dict) -> list[str]:
    errs = []
    for k in ("v", "id", "name", "aliases", "lat", "lon", "country", "zone", "tz", "layer", "verified", "info",
              "generated", "models", "h", "h3", "tide"):
        if k not in doc:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if doc["v"] != config.SCHEMA_VERSION:
        errs.append("bad v")
    if not re.match(r"^[a-z]{2}-[a-z0-9.-]+$", doc["id"]):
        errs.append(f"bad id {doc['id']}")
    if doc["layer"] not in (1, 2):
        errs.append("bad layer")
    if not ISO.match(doc["generated"]):
        errs.append("bad generated")
    info = doc["info"]
    missing = INFO_KEYS - set(info)
    if missing:
        errs.append(f"info missing {sorted(missing)}")
    if info.get("break") not in BREAKS:
        errs.append(f"bad break {info.get('break')}")
    if not set(info.get("sports") or []) <= SPORTS:
        errs.append("bad sports")
    if not set(info.get("bestTide") or []) <= TIDES or not set(info.get("dangerTide") or []) <= TIDES:
        errs.append("bad tide sets")
    if info.get("level") not in LEVELS:
        errs.append("bad level")
    for k in ("window", "bestSwell", "bestWind", "kiteWind"):
        if not _arc(info.get(k)):
            errs.append(f"bad arc {k}")
    errs += validate_series(doc["h"], config.H_HOURS, 1, "h")
    errs += validate_series(doc["h3"], config.H3_N, config.H3_STEP, "h3")
    tide = doc["tide"]
    if tide is not None:
        cons = tide.get("cons") or {}
        if not _num(tide.get("z0")) or not cons:
            errs.append("bad tide")
        for name, pair in cons.items():
            if not (isinstance(pair, list) and len(pair) == 2 and all(_num(v) for v in pair)):
                errs.append(f"bad constituent {name}")
    return errs


def validate_tile(doc: dict) -> list[str]:
    errs = []
    if doc.get("v") != config.SCHEMA_VERSION or not isinstance(doc.get("spots"), list):
        return ["bad tile header"]
    for e in doc["spots"]:
        for k in ("id", "n", "lat", "lon", "l", "s", "z", "r"):
            if k not in e:
                errs.append(f"tile entry missing {k}")
        r = e.get("r")
        if not (isinstance(r, list) and len(r) == 3 and all(isinstance(x, int) and 0 <= x <= 5 for x in r)):
            errs.append(f"bad r for {e.get('id')}")
        rk = e.get("rk")
        if rk is not None and not (isinstance(rk, int) and 0 <= rk <= 5):
            errs.append(f"bad rk for {e.get('id')}")
    return errs


def validate_zone(doc: dict) -> list[str]:
    errs = []
    if doc.get("v") != config.SCHEMA_VERSION or not isinstance(doc.get("days"), list):
        return ["bad zone header"]
    for day in doc["days"]:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day.get("date", "")):
            errs.append("bad date")
        lists = list((day.get("levels") or {}).values()) + [day.get("kite") or []]
        if set(day.get("levels") or {}) != {"beginner", "intermediate", "advanced"}:
            errs.append("bad levels")
        for lst in lists:
            if len(lst) > 5:
                errs.append("more than 5 entries")
            for e in lst:
                w = e.get("win")
                if not (isinstance(e.get("r"), int) and 2 <= e["r"] <= 5 and isinstance(w, list) and len(w) == 2
                        and all(HHMM.match(x) for x in w)):
                    errs.append(f"bad zone entry {e}")
    return errs


def validate_models(doc: dict) -> list[str]:
    errs = []
    if doc.get("v") != config.SCHEMA_VERSION or doc.get("step") != config.MODELS_STEP or doc.get("n") != config.MODELS_N:
        return ["bad models header"]
    if not ISO.match(str(doc.get("start"))):
        errs.append("bad start")
    for group, fields in (("waves", ("hs", "tp", "dir")), ("wind", ("ws", "wd"))):
        for model, block in (doc.get(group) or {}).items():
            for f in fields:
                arr = block.get(f)
                if not isinstance(arr, list) or len(arr) != doc["n"]:
                    errs.append(f"{group}.{model}.{f} bad length")
    return errs


def validate_buoys(doc: dict) -> list[str]:
    errs = []
    if doc.get("v") != config.SCHEMA_VERSION or not ISO.match(str(doc.get("generated"))):
        return ["bad buoys header"]
    for b in doc.get("buoys", []):
        for k in ("id", "name", "lat", "lon", "t", "hs", "tp", "dir", "ws", "wd", "sst"):
            if k not in b:
                errs.append(f"buoy {b.get('id')} missing {k}")
        if not ISO.match(str(b.get("t"))):
            errs.append(f"buoy {b.get('id')} bad t")
    return errs


def validate_meta(doc: dict) -> list[str]:
    errs = []
    for k in ("v", "generated", "tiles", "zones", "attribution"):
        if k not in doc:
            errs.append(f"meta missing {k}")
    for z in doc.get("zones", []):
        if not (isinstance(z.get("name"), dict) and isinstance(z.get("bbox"), list) and len(z["bbox"]) == 4):
            errs.append(f"bad zone {z.get('id')}")
    return errs


def validate_site(root: str) -> list[str]:
    errs = []
    meta_p = os.path.join(root, "index", "meta.json")
    with open(meta_p) as f:
        meta = json.load(f)
    errs += [f"meta: {e}" for e in validate_meta(meta)]
    for t in meta.get("tiles", []):
        p = os.path.join(root, "index", f"{t}.json")
        if not os.path.exists(p):
            errs.append(f"tile {t} missing")
            continue
        with open(p) as f:
            tile = json.load(f)
        errs += [f"{t}: {e}" for e in validate_tile(tile)]
        for e in tile["spots"]:
            sp = os.path.join(root, "spots", f"{e['id']}.json")
            if not os.path.exists(sp):
                errs.append(f"spot file missing for {e['id']}")
    for name in sorted(os.listdir(os.path.join(root, "spots"))):
        with open(os.path.join(root, "spots", name)) as f:
            errs += [f"{name}: {e}" for e in validate_spot(json.load(f))]
    mdir = os.path.join(root, "models")
    for name in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        with open(os.path.join(mdir, name)) as f:
            errs += [f"models/{name}: {e}" for e in validate_models(json.load(f))]
    bpath = os.path.join(root, "buoys", "latest.json")
    if os.path.exists(bpath):
        with open(bpath) as f:
            errs += [f"buoys: {e}" for e in validate_buoys(json.load(f))]
    zdir = os.path.join(root, "zones")
    for name in sorted(os.listdir(zdir)) if os.path.isdir(zdir) else []:
        with open(os.path.join(zdir, name)) as f:
            errs += [f"{name}: {e}" for e in validate_zone(json.load(f))]
    return errs


def main(argv=None) -> int:
    root = (argv or sys.argv[1:] or ["site/v1"])[0]
    errs = validate_site(root)
    for e in errs[:200]:
        print(e)
    print(f"{len(errs)} validation errors in {root}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
