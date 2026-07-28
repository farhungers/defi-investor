---
id: LIB_0006
title: "Designing Data-Intensive Applications (2nd Edition, Early Release)"
authors: ["Kleppmann, Martin", "Riccomini, Chris"]
year: 2025
type: book
source_path: "reaserch/Designing_Data-Intensive_Apllications_2nd_Edition_-_Martin_Kleppmann.pdf"
tags: [data-systems, architecture, trade-offs, reliability, scalability, maintainability]
themes: [data-systems, discipline]
links: [LIB_0005]
status: skimmed
last_touched: 2026-07-28
---

## Thesis
There are no perfect data-system solutions, only trade-offs. Reliable, scalable, and maintainable systems come from picking the right compromises for the specific workload, not from adopting a universal architecture.

## Key claims (from Ch 1 preview)
- **Reliability + Scalability + Maintainability** is the triangle. Every design choice moves you around inside it.
- **Transaction processing vs analytics** are structurally different workloads and force different data models.
- **Cloud vs self-hosting** trade off ops burden against control and cost.
- **Data-intensive vs compute-intensive**: for data-intensive apps, the challenge is storing and moving data, not parallelizing computation.

## Relevance to defi-investor
- **Trade-off lens for the pipeline**. Supabase choice, GH Actions vs external cron, deep vs lightweight scrapers, single-labeler vs multi-labeler — every architecture decision in Decisions 1-6 is a DDIA-style trade-off.
- **Simplicity heuristic for the library** — DDIA's "no perfect scheme, pick simple, revisit" matches Ahrens's Zettelkasten philosophy exactly. Both were the intellectual basis for the library architecture in this repo.
- **Scaling threshold**: DDIA implicitly justifies deferring database-based library search until we exceed ~500 notes.

## Open questions
- Which later chapters (unavailable in Early Release) will matter as the project grows? Likely Ch 11 (Batch Processing) for the labeler pipeline and Ch 12 (Stream Processing) if we go to near-real-time event handling.
- When does Supabase become the wrong tool? Likely never at our scale — but worth reading Ch 4/5 when they land to check.

## Related notes
- LIB_0005 — Ahrens Zettelkasten (agrees on simple-structure principle)
