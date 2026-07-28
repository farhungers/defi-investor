# Map of Content

Entry point for the library. Organized by intellectual theme, not by folder. Add a note to a theme when it's a *load-bearing* input to that theme, not just tangentially related.

## Themes

### Discipline & epistemology
The intellectual scaffolding for how we do research. Popper, Ahrens, Hamming, and de Prado's methodological chapters live here.
- `LIB_0001` Advances in Financial Machine Learning (de Prado) — **integrated**
- `LIB_0005` How to Take Smart Notes (Ahrens) — **integrated**
- `LIB_0011` Popper — Logic of Scientific Discovery
- `LIB_0012` Hamming — Art of Doing Science and Engineering
- `LIB_0014` Bevelin — Seeking Wisdom (checklists/mental models)
- `LIB_0028` AFML · Reasonable Deviations (secondary summary)

### Validation & statistics
Backtest overfitting, Sharpe deflation, walk-forward, PSR, family-wise correction. Everything about "did we actually find a signal or fool ourselves."
- `LIB_0002` Deflated Sharpe Ratio (Bailey & de Prado 2014) — **skimmed, load-bearing**
- `LIB_0026` Walk-Forward Correlation (diagnostic)
- `LIB_0027` Walk-Forward Optimization
- `LIB_0029` Machine Learning in Econometrics

### Event studies & sentiment
Formal machinery for measuring abnormal returns around discrete events. Media-content as a signal channel.
- `LIB_0003` Tetlock 2007 — Giving Content to Investor Sentiment — **skimmed**
- `LIB_0037` Campbell/Lo/MacKinlay — placeholder (**awaiting actual chapter PDF**)

### Informed trading detection
Prediction-market corpus. Methodology for identifying when specific participants have informational edge. Directly relevant to the C1 frame.
- `LIB_0021` Detecting Informed Trading in Prediction Markets
- `LIB_0022` Wisdom of the Crowd or Wisdom of the Insider
- `LIB_0023` Smart Money on Polymarket
- `LIB_0024` Per-Market Information Leakage
- `LIB_0025` Wisdom of the Few Skilled Traders

### Microstructure
Order-book dynamics, funding rates, cross-venue liquidity. Direct input to Hypothesis A3 (order-book impact).
- `LIB_0015` BitMEX Research — Rate Gaps in Perpetual Futures
- `LIB_0016` Zhang 2026 — Funding Rate Mechanism (theory) — **skimmed**
- `LIB_0017` Crypto Perp Temporal Dynamics
- `LIB_0018` High-frequency dynamics of Bitcoin futures
- `LIB_0019` Brunnermeier & Pedersen — Market Liquidity and Funding Liquidity
- `LIB_0020` Flint 2017 PhD — Order placement strategies across venues — **skimmed, load-bearing for A3**

### Sizing & Kelly
Capital allocation, bet sizing, portfolio math. Relevant only after gate call, when execution enters scope.
- `LIB_0007` Kelly 1956 — original paper
- `LIB_0008` Chen — Kelly Criterion overview — **skimmed**
- `LIB_0009` Poundstone — Fortune's Formula
- `LIB_0010` Vince — Handbook of Portfolio Mathematics

### On-chain
Wallet clustering, cross-chain flows, on-chain crime patterns. Input for the on-chain confound channel (C3 from Decision 2 menu — deferred to post-A2).
- `LIB_0004` Victor — Address Clustering Heuristics for Ethereum — **skimmed, load-bearing for C3**
- `LIB_0035` Chainalysis 2025 Crypto Crime Report
- `LIB_0036` Elliptic — State of Cross-Chain Crime 2025

### Behavioral / mental models
Cognitive biases and reasoning frameworks. Background, not load-bearing for any current hypothesis.
- `LIB_0013` Kahneman — Thinking Fast and Slow
- `LIB_0014` Bevelin — Seeking Wisdom (also under discipline)

### Data systems architecture
Kleppmann DDIA. How to think about the trade-offs in our data pipeline.
- `LIB_0006` Kleppmann — Designing Data-Intensive Applications — **skimmed**

### Meta / process
Loops, agent design, research organization, practitioner guides.
- `LIB_0030` How to Succeed in Quant Trading
- `LIB_0031` Narang — Inside the Black Box (systematic investing) — **skimmed**
- `LIB_0032` Mitchell — Logic of Architecture (tangential; formal design reasoning)
- `LIB_0033` Kopadze — Loops explained (agent orchestration)
- `LIB_0034` Recommender System for Software Engineering

### Confirmed stray (not indexed)
- `verne-castaways-of-the-flag.pdf` — Jules Verne novel; assumed accidental drop by user. Not creating a LIB stub. Confirm with user if this was intentional; otherwise, safe to ignore or delete.

## Permanent notes
`permanent/*.md` — Vault's synthesis in own words. Populated as themes generate insight.

## How to grow this
- Adding a LIB stub for an unread paper: fine, put it under queued.
- Adding a paper to a theme after reading: move from queued to numbered LIB and edit relevant permanent notes.
- New theme: add a section here. Don't create parallel MOCs; one map, evolving.
