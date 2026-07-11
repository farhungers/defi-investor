"""Tests for confound-tag computation with injected candle fetcher."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from defi_investor import confounds as cf_mod
from defi_investor.candles import CandleFetch


def _patch_fetch(monkeypatch, sequence: list[tuple[pd.DataFrame, str]]):
    """Return a stateful patched fetch_candles. sequence entries are
    (df, market) — consumed in order."""
    it = iter(sequence)

    def fake(**kw):
        try:
            df, market = next(it)
        except StopIteration:
            df, market = pd.DataFrame(), "none"
        prov = CandleFetch(
            url="fake", market=market, symbol="X", granularity="4H",
            start_ms=0, end_ms=1, n_bars=len(df),
            fetched_at="2026-07-10T00:00:00+00:00", http_status=200,
        )
        return df, prov

    monkeypatch.setattr(cf_mod, "fetch_candles", fake)


def _mk_daily(ts_iso_list):
    idx = pd.to_datetime(ts_iso_list, utc=True)
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "base_vol": 1.0, "quote_vol": 100.0,
    }, index=idx)
    return df


# --- listing_age_days ------------------------------------------------------


def test_listing_age_days_from_first_candle(monkeypatch):
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    df = _mk_daily(["2026-06-01", "2026-06-02", "2026-06-03"])
    _patch_fetch(monkeypatch, [(df, "perp")])
    age = cf_mod.listing_age_days("LAB", now)
    # 2026-06-01 → 2026-07-10 = 39 days
    assert age == 39


def test_listing_age_days_no_candles_returns_none(monkeypatch):
    _patch_fetch(monkeypatch, [(pd.DataFrame(), "none")])
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    assert cf_mod.listing_age_days("GHOST", now) is None


def test_listing_age_days_is_non_negative(monkeypatch):
    """Anchor slightly before earliest candle (edge case)."""
    df = _mk_daily(["2026-06-10"])
    _patch_fetch(monkeypatch, [(df, "perp")])
    now = datetime(2026, 6, 9, tzinfo=timezone.utc)
    assert cf_mod.listing_age_days("X", now) == 0


# --- btc_return ------------------------------------------------------------


def test_btc_return_positive_when_price_rises(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC")
    df = pd.DataFrame({
        "open": [100, 100, 100, 100],
        "high": [101, 101, 101, 101],
        "low":  [99, 99, 99, 99],
        "close": [100, 110, 115, 120],
        "base_vol": 1.0, "quote_vol": 100.0,
    }, index=idx)
    _patch_fetch(monkeypatch, [(df, "perp")])
    r = cf_mod.btc_return(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
    )
    assert r == pytest.approx(0.20, abs=1e-9)


def test_btc_return_negative_when_price_falls(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC")
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0,
        "close": [100, 90, 80],
        "base_vol": 1.0, "quote_vol": 100.0,
    }, index=idx)
    _patch_fetch(monkeypatch, [(df, "perp")])
    r = cf_mod.btc_return(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
    )
    assert r < 0


def test_btc_return_none_on_empty(monkeypatch):
    _patch_fetch(monkeypatch, [(pd.DataFrame(), "none")])
    r = cf_mod.btc_return(
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    assert r is None


# --- perp_vol_change_prior_24h --------------------------------------------


def test_vol_change_positive_when_recent_volume_ramps(monkeypatch):
    anchor = datetime(2026, 5, 15, tzinfo=timezone.utc)
    idx = pd.date_range(anchor - timedelta(hours=48), anchor, freq="4h", tz="UTC")[:-1]
    # First half (prior 24h) has low volume, second half (recent 24h) high
    n = len(idx)
    vols = [1.0] * (n // 2) + [10.0] * (n - n // 2)
    df = pd.DataFrame({
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
        "base_vol": vols, "quote_vol": 100.0,
    }, index=idx)
    _patch_fetch(monkeypatch, [(df, "perp")])
    v = cf_mod.perp_vol_change_prior_24h("LAB", anchor)
    assert v is not None
    assert v > 0


def test_vol_change_none_when_no_candles(monkeypatch):
    _patch_fetch(monkeypatch, [(pd.DataFrame(), "none")])
    anchor = datetime(2026, 5, 15, tzinfo=timezone.utc)
    assert cf_mod.perp_vol_change_prior_24h("X", anchor) is None


# --- compute_confounds ----------------------------------------------------


def test_compute_confounds_returns_stable_keys(monkeypatch):
    """All expected keys are always present."""
    _patch_fetch(monkeypatch, [(pd.DataFrame(), "none")])
    d = cf_mod.compute_confounds("X", "2026-05-15T00:00:00+00:00")
    assert set(d.keys()) == {
        "bitget_listing_age_days", "within_7d_of_tge",
        "btc_ret_7d_prior", "perp_vol_change_prior_24h",
        "perp_oi_pct_change_prior_24h",
    }


def test_compute_confounds_bad_anchor_returns_all_none(monkeypatch):
    d = cf_mod.compute_confounds("X", "not-a-date")
    for v in d.values():
        assert v is None


# --- perp_oi_pct_change_prior_24h -----------------------------------------


class _StubSbTable:
    """Minimal Supabase-like builder that captures the query and returns fixed rows."""
    def __init__(self, rows):
        self._rows = rows
        self.filters: dict = {}

    def select(self, *_a, **_k): return self
    def eq(self, k, v): self.filters[f"eq:{k}"] = v; return self
    def gte(self, k, v): self.filters[f"gte:{k}"] = v; return self
    def lte(self, k, v): self.filters[f"lte:{k}"] = v; return self
    def order(self, *_a, **_k): return self

    def execute(self):
        class R: pass
        r = R()
        r.data = self._rows
        return r


class _StubSbClient:
    def __init__(self, rows):
        self._rows = rows
        self.last_table = None

    def table(self, name):
        self.last_table = name
        return _StubSbTable(self._rows)


def test_perp_oi_pct_change_prior_24h_none_without_client():
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert cf_mod.perp_oi_pct_change_prior_24h("LAB", anchor, sb_client=None) is None


def test_perp_oi_pct_change_prior_24h_returns_ratio_from_snapshots():
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = [
        {"snapped_at": (anchor - timedelta(hours=24)).isoformat(),
         "market": "perp", "oi_base": 1000.0},
        {"snapped_at": (anchor - timedelta(hours=12)).isoformat(),
         "market": "perp", "oi_base": 1200.0},
        {"snapped_at": anchor.isoformat(),
         "market": "perp", "oi_base": 1500.0},
    ]
    sb = _StubSbClient(rows)
    v = cf_mod.perp_oi_pct_change_prior_24h("LAB", anchor, sb_client=sb)
    assert v == pytest.approx(0.5)
    assert sb.last_table == "earn_oi_snapshots"


def test_perp_oi_pct_change_prior_24h_none_when_no_perp_rows():
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = [
        {"snapped_at": (anchor - timedelta(hours=24)).isoformat(),
         "market": "none", "oi_base": None},
        {"snapped_at": anchor.isoformat(),
         "market": "none", "oi_base": None},
    ]
    sb = _StubSbClient(rows)
    assert cf_mod.perp_oi_pct_change_prior_24h("LAB", anchor, sb_client=sb) is None


def test_perp_oi_pct_change_prior_24h_none_when_endpoint_missing():
    """Anchor snapshot present, prior-24h snapshot absent → None."""
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = [
        {"snapped_at": anchor.isoformat(),
         "market": "perp", "oi_base": 1500.0},
    ]
    sb = _StubSbClient(rows)
    assert cf_mod.perp_oi_pct_change_prior_24h("LAB", anchor, sb_client=sb) is None


def test_perp_oi_pct_change_prior_24h_none_when_before_is_zero():
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    rows = [
        {"snapped_at": (anchor - timedelta(hours=24)).isoformat(),
         "market": "perp", "oi_base": 0.0},
        {"snapped_at": anchor.isoformat(),
         "market": "perp", "oi_base": 500.0},
    ]
    sb = _StubSbClient(rows)
    assert cf_mod.perp_oi_pct_change_prior_24h("LAB", anchor, sb_client=sb) is None


def test_perp_oi_pct_change_prior_24h_survives_query_exception():
    class BrokenSb:
        def table(self, _n):
            class T:
                def select(self, *a, **k): return self
                def eq(self, *a, **k): return self
                def gte(self, *a, **k): return self
                def lte(self, *a, **k): return self
                def order(self, *a, **k): return self
                def execute(self): raise RuntimeError("boom")
            return T()
    anchor = datetime(2026, 7, 20, tzinfo=timezone.utc)
    assert cf_mod.perp_oi_pct_change_prior_24h(
        "LAB", anchor, sb_client=BrokenSb(),
    ) is None


def test_compute_confounds_passes_sb_client_to_oi(monkeypatch):
    """When sb_client provided, the OI key is populated (or None on empty rows)."""
    _patch_fetch(monkeypatch, [
        (_mk_daily(["2026-06-01"]), "perp"),
        (_mk_daily(["2026-05-01", "2026-05-02"]), "perp"),
        (_mk_daily(["2026-06-30", "2026-07-01"]), "perp"),
    ])
    sb = _StubSbClient([])  # no snapshots yet → OI stays None gracefully
    d = cf_mod.compute_confounds(
        "LAB", "2026-07-10T00:00:00+00:00", sb_client=sb,
    )
    assert d["perp_oi_pct_change_prior_24h"] is None
    assert "perp_oi_pct_change_prior_24h" in d
