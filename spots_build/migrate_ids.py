"""One-off: rewrite synthetic ids in data/spots/layer1.json to the current format.

The full build needs the big OSM caches; this keeps every other field intact and
re-derives the synthetic id from the coordinates encoded in the old id.

    python spots_build/migrate_ids.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import naming  # noqa: E402
from config import OUT_DIR  # noqa: E402

OLD = re.compile(r"^([a-z]{2})-p-(-?\d+\.\d{4})-(-?\d+\.\d{4})$")


def main():
    path = os.path.join(OUT_DIR, "layer1.json")
    with open(path) as f:
        spots = json.load(f)
    n = 0
    for s in spots:
        m = OLD.match(s["id"])
        if m:
            s["id"] = naming.synthetic_id(m.group(1).upper(), float(m.group(2)), float(m.group(3)))
            n += 1
    assert len({s["id"] for s in spots}) == len(spots)
    with open(path, "w") as f:
        json.dump(spots, f, ensure_ascii=False, separators=(",", ":"))
    print(f"rewrote {n} synthetic ids")


if __name__ == "__main__":
    main()
