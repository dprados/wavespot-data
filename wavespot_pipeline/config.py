"""Static configuration: datasets, coastal strips, zones, attribution.

Everything that is "data about the pipeline" lives here so sources and outputs
stay generic. Boxes are (lat_min, lat_max, lon_min, lon_max) unless noted.
"""
from __future__ import annotations

import os

SCHEMA_VERSION = 1
BASE_URL = os.environ.get("WAVESPOT_BASE_URL", "https://dprados.github.io/wavespot-data/v1/")

# Horizons (schema §2): `h` = today 00Z .. +9 days hourly, `h3` = up to day 15 every 3 h.
H_HOURS = 216
H3_STEP = 3
H3_N = 48

# ---------------------------------------------------------------- Copernicus IBI
IBI_WAV_DATASET = "cmems_mod_ibi_wav_anfc_0.027deg_PT1H-i"
IBI_WAV_VARS = [
    "VHM0", "VTPK", "VMDR",
    "VHM0_SW1", "VTM01_SW1", "VMDR_SW1",
    "VHM0_SW2", "VTM01_SW2", "VMDR_SW2",
    "VHM0_WW", "VTM01_WW", "VMDR_WW",
]
IBI_PHY_DAILY_DATASET = "cmems_mod_ibi_phy_anfc_0.027deg-3D_P1D-m"
IBI_DOMAIN = (26.0, 56.0, -19.0, 5.0)

# Coastal strips for IBI downloads (lat_min, lat_max, lon_min, lon_max).
# They cover every Atlantic coast in scope inside the IBI domain; a spot is
# served by the first strip that contains it with a margin.
IBI_STRIPS: dict[str, tuple[float, float, float, float]] = {
    "fr-bretagne-n": (48.35, 48.95, -5.20, -1.30),
    "fr-bretagne-w": (47.60, 48.45, -5.20, -3.90),
    "fr-bretagne-s": (46.90, 47.95, -4.00, -1.95),
    "fr-vendee-charente": (45.55, 47.00, -2.60, -0.95),
    "fr-aquitaine": (43.50, 45.65, -1.65, -0.95),
    "es-cantabrico-e": (43.20, 43.75, -4.60, -1.20),
    "es-asturias": (43.25, 43.80, -7.15, -4.50),
    "es-galicia-n": (43.25, 43.95, -8.70, -7.00),
    "es-galicia-w": (41.80, 43.40, -9.45, -8.55),
    "pt-norte": (40.40, 41.95, -9.05, -8.55),
    "pt-centro": (38.55, 40.45, -9.60, -8.70),
    "pt-alentejo": (37.20, 38.60, -9.60, -8.60),
    "pt-algarve": (36.85, 37.30, -9.05, -7.35),
    "es-golfo-cadiz": (35.95, 37.30, -7.45, -5.55),
    "ma-nord": (34.00, 35.95, -6.95, -5.30),
    "ma-casablanca": (32.20, 34.10, -9.40, -6.70),
    "ma-safi-essaouira": (30.90, 32.40, -9.95, -9.05),
    "ma-agadir": (29.40, 31.00, -10.30, -9.45),
    "ma-sud-1": (27.90, 29.60, -13.05, -9.95),
    "ma-sud-2": (26.00, 28.10, -14.80, -12.75),
    "can-este": (27.85, 29.50, -14.60, -13.20),
    "can-centro": (27.60, 28.65, -16.95, -15.30),
    "can-oeste": (27.55, 28.90, -18.20, -16.85),
    "madeira": (32.45, 33.15, -17.35, -16.20),
}

# ------------------------------------------------------------------- ECMWF
ECMWF_MIRRORS = [
    "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com",
    "https://data.ecmwf.int/forecasts",
]
ECMWF_RESOL = "0p1"
ECMWF_WAVE_PARAMS = ["swh", "mwd", "pp1d"]
ECMWF_OPER_PARAMS = ["10u", "10v", "10fg", "2t"]
# 00z/12z runs: 3-hourly to 144 h, then 6-hourly to 360 h.
ECMWF_STEPS = list(range(0, 145, 3)) + list(range(150, 361, 6))

# ------------------------------------------------------------------ DWD ICON-EU
ICON_EU_BASE = "https://opendata.dwd.de/weather/nwp/icon-eu/grib"
ICON_EU_VARS = {"u_10m": "U_10M", "v_10m": "V_10M", "vmax_10m": "VMAX_10M"}
ICON_EU_STEPS = list(range(0, 79)) + list(range(81, 121, 3))
ICON_EU_DOMAIN = (29.5, 70.5, -23.5, 62.5)

# ------------------------------------------------------------------ NOAA GFS-Wave
GFSWAVE_NOMADS = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl"
GFSWAVE_AWS = "https://noaa-gfs-bdp-pds.s3.amazonaws.com"
GFSWAVE_BBOX = (20.0, 52.0, -20.0, 5.0)

# ------------------------------------------------------------------ NOAA OISST
OISST_BASE = "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"

# ------------------------------------------------------------------ EOT20
EOT20_URL = "https://www.seanoe.org/data/00683/79489/data/85762.zip"
EOT20_CONSTITUENTS = ["2N2", "J1", "K1", "K2", "M2", "M4", "MF", "MM", "N2",
                      "O1", "P1", "Q1", "S1", "S2", "SA", "SSA", "T2"]

ATTRIBUTION = [
    "Copernicus Marine Service",
    "ECMWF (CC BY 4.0)",
    "DWD",
    "Météo-France",
    "NOAA",
    "EOT20 DGFI-TUM (CC BY 4.0)",
    "© OpenStreetMap contributors (ODbL)",
    "EEA (CC BY 4.0)",
    "Wikidata (CC0)",
]

# ------------------------------------------------------------------ Zones
# Display names per zone. Assignment rules live in spots.assign_zone().
ZONE_NAMES: dict[str, dict[str, str]] = {
    "fr-bretagne-nord": {"es": "Bretaña norte", "en": "North Brittany", "fr": "Bretagne nord", "pt": "Bretanha norte"},
    "fr-finistere": {"es": "Finisterre (Bretaña)", "en": "Finistère", "fr": "Finistère", "pt": "Finistère"},
    "fr-bretagne-sud": {"es": "Bretaña sur", "en": "South Brittany", "fr": "Bretagne sud", "pt": "Bretanha sul"},
    "fr-vendee-charente": {"es": "Vendée y Charente", "en": "Vendée & Charente", "fr": "Vendée et Charente", "pt": "Vendée e Charente"},
    "fr-gironde": {"es": "Gironda", "en": "Gironde", "fr": "Gironde", "pt": "Gironda"},
    "fr-landes": {"es": "Las Landas", "en": "Landes", "fr": "Landes", "pt": "Landes"},
    "fr-pays-basque": {"es": "País Vasco francés", "en": "French Basque coast", "fr": "Pays basque", "pt": "País Basco francês"},
    "es-costa-vasca": {"es": "Costa vasca", "en": "Basque coast", "fr": "Côte basque espagnole", "pt": "Costa basca"},
    "es-cantabria": {"es": "Cantabria", "en": "Cantabria", "fr": "Cantabrie", "pt": "Cantábria"},
    "es-asturias": {"es": "Asturias", "en": "Asturias", "fr": "Asturies", "pt": "Astúrias"},
    "es-galicia": {"es": "Galicia", "en": "Galicia", "fr": "Galice", "pt": "Galiza"},
    "es-golfo-cadiz": {"es": "Cádiz y Huelva", "en": "Cádiz & Huelva", "fr": "Cadix et Huelva", "pt": "Cádis e Huelva"},
    "es-lanzarote": {"es": "Lanzarote", "en": "Lanzarote", "fr": "Lanzarote", "pt": "Lanzarote"},
    "es-fuerteventura": {"es": "Fuerteventura", "en": "Fuerteventura", "fr": "Fuerteventura", "pt": "Fuerteventura"},
    "es-gran-canaria": {"es": "Gran Canaria", "en": "Gran Canaria", "fr": "Grande Canarie", "pt": "Gran Canaria"},
    "es-tenerife": {"es": "Tenerife", "en": "Tenerife", "fr": "Tenerife", "pt": "Tenerife"},
    "es-canarias-oeste": {"es": "La Palma, La Gomera y El Hierro", "en": "La Palma, La Gomera & El Hierro", "fr": "La Palma, La Gomera et El Hierro", "pt": "La Palma, La Gomera e El Hierro"},
    "pt-norte": {"es": "Norte de Portugal", "en": "Northern Portugal", "fr": "Nord du Portugal", "pt": "Norte"},
    "pt-centro-oeste": {"es": "Centro y Oeste (Peniche, Ericeira)", "en": "Centre & Oeste (Peniche, Ericeira)", "fr": "Centre et Oeste (Peniche, Ericeira)", "pt": "Centro e Oeste"},
    "pt-lisboa": {"es": "Lisboa", "en": "Lisbon", "fr": "Lisbonne", "pt": "Lisboa"},
    "pt-alentejo": {"es": "Alentejo", "en": "Alentejo", "fr": "Alentejo", "pt": "Alentejo"},
    "pt-algarve": {"es": "Algarve", "en": "Algarve", "fr": "Algarve", "pt": "Algarve"},
    "pt-madeira": {"es": "Madeira", "en": "Madeira", "fr": "Madère", "pt": "Madeira"},
    "ma-nord": {"es": "Tánger y Kenitra", "en": "Tangier & Kenitra", "fr": "Tanger et Kénitra", "pt": "Tânger e Kenitra"},
    "ma-rabat-casablanca": {"es": "Rabat y Casablanca", "en": "Rabat & Casablanca", "fr": "Rabat et Casablanca", "pt": "Rabat e Casablanca"},
    "ma-safi-essaouira": {"es": "Safi y Essaouira", "en": "Safi & Essaouira", "fr": "Safi et Essaouira", "pt": "Safi e Essaouira"},
    "ma-agadir": {"es": "Agadir y Taghazout", "en": "Agadir & Taghazout", "fr": "Agadir et Taghazout", "pt": "Agadir e Taghazout"},
    "ma-sud": {"es": "Sidi Ifni a Tarfaya", "en": "Sidi Ifni to Tarfaya", "fr": "Sidi Ifni à Tarfaya", "pt": "Sidi Ifni a Tarfaya"},
    "ma-dakhla": {"es": "Dakhla y costa sur", "en": "Dakhla & south coast", "fr": "Dakhla et côte sud", "pt": "Dakhla e costa sul"},
}
