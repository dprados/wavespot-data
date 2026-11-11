"""Static configuration for the layer-1 spot build: scope, countries, kite lagoons.

All boxes are (south, west, north, east) in WGS84 degrees.
"""
import os

# Cache dir for big downloads / intermediate files (never committed).
CACHE = os.environ.get(
    "WAVESPOT_SPOTS_CACHE",
    os.path.expanduser("~/.cache/wavespot-spots"),
)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "data", "spots")

# Geofabrik extracts used (download.geofabrik.de, ODbL).
PBF_FILES = [
    "europe/spain/galicia", "europe/spain/asturias", "europe/spain/cantabria",
    "europe/spain/pais-vasco", "europe/spain/andalucia", "africa/canary-islands",
    "europe/portugal", "europe/france/aquitaine", "europe/france/poitou-charentes",
    "europe/france/pays-de-la-loire", "europe/france/bretagne", "africa/morocco",
]

# Coarse scope boxes (with country). A point must fall in one of them AND pass
# `in_scope()` rules. Order matters for overlaps: first match wins.
SCOPE_BOXES = [
    ("ES", (27.4, -18.4, 29.6, -13.35)),     # Canary Islands (Moroccan coast is east of -13.3)
    ("PT", (32.3, -17.4, 33.2, -16.1)),      # Madeira + Porto Santo + Desertas
    ("ES", (41.865, -9.6, 44.0, -1.785)),    # Galicia .. Euskadi (north coast)
    ("FR", (43.30, -5.3, 48.95, -0.85)),     # Atlantic France (Pays Basque .. Brittany)
    ("PT", (36.85, -9.7, 41.87, -7.40)),     # mainland Portugal
    ("ES", (35.95, -7.40, 37.40, -5.595)),   # Andalusia Atlantic (Ayamonte .. Tarifa)
    ("MA", (20.76, -17.25, 35.95, -5.74)),   # Morocco Atlantic + Sahara coast
]


def country_of(lat, lon):
    """Country code for a coastal point inside scope, else None."""
    for cc, (s, w, n, e) in SCOPE_BOXES:
        if s <= lat <= n and w <= lon <= e:
            if not in_scope(cc, lat, lon):
                return None
            return cc
    return None


def in_scope(cc, lat, lon):
    if cc == "FR":
        # No Normandy: cut at the Couesnon (Mont-Saint-Michel bay); Chausey/Granville are out.
        if lat > 48.50 and lon > -1.51:
            return False
        if lat > 48.66 and lon > -1.70:
            return False
        if lat > 48.72 and lon > -1.95:
            return False
        # Spanish side of the Bidasoa handled by box order; French side only east of it.
        if lat < 43.30:
            return False
        return True
    if cc == "MA":
        # Mediterranean / Strait east of Cap Malabata is out.
        if lat > 35.2 and lon > -5.74:
            return False
        # Cap Blanc peninsula: east side (Baie du Levrier) is Mauritania.
        if lat < 21.40 and lon > -17.045:
            return False
        # Open ocean west of the coast: Selvagens (PT) and anything off-shore.
        if lat > 27.6 and lon < -13.3:
            return False
        return True
    if cc == "ES" and lat < 38 and lon > -5.595:
        return False  # Mediterranean Andalusia
    return True


# Padded boxes used to load land polygons around the scope.
LAND_BOXES = [
    (27.0, -18.8, 30.0, -12.6),
    (32.0, -17.8, 33.5, -15.8),
    (20.4, -17.6, 36.3, -5.2),
    (35.6, -10.2, 44.3, -5.2),
    (41.5, -10.2, 49.3, -0.5),
]

# Named lagoons/bays that are kite spots although their swell window is closed.
# Points inside these boxes with a narrow window get sports=["kite"].
KITE_LAGOONS = [
    ("Dakhla lagoon", (23.50, -15.98, 23.98, -15.58)),
    ("Lagune de Khnifiss (Naila)", (28.00, -12.32, 28.08, -12.18)),
    ("Lagune d'Oualidia", (32.70, -9.06, 32.76, -8.99)),
    ("Merja Zerga (Moulay Bousselham)", (34.80, -6.32, 34.90, -6.22)),
    ("Lagoa de Albufeira", (38.49, -9.20, 38.52, -9.14)),
    ("Lagoa de Obidos", (39.38, -9.24, 39.43, -9.17)),
    ("Ria Formosa (Faro)", (36.97, -7.97, 37.05, -7.85)),
    ("Bahia de Cadiz (Valdelagrana)", (36.55, -6.27, 36.60, -6.20)),
]


def kite_lagoon(lat, lon):
    for name, (s, w, n, e) in KITE_LAGOONS:
        if s <= lat <= n and w <= lon <= e:
            return name
    return None


# Orientation parameters (exposure-window method).
RAY_LEN_M = 20_000        # ray length; open if no land within this distance
RAY_STEP_DEG = 5          # angular resolution
CAND_RADIUS_M = 600       # coastline within this radius gives water candidates
CAND_OFFSET_M = 120       # candidate offset seaward from the coastline
MAX_CANDS = 12
NORMAL_RADIUS_M = 600    # coast used for the local normal around the chosen origin
NORMAL_MARGIN_DEG = 30    # keep the normal at least this far inside the open arc
NORMAL_WEIGHT = 0.5       # facing = centre + weight * (clamped normal - centre)
MIN_WINDOW_DEG = 20       # narrower windows are estuaries/harbours -> dropped
MIN_ISLAND_KM2 = 0.05     # ignore rocks/islets smaller than this for ray casting
MAX_COAST_DIST_M = {"beach": 1500, "bathing": 1500, "wikidata": 1500,
                    "cape": 800, "bay": 1500, "locality": 300}
DEDUPE_M = 300
# Localities/bays are only kept where no better (beach/bathing/cape) point lies within:
SUPPRESS_M = {"locality": 1000, "bay": 600}
GAP_RADIUS_M = 2500       # synthetic point if nothing within this radius (~5 km spacing)
