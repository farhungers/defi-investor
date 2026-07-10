"""Backtest reporting stats for defi-investor.

Built from de Prado *Advances in Financial Machine Learning* Ch 14 and
Bailey & de Prado (2012) "The Sharpe Ratio Efficient Frontier". Standard
math; the code is defi-investor-native.

## What lives here

- Per-bet Sharpe from a list of realized R values (no annualization —
  Earn events don't have a natural time index).
- Probabilistic Sharpe Ratio (PSR): P(true SR > benchmark) given the
  observed skew, kurtosis, and n. This is the number the Phase 3 gate
  reads (`METHOD.md` §2.4 — must be ≥ 0.95).
- Herfindahl-Hirschman concentration of positive / negative returns —
  guards against edges that hinge on 1-2 outlier events (`METHOD.md`
  §2.4 gate item — `h_plus ≤ 0.15`).
- de Prado Ch 4.4 average uniqueness for overlapping label intervals.
  Feeds the effective n that goes into PSR.

## What does NOT live here

- Deflated Sharpe Ratio. Requires an honest count of independent trials.
  Not applicable at n = 30 primary decision (single hypothesis H1).
  Reintroduce at n ≥ 100 if we compare sub-hypotheses.
- Annualized Sharpe. Requires a bets-per-year assumption; the reporting
  layer decides that, not this module.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Iterable, Optional


# ---------- container ------------------------------------------------------


@dataclass(frozen=True)
class BetStats:
    """Aggregated per-bet statistics.

    All fields are dimensionless (Sharpe is per-bet, not annualized).
    """
    n: int
    mean_r: float
    stdev_r: float
    sharpe: float
    skew: float           # γ3 — 0 for Gaussian
    kurt: float           # γ4 — 3 for Gaussian (non-excess)
    psr_vs_zero: float    # P(true SR > 0) in [0, 1]


# ---------- moment helpers -------------------------------------------------


def _standard_normal_cdf(z: float) -> float:
    """Φ(z) via math.erf. Kept private so callers don't reach for scipy."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _central_moment(values: list[float], mean: float, order: int) -> float:
    """Sample central moment of the given order. n divisor (not n-1)."""
    n = len(values)
    if n == 0:
        return 0.0
    return sum((v - mean) ** order for v in values) / n


def _skew(values: list[float], mean: float, stdev: float) -> float:
    """Sample skewness γ3. Returns 0 when the sample is degenerate."""
    if len(values) < 3 or stdev == 0:
        return 0.0
    return _central_moment(values, mean, 3) / (stdev ** 3)


def _kurt(values: list[float], mean: float, stdev: float) -> float:
    """Sample kurtosis γ4 (non-excess: Gaussian value is 3.0)."""
    if len(values) < 4 or stdev == 0:
        return 3.0
    return _central_moment(values, mean, 4) / (stdev ** 4)


# ---------- core APIs ------------------------------------------------------


def psr(*, sharpe: float, n: int, skew: float, kurt: float,
        benchmark_sr: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio — P(true SR > benchmark_sr) given the
    observed sample statistics.

    Bailey & de Prado (2012):

        PSR(SR*) = Φ(  (SR - SR*) · √(n - 1)
                       / √(1 - γ3·SR + ((γ4 - 1) / 4) · SR²)  )

    Returns a value in [0, 1]. Passes the Phase 3 gate (METHOD §2.4) at
    PSR ≥ 0.95.

    Guardrails:
    - n < 2 → return 0.5 ("cannot tell"). PSR is meaningless on a single
      observation and the honest report is indifference.
    - Denominator variance ≤ 0 → return 0.5. Happens when negative skew
      combined with a very large Sharpe implies fat left tail heavier
      than the SR can support. Refuse to report a spurious near-1 number.

    The 0.5 fallback is deliberate: it lets downstream `if psr > 0.95`
    gates fail closed on degenerate input.
    """
    if n < 2:
        return 0.5
    variance = 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * (sharpe ** 2)
    if variance <= 0:
        return 0.5
    z = ((sharpe - benchmark_sr) * math.sqrt(n - 1)) / math.sqrt(variance)
    return _standard_normal_cdf(z)


def bet_stats(returns: Iterable[float]) -> Optional[BetStats]:
    """Fold a return series down to `BetStats`. `None` on degenerate input.

    Degenerate = fewer than 2 samples, or zero stdev (constant series).
    Returning None instead of a fake number is the point — the Phase 3
    gate reads this, and a fabricated PSR would be a discipline break.
    """
    rs = list(returns)
    if len(rs) < 2:
        return None
    mean = statistics.fmean(rs)
    stdev = statistics.stdev(rs)
    if stdev == 0:
        return None
    sharpe = mean / stdev
    sk = _skew(rs, mean, stdev)
    kt = _kurt(rs, mean, stdev)
    return BetStats(
        n=len(rs), mean_r=mean, stdev_r=stdev, sharpe=sharpe,
        skew=sk, kurt=kt,
        psr_vs_zero=psr(sharpe=sharpe, n=len(rs), skew=sk, kurt=kt, benchmark_sr=0.0),
    )


def hhi(returns: Iterable[float], *, side: str) -> Optional[float]:
    """Herfindahl-Hirschman concentration index, normalized to [0, 1].

    - 0.0 = the returns on the requested side are perfectly uniform
      (winners each contribute an equal share — a diversified edge)
    - 1.0 = one return accounts for the entire side (single-outlier
      edge — the exact fragility the gate is designed to catch)

    Returns None when fewer than 2 returns of the requested sign exist
    (not enough to characterize concentration).

    Args:
        returns: any iterable of realized R values.
        side: 'positive' for h+ (winner concentration) or 'negative' for
              h- (loser concentration).
    """
    if side == "positive":
        cohort = [r for r in returns if r > 0]
    elif side == "negative":
        cohort = [r for r in returns if r < 0]
    else:
        raise ValueError("side must be 'positive' or 'negative'")

    n = len(cohort)
    if n < 2:
        return None
    total = sum(abs(r) for r in cohort)
    if total == 0:
        return None
    shares = [abs(r) / total for r in cohort]
    raw = sum(s * s for s in shares)
    # Rescale so uniform → 0 and one-dominant → 1.
    return (raw - 1.0 / n) / (1.0 - 1.0 / n)


# ---------- overlap uniqueness (de Prado Ch 4.4) --------------------------


def average_uniqueness(intervals: list[tuple], *, grid: list) -> float:
    """Average label uniqueness given a set of overlapping intervals.

    de Prado Ch 4.4: label i's uniqueness at time t is 1 / concurrency(t)
    where concurrency(t) counts how many label intervals cover t. Label
    uniqueness u_i is the mean of that ratio across label i's own span.
    The corpus-level `average_uniqueness` is the mean of u_i.

    A corpus with no overlaps returns 1.0. A corpus where every pair of
    labels perfectly overlaps returns ~0.5. This feeds the effective n
    that PSR consumes at the Phase 3 gate.

    Args:
        intervals: list of (anchor, barrier_hit) tuples. Any comparable
            timestamp type works — this uses only `<=` comparisons.
        grid: sorted list of comparison timestamps at which to evaluate
            concurrency. Typically the sorted anchor list is enough for
            Earn events (spans are large relative to anchor granularity).

    Returns:
        A float in (0, 1]. Empty inputs return 1.0 by convention.
    """
    if not intervals:
        return 1.0
    concurrency = {t: 0 for t in grid}
    for a, b in intervals:
        for t in grid:
            if a <= t <= b:
                concurrency[t] += 1

    per_label = []
    for a, b in intervals:
        contribs = [
            1.0 / concurrency[t]
            for t in grid
            if a <= t <= b and concurrency[t] > 0
        ]
        if contribs:
            per_label.append(sum(contribs) / len(contribs))
    if not per_label:
        return 1.0
    return sum(per_label) / len(per_label)
