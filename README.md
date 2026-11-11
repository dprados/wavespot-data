# wavespot-data

Pipeline de datos abiertos de Wavespot (olas, viento, mareas, spots). Datos: Copernicus Marine, ECMWF (CC BY 4.0), DWD, Météo-France, NOAA, EOT20 (CC BY 4.0), © OpenStreetMap contributors (ODbL), EEA (CC BY 4.0), Wikidata (CC0).

Published at `https://dprados.github.io/wavespot-data/v1/` (contract: `apps/wavespot/docs/data-schema.md`).

## Layout

| Path | What |
|---|---|
| `wavespot_pipeline/` | Forecast build (Python 3.12) |
| `wavespot_pipeline/sources/` | One module per source: `ibi` (Copernicus IBI waves + SST), `ecmwf` (IFS 0.1° waves/wind/2t), `icon_eu` (DWD wind), `arome` (Météo-France wind, FR + north ES, 48 h), `gfswave` (NOAA partitions), `oisst` (NOAA SST) |
| `wavespot_pipeline/blend.py` | IBI → ECMWF(+GFS partitions) → GFS fallback per hour; AROME → ICON-EU → ECMWF wind with cross-fades; model comparison series |
| `wavespot_pipeline/buoys.py` | Copernicus In Situ IBI NRT → `buoys/latest.json`; spot→buoy assignment (≤60 km, ±60° of facing, no land on the line) |
| `wavespot_pipeline/landcheck.py` | Layer-2 points must not be on land (OSM land polygons) |
| `wavespot_pipeline/rating.py`, `sun.py`, `tides.py` | Schema §3 formula, civil twilight, harmonic tides — ported 1:1 to Swift |
| `wavespot_pipeline/fixtures.py` | Generates `tests/fixtures/rating_parity.json` and `tide_reference.json` for the Swift tests |
| `data/spots/curated/*.json` | Curated layer 2 (format: `docs/curated-brief.md`); wins over seed and layer 1 |
| `data/seed_spots.json` | ~40 hand-picked spots (layer 2, `verified:false`), kept until a curated equivalent exists |
| `data/spots/` | Automatic layer 1 + zones (built by `spots_build/`) |
| `data/tides/eot20_constituents.json` | EOT20 amplitude/phase per spot (built by `tides.yml`) |

## Workflows

- `forecast.yml` — 10:00 and 22:00 UTC + manual. Tests, fetches all sources in parallel, builds `site/v1` (spots, index tiles with `r`/`rk`, zones, `models/` for layer 2, `buoys/latest.json`), validates it and deploys with `actions/deploy-pages`. Cell mappings and last-good spot files persist in `actions/cache` (`state-*`). If no spot gets fresh data the deploy is skipped and the previous site stays online. Run status per source is in `index/meta.json → status`.
- `monitor.yml` — daily 11:40 UTC: opens an issue if the data is >14 h old, a source failed or >20 % of spots are stale.
- `buoys.yml` — hourly: restores the last forecast site from `actions/cache` (`site-*`), refreshes `buoys/latest.json` and redeploys (same `pages` concurrency group as the forecast).
- `spots.yml` — on spot-file changes: unique ids, merge rules and the land check (OSM land polygons cached as `osm-land-v1`).
- `tides.yml` — when spot files change (and twice a week to keep the 2.1 GB EOT20 cache warm): extracts constituents for new/moved spots and commits the JSON.

## Local run

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
set -a; source ../../../credentials.env; set +a          # Copernicus Marine account
.venv/bin/python -m wavespot_pipeline.build --out /tmp/site/v1 --cache /tmp/ws-cache --work /tmp/ws-work
.venv/bin/python -m wavespot_pipeline.validate /tmp/site/v1
.venv/bin/python -m pytest -q tests
```

Regenerate the parity fixtures after any change to the formula: `python -m wavespot_pipeline.fixtures --tides <EOT20 dir>`.
