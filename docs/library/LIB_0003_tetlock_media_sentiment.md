---
id: LIB_0003
title: "Giving Content to Investor Sentiment: The Role of Media in the Stock Market"
authors: ["Tetlock, Paul C."]
year: 2007
type: paper
source_path: "reaserch/your requests/Tetlock_Media_Sentiment_JF.pdf"
tags: [sentiment, media, event-study, var, principal-components]
themes: [event-studies, informed-trading]
links: []
status: skimmed
last_touched: 2026-07-28
---

## Thesis
Media content quantitatively predicts short-term market movements. High pessimism in a WSJ column ("Abreast of the Market") predicts downward price pressure followed by reversion; extreme pessimism (high or low) predicts high volume. Consistent with noise-trader / liquidity-trader models; inconsistent with media as pure information proxy.

## Key claims (from abstract + intro)
- First paper to show news media content predicts broad market indicators.
- Method: principal-components analysis on WSJ text → simple pessimism measure → VAR against market returns.
- Effect: high pessimism → downward pressure → reversion. Predicts volume regardless of direction.
- Inconsistent with theories treating media as (a) proxy for new fundamental info, (b) proxy for volatility, (c) irrelevant sideshow.

## Relevance to defi-investor
- **Methodological template** for turning unstructured text into a numeric signal series that can enter a VAR/event-study framework. If we ever revisit D5 (community sourcing, Telegram/Discord), Tetlock's PCA-on-text pattern is the reference implementation.
- **Signal-vs-noise framing** — the paper carefully distinguishes "sentiment predicts price" from "sentiment reflects fundamentals." Same distinction applies to Earn signals: does the sold-out event *cause* the pump (insider positioning) or *reflect* it (retail chasing already-moving price)?
- **Event-study exposure** — this paper uses VAR rather than the Campbell/Lo/MacKinlay Ch 4 abnormal-return framework. Useful contrast when we build v0.4.0 CAR labeler.

## Open questions
- How does Tetlock control for reverse causality (returns → sentiment)? Deep-read to extract the identification strategy.
- Would his short-window predictive effect (~1 day) map to our 24h/48h horizons, or does noise-trader reversion swamp our windows?

## Related notes
- (queued) Campbell/Lo/MacKinlay Ch 4 — the event-study benchmark methodology
