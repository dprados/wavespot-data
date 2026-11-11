"""Freshness/health check of the published data. Prints a Markdown report.

    python -m wavespot_pipeline.monitor https://dprados.github.io/wavespot-data/v1/

Exit 1 (=> the workflow opens an issue) when the last build is older than
--max-age hours, a source failed in the last build, or too many spots are stale.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request

from . import config


def check(meta: dict, now: dt.datetime, max_age_h: float, max_stale: float) -> tuple[bool, list[str]]:
    lines = []
    ok = True
    gen = dt.datetime.strptime(meta["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    age = (now - gen).total_seconds() / 3600
    lines.append(f"- Last build: `{meta['generated']}` ({age:.1f} h ago)")
    if age > max_age_h:
        ok = False
        lines.append(f"- **Data is older than {max_age_h:.0f} h** — the forecast workflow has not succeeded.")
    status = meta.get("status") or {}
    for name, st in sorted((status.get("sources") or {}).items()):
        mark = "ok" if st.get("ok") else "**FAILED**"
        lines.append(f"- Source `{name}`: {mark} — {st.get('detail', '')} (run {st.get('run', '-')}, "
                     f"{st.get('seconds', 0)} s)")
        if not st.get("ok"):
            ok = False
    spots = status.get("spots") or {}
    total = spots.get("total") or 0
    stale = spots.get("stale", 0) + spots.get("dropped", 0)
    lines.append(f"- Spots: {spots}")
    if total and stale / total > max_stale:
        ok = False
        lines.append(f"- **{stale}/{total} spots are stale or missing**")
    return ok, lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?", default=config.BASE_URL)
    ap.add_argument("--max-age", type=float, default=14.0)
    ap.add_argument("--max-stale", type=float, default=0.2)
    args = ap.parse_args(argv)
    url = args.base.rstrip("/") + "/index/meta.json"
    now = dt.datetime.now(dt.timezone.utc)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            meta = json.load(r)
    except Exception as e:
        print(f"Could not read {url}: {e}")
        return 1
    ok, lines = check(meta, now, args.max_age, args.max_stale)
    print(f"Wavespot data health ({now:%Y-%m-%d %H:%M} UTC): {'OK' if ok else 'PROBLEM'}\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
