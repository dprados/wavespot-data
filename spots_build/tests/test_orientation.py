"""Orientation accuracy against reference spots (needs the land cache: see README)."""
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import config  # noqa: E402
from orientation import largest_arc, arc_to_facing_window, angdiff, blend_facing  # noqa: E402
from reference_spots import REFERENCE_SPOTS  # noqa: E402

HAVE_LAND = os.path.exists(os.path.join(config.CACHE, "land.pkl"))


def test_largest_arc_wraps_around_north():
    mask = np.zeros(72, bool)
    mask[66:] = True   # 330..355
    mask[:5] = True    # 0..20
    w, s, n = largest_arc(mask)
    assert w == 55 and s == 66 and n == 11
    facing, window = arc_to_facing_window(s, n)
    assert window == [330, 20]
    assert facing == 355


def test_blend_clamps_inside_arc():
    # normal outside the arc: pulled at most (half - margin) from the centre
    assert blend_facing(0, 330, 30, 90) == 0  # half=30, margin 30 -> no move
    assert abs(angdiff(blend_facing(270, 180, 0, 300), 285)) <= 1


@pytest.fixture(scope="module")
def orienter():
    if not HAVE_LAND:
        pytest.skip("land cache missing")
    from land import Land
    from orientation import Orienter
    return Orienter(Land())


def test_reference_accuracy(orienter):
    errs, rows = [], []
    for name, lat, lon, ref in REFERENCE_SPOTS:
        r = orienter.orient(lat, lon)
        assert r is not None and r["facing"] is not None, name
        e = abs(angdiff(r["facing"], ref))
        errs.append(e)
        rows.append(f"{name:30s} ref {ref:3d} got {r['facing']:3d} err {e:3.0f} window {r['window']}")
    errs = np.array(errs)
    within = float((errs <= 22.5).mean())
    print("\n".join(rows))
    print(f"n={len(errs)} within22.5={within:.3f} median={np.median(errs):.1f} mean={errs.mean():.1f}")
    assert len(errs) >= 30
    assert within >= 0.85
    assert np.median(errs) <= 15


def test_reference_window_contains_facing(orienter):
    for name, lat, lon, _ in REFERENCE_SPOTS:
        r = orienter.orient(lat, lon)
        a0, a1 = r["window"]
        assert (r["facing"] - a0) % 360 <= (a1 - a0) % 360, name
