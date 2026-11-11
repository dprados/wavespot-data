"""Stats (layer1_stats.md), reference accuracy and preview maps for layer 1.

Usage: python -I spots_build/report.py
"""
import collections
import json
import math
import os
import sys

import numpy as np
import shapely
from shapely.geometry import box

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config  # noqa: E402
import zones  # noqa: E402
from reference_spots import REFERENCE_SPOTS  # noqa: E402

KINDS = ["beach", "bathing", "wikidata", "cape", "bay", "locality", "synthetic"]
PREVIEWS = {
    "euskadi": (43.28, -3.05, 43.48, -1.75),
    "peniche": (39.20, -9.50, 39.50, -9.20),
    "taghazout": (30.35, -9.90, 30.90, -9.55),
}


def accuracy():
    from land import Land
    from orientation import Orienter, angdiff
    o = Orienter(Land())
    rows, errs = [], []
    for name, lat, lon, ref in REFERENCE_SPOTS:
        r = o.orient(lat, lon)
        e = abs(angdiff(r["facing"], ref))
        errs.append(e)
        rows.append((name, ref, r["facing"], e, r["window"]))
    return rows, np.array(errs)


def render(points, land, name, bb):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s, w, n, e = bb
    lat0 = (s + n) / 2
    aspect = (n - s) / ((e - w) * math.cos(math.radians(lat0)))
    fig, ax = plt.subplots(figsize=(16, max(5, 16 * aspect)) if aspect < 1 else (11, 11 * aspect))
    clip = box(w, s, e, n)
    for g in land.pieces[land.piece_tree.query(clip)]:
        for q in shapely.get_parts(shapely.intersection(g, clip)):
            if q.geom_type == "Polygon":
                x, y = q.exterior.xy
                ax.fill(x, y, color="#dedad2", lw=0)
    pts = [p for p in points if s <= p["lat"] <= n and w <= p["lon"] <= e]
    cmap = plt.get_cmap("hsv")
    kx = 1 / math.cos(math.radians(lat0))
    L = max(n - s, (e - w) / kx) / 70
    for p in pts:
        f = p["info"]["facing"]
        col = cmap(f / 360)
        mk = "^" if p["kind"] == "synthetic" else "o"
        ax.plot(p["lon"], p["lat"], mk, color=col, ms=5, mec="k", mew=0.3)
        ax.plot([p["lon"], p["lon"] + L * kx * math.sin(math.radians(f))],
                [p["lat"], p["lat"] + L * math.cos(math.radians(f))], color=col, lw=1.2)
        if p["kind"] in ("beach", "bathing") and len(pts) < 260:
            ax.annotate(p["name"][:22], (p["lon"], p["lat"]), fontsize=5, alpha=0.7,
                        xytext=(2, 2), textcoords="offset points")
    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_aspect(kx)
    ax.set_title(f"Wavespot layer 1 - {name}: {len(pts)} points, colour/arrow = facing "
                 f"(triangles = synthetic)", fontsize=9)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 360))
    fig.colorbar(sm, ax=ax, shrink=0.5, label="facing (deg)")
    ax.text(0.01, 0.01, "© OpenStreetMap contributors (ODbL)", transform=ax.transAxes, fontsize=6)
    os.makedirs(os.path.join(config.OUT_DIR, "preview"), exist_ok=True)
    fig.savefig(os.path.join(config.OUT_DIR, "preview", f"{name}.png"), dpi=110, bbox_inches="tight")
    plt.close(fig)


def main():
    pts = json.load(open(os.path.join(config.OUT_DIR, "layer1.json")))
    meta = json.load(open(os.path.join(config.CACHE, "build_meta.json")))
    rows, errs = accuracy()
    L = []
    L.append("# Layer 1 spots — stats\n")
    L.append(f"Total points: **{len(pts)}** · build runtime {meta['runtime_s']} s · "
             f"layer1.json {meta['size_bytes'] / 2**20:.1f} MB\n")
    L.append("Sources: © OpenStreetMap contributors (ODbL), EEA bathing water sites 2025 (CC BY 4.0), "
             "Wikidata (CC0). Orientation computed from OSM land polygons (ODbL).\n")
    L.append("## By country and kind\n")
    L.append("| country | " + " | ".join(KINDS) + " | kite | total |")
    L.append("|---" * (len(KINDS) + 3) + "|")
    for cc in ["ES", "PT", "FR", "MA"]:
        c = collections.Counter(p["kind"] for p in pts if p["country"] == cc)
        kite = sum(1 for p in pts if p["country"] == cc and "kite" in p["info"]["sports"])
        L.append(f"| {cc} | " + " | ".join(str(c.get(k, 0)) for k in KINDS) + f" | {kite} | {sum(c.values())} |")
    c = collections.Counter(p["kind"] for p in pts)
    L.append("| **all** | " + " | ".join(str(c.get(k, 0)) for k in KINDS) +
             f" | {sum(1 for p in pts if 'kite' in p['info']['sports'])} | {len(pts)} |\n")
    L.append("## By zone and kind\n")
    L.append("| zone | " + " | ".join(KINDS) + " | total | median window width |")
    L.append("|---" * (len(KINDS) + 3) + "|")
    for zid, cc, bb, names in zones.ZONES:
        zp = [p for p in pts if p["zone"] == zid]
        c = collections.Counter(p["kind"] for p in zp)
        ww = [((p["info"]["window"][1] - p["info"]["window"][0]) % 360) or 360 for p in zp]
        L.append(f"| {zid} | " + " | ".join(str(c.get(k, 0)) for k in KINDS) +
                 f" | {len(zp)} | {int(np.median(ww)) if ww else '-'}° |")
    L.append("\n## Dropped real candidates (window < "
             f"{config.MIN_WINDOW_DEG}° or no coast within reach)\n")
    L.append(", ".join(f"{k}: {v}" for k, v in meta["real_dropped"].items()) + "\n")
    L.append("## Orientation accuracy (reference spots)\n")
    L.append(f"n = {len(errs)} · within ±22.5°: **{(errs <= 22.5).mean() * 100:.0f}%** · "
             f"median error {np.median(errs):.0f}° · mean {errs.mean():.0f}°\n")
    L.append("| spot | reference | computed | error | window |")
    L.append("|---|---|---|---|---|")
    for name, ref, got, e, win in rows:
        L.append(f"| {name} | {ref} | {got} | {e:.0f} | {win[0]}–{win[1]} |")
    with open(os.path.join(config.OUT_DIR, "layer1_stats.md"), "w") as f:
        f.write("\n".join(L) + "\n")

    from land import Land
    land = Land()
    for name, bb in PREVIEWS.items():
        render(pts, land, name, bb)
    print("\n".join(L[:12]))


if __name__ == "__main__":
    main()
