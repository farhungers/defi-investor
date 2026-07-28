---
id: LIB_0019
title: "Market Liquidity and Funding Liquidity"
authors: ["Brunnermeier, Markus K.", "Pedersen, Lasse Heje"]
year: 2009
type: paper
source_path: "reaserch/operator suggestions/Market Liquidity and Funding Liquidity.pdf"
tags: [liquidity, funding-liquidity, margin-spirals, brunnermeier-pedersen]
themes: [microstructure]
links: [LIB_0015]
status: unread
last_touched: 2026-07-28
---

## Thesis
Market liquidity (ease of trading) and funding liquidity (ease of financing positions) are jointly determined and can reinforce each other via margin spirals. The paper formalizes the feedback loop that drives liquidity crises.

## Key claims (from reputation)
- Margin requirements amplify shocks: falling prices → tighter margins → forced deleveraging → further falling prices.
- Speculator funding constraints affect market liquidity even for uncorrelated assets.
- Liquidity dries up asymmetrically — usually when needed most.

## Relevance to defi-investor
- Background for interpreting crypto crashes and their aftermath.
- Not directly load-bearing for A2 or A3, but relevant if we ever explicitly model liquidation-cascade regimes (Decision 5 D2 wildcard territory).
- Also foundational for understanding funding-rate dynamics (LIB_0015, LIB_0016).

## Open questions
- Do their identified margin-spiral patterns show up in crypto perp liquidation cascades? Likely yes; Zhang 2026 (LIB_0016) may implicitly test this.

## Related notes
- LIB_0015, LIB_0016 — funding rate mechanics
