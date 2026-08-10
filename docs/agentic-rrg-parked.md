# Parked — Agentic RRG

- **Status:** Deliberately deferred, 2026-06-26. Captured so the idea is safe on disk and stops
  pulling on the build. **Not** scheduled. See `docs/PHASES.md` for where it sits.
- **One-line:** a future in which a model *operates* RRG — orchestrating packaging, dispatch,
  import, and grading prep — instead of an operator driving the CLI/GUI by hand.

## The idea (so it isn't lost)

RRG becomes agentic *within itself*: the model creates the packages, runs the blinding lint,
dispatches to validators, imports returns, and stages the round-trip — with the human as
reviewer/approver rather than driver. The pipeline already has the shape for this: every step
is a discrete `rrg` command with structured I/O (provenance JSON, breach records, grading
state), which is exactly what an agent needs to act and verify. The operator's role would
shift from "run the steps" to "own the secrets and confirm the verdicts."

## Why it is parked (not just "out of scope")

1. **You cannot automate a process you have never run manually end-to-end even once.** The
   agent's spec *is* the proven manual loop — Phases 2–4 in `PHASES.md`. Automating a loop you
   haven't run risks hard-coding the wrong loop.
2. **It is a different category of thing.** RRG today is an *instrument* for the LoveSmarter
   paper. Agentic RRG is a *product/research direction*. Conflating them is the specific scope
   risk this whole roadmap exists to manage.
3. **It multiplies surface area before the core loop is proven.** New failure modes (an agent
   that mis-routes a package, leaks a secret, or fabricates a verdict) land on top of a
   pipeline whose blinding has been validated by one real run. Wrong order.
4. **It does not unblock anything real.** The actual blockers are scientific (CFA,
   generalization, paper scope). An agent operating the pipeline solves none of them.

## What would un-park it (the trigger)

- The methods paper exists (Phase 4 done), **and**
- one of: RRG becomes its own project independent of the LoveSmarter paper, *or* a second lab
  / study wants to use it (i.e. the cartridge's generality is finally *earned*, not speculative).

## When it returns, start here (notes to future-you)

- The manual loop from Phases 2–4 is the ground truth — encode *that*, not an idealized version.
- The safety boundary is unchanged and non-negotiable: the agent may operate the **package
  boundary**, but the origin/results-key stays operator-only, and the **blinding lint remains
  the hard gate** no agent can `--force` past without a recorded human override.
- Grading stays human. The engine already refuses to assign final verdicts (`SPEC.md` §11);
  an agent must inherit that refusal, not relax it.
- Likely first slice: agent *drafts* a package build + dispatch plan and a human approves —
  read-and-propose before act-and-verify.
