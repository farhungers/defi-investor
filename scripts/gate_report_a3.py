"""Phase 3 gate report for HYPOTHESIS_A3 (order-book impact labeler).

A3 gate criteria (verbatim from HYPOTHESIS_A3.md):
  1. E[R_24h | label = +1] > E[R_24h | label = -1]
  2. Difference-in-means t-test: p < corrected alpha
     (corrected alpha = 0.05 / N_registered)
  3. n_labeled >= 30
  4. Order-book data coverage >= 70% of primary events
     (otherwise coverage bias dominates)

Read-only. Runs today (descriptive-only until orderbook_features has data).

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import math
import os
import statistics as st
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

from defi_investor.backtest.family_wise import DEFAULT_ALPHA, N_REGISTERED, bonferroni_alpha


LOG = logging.getLogger("defi_investor.gate_report_a3")

LABELER_VERSION = "A3_v0.1.0"
MIN_N_FOR_GATE = 30
COVERAGE_GATE = 0.70


def _load_labels(sb) -> Optional[list[dict]]:
    """Return rows or None if the orderbook_features table doesn't exist yet
    (Migration 010 unapplied). None signals the caller to print a friendly
    'not yet' message instead of crashing."""
    try:
        r = (
            sb.table("orderbook_features")
            .select("*")
            .eq("labeler_version", LABELER_VERSION)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "PGRST205" in msg or "orderbook_features" in msg:
            return None
        raise
    return r.data or []


def _welch_t_stat(a: list[float], b: list[float]) -> Optional[tuple[float, float]]:
    """Welch's t-statistic and approximate two-sided p (normal approximation).

    For small n we'd prefer a proper t-distribution p-value with
    Welch-Satterthwaite dof. Using normal approx keeps the module
    dependency-light; if n reaches gate, use scipy.stats.ttest_ind in a
    downstream notebook for the official number.
    """
    if len(a) < 2 or len(b) < 2:
        return None
    mean_a = st.fmean(a)
    mean_b = st.fmean(b)
    var_a = st.variance(a)
    var_b = st.variance(b)
    n_a, n_b = len(a), len(b)
    denom = math.sqrt(var_a / n_a + var_b / n_b)
    if denom == 0:
        return None
    t = (mean_a - mean_b) / denom
    # Normal-approx two-sided p
    from math import erf, sqrt
    p_one_sided = 0.5 * (1.0 - erf(abs(t) / sqrt(2)))
    p_two_sided = min(1.0, 2 * p_one_sided)
    return t, p_two_sided


def _fmt(v: Optional[float], places: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:+.{places}f}"


def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return f"{p:.4g}"


def _pass_fail(cond: bool) -> str:
    return "PASS" if cond else "FAIL"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    corrected_alpha = bonferroni_alpha()
    raw = _load_labels(sb)

    if raw is None:
        print("\n".join([
            "=" * 70,
            "defi-investor - Phase 3 Gate Report - HYPOTHESIS_A3",
            f"timestamp:  {now}",
            "-" * 70,
            "orderbook_features table does not exist yet.",
            "Apply Migration 010 (db/migrations/010_orderbook.sql), deploy the",
            "capture_daemon, wait for sold-out events to occur with pre-window",
            "L2 data captured, then run scripts/backfill_labels_a3.py.",
            "=" * 70,
        ]))
        return 0

    primary = [r for r in raw if r.get("label") is not None and not r.get("unlabelable_reason")]
    excl_no_ob = sum(1 for r in raw if r.get("unlabelable_reason") == "no_orderbook_data")
    excl_gap = sum(1 for r in raw if r.get("unlabelable_reason") == "ws_gap_over_60s_in_pre_window")
    excl_no_spot = sum(1 for r in raw if r.get("unlabelable_reason") == "no_spot_candles")
    excl_tge = sum(1 for r in raw if r.get("within_7d_of_tge") is True)

    coverage = (len(primary) / len(raw)) if raw else 0.0

    lines = [
        "=" * 70,
        "defi-investor - Phase 3 Gate Report - HYPOTHESIS_A3",
        f"timestamp:        {now}",
        f"labeler_version:  {LABELER_VERSION}",
        f"family size N:    {N_REGISTERED}",
        f"corrected alpha:  {corrected_alpha:.4f}  (raw={DEFAULT_ALPHA})",
        "-" * 70,
        "Corpus",
        f"  Raw feature rows:               {len(raw)}",
        f"  Excluded - no_orderbook_data:   {excl_no_ob}",
        f"  Excluded - ws gap over 60s:     {excl_gap}",
        f"  Excluded - no_spot_candles:     {excl_no_spot}",
        f"  Excluded - within 7d of TGE:    {excl_tge}",
        f"  Primary universe (resolved):    {len(primary)}",
        f"  Coverage:                       {coverage:.1%}  (gate: >= {COVERAGE_GATE:.0%})",
    ]

    if not primary:
        lines += [
            "",
            f"n=0 -- gate suppressed (descriptive only).",
            "Enable by capturing L2 data (deploy the capture_daemon) and running",
            "scripts/backfill_labels_a3.py after events sold-out with pre-window data.",
            "=" * 70,
        ]
        print("\n".join(lines))
        return 0

    plus = [float(r["r_24h"]) for r in primary if r.get("label") == 1 and r.get("r_24h") is not None]
    minus = [float(r["r_24h"]) for r in primary if r.get("label") == -1 and r.get("r_24h") is not None]
    zero = [float(r["r_24h"]) for r in primary if r.get("label") == 0 and r.get("r_24h") is not None]

    mean_plus = st.fmean(plus) if plus else None
    mean_minus = st.fmean(minus) if minus else None
    mean_zero = st.fmean(zero) if zero else None

    lines += [
        "-" * 70,
        "Primary label statistics",
        f"  Label distribution:  +1={len(plus)}  -1={len(minus)}  0={len(zero)}",
        f"  E[R_24h | +1]:       {_fmt(mean_plus)}",
        f"  E[R_24h | -1]:       {_fmt(mean_minus)}",
        f"  E[R_24h |  0]:       {_fmt(mean_zero)}",
    ]

    t_result = _welch_t_stat(plus, minus)
    if t_result is not None:
        t_stat, p_val = t_result
        lines += [
            f"  Welch t (+1 vs -1):  t={_fmt(t_stat, 3)}  p~{_fmt_p(p_val)} (normal approx)",
        ]
    else:
        t_stat, p_val = None, None

    n_gate_pass = len(primary) >= MIN_N_FOR_GATE
    coverage_gate_pass = coverage >= COVERAGE_GATE
    mean_gate_pass = (
        mean_plus is not None and mean_minus is not None and mean_plus > mean_minus
    )
    p_gate_pass = p_val is not None and p_val < corrected_alpha

    lines += [
        "-" * 70,
        "Gate criteria (all four must PASS to declare edge)",
        f"  [{_pass_fail(n_gate_pass)}]         n_labeled >= {MIN_N_FOR_GATE}  (n={len(primary)})",
        f"  [{_pass_fail(coverage_gate_pass)}]         Coverage >= {COVERAGE_GATE:.0%}  ({coverage:.1%})",
        f"  [{_pass_fail(mean_gate_pass)}]         E[R|+1] > E[R|-1]",
        f"  [{_pass_fail(p_gate_pass)}]         Welch p < corrected alpha ({corrected_alpha:.4f})",
    ]

    pass_all = n_gate_pass and coverage_gate_pass and mean_gate_pass and p_gate_pass
    lines += [
        "-" * 70,
        f"RESULT:       {'EDGE DECLARED' if pass_all else 'DO NOT DECLARE EDGE'}",
        "=" * 70,
    ]

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
