"""Event dataclasses for the Bitget Earn catalog.

Wire schema is documented in ../../docs/DATA_MODEL.md and confirmed empirically
in ../../docs/PHASE_1_PROBE_LOG.md.

One EarnEvent per Bitget product per unique product_id. Multiple scrapes update
first_seen / last_seen / observed_status_transitions but do not create new
event rows.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


SCRAPER_VERSION = "0.2.0"


def _epoch_ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


@dataclass
class EarnEvent:
    """One Bitget Earn product observation, keyed by product_id."""

    # Identity
    product_id: str
    coin_name: str
    second_biz_line: str  # 'Savings', 'PosStaking', 'SharkFin', 'CashPlus', 'FundMarket', 'Trend'

    # Pricing
    max_apy: Optional[float] = None
    min_apy: Optional[float] = None
    per_user_cap_underlying: Optional[float] = None  # apyList[0].maxStepValue

    # Full tier ladder (raw apyList, keys per Bitget wire: apy, maxStepValue,
    # minStepValue, productId, rateLevel). Preserved verbatim so downstream
    # cohorting can split single-tier bait pools from multi-tier stablecoin
    # ladders. See PHASE_1_PROBE_LOG_v2.md §5.
    tiers: list[dict] = field(default_factory=list)

    # Timing
    start_time: Optional[str] = None  # product creation, ISO 8601 UTC
    period_days: Optional[int] = None
    lock_model: Optional[bool] = None
    period_type: Optional[int] = None

    # Status
    status: Optional[int] = None  # 2=active, 6=sold_out, 4=paused (see PROBE_LOG)
    sold_out: Optional[bool] = None  # convenience: status == 6

    # Observation windows (filled by scraper, not parser)
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    sold_out_first_seen_at: Optional[str] = None

    # Provenance (filled by scraper)
    raw_capture_sha256: Optional[str] = None
    raw_capture_path: Optional[str] = None
    scraper_version: str = SCRAPER_VERSION

    # Data quality
    data_quality: str = "complete"  # 'complete' | 'incomplete' | 'schema_drift'
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EarnEvent":
        # Ignore unknown keys defensively — schema drift future-proofing
        known = {f: d.get(f) for f in cls.__dataclass_fields__ if f in d}
        # notes and tiers may be absent in legacy rows (pre-0.2.0)
        if "notes" not in known or known["notes"] is None:
            known["notes"] = []
        if "tiers" not in known or known["tiers"] is None:
            known["tiers"] = []
        return cls(**known)


def parse_apy(raw: object) -> Optional[float]:
    """Bitget wire APR is a string like '365.00'. Return float or None on empty."""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def parse_max_step(apy_list: object) -> Optional[float]:
    """From productList[i].apyList[0].maxStepValue if present.

    apyList shape: [{apy: '365.00', maxStepValue: '1000.00', minStepValue: '0.00', ...}]
    Returns the maxStepValue of the first tier, or None.
    """
    if not isinstance(apy_list, list) or not apy_list:
        return None
    first = apy_list[0]
    if not isinstance(first, dict):
        return None
    return parse_apy(first.get("maxStepValue"))


def coin_to_symbol(coin_name: str) -> str:
    """LAB -> LABUSDT. Used for joining to Bitget perp candles later."""
    return f"{coin_name.upper()}USDT"
