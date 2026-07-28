"""Family-wise correction utilities per KILL_COUNTER.md.

Two methods:
- Bonferroni:   alpha_i = alpha / N  for every hypothesis (conservative)
- Holm-Bonferroni: sort p-values ascending; compare p_(i) against
    alpha / (N - i + 1) for i = 1..N. Stop at first non-rejection.

`N` here is the total number of *registered* hypotheses in the family
(kill counter positions with status != queued). Even hypotheses whose
gates haven't been run yet count — that's the discipline principle.

Reference: Holm (1979); Bailey & de Prado (2014) for the DSR analogue.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


DEFAULT_ALPHA = 0.05

# Total registered hypotheses in the FRAME_C1 family per KILL_COUNTER.md
# as of 2026-07-28. When a new hypothesis is registered, bump this and
# update KILL_COUNTER.md in the same commit. A2c is 'queued' pre-gate and
# does NOT count until it's promoted; so N=3 (A2a, A2b, A3).
N_REGISTERED = 3


def bonferroni_alpha(alpha: float = DEFAULT_ALPHA, n: int = N_REGISTERED) -> float:
    """Simple Bonferroni-corrected significance level."""
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    return alpha / n


@dataclass(frozen=True)
class HolmResult:
    hypothesis_id: str
    p_value: float
    rank: int                # 1-based
    corrected_alpha: float
    rejected: bool           # under Holm-Bonferroni at rank i
    corrected_p: float       # p * (N - i + 1), capped at 1.0


def holm_bonferroni(
    pvalues: dict[str, float],
    *,
    alpha: float = DEFAULT_ALPHA,
    n: int = N_REGISTERED,
) -> list[HolmResult]:
    """Return per-hypothesis Holm-Bonferroni results, sorted by p ascending.

    `pvalues` is a mapping from hypothesis_id -> raw p-value. `n` is the
    family size (defaults to N_REGISTERED).

    Holm's step-down: sort ascending; the smallest is compared against
    alpha/n, the next against alpha/(n-1), ... the largest against
    alpha/1. As soon as one FAILS to be rejected, none of the subsequent
    (larger) p-values can be rejected either — Holm stops the cascade.
    """
    if not pvalues:
        return []
    if n < len(pvalues):
        raise ValueError(
            f"n ({n}) must be >= number of pvalues ({len(pvalues)}); "
            "family size is fixed pre-gate and cannot shrink post-hoc."
        )

    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    results: list[HolmResult] = []
    stopped = False
    for rank, (hid, p) in enumerate(items, start=1):
        corrected_alpha = alpha / (n - rank + 1)
        if stopped:
            rejected = False
        else:
            rejected = p <= corrected_alpha
            if not rejected:
                stopped = True
        corrected_p = min(p * (n - rank + 1), 1.0)
        results.append(HolmResult(
            hypothesis_id=hid,
            p_value=p,
            rank=rank,
            corrected_alpha=corrected_alpha,
            rejected=rejected,
            corrected_p=corrected_p,
        ))
    return results
