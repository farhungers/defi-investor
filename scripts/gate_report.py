"""Phase 3 gate report (METHOD §4.3).

Reads resolved labels from `earn_event_labels`, applies exclusion criteria,
runs per-bet Sharpe + PSR + HHI + purged K-Fold CV + confound splits, and
prints the METHOD §4.3 report format with a PASS/FAIL line per gate item.

Runs today. Report is provisional until CHARTER kill-criterion #2 is met
(n >= 30 primary universe). Below that the script prints the current
state but does not "declare" anything either way.

Read-only. Zero Supabase writes. Zero Telegram traffic.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    LABELER_VERSION   optional; defaults to the current labeler version
"""
from __future__ import annotations

import logging
import os
import statistics as st
import sys
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.backtest.cv import PurgedKFold
from defi_investor.backtest.stats import average_uniqueness, bet_stats, hhi, psr
from defi_investor.labeler import LABELER_VERSION


LOG = logging.getLogger("defi_investor.gate_report")

MIN_N_FOR_GATE = 30                # CHARTER kill-criterion #2
PSR_GATE = 0.95                    # METHOD §2.4 item 2
HHI_WINNER_GATE = 0.15             # METHOD §2.4 item 3
MEDIAN_MEAN_GATE = 0.5             # METHOD §2.4 item 4
CONFOUND_SPLIT_HITS_REQUIRED = 2   # of 3 splits (METHOD §2.4 item 5)


def _load_labels(sb, labeler_version: str) -> list[dict]:
    r = (
        sb.table("earn_event_labels")
        .select("*")
        .eq("labeler_version", labeler_version)
        .execute()
    )
    return r.data or []


def _resolved_primary(labels: list[dict]) -> list[dict]:
    """Filter to the primary universe: resolved label AND clean anchor
    AND not within-7d-of-TGE."""
    kept = []
    for row in labels:
        if row.get("label") is None:
            continue
        if row.get("unlabelable_reason"):
            continue
        if row.get("within_7d_of_tge") is True:
            continue
        kept.append(row)
    return kept


def _confound_split_stats(
    labels: list[dict], predicate, label_name: str,
) -> tuple[int, Optional[float], str]:
    """Slice by predicate, return (n, mean_R, sign_flag)."""
    slice_ = [r for r in labels if predicate(r)]
    rs = [float(r["realized_r"]) for r in slice_
          if r.get("realized_r") is not None]
    if len(rs) < 2:
        return len(slice_), None, "n/a"
    mean_r = st.fmean(rs)
    return len(slice_), mean_r, "positive" if mean_r > 0 else "negative"


def _fmt(v: Optional[float], places: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:+.{places}f}"


def _fmt_pct(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v * 100:+.2f}%"


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
    version = os.environ.get("LABELER_VERSION", LABELER_VERSION)
    sb = create_client(url, key)

    raw = _load_labels(sb, version)
    primary = _resolved_primary(raw)
    excl_stale = sum(1 for r in raw if r.get("unlabelable_reason") == "stale_anchor")
    excl_horizon = sum(1 for r in raw if r.get("unlabelable_reason") == "horizon_not_yet_resolved")
    excl_nocandles = sum(1 for r in raw if r.get("unlabelable_reason") == "no_candles_available")
    excl_tge = sum(1 for r in raw if r.get("within_7d_of_tge") is True)
    unresolved = sum(1 for r in raw if r.get("label") is None
                     and not r.get("unlabelable_reason"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "=" * 70,
        "defi-investor · Phase 3 Gate Report",
        f"timestamp:        {now}",
        f"labeler_version:  {version}",
        "-" * 70,
        "Corpus",
        f"  Raw label rows:                 {len(raw)}",
        f"  Excluded — stale_anchor:        {excl_stale}",
        f"  Excluded — horizon unresolved:  {excl_horizon}",
        f"  Excluded — no candles:          {excl_nocandles}",
        f"  Excluded — within 7d of TGE:    {excl_tge}",
        f"  Unresolved (other):             {unresolved}",
        f"  Primary universe (resolved):    {len(primary)}",
    ]

    if not primary:
        lines.append("")
        lines.append(f"n < {MIN_N_FOR_GATE}. Not enough data to run the gate.")
        lines.append("Current pass/fail lines suppressed — report is descriptive only.")
        lines.append("=" * 70)
        print("\n".join(lines))
        return 0

    rs = [float(r["realized_r"]) for r in primary if r.get("realized_r") is not None]
    stats = bet_stats(rs)
    hhi_pos = hhi(rs, side="positive")
    hhi_neg = hhi(rs, side="negative")
    median_r = st.median(rs) if rs else None
    mean_to_median = (
        stats.mean_r / median_r
        if stats is not None and median_r is not None and median_r != 0
        else None
    )

    # Uniqueness-weighted effective n
    intervals = [
        (pd.to_datetime(r["anchor_ts"]).to_pydatetime(),
         pd.to_datetime(r["barrier_hit_ts"]).to_pydatetime())
        for r in primary
        if r.get("anchor_ts") and r.get("barrier_hit_ts")
    ]
    grid = sorted({t for iv in intervals for t in iv})
    uniqueness = average_uniqueness(intervals, grid=grid) if intervals else 1.0
    effective_n = len(primary) * uniqueness

    # Overlap-adjusted PSR: feed effective_n into the same Bailey & de Prado
    # formula. This is the number the Phase 3 gate should read — the raw-n
    # PSR ignores label-span concurrency and is optimistic when events overlap.
    psr_effective = (
        psr(sharpe=stats.sharpe, n=effective_n,
            skew=stats.skew, kurt=stats.kurt, benchmark_sr=0.0)
        if stats is not None else None
    )

    lines += [
        "-" * 70,
        "Primary label statistics",
        f"  n_raw:            {len(primary)}",
        f"  uniqueness:       {uniqueness:.3f}",
        f"  n_effective:      {effective_n:.1f}",
    ]
    if stats is not None:
        lines += [
            f"  Mean R:           {_fmt(stats.mean_r)}",
            f"  StDev R:          {_fmt(stats.stdev_r)}",
            f"  Sharpe:           {_fmt(stats.sharpe)}",
            f"  Skew (γ3):        {_fmt(stats.skew, 3)}",
            f"  Kurt (γ4):        {_fmt(stats.kurt, 3)}",
            f"  PSR (raw n):      {stats.psr_vs_zero:.3f}",
            f"  PSR (eff n):      {psr_effective:.3f}   (gate: >= {PSR_GATE})",
        ]
    if hhi_pos is not None:
        lines.append(f"  HHI winners:      {hhi_pos:.3f}   (gate: <= {HHI_WINNER_GATE})")
    if hhi_neg is not None:
        lines.append(f"  HHI losers:       {hhi_neg:.3f}")
    if median_r is not None and mean_to_median is not None:
        lines.append(f"  Median R:         {_fmt(median_r)}   (median/mean {mean_to_median:.2f})")

    # Control cohort (METHOD §1.4): count Bitget spot listings inside the
    # primary time window that did NOT get an Earn program on the same
    # coin_name. Descriptive only in Phase 2 — the actual DiD comparison
    # (control R vs Earn R over post-listing 7d) is Phase 3 research work
    # and lives in a downstream notebook, not here.
    try:
        anchor_ts_list = [pd.to_datetime(r["anchor_ts"]) for r in primary
                          if r.get("anchor_ts")]
        if anchor_ts_list:
            t_min = min(anchor_ts_list).isoformat()
            t_max = max(anchor_ts_list).isoformat()
            listings_r = (
                sb.table("bitget_listings")
                .select("symbol,coin_name,listing_ts,status")
                .gte("listing_ts", t_min)
                .lte("listing_ts", t_max)
                .execute()
            )
            listings_rows = listings_r.data or []
            earn_coins = {row["coin_name"] for row in raw if row.get("features", {})}
            # Fall back to a direct earn_events pull for coins seen in labels;
            # the label rows do not carry coin_name at the top level.
            evs = (
                sb.table("earn_events")
                .select("coin_name")
                .execute()
            )
            earn_coin_names = {r["coin_name"] for r in (evs.data or [])
                               if r.get("coin_name")}
            control_only = [l for l in listings_rows
                            if l.get("coin_name")
                            and l["coin_name"] not in earn_coin_names]
            lines += [
                "-" * 70,
                "Control cohort (METHOD §1.4 — descriptive)",
                f"  Primary time window:            [{t_min[:10]} … {t_max[:10]}]",
                f"  Bitget listings in window:      {len(listings_rows)}",
                f"  With Earn program (excluded):   {len(listings_rows) - len(control_only)}",
                f"  Control-arm cohort size:        {len(control_only)}",
                "  DiD analysis (control R vs Earn R): deferred to Phase 3",
            ]
    except Exception as e:  # noqa: BLE001
        LOG.warning("control-cohort section failed: %s", e)

    # Confound splits per METHOD §2.4 item 5: age, regime, positioning.
    # Regime is the 30d BTC return sign (§1.6). The realized-vol tercile
    # distribution is reported descriptively below the split.
    def in_age_bucket(r):
        age = r.get("bitget_listing_age_days")
        return age is not None and age >= 30

    def btc_bull_regime(r):
        v = r.get("btc_ret_30d_prior")
        return v is not None and v >= 0

    def low_vol_ramp(r):
        v = r.get("perp_vol_change_prior_24h")
        return v is not None and abs(v) <= 0.50

    split_specs = [
        ("age >= 30d",             in_age_bucket),
        ("BTC 30d return >= 0",    btc_bull_regime),
        ("|vol ramp 24h| <= 50%",  low_vol_ramp),
    ]
    lines += ["-" * 70, "Confound splits (sign must hold across >= 2/3)"]
    sign_hits = 0
    for name, pred in split_specs:
        n_s, mean_s, sign = _confound_split_stats(primary, pred, name)
        if mean_s is not None and mean_s > 0:
            sign_hits += 1
        lines.append(f"  {name:<25}  n={n_s:3d}  mean R = {_fmt(mean_s)}  ({sign})")

    # Descriptive regime characterization per METHOD §1.6: realized-vol
    # tercile distribution across the primary universe. Not a gate check —
    # buckets thin out effective n below §2.2's floor. Reporting only.
    rvols = [float(r["btc_30d_realized_vol"]) for r in primary
             if r.get("btc_30d_realized_vol") is not None]
    if len(rvols) >= 3:
        q_lo = st.quantiles(rvols, n=3)[0]
        q_hi = st.quantiles(rvols, n=3)[1]
        n_lo = sum(1 for v in rvols if v <= q_lo)
        n_mid = sum(1 for v in rvols if q_lo < v <= q_hi)
        n_hi = sum(1 for v in rvols if v > q_hi)
        lines += [
            f"  Regime vol distribution:  n={len(rvols)}  "
            f"low(<={q_lo:.2f})={n_lo}  mid={n_mid}  high(>{q_hi:.2f})={n_hi}",
        ]

    # Purged CV summary
    if intervals and len(intervals) >= 6:
        spans = pd.Series(
            [pd.Timestamp(b) for _, b in intervals],
            index=pd.DatetimeIndex([pd.Timestamp(a) for a, _ in intervals]),
        ).sort_index()
        cv = PurgedKFold(intervals=spans, n_splits=3, embargo_fraction=0.01)
        lines += ["-" * 70, "Purged 3-Fold CV"]
        for fold in cv.iter_folds():
            fold_labels = [primary[i] for i in fold.test]
            fold_rs = [float(r["realized_r"]) for r in fold_labels
                       if r.get("realized_r") is not None]
            fold_stats = bet_stats(fold_rs)
            if fold_stats:
                lines.append(
                    f"  Fold {fold.index}: n_train={len(fold.train)}  "
                    f"n_test={len(fold.test)}  mean R = {_fmt(fold_stats.mean_r)}  "
                    f"PSR = {fold_stats.psr_vs_zero:.3f}"
                )
            else:
                lines.append(
                    f"  Fold {fold.index}: n_train={len(fold.train)}  "
                    f"n_test={len(fold.test)}  degenerate"
                )
    else:
        lines += ["-" * 70, "Purged CV: skipped (need n >= 6 primary)"]

    # Gate rollup
    lines += ["-" * 70, "Gate criteria (all five must PASS to declare edge)"]
    if stats is None:
        lines.append("  degenerate statistics — no gate call possible")
    else:
        c1 = stats.mean_r > 0
        # Gate reads the effective-n PSR (overlap-adjusted) per de Prado Ch 4.4.
        c2 = psr_effective is not None and psr_effective >= PSR_GATE
        c3 = hhi_pos is not None and hhi_pos <= HHI_WINNER_GATE
        c4 = median_r is not None and stats.mean_r != 0 and (median_r / stats.mean_r) >= MEDIAN_MEAN_GATE
        c5 = sign_hits >= CONFOUND_SPLIT_HITS_REQUIRED
        lines += [
            f"  [{_pass_fail(c1)}]  Sign of mean R is positive",
            f"  [{_pass_fail(c2)}]  PSR (eff n) vs SR* = 0 >= {PSR_GATE}",
            f"  [{_pass_fail(c3)}]  HHI winners <= {HHI_WINNER_GATE}",
            f"  [{_pass_fail(c4)}]  Median/mean >= {MEDIAN_MEAN_GATE}",
            f"  [{_pass_fail(c5)}]  Sign consistency across >= {CONFOUND_SPLIT_HITS_REQUIRED}/3 splits",
        ]
        pass_all = c1 and c2 and c3 and c4 and c5
        gate_n = len(primary) >= MIN_N_FOR_GATE
        lines += [
            "-" * 70,
            f"n gate:       {'PASS' if gate_n else 'NOT YET'}  "
            f"(n={len(primary)}, need >= {MIN_N_FOR_GATE})",
            f"RESULT:       {'EDGE DECLARED' if pass_all and gate_n else 'DO NOT DECLARE EDGE'}",
        ]

    lines.append("=" * 70)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
