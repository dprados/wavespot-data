import datetime as dt

import pytest

from wavespot_pipeline import build

FIXED_NOW = dt.datetime(2026, 11, 11, 10, tzinfo=dt.timezone.utc)  # the stubbed sources start at 2026-11-11


@pytest.fixture
def frozen_build_clock(monkeypatch):
    """The stubbed sources are dated 2026-11-11; without a frozen clock build.main marks them stale once
    the real date moves on and exits 2."""
    class FrozenDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW if tz else FIXED_NOW.replace(tzinfo=None)

    class FrozenModule:
        def __getattr__(self, name):
            return FrozenDT if name == "datetime" else getattr(dt, name)

    monkeypatch.setattr(build, "dt", FrozenModule())
