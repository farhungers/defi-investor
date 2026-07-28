"""Order-book capture and feature extraction (Phase 3e / HYPOTHESIS_A3).

Different runtime model from the rest of the project: WebSocket-based
capture requires a persistent connection, not a cron-driven poll. Deploy
target is a user decision — see `docs/ORDERBOOK_DESIGN.md`.
"""
