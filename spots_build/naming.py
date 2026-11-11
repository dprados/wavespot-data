"""Names, slugs and ids."""
import re
import unicodedata

_LATIN_RE = re.compile(r"^[\s\w'’\-\.,()/&ºª°·]+$")


def is_latin(s):
    if not s:
        return False
    for ch in s:
        if ch.isalpha():
            name = unicodedata.name(ch, "")
            if "LATIN" not in name:
                return False
    return True


LANG_PREF = {
    "ES": ["name", "name:es", "name:gl", "name:eu", "name:ast", "name:en", "name:fr"],
    "PT": ["name", "name:pt", "name:en", "name:es", "name:fr"],
    "FR": ["name", "name:fr", "name:br", "name:en"],
    "MA": ["name:fr", "name:en", "name:es", "name:latin", "name"],
}


def pick_name(tags, cc):
    """Primary display name (Latin script) and aliases from OSM tags."""
    names = []
    for k in LANG_PREF[cc] + ["alt_name"]:
        v = (tags.get(k) or "").strip()
        if v and is_latin(v) and v not in names:
            names.append(v)
    if not names:
        # In Morocco `name` is often "Plage X ⵜⵉⴼⵉⵏⴰⵖ شاطئ" - keep only the Latin prefix if any.
        lp = latin_prefix(tags.get("name") or "")
        if lp and len(lp) >= 3:
            return lp, []
        return None, []
    return names[0], names[1:]


def latin_prefix(s):
    """'Plage Lalla Fatna ⴰⴼⵜⴰⵙ شاطئ' -> 'Plage Lalla Fatna'."""
    out = []
    for tok in s.split():
        if is_latin(tok):
            out.append(tok)
        else:
            break
    return " ".join(out).strip(" -–·,") or None


def slugify(s):
    s = s.replace("’", "'").replace("ß", "ss").replace("æ", "ae").replace("ø", "o").replace("Ø", "o")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


_SMALL = {"de", "del", "la", "las", "los", "el", "da", "das", "do", "dos", "e", "y", "du", "des",
          "le", "les", "sur", "en", "au", "aux", "et", "a", "o", "os", "as", "di", "na", "no", "ar"}


def _cap(tok, first):
    if not tok:
        return tok
    low = tok.lower()
    m = re.match(r"^([dl])'(.+)$", low)
    if m:
        return (m.group(1).upper() if first else m.group(1)) + "'" + _cap(m.group(2), True)
    if not first and low in _SMALL:
        return low
    return low[0].upper() + low[1:]


_LEAD = {"playa", "praia", "plage", "cala", "caleta", "hondartza", "porto", "puerto"}


def title_case(s):
    """Title case for ALL-CAPS official names; articles stay lower except right after 'Playa'."""
    parts = re.split(r"(\s+|-)", s.strip())
    out, first, prev = [], True, ""
    for p in parts:
        if p.strip() and p != "-":
            out.append(_cap(p, first or prev in _LEAD))
            first = False
            prev = p.lower()
        else:
            out.append(p)
    return "".join(out)


_ART = r"(EL|LA|LOS|LAS|O|A|OS|AS|LE|LES|L')"


def clean_eea_name(raw):
    """'PLAYA CABEZO (EL) PM1' -> 'Playa El Cabezo'; 'ST-AUBIN-PLAGE' -> 'St-Aubin-Plage'."""
    s = raw.strip()
    s = re.sub(r"\s+PM\s*\d+\s*$", "", s)
    s = re.sub(r"\s+(PM|ZB|Z\.?B\.?)\s*\d*$", "", s)
    m = re.match(rf"^(PLAYA|PRAIA|PLAGE|CALA)\s+(DE\s+)?(.+?)\s*\({_ART}\)(.*)$", s)
    if m:
        art = m.group(4)
        s = f"{m.group(1)} {art} {m.group(3)}{m.group(5)}"
    else:
        m = re.match(rf"^(.+?)\s*\({_ART}\)(.*)$", s)
        if m:
            s = f"{m.group(2)} {m.group(1)}{m.group(3)}"
    s = re.sub(r"\s+", " ", s).replace("L' ", "L'")
    return title_case(s)


# ---------- synthetic names ----------
_DIRS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]  # Romance abbreviations (es/pt/fr)


def compass8(bearing):
    return _DIRS[int(((bearing % 360) + 22.5) // 45) % 8]


def _of_place(cc, place):
    """'Costa de X' / 'Côte de X' handling articles."""
    p = place.strip()
    if cc == "ES":
        if p.startswith("El "):
            return "Costa del " + p[3:]
        return "Costa de " + p
    if cc == "PT":
        for art, rep in (("O ", "do "), ("A ", "da "), ("Os ", "dos "), ("As ", "das ")):
            if p.startswith(art):
                return "Costa " + rep + p[len(art):]
        return "Costa de " + p
    # FR and MA (French is the usual Latin-script language for Moroccan place names)
    for art, rep in (("Le ", "du "), ("Les ", "des "), ("La ", "de la "), ("L'", "de l'")):
        if p.startswith(art):
            return "Côte " + rep + p[len(art):]
    if p[:1].lower() in "aeiouyéèêâîôû":
        return "Côte d'" + p
    return "Côte de " + p


def synthetic_name(cc, place, dist_km, bearing_from_place):
    base = _of_place(cc, place)
    if dist_km < 1.5:
        return base
    return f"{base} ({int(round(dist_km))} km {compass8(bearing_from_place)})"


def synthetic_id(cc, lat, lon):
    return f"{cc.lower()}-p-{lat:.4f}-{lon:.4f}"
