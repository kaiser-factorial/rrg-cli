# RRG — Phases & Scope

- **Status:** Strategic roadmap. Written 2026-06-26 to refit scope after the *engine
  outran the science*. **Loop-structured, not calendar-structured** — there is no deadline
  yet, so the upcoming advisor meeting is the forcing function that sets the next milestone.
- **Companions:** `SPEC.md` (what RRG *is*), `docs/HANDOFF.md` (what's *built*),
  `docs/eval-harness-brief.md` (the pipeline-eval design), `docs/agentic-rrg-parked.md`
  (the deliberately-deferred agentic direction).

---

## The situation (why this doc exists)

RRG is technically mature — 80 green tests, two ADRs, the full round-trip lifecycle
(`run_id`, breach guard, reversible archive), a multi-tab GUI. But it has been exercised by
exactly **one** real external run (the Gemini MovieRatings test), which already surfaced two
genuine problems (the `../../../origin/` blinding breach and the validator convention gap).
Heavy build, one signal.

Three facts reframe everything:

1. **None of the real blockers are tooling.** `PROJECT_SUMMARY` lists three — the
   CFA/measurement basis is pending, the generalization design doesn't exist, and the paper
   scope needs advisor agreement. All scientific or social. You cannot commit your way out of
   any of them.
2. **The advisor hasn't seen the GUI.** The person who decides those three things hasn't seen
   the instrument built to serve them.
3. **There is no deadline.** A free-running build with no external pull optimizes for the
   *pleasure* of building — generality, polish, the agentic dream — instead of the goal. The
   absence of a deadline is *why* the tool raced ahead.

## The governing principle

> **No new engine feature unless a real run demanded it.**

With no deadline to enforce discipline, this is the self-imposed forcing function. Its
corollary resolves the "science and tool are inseparable" tension cleanly:

> **The single act that advances *both* the science and the tool is operating the pipeline on
> real studies.** A real run produces validation-depth tiers (science) *and* reveals what the
> method actually needs (tool). Speculative generality advances neither.

So the plan is not *science over tool*. It is **run over build**. You are not abandoning the
thing you love building — you are finally *feeding* it.

## Assumptions this plan rests on (check these)

- The advisor is the decision-maker for the CFA basis, the generalization design, and paper
  scope. (If not, Phase 1's target is wrong.)
- **MovieRatings** is a controlled fixture whose answers are known well enough to teach the
  method and shake out mechanics.
- **RMP capstone** is a *real-but-lower-stakes* test set, runnable before LoveSmarter is fully
  unblocked — the bridge between toy and prize.
- The engine is **good enough to run today** (Phase 2 is *not* gated on more building).
- **LoveSmarter (LS)** replication is gated on the settled CFA basis (`PROJECT_SUMMARY`
  blocker #1) — so the real LS run waits on Phase 1's advisor decisions.

---

## The phases

### Phase 0 — Freeze & frame *(this week — mostly not coding)*

- **Goal:** stop the feature drift and manufacture the forcing function.
- **Moves:** declare an **engine feature freeze**; write the agentic idea into
  `docs/agentic-rrg-parked.md` (out of your head, safe on disk, so it stops pulling); refresh
  `docs/ADVISOR_MEETING.md` (demo plan + the three decisions) and define what the meeting must
  *produce*.
- **Exit:** a scheduled advisor meeting + the parked doc + a tight demo plan.
- **Watch-out:** "just one more small feature first" is the exact failure mode this phase
  exists to break. The freeze starts now, not after the next commit.

### Phase 1 — Show the prof / close the loop

- **Goal:** get the science unblocked and the method validated by the one person who matters.
- **Moves:** demo the validation ladder on the **method-teacher fixture** (see the ladder
  below), walk one round-trip, and extract directions on the three blockers — CFA basis,
  generalization design, paper scope.
- **Exit:** the three blockers have answers or directions; the advisor has *reacted* to the
  instrument.
- **Trade-off — which study to demo:** MovieRatings tells the cleanest teaching story (known
  answers, no live fumble); a real LS slice proves it isn't a toy. Lean **MovieRatings to teach
  + one LS slice to prove**, *unless* the advisor only cares about their own study — then lead
  with LS. This is the one genuinely advisor-dependent call; decide it from the relationship.

### Phase 2 — Run it once, for real, end-to-end *(the inseparable act)*

The phase that actually advances both science and tool. Escalate across three rungs:

1. **MovieRatings** — one clean round-trip to shake out mechanics (you roughly know the answers).
2. **RMP capstone** — the first *real* run; lower stakes than LS, exercises the pipeline on
   genuinely unknown output.
3. **LoveSmarter replication** — the prize. One frontier + one open model on the **settled CFA
   basis**, per `PROJECT_SUMMARY`'s immediate path.

- **Moves:** narrate each run into `Projects/voice_logs/`; keep a running **"what broke /
  what was friction"** list. **Do not build during this phase — operate.**
- **Exit:** ≥1 real LS replication run graded + a concrete defect/friction list.
- **Watch-out:** the urge to fix things mid-run. Note them; don't fix them yet. The list *is*
  the deliverable of this phase — it's what makes Phase 3 reactive instead of speculative.

### Phase 3 — Harden from signal *(reactive building only)*

- **Goal:** build only what Phase 2 *proved* necessary.
- **Candidate shelf** (pull only what the run demanded): validator-side import normalizer; eval
  auto-metrics (`rrg eval`); the origin column in the cross-run overview; figure caption-match
  calibration. **Adopt** an off-the-shelf voice logger rather than build one — the eval brief
  already concludes "lowest-effort-that-is-private wins."
- **Exit:** a run rarely needs hand-holding.
- **Trade-off:** every shelf item is justified by a line in the Phase 2 defect list or it waits.
  "It would be nice" is not a justification; "the run failed without it" is.

### Phase 4 — Produce the science *(the actual deliverable)*

- **Goal:** the inseparable pair, realized.
- **Moves:** robustness across the agreed roster; generalization once its design is settled;
  per-finding **validation-depth tiers**; cross-model agreement; a **methods-paper draft** with
  LoveSmarter as the worked example.
- **Exit:** validation-depth tiers + a paper draft. The tool becomes an *appendix* to the
  paper, not the paper.

### ⏸ Parked — Agentic RRG *(capture only — see `docs/agentic-rrg-parked.md`)*

The decisive reason it's later, not merely "out of scope": **you cannot automate a process you
have never run manually end-to-end even once.** The agent would need a proven manual loop as
its spec — which *is* Phases 2–4. It is downstream by definition. **Un-park trigger:** after the
methods paper, *if* RRG becomes its own project or a second lab wants to use it.

---

## The escalation ladder

```
   METHOD TEACHER          REAL TEST SET            THE PRIZE
   (known answers)         (lower stakes)           (the science)
  ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
  │ MovieRatings │  ───▶  │ RMP capstone │  ───▶  │  LoveSmarter │
  │  shake-out   │        │  first real  │        │ replication  │
  │  + prof demo │        │     run      │        │ → robustness │
  └──────────────┘        └──────────────┘        └──────────────┘
       teach                  prove                   deliver
```

## The loop that governs Phases 2–3

```
        ┌──────────────────────────────────────────────────┐
        │            no feature without a run               │
        ▼                                                   │
  [ run it for real ] ──▶ [ what broke? ] ──▶ [ harden only that ]
        ▲                                                   │
        └──────────────────────────────────────────────────┘
```

---

## What I'd revisit as it grows *(deliberately deferred re-evaluations)*

- **A second lab or study appears** → the cartridge's generality finally gets *earned* (today
  it's speculative). This is also the natural un-park trigger for agentic RRG.
- **Runs become routine** → the eval harness (`rrg eval` + auto-metrics) earns its place; until
  then, narrate-and-eyeball is enough.
- **A deadline appears** → recompress from loop-structured to calendar-structured: pick the
  minimum rungs of the escalation ladder that produce a defensible paper and cut the rest.

## Open decisions (carried, not resolved here)

- **Prof-demo study** — MovieRatings to teach vs lead-with-LS (advisor-dependent; see Phase 1).
- **Voice logger** — adopt off-the-shelf vs build (brief leans adopt).
- **Validator-side normalizer** — still open whether the strict prompt + verify turn is enough,
  or an import-time normalizer is needed. Phase 2 decides it with evidence.
- **Generalization design** — what counts as "opening the data," and whether Stage 3 holds a
  method fixed. Advisor input required (`GENERALIZATION_DESIGN.md` has the prior thinking).
