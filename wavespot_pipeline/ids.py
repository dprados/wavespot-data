"""Permanent spot ids.

Users keep favourites, alerts and sessions by spot id, so a published id must
never disappear. `data/published_ids.txt` (versioned) lists every id ever
published; `data/aliases.json` maps retired ids to their current id. The build
publishes `index/aliases.json` and serves `spots/{old}.json` as a copy of the
current spot.

    python -m wavespot_pipeline.ids check     # fail if a published id has no spot and no alias
"""
from __future__ import annotations

import json
import os
import re
import sys

PUBLISHED = os.path.join("data", "published_ids.txt")
ALIASES = os.path.join("data", "aliases.json")
OLD_SYNTHETIC = re.compile(r"^([a-z]{2})-p-(-?\d+\.\d{4})-(-?\d+\.\d{4})$")


def load_published(path: str = PUBLISHED) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return {l.strip() for l in f if l.strip() and not l.startswith("#")}


def load_aliases(path: str = ALIASES) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f).get("aliases", {})


def migrate_synthetic(old: str) -> str | None:
    """Pre-2026-11-11 synthetic ids `cc-p-lat--lon` -> `cc-p-lat-wlon`."""
    m = OLD_SYNTHETIC.match(old)
    if not m:
        return None
    lat, lon = float(m.group(2)), float(m.group(3))
    return f"{m.group(1)}-p-{lat:.4f}-{'w' if lon < 0 else 'e'}{abs(lon):.4f}"


def resolve(published: set[str], current: set[str], merges: dict[str, str],
            previous: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Alias every published id that is not current. Returns (aliases, orphans)."""
    aliases, orphans = {}, []
    candidates = set(published) | set(previous) | set(merges)
    for old in sorted(candidates):
        if old in current:
            continue
        target, seen = old, set()
        while target not in current and target not in seen:
            seen.add(target)
            target = merges.get(target) or previous.get(target) or migrate_synthetic(target) or target
        if target in current:
            aliases[old] = target
        elif old in published:
            orphans.append(old)
    return aliases, orphans


def save(published: set[str], aliases: dict[str, str], published_path: str = PUBLISHED,
         aliases_path: str = ALIASES) -> None:
    os.makedirs(os.path.dirname(published_path) or ".", exist_ok=True)
    with open(published_path, "w") as f:
        f.write("# Every spot id ever published (append-only; see wavespot_pipeline/ids.py)\n")
        f.write("\n".join(sorted(published)) + "\n")
    with open(aliases_path, "w") as f:
        json.dump({"v": 1, "aliases": dict(sorted(aliases.items()))}, f, indent=0, ensure_ascii=False)
        f.write("\n")


def catalogue_check(spot_files, registry=None) -> tuple[dict[str, str], list[str]]:
    from .spots import load_spots

    merges: dict[str, str] = {}
    spots = load_spots(spot_files, registry, merges)
    return resolve(load_published(), {s["id"] for s in spots}, merges, load_aliases())


def main(argv=None) -> int:
    from .build import SPOT_FILES

    aliases, orphans = catalogue_check(SPOT_FILES)
    print(f"{len(aliases)} aliases, {len(orphans)} orphan ids")
    for o in orphans[:50]:
        print("orphan:", o)
    return 1 if orphans else 0


if __name__ == "__main__":
    sys.exit(main())
