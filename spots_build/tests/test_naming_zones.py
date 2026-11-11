import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config  # noqa: E402
import naming  # noqa: E402
import zones  # noqa: E402

LAYER1 = os.path.join(config.OUT_DIR, "layer1.json")


def test_slugify():
    assert naming.slugify("Praia Ribeira d' Ilhas") == "praia-ribeira-d-ilhas"
    assert naming.slugify("Plage de la Gravière") == "plage-de-la-graviere"
    assert naming.slugify("Zarauzko hondartza") == "zarauzko-hondartza"


def test_clean_eea_name():
    assert naming.clean_eea_name("PLAYA CABEZO (EL) PM1") == "Playa El Cabezo"
    assert naming.clean_eea_name("PLAYA LA ARENA - ZIERBENA PM1") == "Playa La Arena - Zierbena"
    assert naming.clean_eea_name("ST-AUBIN-PLAGE") == "St-Aubin-Plage"
    assert naming.clean_eea_name("PORS AR MARC'H") == "Pors ar Marc'h"


def test_synthetic_names():
    assert naming.synthetic_name("MA", "Tarfaya", 12.3, 200) == "Côte de Tarfaya (12 km S)"
    assert naming.synthetic_name("FR", "Le Porge", 3, 270) == "Côte du Porge (3 km O)"
    assert naming.synthetic_name("FR", "Anglet", 0.5, 0) == "Côte d'Anglet"
    assert naming.synthetic_name("ES", "El Palmar", 2, 315) == "Costa del Palmar (2 km NO)"
    assert naming.synthetic_name("PT", "A Ver-o-Mar", 4, 0) == "Costa da Ver-o-Mar (4 km N)"
    assert naming.synthetic_id("MA", 27.71234, -13.04561) == "ma-p-27.7123-w13.0456"


def test_pick_name_morocco_prefers_latin():
    tags = {"name": "شاطئ مهدية", "name:fr": "Plage de Mehdia"}
    assert naming.pick_name(tags, "MA")[0] == "Plage de Mehdia"
    assert naming.pick_name({"name": "Plage Lalla Fatna ⴰⴼⵜⴰⵙ شاطئ"}, "MA")[0] == "Plage Lalla Fatna"


def test_country_scope():
    assert config.country_of(43.288, -2.17) == "ES"          # Zarautz
    assert config.country_of(43.38, -1.76) == "FR"           # Hendaye
    assert config.country_of(39.35, -9.36) == "PT"           # Peniche
    assert config.country_of(30.55, -9.71) == "MA"           # Taghazout
    assert config.country_of(29.1, -13.6) == "ES"            # Lanzarote
    assert config.country_of(27.45, -13.26) == "MA"          # Sahara coast south of Tarfaya
    assert config.country_of(36.72, -4.42) is None           # Malaga (Mediterranean)
    assert config.country_of(48.84, -1.60) is None           # Granville (Normandy)
    assert config.country_of(30.14, -15.87) is None          # Selvagens
    assert config.country_of(20.93, -17.03) is None          # Nouadhibou (Mauritania)


def test_zones():
    assert 40 <= len(zones.ZONES) <= 60
    assert len({z[0] for z in zones.ZONES}) == len(zones.ZONES)
    for zid, cc, bb, names in zones.ZONES:
        assert zid.startswith(cc.lower() + "-")
        assert set(names) == set(zones.LANGS)
        assert bb[0] < bb[2] and bb[1] < bb[3]
    assert zones.assign_zone("ES", 43.288, -2.17) == "es-costa-vasca"
    assert zones.assign_zone("PT", 39.346, -9.365) == "pt-peniche"
    assert zones.assign_zone("MA", 30.546, -9.712) == "ma-taghazout-agadir"
    assert zones.assign_zone("FR", 43.671, -1.442) == "fr-landes-sud"
    assert zones.assign_zone("MA", 23.7, -15.93) == "ma-dakhla"


@pytest.mark.skipif(not os.path.exists(LAYER1), reason="layer1.json not built")
def test_layer1_contract():
    pts = json.load(open(LAYER1))
    ids = [p["id"] for p in pts]
    assert len(ids) == len(set(ids))
    zone_ids = {z[0] for z in zones.ZONES}
    for p in pts:
        assert re.fullmatch(r"[a-z]{2}-[a-z0-9.\-]+", p["id"]), p["id"]
        assert p["layer"] == 1 and p["zone"] in zone_ids
        assert p["kind"] in ("beach", "cape", "bay", "locality", "bathing", "wikidata", "synthetic")
        assert p["licence"] in ("ODbL", "CC-BY-EEA", "CC0")
        info = p["info"]
        assert 0 <= info["facing"] < 360 and info["break"] == "unknown"
        a0, a1 = info["window"]
        width = (a1 - a0) % 360
        assert width >= config.MIN_WINDOW_DEG - config.RAY_STEP_DEG or p.get("lagoon")
        assert (info["facing"] - a0) % 360 <= width or a1 == 360
        assert p["name"] and p["sources"]
        if p["kind"] == "synthetic":
            assert p["id"].startswith(p["country"].lower() + "-p-")
