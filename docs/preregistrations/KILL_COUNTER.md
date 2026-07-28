# Kill counter — family-wise correction ledger

Per Decision 4 D3 (Session 3, 2026-07-28), this file tracks every hypothesis registered under any frame in this project. The count drives family-wise correction of gate thresholds (Holm-Bonferroni or Deflated Sharpe).

## Ledger

| # | Hypothesis ID | Frame | Registered | Status | Gate date | Gate result | Notes |
|---|---|---|---|---|---|---|---|
| 1 | A2a | FRAME_C1 | (pending) | draft | 2026-09-30 | — | v0.2.1 fixed-horizon labeler |
| 2 | A2b | FRAME_C1 | (pending) | draft | 2026-09-30 | — | v0.3.0 triple-barrier labeler |
| 3 | A2c | FRAME_C1 | (pre-committed post-gate) | queued | TBD | — | v0.4.0 event-study CAR labeler; registered only if A2a or A2b passes |
| 4 | A3 | FRAME_C1 | (pending) | draft | TBD | — | Order-book impact labeler; separate signal channel |

## How this drives correction

- Total registered count `N` = number of rows in "Status ≠ queued".
- Bonferroni-corrected significance: `alpha_i = 0.05 / N` for each hypothesis.
- Holm-Bonferroni: sort p-values, compare rank-i p-value against `0.05 / (N - i + 1)`.
- Deflated Sharpe (Bailey & de Prado 2014, LIB_0002): substitute `N` as the number of trials in the DSR formula.

Retired hypotheses stay counted. That's the whole point.

## Updating this file

- Adding a hypothesis: append a row, note in the hypothesis YAML that its `kill_counter_position` matches the new row.
- Gate result reported: update the row with the result and any notes.
- Never delete rows. History is the correction.

## Amendment log

| Date | Change | Reason |
|---|---|---|
| 2026-07-28 | Initial ledger created | Decision 4 D3 in Session 3 |
