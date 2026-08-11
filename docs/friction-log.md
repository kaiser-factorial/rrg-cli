# Friction log

Running tally of friction and "what broke" while *operating* RRG — the input to the
run-over-build loop in `docs/PHASES.md` (Phase 2 produces it, Phase 3 consumes it). An item
earns an engine change only once a **real run** shows it actually bites. "Adopt don't build" and
"is it really demanded?" apply.

| # | Date | Friction | Proposed fix | Earned? (a real run hit it) |
|---|------|----------|--------------|------------------------------|
| 1 | 2026-06-26 | Opening the GUI needs the full `rrg gui --workspace workspace --open` each time | Top-level `rrg --gui` shortcut defaulting `--workspace ./workspace --open` | Not yet — logged at first instinct, pre-run |
| 2 | 2025-08-10 | Report file named after roster model, not actual validator model (e.g. "default_MovieRatings_Report.md") | Normalizer or dispatch should rename report file on import to match validator+model | Yes — Grok run had wrong report name |
| 3 | 2025-08-10 | DYFA check misses "## Question N" headers (only matched "## Q<n>") | Fixed: check_deliverable_contract now matches both patterns | Yes — Grok run falsely reported all DYFA sections missing |
| 4 | 2025-08-10 | Validators produce output in subfolder (replication_default/) not work dir root | Import source should be the subfolder, not the work dir | Yes — both runs |
| 5 | 2025-08-11 | PANEL_VAL/ was a stale duplicate of LoveSmarter operator data | Removed entirely; canonical copy in workspace/LoveSmarter/ | Yes — confusing during cleanup |
