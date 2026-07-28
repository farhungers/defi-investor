# Pre-registration YAML schema

Every hypothesis has a machine-readable YAML spec at `<id>.yaml`. Gate report auto-parses these; no drift between spec and executing code.

## Schema

```yaml
# Identity
hypothesis_id: A2a                    # unique, stable identifier
name: "Bitget+Binance Earn sold-out predicts short-horizon return"
frame_id: FRAME_C1                    # link to the parent frame
version: 1                            # bump on any amendment

# Provenance
registered_date: 2026-07-28
registered_by: Vault
git_commit_hash: "abc123..."          # populated at commit
git_tag: "prereg-A2a-v1-2026-07-28"
osf_id: "xxxxx"                       # populated after OSF upload
supersedes: null                      # id of prior version if applicable

# What is being tested
event_class: "earn_sold_out"          # short label of the triggering event
event_source_venues: ["bitget", "binance"]
tradable_venue: "bitget"              # execution universe (Decision 1)

# Labeler
labeler_id: "v0.2.1"                  # points to code
labeler_type: "fixed_horizon"         # fixed_horizon | triple_barrier | event_study_car | order_book_impact
labeler_config:
  horizons: [24, 48, 168]             # hours; CV search space per Decision 5
  anchor: "sold_out_ts"
  price_source: "bitget_kline_1m"     # Bitget chart per Decision 1

# Gate criteria (all must pass to declare edge)
gate:
  min_primary_n: 30                   # CHARTER kill-criterion #2
  mean_r_positive: true
  psr_effective_gate: 0.95            # apply family-wise correction on top
  hhi_winners_max: 0.15
  median_over_mean_min: 0.5
  confound_split_hits_required: 2     # of 3 splits

# Family-wise correction
correction_method: "holm_bonferroni"  # holm_bonferroni | bonferroni | deflated_sharpe
kill_counter_position: 1              # this hypothesis's slot in KILL_COUNTER.md

# Decision date (pre-committed per Decision 9)
decision_date: 2026-09-30             # hard date; whichever first: n>=30 OR this date

# Red-team section location
red_team_section: "HYPOTHESIS_A2a.md#red-team"

# Status
status: draft                         # draft | active | gated_pass | gated_fail | retired
```

## Field notes

- `hypothesis_id`: stable and unique. Never reused. Renaming requires a new id + `supersedes` link.
- `git_commit_hash` and `git_tag`: populated at registration commit. YAML MAY be updated once with these fields (not counted as a real amendment).
- `osf_id`: populated after Open Science Framework upload. YAML MAY be updated once with this.
- `labeler_id`: must point at an actual labeler in `src/defi_investor/labelers/`. Discrepancy = code drift = discipline failure.
- `labeler_config.horizons`: CV search space, not multiple hypotheses. Per Decision 5, multi-timeframe is CV, not separate tests.
- `gate.psr_effective_gate`: nominal threshold. Actual gate applied by report is threshold with `correction_method` applied against `kill_counter_position` and total registered count.
- `decision_date`: mandatory. No open-ended experiments.

## Validation

`scripts/validate_prereg.py` (to be built in Phase 3d) will:
- Parse the YAML.
- Confirm all required fields present.
- Verify `labeler_id` exists in code.
- Verify `git_tag` exists and points to a commit that contains this YAML file.
- Verify `red_team_section` exists in the linked Markdown with at least 3 enumerated null-explanations.
- Verify `kill_counter_position` matches KILL_COUNTER.md.
