"""Order-book capture and feature extraction (Phase 3e / HYPOTHESIS_A3).

Different runtime model from the rest of the project: WebSocket-based
capture requires a persistent connection, not a cron-driven poll. Deploy
target is a user decision — see `docs/ORDERBOOK_DESIGN.md`.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class L2Snapshot:
    """One top-5 L2 snapshot from any venue.

    Every venue client normalises its wire format to this shape so
    downstream feature extraction and storage don't need to know the
    source. Constructed in `bitget_l2._parse_books5_payload` and
    `binance_l2._parse_depth5_payload`.
    """
    venue: str                            # 'bitget' | 'binance' | ...
    inst_id: str                          # e.g. 'BTCUSDT'
    received_at: str                      # ISO 8601 UTC, wall-clock at receive
    exchange_ts_ms: int                   # server-side timestamp (ms epoch)
    bids: list[tuple[float, float]]       # [(price, size), ...] top-5
    asks: list[tuple[float, float]]       # [(price, size), ...] top-5
