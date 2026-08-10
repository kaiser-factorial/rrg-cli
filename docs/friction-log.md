# Friction log

Running tally of friction and "what broke" while *operating* RRG — the input to the
run-over-build loop in `docs/PHASES.md` (Phase 2 produces it, Phase 3 consumes it). An item
earns an engine change only once a **real run** shows it actually bites. "Adopt don't build" and
"is it really demanded?" apply.

| # | Date | Friction | Proposed fix | Earned? (a real run hit it) |
|---|------|----------|--------------|------------------------------|
| 1 | 2026-06-26 | Opening the GUI needs the full `rrg gui --workspace workspace --open` each time | Top-level `rrg --gui` shortcut defaulting `--workspace ./workspace --open` | Not yet — logged at first instinct, pre-run |
