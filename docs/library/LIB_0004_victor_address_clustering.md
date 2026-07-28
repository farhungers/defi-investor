---
id: LIB_0004
title: "Address Clustering Heuristics for Ethereum"
authors: ["Victor, Friedhelm"]
year: 2020
type: paper
source_path: "reaserch/your requests/FC20_31_camera_ready.pdf"
tags: [on-chain, ethereum, wallet-clustering, address-heuristics, entity-detection]
themes: [on-chain, informed-trading]
links: []
status: skimmed
last_touched: 2026-07-28
---

## Thesis
Ethereum's account model breaks the classic Bitcoin UTXO-based clustering heuristics. Victor proposes account-model-native heuristics (deposit-address reuse, airdrop multi-participation, token-transfer authorization) that cluster ~17.9% of active EOAs into ~340k entities. Deposit-address heuristic is the strongest.

## Key claims
- Bitcoin's multi-input heuristic is the workhorse of clustering research but doesn't apply to Ethereum (single input/single output txs).
- Three novel heuristics for Ethereum: (1) exchange deposit-address reuse (users send to same deposit address across visits), (2) airdrop multi-participation (an entity claiming from multiple addresses gets grouped), (3) token-transfer authorization patterns.
- Deposit-address heuristic clusters the most and is highest-confidence.
- Public implementation: `github.com/etherclust/etherclust`.

## Relevance to defi-investor
- **Foundation for on-chain confound channel (C3 from Decision 2 menu — deferred to post-A2).** If/when we bring on-chain into scope, Victor's heuristics are the reference implementation for "which wallets are the same entity."
- **Free-tier compatible** — deposit-address heuristic requires only Etherscan API + basic tx graph, no Nansen. Aligns with Decision 2's free-only constraint.
- **Substitutes for the "Mastering Ethereum Ch on addresses" I originally asked for** — this is more rigorous (academic, reproducible, has code).

## Open questions
- Coverage: 17.9% of EOAs is substantial but leaves 82% uncounted. Does the coverage skew toward or away from the wallets we care about (whales, informed traders)?
- Applicability to non-Ethereum chains — Bitget lists many BSC/Arbitrum/Base coins. Does the deposit-address heuristic transfer? (BSC yes, L2s partially — deposit addresses may live on L1.)
- Freshness: paper is 2020, on-chain patterns evolve. Are the heuristics still ~current, or has abstraction (account abstraction, smart wallets) diluted them?

## Related notes
- (queued) LIB for Chainalysis 2025 report — cross-chain crime patterns, may cite updated Ethereum heuristics
- (queued) LIB for Elliptic cross-chain crime 2025
