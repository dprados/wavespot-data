"""Last-good spot documents, so a spot is never published without data.

Primary store: `<cache>/lastgood/{id}.json` (persisted by actions/cache).
Fallback: the currently published file on GitHub Pages.
"""
from __future__ import annotations

import json
import os

from .sources.base import http_get, log


class LastGood:
    def __init__(self, cache_dir: str | None, base_url: str | None):
        self.dir = os.path.join(cache_dir, "lastgood") if cache_dir else None
        self.base_url = base_url
        if self.dir:
            os.makedirs(self.dir, exist_ok=True)

    def save(self, doc: dict, raw: str) -> None:
        if self.dir:
            with open(os.path.join(self.dir, f"{doc['id']}.json"), "w") as f:
                f.write(raw)

    def load(self, spot_id: str) -> dict | None:
        if self.dir:
            p = os.path.join(self.dir, f"{spot_id}.json")
            if os.path.exists(p):
                try:
                    with open(p) as f:
                        return json.load(f)
                except (OSError, ValueError):
                    pass
        if self.base_url:
            try:
                return json.loads(http_get(f"{self.base_url}spots/{spot_id}.json", timeout=20))
            except Exception as e:  # not published yet or site down
                log.info("no last-good for %s: %s", spot_id, e)
        return None
