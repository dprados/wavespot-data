"""Fetch beaches (and surf spots) from Wikidata (CC0) inside the scope boxes.

Writes CACHE/wikidata_beaches.json: [{qid, lat, lon, labels:{lang: label}}].
Usage: python -I spots_build/fetch_wikidata.py
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402

ENDPOINT = "https://query.wikidata.org/sparql"
LANGS = ["es", "pt", "fr", "en", "gl", "eu", "ast", "ca"]
# beach, surf spot, surf break, reef break, beach break
CLASSES = "wd:Q40080 wd:Q2368508 wd:Q3482498 wd:Q3423020 wd:Q99658891"

QUERY = """
SELECT ?i ?coord ?l ?lang WHERE {
  SERVICE wikibase:box {
    ?i wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point(%(w)f %(s)f)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point(%(e)f %(n)f)"^^geo:wktLiteral .
  }
  VALUES ?cls { %(classes)s }
  ?i wdt:P31/wdt:P279? ?cls .
  OPTIONAL { ?i rdfs:label ?l . BIND(LANG(?l) AS ?lang) FILTER(?lang IN (%(langs)s)) }
}
"""


def fetch(box):
    s, w, n, e = box
    q = QUERY % {"s": s, "w": w, "n": n, "e": e, "classes": CLASSES,
                 "langs": ",".join(f'"{x}"' for x in LANGS)}
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": "wavespot-data-pipeline/1.0 (open data build)"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)["results"]["bindings"]
        except Exception as ex:  # noqa: BLE001
            print("retry", box, ex, flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"wikidata failed for {box}")


def main():
    items = {}
    for box in config.LAND_BOXES:
        rows = fetch(box)
        for r in rows:
            qid = r["i"]["value"].rsplit("/", 1)[-1]
            lon, lat = map(float, r["coord"]["value"].split("(")[1].rstrip(")").split())
            it = items.setdefault(qid, {"qid": qid, "lat": round(lat, 6), "lon": round(lon, 6), "labels": {}})
            if "l" in r:
                it["labels"][r["lang"]["value"]] = r["l"]["value"]
        print(box, len(rows), len(items), flush=True)
        time.sleep(2)
    os.makedirs(config.CACHE, exist_ok=True)
    with open(os.path.join(config.CACHE, "wikidata_beaches.json"), "w") as f:
        json.dump(list(items.values()), f, ensure_ascii=False)
    print("total", len(items))


if __name__ == "__main__":
    main()
