# Pre-registrations

Per Decision 4 (Session 3, 2026-07-28), this directory holds all pre-registered research hypotheses for defi-investor. Each hypothesis has:

1. A human-readable Markdown narrative (`HYPOTHESIS_<id>.md`)
2. A machine-readable YAML spec (`<id>.yaml`) that the gate report auto-parses
3. A git-tag at registration time (`prereg-<id>-v<n>-<date>`)
4. An OSF timestamp (populated after upload)
5. A mandatory red-team section within the narrative

## Files

- `README.md` — this file
- `FRAME_C1.md` — the broad research frame all hypotheses inherit from
- `YAML_SCHEMA.md` — schema definition for `<id>.yaml` files
- `HYPOTHESIS_<id>.md` — one per hypothesis
- `<id>.yaml` — machine-readable spec, one per hypothesis
- `REGISTRY.md` — index of all pre-registrations with status and links
- `KILL_COUNTER.md` — running ledger of tested hypotheses for family-wise correction

## Registration protocol

1. Draft `HYPOTHESIS_<id>.md` and `<id>.yaml`.
2. Verify the red-team section enumerates at least 3 concrete null-explanations.
3. Verify the YAML validates against `YAML_SCHEMA.md`.
4. `git commit` with message `prereg: register HYPOTHESIS_<id>`.
5. `git tag prereg-<id>-v1-YYYY-MM-DD`.
6. Push tag to origin.
7. Upload the two files to OSF; record OSF ID in the YAML frontmatter.
8. Update `REGISTRY.md`.
9. Update `KILL_COUNTER.md` with the new hypothesis at position `n+1`.
10. Only AFTER steps 1-9 complete: the labeler pointed at by this hypothesis is allowed to write labels.

## Amendment protocol

- **Bumping labeler versions or gate thresholds**: bump YAML version, git-tag as `-v2-`, upload to OSF, note in the hypothesis's amendment log.
- **Retiring a hypothesis**: mark `status: retired` in YAML, note reason, keep in KILL_COUNTER (retired hypotheses still count for family-wise correction — that's the point of tracking every test).
- **Reframing after gate call**: per FRAME_C1 §6, gate call may trigger frame-level reframe. That's a new frame (`FRAME_C1.v2` or `FRAME_C2`), which requires re-registering hypotheses under the new frame.
