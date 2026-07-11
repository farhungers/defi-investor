"""Vest-unlock scraper against tokenomist.ai SSR (Phase 2 confound §1.2).

Approach and its limits, spelled out because the confound design in
METHOD §1.2 is opinionated about "best effort":

- **Source:** tokenomist.ai renders a `<meta name="description">` tag
  server-side that carries the single **next unlock** date for each
  tracked token, e.g.

      "Arbitrum (ARB) tokenomics intelligence: next unlock on
       July 16, 2026 releasing 92,645,833 ARB (~$8,528,604.80)."

  We fetch the page, extract the description via a regex, parse the
  date/amount/USD. No Playwright — plain HTTP.

- **Slug resolution:** tokenomist slugs are frequently the coin's
  lowercased ticker (LAB, PUMP → `lab`, `pump`) but more often are
  CoinGecko-style project names (ARB → `arbitrum`, PYTH →
  `pyth-network`). We guess `slug = lower(coin_name)` and record the
  status accordingly. When it's wrong the page 404s and we record
  `status='untracked'`. Operators can extend `KNOWN_SLUG_OVERRIDES`
  as high-value 404s show up.

- **What we do NOT get:** the full historical schedule, or unlock
  events past the single "next" one. The description carries only the
  next upcoming release. This limits the confound to events whose
  anchor happens to fall within ±3d of a snapshot's `next_unlock_at`.
  METHOD §1.2 already labels this "best effort" and accepts the
  residual risk.

- **Cadence:** vest schedules change on the order of days, not minutes.
  The scraper calls `snapshot_universe` only on the hourly aligned run
  (see scraper.py) — a ~4x deflation vs the OI cron.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx


LOG = logging.getLogger("defi_investor.vest_unlocks")

TOKENOMIST_BASE = "https://tokenomist.ai"
USER_AGENT = (
    "defi-investor-research/0.2.1 (Bitget Earn hypothesis test; contact via GitHub)"
)

# Operator-extendable static overrides. Populate as high-value 404s show up.
# Key: canonical coin symbol upper. Value: tokenomist slug.
KNOWN_SLUG_OVERRIDES: dict[str, str] = {
    "ARB": "arbitrum",
    "PYTH": "pyth-network",
    "W": "wormhole",
    "PUMP": "pump-fun",
    "APT": "aptos",
    "SUI": "sui",
    "SEI": "sei",
    "TIA": "celestia",
    "STRK": "starknet",
    "JUP": "jupiter-exchange-solana",
    "WLD": "worldcoin",
    "ONDO": "ondo-finance",
    "ENA": "ethena",
    "BONK": "bonk",
    "WIF": "dogwifhat",
    "JTO": "jito-governance-token",
    "MANTA": "manta-network",
    "IO": "io",
    "ETHFI": "ether-fi",
    "REZ": "renzo",
    "BB": "bouncebit",
}

_INTER_CALL_SLEEP_S = 0.5
_MAX_COINS_PER_RUN = 300

# Extract the meta description text out of an HTML blob. Two escaping
# variants show up on tokenomist's SSR (bare and JSON-escaped inside
# script tags); the regex handles both by anchoring on "next unlock".
_DESC_RE = re.compile(
    r'(?:"description"\s*:\s*"|<meta[^>]*name="description"[^>]*content=")'
    r'([^"]{0,500}next unlock[^"]{0,500})',
    re.IGNORECASE,
)

# From "next unlock on July 16, 2026 releasing 92,645,833 ARB (~$8,528,604.80)"
_UNLOCK_RE = re.compile(
    r'next unlock on\s+(?P<date>[A-Za-z]+\s+\d{1,2},\s+\d{4}|undefined)'
    r'(?:\s+releasing\s+(?P<amount>[\d,\.]+|undefined)\s+[A-Za-z0-9\.]+'
    r'\s*\(~?\$(?P<usd>[\d,\.]+|undefined)\))?',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NextUnlockSnapshot:
    """One coin's next-unlock reading, ready to persist."""
    coin_name: str
    snapped_at: str
    tokenomist_slug: Optional[str]
    status: str                             # see migration 006 header
    next_unlock_at: Optional[str] = None
    next_unlock_amount: Optional[float] = None
    next_unlock_usd: Optional[float] = None
    http_status: Optional[int] = None
    error: Optional[str] = None

    def to_row(self) -> dict:
        return {
            "coin_name": self.coin_name,
            "snapped_at": self.snapped_at,
            "tokenomist_slug": self.tokenomist_slug,
            "status": self.status,
            "next_unlock_at": self.next_unlock_at,
            "next_unlock_amount": self.next_unlock_amount,
            "next_unlock_usd": self.next_unlock_usd,
            "http_status": self.http_status,
            "error": self.error,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_slug(coin_name: str) -> str:
    """SYMBOL -> tokenomist slug guess. Overrides win, else lower(symbol)."""
    upper = coin_name.upper()
    return KNOWN_SLUG_OVERRIDES.get(upper, coin_name.lower())


def _parse_amount(raw: str) -> Optional[float]:
    if raw is None or raw == "undefined":
        return None
    try:
        return float(raw.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _parse_date(raw: str) -> Optional[str]:
    if raw is None or raw == "undefined":
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def parse_description(html: str) -> tuple[str, Optional[str], Optional[float], Optional[float]]:
    """Extract (status, iso_date, amount, usd) from a tokenomist page HTML.

    Returns status one of:
      'tracked_with_unlock', 'no_upcoming_unlock', 'malformed'.
    """
    dm = _DESC_RE.search(html)
    if dm is None:
        return ("malformed", None, None, None)
    desc = dm.group(1)
    um = _UNLOCK_RE.search(desc)
    if um is None:
        return ("malformed", None, None, None)
    date_raw = um.group("date")
    amount_raw = um.group("amount")
    usd_raw = um.group("usd")
    if date_raw == "undefined":
        return ("no_upcoming_unlock", None, None, None)
    iso = _parse_date(date_raw)
    if iso is None:
        return ("malformed", None, None, None)
    return ("tracked_with_unlock", iso, _parse_amount(amount_raw or ""),
            _parse_amount(usd_raw or ""))


def fetch_next_unlock(
    coin_name: str,
    *,
    snapped_at: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> NextUnlockSnapshot:
    """Fetch one coin's next-unlock snapshot from tokenomist.ai. Never raises."""
    ts = snapped_at or _now_iso()
    slug = resolve_slug(coin_name)
    url = f"{TOKENOMIST_BASE}/{slug}"
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml"},
            timeout=15.0, follow_redirects=True,
        )
    try:
        try:
            r = client.get(url)
        except httpx.HTTPError as e:
            return NextUnlockSnapshot(
                coin_name=coin_name, snapped_at=ts, tokenomist_slug=slug,
                status="error", http_status=0, error=f"http_error: {e}",
            )
        status = r.status_code
        if status == 404:
            return NextUnlockSnapshot(
                coin_name=coin_name, snapped_at=ts, tokenomist_slug=slug,
                status="untracked", http_status=404,
            )
        if status != 200:
            return NextUnlockSnapshot(
                coin_name=coin_name, snapped_at=ts, tokenomist_slug=slug,
                status="error", http_status=status,
                error=f"non_200: {r.text[:200]}",
            )
        parsed_status, iso_date, amount, usd = parse_description(r.text)
        return NextUnlockSnapshot(
            coin_name=coin_name, snapped_at=ts, tokenomist_slug=slug,
            status=parsed_status, next_unlock_at=iso_date,
            next_unlock_amount=amount, next_unlock_usd=usd,
            http_status=status,
        )
    finally:
        if close_after:
            client.close()


def snapshot_universe(
    coin_names: Iterable[str],
    *,
    snapped_at: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    max_coins: int = _MAX_COINS_PER_RUN,
    inter_call_sleep_s: float = _INTER_CALL_SLEEP_S,
) -> list[NextUnlockSnapshot]:
    """Snapshot next-unlock for every distinct coin in the universe.

    Slower per call than OI (tokenomist is HTML, ~600 KB per page vs
    Bitget's ~150 bytes of JSON). Called from the scraper only on the
    hourly-aligned run to keep the /15 cron under its 5-minute budget.
    """
    ts = snapped_at or _now_iso()
    seen: set[str] = set()
    ordered: list[str] = []
    for c in coin_names:
        if not c:
            continue
        u = c.upper()
        if u in seen:
            continue
        seen.add(u)
        ordered.append(u)

    if len(ordered) > max_coins:
        LOG.warning("vest snapshot_universe: %d coins exceeds cap %d; truncating",
                    len(ordered), max_coins)
        ordered = ordered[:max_coins]

    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT,
                     "Accept": "text/html,application/xhtml+xml"},
            timeout=15.0, follow_redirects=True,
        )
    out: list[NextUnlockSnapshot] = []
    try:
        for i, coin in enumerate(ordered):
            snap = fetch_next_unlock(coin, snapped_at=ts, client=client)
            out.append(snap)
            if i + 1 < len(ordered) and inter_call_sleep_s > 0:
                time.sleep(inter_call_sleep_s)
        by_status = {}
        for s in out:
            by_status[s.status] = by_status.get(s.status, 0) + 1
        LOG.info("vest snapshot_universe: %d coins  status_breakdown=%s",
                 len(out), by_status)
        return out
    finally:
        if close_after:
            client.close()
