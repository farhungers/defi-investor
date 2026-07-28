---
id: LIB_0037
title: "The Econometrics of Financial Markets (book listing / placeholder)"
authors: ["Campbell, John Y.", "Lo, Andrew W.", "MacKinlay, A. Craig"]
year: 1997
type: book
source_path: "reaserch/your requests/8bCampbell.pdf"
tags: [event-study, econometrics, textbook, placeholder]
themes: [event-studies, validation]
links: [LIB_0003]
status: unread
last_touched: 2026-07-28
---

## Thesis
Textbook on empirical methods in financial economics. Chapter 4 (event studies) is the load-bearing reference for measuring abnormal returns around discrete events — directly relevant to our labeler design.

## Key claims
- Event study methodology: define event window, estimate normal returns via market model, compute CARs (Cumulative Abnormal Returns), test for statistical significance.
- Framework used by essentially all financial event studies since 1997.

## Relevance to defi-investor
**Load-bearing for A2c labeler (event-study CAR, pre-committed for post-gate).** Without this chapter, we can't formally implement the CAR labeler.

## Status
**File in `reaserch/your requests/` is only the book listing/marketing page, NOT the Ch 4 content.** User is providing the actual chapter or full book when convenient.

## Open questions
- Which market-model to use as "normal returns" benchmark for a crypto coin? BTC? A Bitget spot index? An equal-weighted altcoin basket?
- Event-window length and estimation-window length conventions.

## Related notes
- LIB_0003 — Tetlock (contrasting VAR-based event methodology)
