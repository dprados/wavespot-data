"""Human zones for layer 1 with localized names and bboxes.

bbox = [south, west, north, east]. A point gets the smallest matching bbox of its country;
if none matches, the nearest bbox of its country.
Languages: es, pt, fr, en, de, ca, eu, gl.
"""
import math

LANGS = ["es", "pt", "fr", "en", "de", "ca", "eu", "gl"]


def _n(es, pt=None, fr=None, en=None, de=None, ca=None, eu=None, gl=None):
    d = {"es": es, "pt": pt or es, "fr": fr or es, "en": en or es, "de": de or en or es,
         "ca": ca or es, "eu": eu or es, "gl": gl or es}
    return d


# (id, country, bbox, names)
ZONES = [
    # ---------------- Spain: Cantabrian coast ----------------
    ("es-costa-vasca", "ES", [43.25, -3.17, 43.50, -1.78],
     _n("Costa vasca", "Costa basca", "Côte basque espagnole", "Basque coast", "Baskische Küste",
        "Costa basca", "Euskal kostaldea", "Costa vasca")),
    ("es-cantabria", "ES", [43.25, -4.52, 43.55, -3.17],
     _n("Cantabria", "Cantábria", "Cantabrie", "Cantabria", "Kantabrien", "Cantàbria", "Kantabria", "Cantabria")),
    ("es-asturias-oriente", "ES", [43.35, -5.75, 43.60, -4.52],
     _n("Asturias oriental", "Astúrias oriental", "Asturies orientales", "Eastern Asturias", "Ost-Asturien",
        "Astúries oriental", "Asturias ekialdea", "Asturias oriental")),
    ("es-asturias-centro", "ES", [43.45, -6.30, 43.70, -5.75],
     _n("Asturias central", "Astúrias central", "Asturies centrales", "Central Asturias", "Zentral-Asturien",
        "Astúries central", "Asturias erdialdea", "Asturias central")),
    ("es-asturias-occidente", "ES", [43.45, -7.05, 43.65, -6.30],
     _n("Asturias occidental", "Astúrias ocidental", "Asturies occidentales", "Western Asturias", "West-Asturien",
        "Astúries occidental", "Asturias mendebaldea", "Asturias occidental")),
    ("es-a-marina", "ES", [43.40, -7.70, 43.80, -7.05],
     _n("A Mariña lucense", "A Mariña lucense", "A Mariña (Lugo)", "A Mariña (Lugo coast)", "A Mariña (Lugo)",
        "A Mariña lucense", "A Mariña", "A Mariña lucense")),
    ("es-galicia-rias-altas", "ES", [43.25, -8.58, 43.80, -7.70],
     _n("Rías Altas (Ferrol–A Coruña)", "Rias Altas (Ferrol–Corunha)", "Rías Altas (Ferrol–La Corogne)",
        "Rías Altas (Ferrol–A Coruña)", "Rías Altas (Ferrol–A Coruña)", "Rías Altas (Ferrol–la Corunya)",
        "Rías Altas (Ferrol–A Coruña)", "Rías Altas (Ferrol–A Coruña)")),
    ("es-costa-da-morte", "ES", [42.75, -9.35, 43.40, -8.58],
     _n("Costa da Morte", "Costa da Morte", "Costa da Morte", "Costa da Morte", "Costa da Morte",
        "Costa da Morte", "Costa da Morte", "Costa da Morte")),
    ("es-rias-baixas", "ES", [41.86, -9.20, 42.75, -8.55],
     _n("Rías Baixas", "Rias Baixas", "Rías Baixas", "Rías Baixas", "Rías Baixas",
        "Rías Baixas", "Rías Baixas", "Rías Baixas")),
    # ---------------- Spain: Andalusia Atlantic ----------------
    ("es-huelva", "ES", [36.85, -7.40, 37.30, -6.34],
     _n("Costa de Huelva", "Costa de Huelva", "Côte de Huelva", "Huelva coast", "Küste von Huelva",
        "Costa de Huelva", "Huelvako kostaldea", "Costa de Huelva")),
    ("es-cadiz-norte", "ES", [36.38, -6.45, 36.85, -6.10],
     _n("Cádiz norte (Chipiona–Cádiz)", "Cádis norte (Chipiona–Cádis)", "Cadix nord (Chipiona–Cadix)",
        "North Cádiz (Chipiona–Cádiz)", "Nord-Cádiz (Chipiona–Cádiz)", "Cadis nord (Chipiona–Cadis)",
        "Cadiz iparraldea", "Cádiz norte (Chipiona–Cádiz)")),
    ("es-la-janda", "ES", [36.05, -6.20, 36.42, -5.78],
     _n("Costa de La Janda (Conil–Bolonia)", "Costa de La Janda (Conil–Bolonia)", "Côte de La Janda (Conil–Bolonia)",
        "La Janda coast (Conil–Bolonia)", "Küste von La Janda (Conil–Bolonia)", "Costa de La Janda (Conil–Bolonia)",
        "La Janda kostaldea (Conil–Bolonia)", "Costa da Janda (Conil–Bolonia)")),
    ("es-tarifa", "ES", [35.95, -5.80, 36.10, -5.59],
     _n("Tarifa", "Tarifa", "Tarifa", "Tarifa", "Tarifa", "Tarifa", "Tarifa", "Tarifa")),
    # ---------------- Canary Islands ----------------
    ("es-lanzarote", "ES", [28.80, -13.95, 29.45, -13.30],
     _n("Lanzarote y La Graciosa", "Lanzarote e La Graciosa", "Lanzarote et La Graciosa", "Lanzarote & La Graciosa",
        "Lanzarote und La Graciosa", "Lanzarote i La Graciosa", "Lanzarote eta La Graciosa", "Lanzarote e A Graciosa")),
    ("es-fuerteventura", "ES", [28.00, -14.55, 28.80, -13.80],
     _n("Fuerteventura", "Fuerteventura", "Fuerteventura", "Fuerteventura", "Fuerteventura",
        "Fuerteventura", "Fuerteventura", "Fuerteventura")),
    ("es-gran-canaria", "ES", [27.70, -15.90, 28.20, -15.30],
     _n("Gran Canaria", "Gran Canária", "Grande Canarie", "Gran Canaria", "Gran Canaria",
        "Gran Canària", "Kanaria Handia", "Gran Canaria")),
    ("es-tenerife", "ES", [27.95, -16.95, 28.62, -16.10],
     _n("Tenerife", "Tenerife", "Tenerife", "Tenerife", "Teneriffa", "Tenerife", "Tenerife", "Tenerife")),
    ("es-la-gomera", "ES", [27.95, -17.40, 28.25, -17.05],
     _n("La Gomera", "La Gomera", "La Gomera", "La Gomera", "La Gomera", "La Gomera", "La Gomera", "A Gomera")),
    ("es-la-palma", "ES", [28.40, -18.05, 28.90, -17.70],
     _n("La Palma", "La Palma", "La Palma", "La Palma", "La Palma", "La Palma", "La Palma", "A Palma")),
    ("es-el-hierro", "ES", [27.60, -18.20, 27.90, -17.85],
     _n("El Hierro", "El Hierro", "El Hierro", "El Hierro", "El Hierro", "El Hierro", "El Hierro", "O Hierro")),
    # ---------------- Portugal ----------------
    ("pt-minho", "PT", [41.40, -8.95, 41.87, -8.60],
     _n("Minho (Caminha–Póvoa de Varzim)", "Minho (Caminha–Póvoa de Varzim)", "Minho (Caminha–Póvoa de Varzim)",
        "Minho (Caminha–Póvoa de Varzim)", "Minho (Caminha–Póvoa de Varzim)", "Minho (Caminha–Póvoa de Varzim)",
        "Minho (Caminha–Póvoa de Varzim)", "Miño (Caminha–Póvoa de Varzim)")),
    ("pt-porto", "PT", [40.90, -8.80, 41.40, -8.55],
     _n("Oporto y Espinho", "Porto e Espinho", "Porto et Espinho", "Porto & Espinho", "Porto und Espinho",
        "Porto i Espinho", "Porto eta Espinho", "Porto e Espinho")),
    ("pt-aveiro", "PT", [40.30, -8.90, 40.90, -8.60],
     _n("Costa de Aveiro", "Costa de Aveiro", "Côte d'Aveiro", "Aveiro coast", "Küste von Aveiro",
        "Costa d'Aveiro", "Aveiroko kostaldea", "Costa de Aveiro")),
    ("pt-figueira-leiria", "PT", [39.65, -9.05, 40.30, -8.75],
     _n("Figueira da Foz y Leiria", "Figueira da Foz e Leiria", "Figueira da Foz et Leiria", "Figueira da Foz & Leiria",
        "Figueira da Foz und Leiria", "Figueira da Foz i Leiria", "Figueira da Foz eta Leiria", "Figueira da Foz e Leiria")),
    ("pt-nazare", "PT", [39.45, -9.15, 39.65, -8.95],
     _n("Nazaré", "Nazaré", "Nazaré", "Nazaré", "Nazaré", "Nazaré", "Nazaré", "Nazaré")),
    ("pt-peniche", "PT", [39.25, -9.60, 39.45, -9.15],
     _n("Peniche", "Peniche", "Peniche", "Peniche", "Peniche", "Peniche", "Peniche", "Peniche")),
    ("pt-ericeira", "PT", [38.85, -9.50, 39.25, -9.25],
     _n("Ericeira y Oeste", "Ericeira e Oeste", "Ericeira et Oeste", "Ericeira & Oeste", "Ericeira und Oeste",
        "Ericeira i Oeste", "Ericeira eta Oeste", "Ericeira e Oeste")),
    ("pt-lisboa", "PT", [38.56, -9.55, 38.85, -9.05],
     _n("Lisboa (Sintra–Cascais–Caparica)", "Lisboa (Sintra–Cascais–Caparica)", "Lisbonne (Sintra–Cascais–Caparica)",
        "Lisbon (Sintra–Cascais–Caparica)", "Lissabon (Sintra–Cascais–Caparica)", "Lisboa (Sintra–Cascais–Caparica)",
        "Lisboa (Sintra–Cascais–Caparica)", "Lisboa (Sintra–Cascais–Caparica)")),
    ("pt-setubal", "PT", [38.36, -9.25, 38.56, -8.70],
     _n("Sesimbra, Arrábida y Troia", "Sesimbra, Arrábida e Troia", "Sesimbra, Arrábida et Troia",
        "Sesimbra, Arrábida & Troia", "Sesimbra, Arrábida und Troia", "Sesimbra, Arrábida i Troia",
        "Sesimbra, Arrábida eta Troia", "Sesimbra, Arrábida e Troia")),
    ("pt-alentejo", "PT", [37.40, -8.95, 38.36, -8.60],
     _n("Costa alentejana", "Costa Alentejana", "Côte de l'Alentejo", "Alentejo coast", "Alentejo-Küste",
        "Costa de l'Alentejo", "Alentejoko kostaldea", "Costa alentexana")),
    ("pt-costa-vicentina", "PT", [36.95, -9.05, 37.40, -8.75],
     _n("Costa Vicentina y Sagres", "Costa Vicentina e Sagres", "Costa Vicentina et Sagres", "Costa Vicentina & Sagres",
        "Costa Vicentina und Sagres", "Costa Vicentina i Sagres", "Costa Vicentina eta Sagres", "Costa Vicentina e Sagres")),
    ("pt-algarve", "PT", [36.90, -8.75, 37.25, -7.40],
     _n("Algarve sur", "Algarve sul", "Algarve sud", "South Algarve", "Süd-Algarve",
        "Algarve sud", "Algarve hegoaldea", "Algarve sur")),
    ("pt-madeira", "PT", [32.35, -17.35, 33.15, -16.10],
     _n("Madeira y Porto Santo", "Madeira e Porto Santo", "Madère et Porto Santo", "Madeira & Porto Santo",
        "Madeira und Porto Santo", "Madeira i Porto Santo", "Madeira eta Porto Santo", "Madeira e Porto Santo")),
    # ---------------- France ----------------
    ("fr-pays-basque", "FR", [43.30, -1.80, 43.53, -1.40],
     _n("País Vasco francés", "País Basco francês", "Pays basque", "French Basque Country", "Französisches Baskenland",
        "País Basc francès", "Lapurdi", "País Vasco francés")),
    ("fr-landes-sud", "FR", [43.53, -1.55, 43.80, -1.30],
     _n("Landas sur (Hossegor–Capbreton)", "Landes sul (Hossegor–Capbreton)", "Sud Landes (Hossegor–Capbreton)",
        "South Landes (Hossegor–Capbreton)", "Süd-Landes (Hossegor–Capbreton)", "Landes sud (Hossegor–Capbreton)",
        "Landak hegoaldea (Hossegor–Capbreton)", "Landas sur (Hossegor–Capbreton)")),
    ("fr-landes-nord", "FR", [43.80, -1.40, 44.53, -1.10],
     _n("Landas norte", "Landes norte", "Nord Landes", "North Landes", "Nord-Landes",
        "Landes nord", "Landak iparraldea", "Landas norte")),
    ("fr-gironde", "FR", [44.53, -1.35, 45.60, -0.85],
     _n("Gironda (Lacanau–Cap Ferret)", "Gironda (Lacanau–Cap Ferret)", "Gironde (Lacanau–Cap Ferret)",
        "Gironde (Lacanau–Cap Ferret)", "Gironde (Lacanau–Cap Ferret)", "Gironda (Lacanau–Cap Ferret)",
        "Gironda (Lacanau–Cap Ferret)", "Xironda (Lacanau–Cap Ferret)")),
    ("fr-charente", "FR", [45.55, -1.60, 46.33, -0.85],
     _n("Charente Marítimo (Oléron–Ré)", "Charente-Maritime (Oléron–Ré)", "Charente-Maritime (Oléron–Ré)",
        "Charente-Maritime (Oléron–Ré)", "Charente-Maritime (Oléron–Ré)", "Charente Marítim (Oléron–Ré)",
        "Itsas Charente (Oléron–Ré)", "Charente Marítimo (Oléron–Ré)")),
    ("fr-vendee", "FR", [46.25, -2.40, 47.05, -1.10],
     _n("Vendée", "Vendeia", "Vendée", "Vendée", "Vendée", "Vendée", "Vendée", "Vendée")),
    ("fr-loire-atlantique", "FR", [47.00, -2.60, 47.45, -1.90],
     _n("Loira Atlántico (La Baule–Pornic)", "Loire-Atlantique (La Baule–Pornic)", "Loire-Atlantique (La Baule–Pornic)",
        "Loire-Atlantique (La Baule–Pornic)", "Loire-Atlantique (La Baule–Pornic)", "Loira Atlàntic (La Baule–Pornic)",
        "Loira Atlantikoa (La Baule–Pornic)", "Loira Atlántico (La Baule–Pornic)")),
    ("fr-morbihan", "FR", [47.25, -3.60, 47.85, -2.40],
     _n("Morbihan (Quiberon–Lorient)", "Morbihan (Quiberon–Lorient)", "Morbihan (Quiberon–Lorient)",
        "Morbihan (Quiberon–Lorient)", "Morbihan (Quiberon–Lorient)", "Morbihan (Quiberon–Lorient)",
        "Morbihan (Quiberon–Lorient)", "Morbihan (Quiberon–Lorient)")),
    ("fr-finistere-sud", "FR", [47.70, -4.95, 48.18, -3.50],
     _n("Finisterre sur (La Torche–Douarnenez)", "Finistère sul (La Torche–Douarnenez)",
        "Sud Finistère (La Torche–Douarnenez)", "South Finistère (La Torche–Douarnenez)",
        "Süd-Finistère (La Torche–Douarnenez)", "Finisterre sud (La Torche–Douarnenez)",
        "Finisterre hegoaldea (La Torche–Douarnenez)", "Finisterre sur (La Torche–Douarnenez)")),
    ("fr-finistere-ouest", "FR", [48.18, -5.20, 48.52, -4.15],
     _n("Iroise y Crozon", "Iroise e Crozon", "Iroise et presqu'île de Crozon", "Iroise & Crozon",
        "Iroise und Crozon", "Iroise i Crozon", "Iroise eta Crozon", "Iroise e Crozon")),
    ("fr-finistere-nord", "FR", [48.52, -5.20, 48.80, -3.85],
     _n("Finisterre norte (Léon)", "Finistère norte (Léon)", "Nord Finistère (Léon)", "North Finistère (Léon)",
        "Nord-Finistère (Léon)", "Finisterre nord (Léon)", "Finisterre iparraldea (Léon)", "Finisterre norte (Léon)")),
    ("fr-cotes-darmor", "FR", [48.45, -3.85, 48.95, -2.15],
     _n("Costas de Armor", "Côtes-d'Armor", "Côtes-d'Armor", "Côtes-d'Armor", "Côtes-d'Armor",
        "Costes d'Armor", "Armorreko kostaldeak", "Costas de Armor")),
    ("fr-cote-emeraude", "FR", [48.50, -2.15, 48.75, -1.55],
     _n("Costa Esmeralda (Saint-Malo)", "Costa Esmeralda (Saint-Malo)", "Côte d'Émeraude (Saint-Malo)",
        "Emerald Coast (Saint-Malo)", "Smaragdküste (Saint-Malo)", "Costa Maragda (Saint-Malo)",
        "Esmeralda kostaldea (Saint-Malo)", "Costa Esmeralda (Saint-Malo)")),
    # ---------------- Morocco ----------------
    ("ma-tanger-asilah", "MA", [35.30, -6.20, 35.95, -5.74],
     _n("Tánger y Asilah", "Tânger e Asilah", "Tanger et Asilah", "Tangier & Asilah", "Tanger und Asilah",
        "Tànger i Asilah", "Tanger eta Asilah", "Tánxer e Asilah")),
    ("ma-larache-kenitra", "MA", [34.35, -6.50, 35.30, -5.90],
     _n("Larache y Moulay Bousselham", "Larache e Moulay Bousselham", "Larache et Moulay Bousselham",
        "Larache & Moulay Bousselham", "Larache und Moulay Bousselham", "Larache i Moulay Bousselham",
        "Larache eta Moulay Bousselham", "Larache e Moulay Bousselham")),
    ("ma-rabat-casablanca", "MA", [33.40, -7.95, 34.35, -6.50],
     _n("Rabat y Casablanca", "Rabat e Casablanca", "Rabat et Casablanca", "Rabat & Casablanca",
        "Rabat und Casablanca", "Rabat i Casablanca", "Rabat eta Casablanca", "Rabat e Casablanca")),
    ("ma-el-jadida-oualidia", "MA", [32.55, -9.15, 33.40, -7.95],
     _n("El Jadida y Oualidia", "El Jadida e Oualidia", "El Jadida et Oualidia", "El Jadida & Oualidia",
        "El Jadida und Oualidia", "El Jadida i Oualidia", "El Jadida eta Oualidia", "El Jadida e Oualidia")),
    ("ma-safi", "MA", [31.90, -9.40, 32.55, -9.00],
     _n("Safi", "Safi", "Safi", "Safi", "Safi", "Safi", "Safi", "Safi")),
    ("ma-essaouira", "MA", [31.00, -9.90, 31.90, -9.40],
     _n("Essaouira", "Essaouira", "Essaouira", "Essaouira", "Essaouira", "Essaouira", "Essaouira", "Essaouira")),
    ("ma-imsouane", "MA", [30.75, -9.90, 31.00, -9.55],
     _n("Imsouane", "Imsouane", "Imsouane", "Imsouane", "Imsouane", "Imsouane", "Imsouane", "Imsouane")),
    ("ma-taghazout-agadir", "MA", [30.30, -9.90, 30.75, -9.55],
     _n("Taghazout y Agadir", "Taghazout e Agadir", "Taghazout et Agadir", "Taghazout & Agadir",
        "Taghazout und Agadir", "Taghazout i Agadir", "Taghazout eta Agadir", "Taghazout e Agadir")),
    ("ma-souss-tiznit", "MA", [29.50, -10.20, 30.30, -9.55],
     _n("Souss y Tiznit (Aglou–Mirleft)", "Souss e Tiznit (Aglou–Mirleft)", "Souss et Tiznit (Aglou–Mirleft)",
        "Souss & Tiznit (Aglou–Mirleft)", "Souss und Tiznit (Aglou–Mirleft)", "Souss i Tiznit (Aglou–Mirleft)",
        "Souss eta Tiznit (Aglou–Mirleft)", "Souss e Tiznit (Aglou–Mirleft)")),
    ("ma-sidi-ifni", "MA", [28.50, -11.30, 29.50, -10.05],
     _n("Sidi Ifni y Guelmim", "Sidi Ifni e Guelmim", "Sidi Ifni et Guelmim", "Sidi Ifni & Guelmim",
        "Sidi Ifni und Guelmim", "Sidi Ifni i Guelmim", "Sidi Ifni eta Guelmim", "Sidi Ifni e Guelmim")),
    ("ma-tan-tan-tarfaya", "MA", [27.50, -13.20, 28.50, -11.15],
     _n("Tan-Tan y Tarfaya", "Tan-Tan e Tarfaya", "Tan-Tan et Tarfaya", "Tan-Tan & Tarfaya",
        "Tan-Tan und Tarfaya", "Tan-Tan i Tarfaya", "Tan-Tan eta Tarfaya", "Tan-Tan e Tarfaya")),
    ("ma-laayoune-boujdour", "MA", [25.50, -14.95, 27.50, -13.20],
     _n("El Aaiún y Bojador", "El Aaiún e Bojador", "Laâyoune et Boujdour", "Laayoune & Boujdour",
        "Laâyoune und Boujdour", "El Aaiún i Bojador", "El Aaiún eta Bojador", "El Aaiún e Bojador")),
    ("ma-dakhla", "MA", [22.80, -16.60, 25.50, -14.50],
     _n("Dajla", "Dakhla", "Dakhla", "Dakhla", "Dakhla", "Dakhla", "Dakhla", "Dakhla")),
    ("ma-lagouira", "MA", [20.76, -17.25, 22.80, -16.30],
     _n("Costa sur (Lagüera)", "Costa sul (Lagouira)", "Côte sud (Lagouira)", "Southern coast (Lagouira)",
        "Südküste (Lagouira)", "Costa sud (Lagouira)", "Hegoaldeko kostaldea (Lagouira)", "Costa sur (Lagouira)")),
]

ZONE_BY_ID = {z[0]: z for z in ZONES}


def _bbox_dist(lat, lon, bb):
    s, w, n, e = bb
    dy = max(s - lat, 0, lat - n)
    dx = max(w - lon, 0, lon - e) * math.cos(math.radians(lat))
    return math.hypot(dx, dy)


def _area(bb):
    return (bb[2] - bb[0]) * (bb[3] - bb[1])


def assign_zone(country, lat, lon):
    cands = [z for z in ZONES if z[1] == country]
    inside = [z for z in cands if _bbox_dist(lat, lon, z[2]) == 0]
    if inside:
        return min(inside, key=lambda z: _area(z[2]))[0]
    return min(cands, key=lambda z: _bbox_dist(lat, lon, z[2]))[0]


def zones_json(points=None):
    """Zone list per contract (index/meta.json `zones`), bbox tightened to points if given."""
    out = []
    for zid, cc, bb, names in ZONES:
        bbox = list(bb)
        if points is not None:
            pts = [p for p in points if p["zone"] == zid]
            if pts:
                bbox = [round(min(p["lat"] for p in pts) - 0.02, 3), round(min(p["lon"] for p in pts) - 0.02, 3),
                        round(max(p["lat"] for p in pts) + 0.02, 3), round(max(p["lon"] for p in pts) + 0.02, 3)]
        out.append({"id": zid, "country": cc, "name": names, "bbox": bbox})
    return out
