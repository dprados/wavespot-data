"""Spot catalogue: curated/seed/layer-1 merge rules, unique ids, no layer-2 point on land."""
import collections
import glob
import json
import os

import pytest

from wavespot_pipeline import build
from wavespot_pipeline.spots import is_named, load_spots, load_zone_registry, similar_names

ROOT = os.path.dirname(os.path.dirname(__file__))
FILES = [os.path.join(ROOT, f) for f in build.SPOT_FILES]


def curated(**kw):
    base = {"id": "es-zarautz", "name": "Zarautz", "aliases": [], "lat": 43.2870, "lon": -2.1700, "country": "ES",
            "zone": "es-costa-vasca", "break": "beach", "sports": ["surf"], "facing": 350, "window": [285, 45],
            "bestTide": ["mid", "high"], "dangerTide": [], "bestSwell": [290, 340], "bestWind": [120, 210],
            "kiteWind": None, "level": "all", "hazards": ["rips"], "notes": "x", "sources": ["https://a", "https://b"],
            "confidence": "high"}
    base.update(kw)
    return base


def l1(**kw):
    base = {"id": "es-playa-de-zarautz", "name": "Playa de Zarautz", "lat": 43.2880, "lon": -2.1705, "country": "ES",
            "zone": "es-costa-vasca", "layer": 1, "info": {"facing": 0, "window": [280, 50], "break": "unknown",
                                                         "sports": ["surf"]}}
    base.update(kw)
    return base


def write(tmp_path, curated_items, seed_items, layer1_items):
    (tmp_path / "curated").mkdir()
    (tmp_path / "curated" / "es.json").write_text(json.dumps(curated_items))
    (tmp_path / "seed_spots.json").write_text(json.dumps({"layer": 2, "spots": seed_items}))
    (tmp_path / "layer1.json").write_text(json.dumps(layer1_items))
    return [str(tmp_path / "curated" / "*.json"), str(tmp_path / "seed_spots.json"), str(tmp_path / "layer1.json")]


def test_curated_wins_and_maps_fields(tmp_path):
    seed = [{"id": "es-zarautz", "name": "Zarautz", "lat": 43.2885, "lon": -2.17, "country": "ES", "layer": 2,
             "info": {"facing": 340}}]
    files = write(tmp_path, [curated(), curated(id="es-x", name="X", lat=43.5, confidence="low")], seed,
                  [l1(), l1(id="es-otra", name="Punta Otra", lat=43.2890)])
    spots = {s["id"]: s for s in load_spots(files)}
    z = spots["es-zarautz"]
    assert z["layer"] == 2 and z["verified"] is True and z["info"]["facing"] == 350
    assert z["info"]["sources"] == ["https://a", "https://b"] and "notes" not in z["info"]
    assert spots["es-x"]["verified"] is False                 # confidence low
    assert "es-playa-de-zarautz" not in spots                 # ≤300 m, similar name -> replaced
    assert "es-otra" in spots                                 # ≤300 m but a different place -> kept


def test_seed_kept_until_curated_equivalent(tmp_path):
    seed = [{"id": "es-sopelana", "name": "Sopelana", "lat": 43.3894, "lon": -2.9956, "country": "ES", "layer": 2,
             "info": {"facing": 320}}]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    files = write(tmp_path / "a", [curated()], seed, [])
    assert "es-sopelana" in {s["id"] for s in load_spots(files)}
    files2 = write(tmp_path / "b", [curated(id="es-sopela", name="Sopela", lat=43.3895, lon=-2.9957)], seed, [])
    ids = {s["id"] for s in load_spots(files2)}
    assert "es-sopela" in ids and "es-sopelana" not in ids


def test_similar_names():
    a = {"name": "Côte des Basques", "aliases": []}
    assert similar_names(a, {"name": "Cote des Basques"})
    assert similar_names({"name": "Pantín"}, {"name": "Playa Pant?in"})
    assert not similar_names({"name": "Zarautz"}, {"name": "Punta Otra"})


def test_real_catalogue_has_unique_ids():
    raw_ids = collections.Counter()
    for p in glob.glob(os.path.join(ROOT, "data", "spots", "curated", "*.json")):
        with open(p) as f:
            raw_ids.update(s["id"] for s in json.load(f))
    dup = [k for k, n in raw_ids.items() if n > 1]
    assert not dup, f"duplicate ids in curated files: {dup[:10]}"
    spots = load_spots(FILES, load_zone_registry(os.path.join(ROOT, "data", "spots", "zones.json")))
    ids = [s["id"] for s in spots]
    assert len(ids) == len(set(ids))
    assert all("--" not in i for i in ids)


def test_zone_membership_rules():
    """zones/*.json include layer 2 and named (non-synthetic) layer-1 spots only."""
    assert is_named({"id": "es-zarautz", "name": "Zarautz"})
    assert not is_named({"id": "ma-p-27.7123-w13.0456", "name": "Côte de Tarfaya (3 km N)"})
    assert not is_named({"id": "es-x", "name": ""})


@pytest.mark.skipif(not os.environ.get("WAVESPOT_LAND"), reason="needs OSM land polygons (WAVESPOT_LAND=…/land_polygons.shp)")
def test_layer2_points_not_on_land():
    from wavespot_pipeline.landcheck import inland_points, is_lagoon

    spots = [s for s in load_spots(FILES) if s["layer"] == 2 and not is_lagoon(s)]
    bad = inland_points(os.environ["WAVESPOT_LAND"], [(s["id"], s["lat"], s["lon"]) for s in spots])
    assert not bad, f"layer-2 points on land: {bad[:20]}"
