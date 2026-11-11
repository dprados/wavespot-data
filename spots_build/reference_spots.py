"""Reference spots for validating the automatic orientation.

Reference facing = direction the break faces towards open sea, from public knowledge
(coast geometry, published ideal offshore wind = facing+180, official tourism/federation
descriptions). 16-point compass precision, so each reference carries +-11 deg of its own
uncertainty. Coordinates are taken from the matching OSM feature (beach / surf-zone node) when one
exists, otherwise approximate (+-300 m). Commercial forecast sites were NOT used.
"""

# name, lat, lon, reference facing (deg)
REFERENCE_SPOTS = [
    ("Mundaka", 43.4081, -2.6942, 340),
    ("Zarautz", 43.2883, -2.1668, 0),
    ("Sopelana (Arrietara)", 43.3880, -2.9966, 315),
    ("Zurriola (Donostia)", 43.3263, -1.9754, 0),
    ("Somo", 43.4591, -3.7332, 350),
    ("Liencres (Canallave)", 43.4526, -3.9619, 330),
    ("Rodiles", 43.5338, -5.3796, 0),
    ("Salinas (El Espartal)", 43.5824, -5.9544, 340),
    ("Pantin", 43.6391, -8.1153, 300),
    ("Doninos", 43.4940, -8.3208, 285),
    ("Razo", 43.2934, -8.7016, 330),
    ("Patos (Nigran)", 42.1546, -8.8270, 270),
    ("El Palmar (Vejer)", 36.2208, -6.0640, 225),
    ("Los Lances (Tarifa)", 36.0215, -5.6179, 210),
    ("Espinho", 41.0075, -8.6463, 270),
    ("Matosinhos", 41.1769, -8.6929, 250),
    ("Nazare Praia do Norte", 39.6080, -9.0800, 285),
    ("Supertubos (Peniche)", 39.3457, -9.3647, 225),
    ("Ribeira d'Ilhas", 38.9878, -9.4191, 265),
    ("Foz do Lizandro", 38.9421, -9.4144, 270),
    ("Guincho", 38.7337, -9.4727, 270),
    ("Carcavelos", 38.6795, -9.3351, 190),
    ("Costa da Caparica", 38.6396, -9.2370, 250),
    ("Arrifana", 37.2926, -8.8652, 285),
    ("Tonel (Sagres)", 37.0061, -8.9478, 260),
    ("Mareta (Sagres)", 37.0055, -8.9391, 180),
    ("Jardim do Mar", 32.7380, -17.2090, 220),
    ("Cote des Basques (Biarritz)", 43.4780, -1.5670, 280),
    ("Grande Plage (Biarritz)", 43.4852, -1.5589, 300),
    ("Parlementia (Guethary)", 43.4282, -1.6068, 300),
    ("Hossegor La Graviere", 43.6713, -1.4420, 280),
    ("Lacanau Ocean", 45.0023, -1.2020, 270),
    ("Montalivet", 45.3780, -1.1600, 270),
    ("Les Sables d'Olonne", 46.4933, -1.7845, 200),
    ("La Torche", 47.8410, -4.3468, 255),
    ("El Cotillo", 28.6850, -14.0130, 270),
    ("La Santa (Lanzarote)", 29.1199, -13.6577, 330),
    ("Famara", 29.1170, -13.5644, 320),
    ("El Confital (Las Palmas)", 28.1579, -15.4364, 330),
    ("Mehdia", 34.2558, -6.6792, 300),
    ("Plage de Safi", 32.3174, -9.2518, 280),
    ("Sidi Kaouki", 31.3533, -9.7966, 270),
    ("Imsouane (The Bay)", 30.8372, -9.8198, 200),
    ("Anchor Point", 30.5460, -9.7120, 225),
]
