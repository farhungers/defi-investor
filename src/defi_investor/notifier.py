"""Telegram alert sender.

Symmetric to db.py: a Notifier protocol with a NoOpNotifier fallback so the
scraper never crashes when the bot creds are absent.

Two flavors:
- Event notifications (new listings, sold-out, re-opened): called from
  the scraper after each successful scrape.
- Health notifications (stall, parser drift): called from scripts/check_health.

Uses httpx directly rather than a Telegram SDK — one endpoint, one call.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Optional, Protocol

import httpx

from . import cards
from .context import cohort_context
from .models import EarnEvent


LOG = logging.getLogger("defi_investor.notifier")
_TG_MAX_LEN = 4000  # Telegram hard limit is 4096; leave slack


class Notifier(Protocol):
    def notify_new_listing(self, event: EarnEvent, *, observed_at: str) -> bool: ...
    def notify_sold_out(self, event: EarnEvent, *, observed_at: str) -> bool: ...
    def notify_reopened(self, event: EarnEvent, *, observed_at: str) -> bool: ...
    def notify_stall(self, *, last_scrape_at: str, minutes_ago: int,
                     threshold_min: int, actions_url: Optional[str] = None) -> bool: ...
    def notify_parser_drift(self, *, coin_names: list[str], drift_count: int,
                            observed_at: str) -> bool: ...


class NoOpNotifier:
    """Used when TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID are absent."""

    def notify_new_listing(self, event: EarnEvent, *, observed_at: str) -> bool:
        return False

    def notify_sold_out(self, event: EarnEvent, *, observed_at: str) -> bool:
        return False

    def notify_reopened(self, event: EarnEvent, *, observed_at: str) -> bool:
        return False

    def notify_stall(self, *, last_scrape_at: str, minutes_ago: int,
                     threshold_min: int, actions_url: Optional[str] = None) -> bool:
        return False

    def notify_parser_drift(self, *, coin_names: list[str], drift_count: int,
                            observed_at: str) -> bool:
        return False


class TelegramNotifier:
    """Sends HTML-formatted cards to a single chat."""

    def __init__(self, bot_token: str, chat_id: str, *,
                 client: Optional[httpx.Client] = None, timeout: float = 10.0,
                 sb_client=None):
        if not bot_token or not chat_id:
            raise ValueError("TelegramNotifier requires bot_token + chat_id")
        self._bot_token = bot_token
        self._chat_id = str(chat_id)
        self._client = client
        self._timeout = timeout
        self._sb_client = sb_client  # optional; used only for cohort context

    def _ctx(self, event: EarnEvent) -> Optional[dict]:
        if self._sb_client is None:
            return None
        return cohort_context(event, self._sb_client)

    def _send_html(self, html_body: str) -> bool:
        if len(html_body) > _TG_MAX_LEN:
            # Cheap truncation; cards are designed to fit.
            html_body = html_body[: _TG_MAX_LEN - 12] + "\n<i>…</i>"
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": html_body,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        client = self._client
        close_after = False
        if client is None:
            client = httpx.Client(timeout=self._timeout)
            close_after = True
        try:
            r = client.post(url, data=payload)
            if r.status_code != 200:
                LOG.warning("Telegram sendMessage returned %d: %s",
                            r.status_code, r.text[:200])
                return False
            return True
        except httpx.HTTPError as e:
            LOG.warning("Telegram sendMessage error: %s", e)
            return False
        finally:
            if close_after:
                client.close()

    def notify_new_listing(self, event: EarnEvent, *, observed_at: str) -> bool:
        return self._send_html(cards.new_listing_card(
            event, observed_at=observed_at, ctx=self._ctx(event),
        ))

    def notify_sold_out(self, event: EarnEvent, *, observed_at: str) -> bool:
        return self._send_html(cards.sold_out_card(
            event, observed_at=observed_at, ctx=self._ctx(event),
        ))

    def notify_reopened(self, event: EarnEvent, *, observed_at: str) -> bool:
        return self._send_html(cards.reopened_card(
            event, observed_at=observed_at, ctx=self._ctx(event),
        ))

    def notify_stall(self, *, last_scrape_at: str, minutes_ago: int,
                     threshold_min: int, actions_url: Optional[str] = None) -> bool:
        return self._send_html(cards.stall_card(
            last_scrape_at=last_scrape_at,
            minutes_ago=minutes_ago,
            threshold_min=threshold_min,
            actions_url=actions_url,
        ))

    def notify_parser_drift(self, *, coin_names: list[str], drift_count: int,
                            observed_at: str) -> bool:
        return self._send_html(cards.parser_drift_card(
            coin_names=coin_names,
            drift_count=drift_count,
            observed_at=observed_at,
        ))


def build_notifier(bot_token: Optional[str] = None,
                   chat_id: Optional[str] = None,
                   sb_client=None) -> Notifier:
    """SupabaseWriter's cousin: real notifier if both creds present, NoOp otherwise.

    `sb_client` is optional — if passed, cards get cohort context. Scraper
    passes the SupabaseWriter's underlying client so we don't open a second one.
    """
    bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        LOG.info("Telegram credentials not set — using NoOpNotifier")
        return NoOpNotifier()
    return TelegramNotifier(bot_token=bot_token, chat_id=chat_id, sb_client=sb_client)


# ---------- Filtering policy ------------------------------------------------

# APR threshold below which we don't alert on new listings / transitions.
# Keeps stablecoin ladder noise out of the chat. Overrideable via env.
MIN_APR_FOR_ALERT = float(os.environ.get("MIN_APR_FOR_ALERT", "20.0"))


def is_interesting(event: EarnEvent) -> bool:
    """Filter for scraper-triggered notifications."""
    if event.max_apy is None:
        return False
    return event.max_apy >= MIN_APR_FOR_ALERT


def dispatch_scrape_notifications(
    notifier: Notifier,
    *,
    new_events: Iterable[EarnEvent],
    transitions_with_context: Iterable[tuple[EarnEvent, int, int]],
    observed_at: str,
) -> dict[str, int]:
    """One entry point the scraper calls after a scrape.

    `transitions_with_context` — sequence of (event, old_status, new_status).
    Returns a small stats dict for logging.
    """
    n_new = 0
    n_sold = 0
    n_reopen = 0
    for ev in new_events:
        if is_interesting(ev):
            if notifier.notify_new_listing(ev, observed_at=observed_at):
                n_new += 1
    for ev, old, new in transitions_with_context:
        if old == 2 and new == 6 and is_interesting(ev):
            if notifier.notify_sold_out(ev, observed_at=observed_at):
                n_sold += 1
        elif old == 6 and new == 2:
            # re-opens are always interesting (rare)
            if notifier.notify_reopened(ev, observed_at=observed_at):
                n_reopen += 1
    return {"new": n_new, "sold_out": n_sold, "reopened": n_reopen}
