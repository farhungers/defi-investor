"""Phase 3 gate report for HYPOTHESIS_A2b (v0.3.0 triple-barrier labeler).

A2b is CATEGORICAL: the gate is a binomial test on P(+1) vs P(-1) under
symmetric upper/lower barriers, not a continuous-return PSR. This script
lives alongside `gate_report.py` (which handles A2a continuous returns);
both share confound splits and exclusion logic but compute their own stats.

Runs per horizon: 24h / 48h / 168h. Each is a separate rejection in the
family; family size N is imported from `family_wise.N_REGISTERED` and drives
the Holm-Bonferroni correction applied across all horizons AND the parallel
A2a and A3 gates when their scripts feed p-values into a joint rollup.

For now this script reports A2b's own horizon-wise p-values with the
Holm cascade applied AS IF the other family hypotheses' p-values were
provided; when A2a and A3 are run jointly we'll fold their p-values into
the same `holm_bonferroni` call.

Read-only. Zero Supabase writes. Zero Telegram traffic.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import math
import os
import random
import statistics as st
import sys
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client

from defi_investor.backtest.family_wise import (
    DEFAULT_ALPHA,
    N_REGISTERED,
    bonferroni_alpha,
    holm_bonferroni,
)
from defi_investor.backtest.stats import hhi
from defi_investor.labelers.triple_barrier_v030 import HORIZONS_HOURS, LABELER_VERSION


LOG = logging.getLogger("defi_investor.gate_report_a2b")

MIN_N_FOR_GATE = 30
HHI_WINNER_GATE = 0.15
CONFOUND_SPLIT_HITS_REQUIRED = 2

# Bootstrap CI is descriptive, not a gate criterion. Fixed seed keeps
# each run reproducible against the same corpus.
BOOTSTRAP_ITERS = 10_000
BOOTSTRAP_SEED = 20260817


def _load_labels_for_horizon(sb, horizon_hours: int) -> list[dict]:
    """v0.3.0 backfill stores horizon in labeler_version suffix like '0.3.0#h24'.

    Uses LIKE with a wildcard tail so any future extension of the suffix
    (e.g. a retry marker like '0.3.0#h24#r1') still matches. Mirrors the
    fix in backfill_labels_v030._already_labeled, added after an equality
    check on the un-suffixed version silently missed every row.
    """
    version_prefix = f"{LABELER_VERSION}#h{horizon_hours}"
    r = (
        sb.table("earn_event_labels")
        .select("*")
        .like("labeler_version", f"{version_prefix}%")
        .execute()
    )
    return r.data or []


def _resolved_primary(labels: list[dict]) -> list[dict]:
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


def _binomial_p_two_sided(k_plus: int, k_minus: int) -> Optional[float]:
    """Two-sided binomial p-value for k_plus successes out of (k_plus + k_minus)
    trials under H0: p = 0.5.

    Returns None if the pooled n is 0 (test undefined).
    """
    n = k_plus + k_minus
    if n == 0:
        return None
    k_obs = min(k_plus, k_minus)  # tail is the smaller side
    # Sum P(X <= k_obs) under Binom(n, 0.5), double for two-sided
    p_one_tail = 0.0
    log_half_n = -n * math.log(2)  # log(0.5^n)
    for i in range(k_obs + 1):
        log_binom = _log_comb(n, i)
        p_one_tail += math.exp(log_binom + log_half_n)
    p = min(2 * p_one_tail, 1.0)
    return p


def _log_comb(n: int, k: int) -> float:
    """log(C(n,k)) using lgamma to avoid overflow for large n."""
    if k < 0 or k > n:
        return float("-inf")
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def _bootstrap_p_plus_ci(
    directional_labels: list[int], *, iters: int = BOOTSTRAP_ITERS,
    seed: int = BOOTSTRAP_SEED,
) -> Optional[tuple[float, float]]:
    """95% percentile bootstrap CI on P(+1 | directional).

    Descriptive diagnostic only — gate remains the binomial p-value.
    Useful to visualize sample-size uncertainty at low n. Returns None if
    the directional sample is empty.
    """
    if not directional_labels:
        return None
    rng = random.Random(seed)
    n = len(directional_labels)
    p_plus_samples: list[float] = []
    for _ in range(iters):
        draws = [directional_labels[rng.randrange(n)] for _ in range(n)]
        p_plus_samples.append(draws.count(1) / n)
    p_plus_samples.sort()
    lo = p_plus_samples[int(0.025 * iters)]
    hi = p_plus_samples[int(0.975 * iters)]
    return lo, hi


def _confound_split_asymmetry(
    labels: list[dict], predicate, name: str,
) -> tuple[int, Optional[float], str]:
    """Slice by predicate. Return (n, asymmetry, sign).

    Asymmetry = P(+1) - P(-1) among labels in {+1, -1} (ignoring 0/time).
    """
    slice_ = [r for r in labels if predicate(r)]
    plus = sum(1 for r in slice_ if r.get("label") == 1)
    minus = sum(1 for r in slice_ if r.get("label") == -1)
    total_directional = plus + minus
    if total_directional == 0:
        return len(slice_), None, "n/a"
    asym = (plus - minus) / total_directional
    return len(slice_), asym, "positive" if asym > 0 else "negative"


def _fmt(v: Optional[float], places: int = 4) -> str:
    if v is None:
        return "—"
    return f"{v:+.{places}f}"


def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "—"
    return f"{p:.4g}"


def _horizon_block(sb, horizon_hours: int) -> tuple[list[str], Optional[float], int]:
    """Return (report_lines, p_value_or_None, n_directional) for one horizon."""
    labels = _load_labels_for_horizon(sb, horizon_hours)
    primary = _resolved_primary(labels)

    lines = [
        "-" * 70,
        f"Horizon {horizon_hours}h",
        f"  Raw label rows:         {len(labels)}",
        f"  Primary (resolved):     {len(primary)}",
    ]

    if not primary:
        lines.append("  n=0 -- skipping stats for this horizon")
        return lines, None, 0

    counts = {1: 0, -1: 0, 0: 0}
    for r in primary:
        lbl = r.get("label")
        if lbl in counts:
            counts[lbl] += 1
    n_directional = counts[1] + counts[-1]
    p_val = _binomial_p_two_sided(counts[1], counts[-1])

    lines += [
        f"  Label distribution:     UPPER(+1)={counts[1]}  "
        f"LOWER(-1)={counts[-1]}  TIME(0)={counts[0]}",
        f"  Directional n:          {n_directional}  "
        f"(gate: n >= {MIN_N_FOR_GATE})",
    ]
    if n_directional > 0:
        p_plus = counts[1] / n_directional
        lines.append(f"  P(+1 | directional):    {p_plus:.3f}  (H0: 0.500)")
        directional_labels = [r["label"] for r in primary if r.get("label") in (1, -1)]
        ci = _bootstrap_p_plus_ci(directional_labels)
        if ci is not None:
            lines.append(
                f"  Bootstrap 95% CI:       [{ci[0]:.3f}, {ci[1]:.3f}]  "
                f"(descriptive, not a gate criterion; iters={BOOTSTRAP_ITERS})"
            )
    if p_val is not None:
        lines.append(f"  Two-sided binomial p:   {_fmt_p(p_val)}")

    # HHI on positive outcomes (concentration): use realized barrier hit
    # times so each event contributes a magnitude. Since v0.3.0 is
    # categorical we approximate concentration as coin_name distribution
    # among +1 events — if all +1s are one coin, HHI = 1.
    pos_coins = [r.get("coin_name") for r in primary if r.get("label") == 1]
    if pos_coins:
        by_coin: dict[str, int] = {}
        for c in pos_coins:
            by_coin[c] = by_coin.get(c, 0) + 1
        total = sum(by_coin.values())
        hhi_pos = sum((n / total) ** 2 for n in by_coin.values())
        lines.append(
            f"  HHI (+1 coin concentration): {hhi_pos:.3f}  "
            f"(gate: <= {HHI_WINNER_GATE})"
        )

    # Confound-split sign consistency
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
        ("age >= 30d",            in_age_bucket),
        ("BTC 30d return >= 0",   btc_bull_regime),
        ("|vol ramp 24h| <= 50%", low_vol_ramp),
    ]
    lines.append("  Confound splits (asymmetry sign must hold >= 2/3):")
    sign_hits = 0
    for name, pred in split_specs:
        n_s, asym, sign = _confound_split_asymmetry(primary, pred, name)
        if asym is not None and asym > 0:
            sign_hits += 1
        lines.append(f"    {name:<24}  n={n_s:3d}  asym={_fmt(asym)}  ({sign})")
    lines.append(f"  Sign consistency: {sign_hits}/3  (gate: >= {CONFOUND_SPLIT_HITS_REQUIRED})")

    return lines, p_val, n_directional


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
    lines = [
        "=" * 70,
        "defi-investor - Phase 3 Gate Report - HYPOTHESIS_A2b",
        f"timestamp:        {now}",
        f"labeler_version:  {LABELER_VERSION} (per-horizon labels stored as {LABELER_VERSION}#h<H>)",
        f"family size N:    {N_REGISTERED}",
        f"Bonferroni alpha: {bonferroni_alpha():.4f}  (raw alpha={DEFAULT_ALPHA})",
    ]

    p_by_horizon: dict[str, float] = {}
    n_by_horizon: dict[int, int] = {}
    for h in HORIZONS_HOURS:
        block, p, n = _horizon_block(sb, h)
        lines.extend(block)
        if p is not None:
            p_by_horizon[f"A2b_h{h}"] = p
        n_by_horizon[h] = n

    if p_by_horizon:
        lines += ["-" * 70, f"Holm-Bonferroni across A2b horizons (N={N_REGISTERED} counts full family)"]
        for res in holm_bonferroni(p_by_horizon):
            mark = "[REJECT H0]" if res.rejected else "[keep H0]"
            lines.append(
                f"  {res.hypothesis_id:<10}  p={_fmt_p(res.p_value)}  "
                f"corrected_alpha={_fmt_p(res.corrected_alpha)}  {mark}"
            )
        lines.append(
            "  NOTE: rejections above assume no other hypothesis in the family "
            "has been gated yet. Once A2a/A3 gates produce p-values, "
            "fold them into the same holm call for the joint rollup."
        )

    n_gate_hits = sum(1 for n in n_by_horizon.values() if n >= MIN_N_FOR_GATE)
    lines += [
        "-" * 70,
        f"n gate:       {'PASS' if n_gate_hits > 0 else 'NOT YET'}  "
        f"(horizons meeting n>={MIN_N_FOR_GATE}: {n_gate_hits}/{len(HORIZONS_HOURS)})",
        "RESULT:       report is DESCRIPTIVE only until n gate PASSES on at least one horizon",
        "=" * 70,
    ]

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
