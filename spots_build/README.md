# spots_build — layer 1 (automatic) spot database

Builds `data/spots/layer1.json`: one forecast point every few km of the Atlantic coast in scope
(Cantabrian/Atlantic Spain + Canaries, mainland Portugal + Madeira, Atlantic France from the
Pays Basque to Brittany, Atlantic Morocco from Tangier to Lagouira), each with an automatic
orientation (`facing`) and swell window (`window`). Contract: `apps/wavespot/docs/data-schema.md`.

## Sources and licences

| Source | Used for | Licence |
|---|---|---|
| OpenStreetMap (Geofabrik extracts) | named beaches, capes, bays, coastal localities, non-business surf/kite spots, place names for synthetic points | ODbL 1.0 |
| OSM land polygons (osmdata.openstreetmap.de, `land-polygons-split-4326`) | coastline, orientation, gap filling | ODbL 1.0 |
| EEA bathing water sites 2025 (coastal + transitional) | official bathing sites | CC BY 4.0 (© EEA / DG ENV; coordinates by the member states) |
| Wikidata (beaches, surf spots) | extra beaches and aliases | CC0 |

No commercial surf/forecast site (Surfline, MSW, surf-forecast, Wannasurf, Windguru…) is used.
`layer1.json` as a whole is a derivative database of OSM and is published under **ODbL**
(attribution: "© OpenStreetMap contributors, EEA, Wikidata"). The per-point `licence` field
records where the point itself (name/position) comes from; orientation is always OSM-derived.
Keep the curated layer (2) separate and link it by id (ODbL "collective database").

## Pipeline

```
extract_osm.py   Geofabrik .pbf -> CACHE/osm/*.json            (pyosmium, ~2 min, 4 procs)
fetch_wikidata.py SPARQL       -> CACHE/wikidata_beaches.json
land.py          land polygons -> CACHE/land.pkl                (~40 s)
build.py         merge + dedupe + orientation + synthetic gap fill + ids + zones (~60 s, multiprocessing)
report.py        layer1_stats.md, preview/*.png, reference accuracy
```

1. **Candidates**: OSM named `natural=beach` (≤1.5 km from the coast), `natural=cape|peninsula`
   (≤800 m), `natural=bay` (≤1.5 km), `place=locality` whose name is a coastal feature
   (Punta, Praia, Plage, Cala, Porz…, ≤300 m), OSM `sport=surfing|kitesurfing|windsurfing`
   that are not businesses, EEA coastal/transitional bathing sites, Wikidata beaches.
2. **Dedupe** (<300 m) by priority OSM beach > OSM surf spot > EEA > cape > bay > Wikidata >
   locality; the losing names become `aliases`, sources are merged. Localities/bays are dropped
   if a better point lies within 1000/600 m.
3. **Orientation** (`orientation.py`, exposure-window method from `docs/research-raw/spots.md` §7):
   water candidates = coastline samples within 600 m offset 120 m seaward; rays every 5°, 20 km
   long, open if they touch no land (islets <0.05 km² ignored); the candidate with the widest
   contiguous open arc wins. `window` = that arc, `[from, to]` clockwise. `facing` = half-way
   between the arc centre and the 600 m coast normal (normal clamped 30° inside the arc).
4. **Filter**: points whose window is <20° (estuaries, harbours, inner rías, lagoons) are dropped,
   except inside the named kite lagoons of `config.KITE_LAGOONS` (Dakhla, Khnifiss, Oualidia,
   Merja Zerga, Albufeira, Óbidos, Ria Formosa, Cádiz bay) which get `sports: ["kite"]` and a
   `lagoon` field.
5. **Gap filling**: unnamed OSM beaches first, then coastline samples every 1 km, keep those with a
   valid window and no point within 2.5 km → one synthetic point every ~5 km of uncovered coast.
   Name = nearest settlement weighted by size, e.g. `Côte de Tarfaya (12 km S)`,
   `Costa del Palmar (2 km NO)`, `Costa da Nazaré`. ES/PT use "Costa de", FR and MA use
   "Côte de" (French is the usual Latin-script language of Moroccan toponyms); compass letters
   N/NE/E/SE/S/SO/O/NO are the same in es/pt/fr.
6. **Ids**: `{cc}-{slug(name)}` (`-2`, `-3`… on collision, ordered by source priority then
   latitude), synthetic `{cc}-p-{lat:.4f}-{lon:.4f}` (e.g. `ma-p-27.7123--13.0456`).
7. **Zones**: 60 human zones in `zones.py` (names in es, pt, fr, en, de, ca, eu, gl); a point gets
   the smallest bbox of its country that contains it, else the nearest one.
   `data/spots/zones.json` has the bboxes tightened to the points.

## Running

```sh
export WAVESPOT_SPOTS_CACHE=/path/to/big/scratch    # never inside the repo
python -m venv $WAVESPOT_SPOTS_CACHE/venv && $WAVESPOT_SPOTS_CACHE/venv/bin/pip install shapely osmium numpy pyshp matplotlib pytest
# download Geofabrik extracts listed in config.PBF_FILES into PBF_DIR and
# https://osmdata.openstreetmap.de/download/land-polygons-split-4326.zip (unzip)
PY="$WAVESPOT_SPOTS_CACHE/venv/bin/python -I"
$PY spots_build/extract_osm.py PBF_DIR
$PY spots_build/fetch_wikidata.py
$PY spots_build/land.py LAND_DIR/land_polygons.shp
$PY spots_build/build.py EEA_BATHING_SITES.json
$PY spots_build/report.py
$PY -m pytest spots_build/tests -q
```

The EEA input is the JSON list exported from the EEA Bathing Water 2025 map service
(`bathingWaterIdentifier`, `bathingWaterName`, `bwWaterCategory`, `latitude`, `longitude`),
kept in `apps/wavespot/docs/research-raw/spots/eea_bathing_sites_atlantic_2025.json`.

## Validation

`tests/test_orientation.py` checks the computed facing against 44 well-known spots
(`reference_spots.py`, reference = public knowledge, 16-point compass) and requires ≥85 % within
±22.5°. Current result and per-spot errors: `data/spots/layer1_stats.md`.
