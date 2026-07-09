"""Notifier tests. No real HTTP — inject a fake httpx.Client."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from defi_investor.models import EarnEvent
from defi_investor.notifier import (
    NoOpNotifier,
    TelegramNotifier,
    build_notifier,
    dispatch_scrape_notifications,
)


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = "{\"ok\": true}"


@dataclass
class FakeClient:
    calls: list[dict[str, Any]] = field(default_factory=list)
    status_code: int = 200
    raise_error: bool = False

    def post(self, url: str, data: dict) -> FakeResponse:
        if self.raise_error:
            import httpx
            raise httpx.HTTPError("boom")
        self.calls.append({"url": url, "data": data})
        return FakeResponse(status_code=self.status_code)

    def close(self):
        pass


def _ev() -> EarnEvent:
    return EarnEvent(
        product_id="p1",
        coin_name="LAB",
        second_biz_line="Savings",
        max_apy=365.0,
        min_apy=365.0,
        per_user_cap_underlying=1000.0,
        status=6,
        sold_out=True,
        first_seen_at="2026-07-09T18:52:00+00:00",
        start_time="2026-05-12T07:54:45+00:00",
    )


# --------- NoOpNotifier ----------------------------------------------------

def test_noop_notifier_returns_false_for_all():
    n = NoOpNotifier()
    assert n.notify_new_listing(_ev(), observed_at="x") is False
    assert n.notify_sold_out(_ev(), observed_at="x") is False
    assert n.notify_reopened(_ev(), observed_at="x") is False
    assert n.notify_stall(last_scrape_at="x", minutes_ago=1, threshold_min=1) is False
    assert n.notify_parser_drift(coin_names=[], drift_count=0, observed_at="x") is False


# --------- build_notifier --------------------------------------------------

def test_build_notifier_noop_when_creds_missing(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert isinstance(build_notifier(), NoOpNotifier)


def test_build_notifier_noop_when_only_one_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert isinstance(build_notifier(), NoOpNotifier)


# --------- TelegramNotifier ------------------------------------------------

def test_telegram_notifier_sends_html_payload():
    fc = FakeClient()
    n = TelegramNotifier(bot_token="tok", chat_id="123", client=fc)
    ok = n.notify_sold_out(_ev(), observed_at="2026-07-10T02:35:00+00:00")
    assert ok is True
    assert len(fc.calls) == 1
    call = fc.calls[0]
    assert call["url"].endswith("/bottok/sendMessage")
    assert call["data"]["chat_id"] == "123"
    assert call["data"]["parse_mode"] == "HTML"
    assert call["data"]["disable_web_page_preview"] is True
    assert "LAB" in call["data"]["text"]
    assert "Sold out" in call["data"]["text"]


def test_telegram_notifier_returns_false_on_non_200():
    fc = FakeClient(status_code=429)
    n = TelegramNotifier(bot_token="tok", chat_id="123", client=fc)
    assert n.notify_sold_out(_ev(), observed_at="x") is False


def test_telegram_notifier_returns_false_on_http_error():
    fc = FakeClient(raise_error=True)
    n = TelegramNotifier(bot_token="tok", chat_id="123", client=fc)
    assert n.notify_sold_out(_ev(), observed_at="x") is False


def test_telegram_notifier_requires_both_creds():
    with pytest.raises(ValueError):
        TelegramNotifier(bot_token="", chat_id="123")
    with pytest.raises(ValueError):
        TelegramNotifier(bot_token="x", chat_id="")


# --------- dispatch_scrape_notifications policy ----------------------------

class Recording(NoOpNotifier):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def notify_new_listing(self, event, *, observed_at):
        self.calls.append(("new", event.coin_name))
        return True

    def notify_sold_out(self, event, *, observed_at):
        self.calls.append(("sold", event.coin_name))
        return True

    def notify_reopened(self, event, *, observed_at):
        self.calls.append(("reopen", event.coin_name))
        return True


def _mk(pid: str, coin: str, apy: float, status: int = 2) -> EarnEvent:
    return EarnEvent(
        product_id=pid, coin_name=coin, second_biz_line="Savings",
        max_apy=apy, status=status, sold_out=(status == 6),
    )


def test_dispatch_filters_low_apr_new_listings(monkeypatch):
    monkeypatch.setenv("MIN_APR_FOR_ALERT", "20.0")
    # Force re-read of module-level constant by re-importing
    import importlib, defi_investor.notifier as n_mod
    importlib.reload(n_mod)

    rec = n_mod.Recording = type("Rec", (Recording,), {}) if False else Recording()
    stats = n_mod.dispatch_scrape_notifications(
        rec,
        new_events=[_mk("p1", "LAB", 365.0), _mk("p2", "USDT", 1.5)],
        transitions_with_context=[],
        observed_at="2026-07-10T02:35:00+00:00",
    )
    assert stats["new"] == 1
    assert rec.calls == [("new", "LAB")]


def test_dispatch_sold_out_only_above_threshold():
    rec = Recording()
    stats = dispatch_scrape_notifications(
        rec,
        new_events=[],
        transitions_with_context=[
            (_mk("p1", "LAB", 365.0, status=6), 2, 6),
            (_mk("p2", "USDT", 1.5, status=6), 2, 6),
        ],
        observed_at="2026-07-10T02:35:00+00:00",
    )
    assert stats["sold_out"] == 1
    assert ("sold", "LAB") in rec.calls
    assert ("sold", "USDT") not in rec.calls


def test_dispatch_reopen_always_alerts_regardless_of_apr():
    rec = Recording()
    stats = dispatch_scrape_notifications(
        rec,
        new_events=[],
        transitions_with_context=[
            (_mk("p1", "USDT", 1.5, status=2), 6, 2),
        ],
        observed_at="2026-07-10T02:35:00+00:00",
    )
    assert stats["reopened"] == 1
    assert ("reopen", "USDT") in rec.calls
