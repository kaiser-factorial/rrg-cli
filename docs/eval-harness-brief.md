# Design brief — pipeline eval harness (live run-logger + auto-metrics)

- **Status:** Brief / not yet built. Written 2026-06-23 (evening) to seed a future build session.
- **Scope:** evaluate the **RRG pipeline itself** — its process and outcomes as a tool — *not*
  the scientific validation of any origin paper. (That second thing is what RRG already does;
  this measures whether RRG *works well* while doing it.)

## Framing

- **MovieRatings is the test fixture for the pipeline.** It's the controlled demo where we
  roughly know the right answers, so it's the set we use to shake out and evaluate the pipeline
  mechanics. **RMP capstone is the real test set** once MovieRatings is dialed in.
- The harness is **hybrid and voice-first** (this is the key design decision, settled):
  auto-derived metrics from artifacts RRG already emits, **plus** a live voice process-logger
  that captures the operator's experience *as the run happens*. Logs save into a folder under
  `Projects/`; because that's a Cowork-mounted location, Claude (or whichever model is in use)
  reads them back directly to debug/refine together. No copy-paste round-trip.
- **The voice-logger is a standalone, RRG-agnostic meta-tool — not part of the RRG GUI**
  (revised 2026-06-23). Rationale: narrating your process out loud is useful across *any* project
  and *any* tool, and shouldn't be coupled to the RRG codebase or a single GUI session. So it
  lives as a small desktop utility that does STT → writes timestamped transcripts to a
  `Projects/voice_logs/` folder → which any model session can pick up. The RRG-specific part
  (the auto-metrics) stays inside `rrg-cli`; the logger sits beside it, general-purpose.

## Three components

### 1. Auto-metrics (`rrg eval` + a GUI panel)
Most of what a process-eval needs is already on disk — derive, don't re-enter:

- **Process / mechanics** — round-trip completed without error; **blinding held** (read the
  `*.breach.json` record: copied-secret flag, ran-inside-project warning); marker auto-resolved
  vs manual fallback (import return `auto_resolved`); **deliverable-contract compliance** (does
  the returned run actually contain conforming `raw/Q<n>_summary.json`, the
  `Q<n>_analysis.py → raw/Q<n>_raw.csv → Q<n>_fig.py → Q<n>_fig.png` chain, and DYFA `## Q<n>`
  sections?); file counts; re-runs needed. Sources: `operator/_packages/provenance_log.jsonl`,
  `operator/_grading/*.breach.json`, the run folder contents.
- **Outcomes / meaningfulness** — per-question verdict distribution (REPRODUCED / CONVERGED /
  DIVERGED / …) from grading state; inter-model agreement when ≥2 validators; reproduce-vs-copy
  signal (breach guard is one input); human grading effort (verdicts confirmed, reopens).
  Sources: `operator/_grading/*.json`, the cross-run overview.

Deliverable: a per-run scorecard-style **eval report** (markdown/JSON) the operator and Claude
can both read. Likely `rrg eval --run <path>` writing `operator/_eval/EVAL_<run>.md`.

### 2. Voice process-logger (standalone desktop meta-tool, RRG-agnostic)
A small always-available utility for narrating your process out loud while you work — on *any*
project, not just RRG:

- **Trigger:** a global hotkey (start/stop dictation) so you never have to switch windows; it
  should work no matter which app/tool is in front.
- **STT:** prefer a **local model** for privacy and offline use — `whisper.cpp` /
  `faster-whisper` running on-device. (Browser Web Speech API is the quick-and-dirty alternative
  but routes audio to Google and is Chrome-only; only worth it for a throwaway v0.) Existing
  apps like MacWhisper / Superwhisper, or macOS Shortcuts + built-in dictation, are also viable
  if configured to save transcripts to the folder — worth evaluating vs building.
- **Storage:** timestamped transcripts to `Projects/voice_logs/` (e.g.
  `voice_logs/<YYYY-MM-DD>_<HHMMSS>.md`, or `.jsonl` with `{at, text}` per utterance). Optionally
  let the operator speak a tag/context ("…friction:", "…this is for the MovieRatings build")
  that the tool keys on, but keep v1 dumb — just transcribe + timestamp.
- **The loop:** operator narrates as they go → transcripts land in `Projects/voice_logs/` →
  Claude (or whichever model) reads that folder directly, alongside RRG's auto-metrics, and we
  work out the kinks. Because it's just a folder of text, it's portable across sessions, models,
  and projects.
- **Implementation candidates** (decide in build session): (a) a Python utility — `sounddevice`
  capture + `faster-whisper` + a global-hotkey lib (and optionally a `rumps` menubar icon);
  (b) an off-the-shelf dictation app pointed at the folder; (c) macOS Shortcuts + native
  dictation. Lowest-effort-that-is-private wins.

### 3. Synthesis
Claude reads the auto-metrics report + the run logs from the workspace and produces a
findings/refinement pass: friction points, contract violations, blinding results, and concrete
tweaks. This is just analysis — no new tooling — but it's the payoff the other two feed.

## Open decisions for the build session

- **Build the logger vs adopt one** — a `faster-whisper` + global-hotkey Python utility gives
  full control and privacy; an off-the-shelf dictation app pointed at `Projects/voice_logs/`
  might be 90% of the value for 10% of the effort. Evaluate before building.
- **Transcript granularity / schema** — plain timestamped `.md` per session vs `.jsonl` per
  utterance; whether to support a spoken tag/context. Start dumb (transcribe + timestamp).
- **How much RRG to auto-compute** — start with the cheap, certain signals (breach result,
  `auto_resolved`, contract presence-lint, verdict counts); add fuzzier ones (cost, turns) later.
- **Correlating logs with runs** — the logger is RRG-agnostic, so linking a voice note to a
  specific `run_id` is best-effort (timestamp overlap, or the operator just says it aloud). Don't
  over-engineer the coupling.

## Suggested build order

Two independent tracks:

- **RRG auto-metrics (in `rrg-cli`):** `rrg eval --run <path>` + the presence/contract checks
  over a returned run → `operator/_eval/EVAL_<run>.md`. Pure backend, testable without the GUI.
- **Voice process-logger (standalone, in `Projects/`):** STT utility → `Projects/voice_logs/`.
  Start with the lowest-effort-that-is-private option; iterate. Decoupled from RRG entirely.

Synthesis (Claude reads both folders) needs no new tooling. **First real input: the MovieRatings
Gemini replication run** — narrate it into `voice_logs/` and let `rrg eval` chew the artifacts.
