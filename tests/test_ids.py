"""Permanent ids: every published id is current or aliased; aliases are served."""
import json
import os
import sys

from wavespot_pipeline import build, ids
from wavespot_pipeline.spots import load_spots

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(__file__))


def test_no_published_id_disappears():
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        aliases, orphans = ids.catalogue_check(build.SPOT_FILES)
    finally:
        os.chdir(cwd)
    assert not orphans, f"published ids without spot or alias: {orphans[:20]}"
    for seed in ("es-zarautz", "pt-supertubos", "fr-hossegor-la-graviere", "es-sopelana"):
        assert seed not in aliases            # seed ids stay the canonical ids
    assert aliases.get("es-zarauzko-hondartza") == "es-zarautz"


def test_seed_id_kept_when_curated_replaces_it(tmp_path):
    (tmp_path / "curated").mkdir()
    (tmp_path / "curated" / "x.json").write_text(json.dumps([
        {"id": "es-zarauzko-hondartza", "name": "Zarautz", "lat": 43.2895, "lon": -2.169, "country": "ES",
         "break": "beach", "sports": ["surf"], "facing": 0, "window": [280, 40], "confidence": "high"}]))
    (tmp_path / "seed_spots.json").write_text(json.dumps({"layer": 2, "spots": [
        {"id": "es-zarautz", "name": "Zarautz", "lat": 43.2885, "lon": -2.17, "country": "ES", "info": {"facing": 350}}]}))
    (tmp_path / "layer1.json").write_text(json.dumps([
        {"id": "es-playa-de-zarautz", "name": "Playa De Zarautz", "lat": 43.2907, "lon": -2.1616, "country": "ES",
         "layer": 1, "info": {"facing": 0}}]))
    merges = {}
    spots = load_spots([str(tmp_path / "curated" / "*.json"), str(tmp_path / "seed_spots.json"),
                        str(tmp_path / "layer1.json")], None, merges)
    assert [s["id"] for s in spots] == ["es-zarautz"]
    assert spots[0]["verified"] is True and spots[0]["info"]["facing"] == 0       # curated attributes
    assert merges == {"es-zarauzko-hondartza": "es-zarautz", "es-playa-de-zarautz": "es-zarautz"}


def test_resolve_rules():
    aliases, orphans = ids.resolve({"a", "b", "c", "ma-p-27.7123--13.0456", "gone"}, {"a", "x", "ma-p-27.7123-w13.0456"},
                                   {"b": "x"}, {"c": "b"})
    assert aliases == {"b": "x", "c": "x", "ma-p-27.7123--13.0456": "ma-p-27.7123-w13.0456"}
    assert orphans == ["gone"]


def test_build_serves_alias_copies(tmp_path, monkeypatch):
    from test_blend_outputs import make_sources, spots2

    monkeypatch.setattr(build, "fetch_all", lambda *a: (make_sources(), []))
    (tmp_path / "s.json").write_text(json.dumps({"layer": 2, "spots": spots2()}))
    (tmp_path / "pub.txt").write_text("es-zarautz\nes-old-zarautz\n")
    (tmp_path / "al.json").write_text(json.dumps({"v": 1, "aliases": {"es-old-zarautz": "es-zarautz"}}))
    out = tmp_path / "site" / "v1"
    rc = build.main(["--out", str(out), "--spots", str(tmp_path / "s.json"), "--cache", str(tmp_path / "c"),
                     "--work", str(tmp_path / "w"), "--base-url", "", "--tides", "none",
                     "--published", str(tmp_path / "pub.txt"), "--aliases", str(tmp_path / "al.json"),
                     "--update-ids"])
    assert rc == 0
    al = json.loads((out / "index" / "aliases.json").read_text())
    assert al == {"v": 1, "aliases": {"es-old-zarautz": "es-zarautz"}}
    assert (out / "spots" / "es-old-zarautz.json").read_text() == (out / "spots" / "es-zarautz.json").read_text()
    pub = ids.load_published(str(tmp_path / "pub.txt"))
    assert {"es-zarautz", "es-old-zarautz", "ma-dakhla-lagoon"} <= pub
    # An id that vanishes without alias blocks the deploy (exit 3).
    (tmp_path / "pub.txt").write_text("es-vanished\n")
    rc = build.main(["--out", str(tmp_path / "site2" / "v1"), "--spots", str(tmp_path / "s.json"),
                     "--cache", str(tmp_path / "c"), "--work", str(tmp_path / "w"), "--base-url", "",
                     "--tides", "none", "--published", str(tmp_path / "pub.txt"),
                     "--aliases", str(tmp_path / "al2.json")])
    assert rc == 3
