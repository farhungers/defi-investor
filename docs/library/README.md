# defi-investor research library

Atomic literature notes for the corpus in `reaserch/`. One note per source. Follows Sönke Ahrens's Zettelkasten principles (see `LIB_0005`) and Kleppmann's DDIA trade-off philosophy: simple structure at the top, complexity lives in content and connections.

## Structure

- `README.md` — this file
- `MOC.md` — Map of Content. Organized by intellectual theme, not by folder or source. Entry point for navigation.
- `LIB_NNNN_slug.md` — one atomic note per source, sequentially numbered
- `permanent/` — synthesis notes in Vault's own words, cross-linking multiple LIB notes. This is where Zettelkasten value compounds

## Naming convention

`LIB_NNNN_<short-slug>.md` where:
- `NNNN` is a stable, monotonic ID assigned in creation order. Never re-used.
- `<short-slug>` is a memorable hint (author-lastname_short-title). Slug can change, ID cannot.

## Frontmatter schema

```yaml
---
id: LIB_0001
title: "Full title"
authors: ["Last, First"]
year: 2020
type: book | paper | report | article | thread
source_path: reaserch/operator suggestions/xxx.pdf
tags: [tag1, tag2]
themes: [see MOC themes list]
links: [LIB_0002, LIB_0007]
status: unread | skimmed | read | integrated
last_touched: YYYY-MM-DD
---
```

## Body sections

1. **Thesis** — one line, the core claim
2. **Key claims** — 2-5 bullets
3. **Relevance to defi-investor** — how this maps to project decisions/hypotheses
4. **Open questions** — what this raises for us
5. **Related notes** — links to other LIB or permanent notes

## Read-status protocol

- `unread` — stub only, from title/abstract skim
- `skimmed` — abstract + intro + conclusion read; body untouched
- `read` — full read; key claims extracted with citations
- `integrated` — synthesized into at least one permanent note

Level up notes as they're actually engaged with. JIT reading: don't force a jump from `unread` to `read` unless a specific decision requires it.

## Search

`ripgrep` over `docs/library/` handles it. No DB. If the library exceeds ~500 notes, revisit (DDIA scaling threshold).
