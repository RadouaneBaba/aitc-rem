# What is broken, and what is left

The working document. [SPEC.md](SPEC.md) is the design and does not change;
[CLAUDE.md](CLAUDE.md) is the rules you need in order to change things safely;
this is the list of things that are wrong right now and the things not yet
built. It replaces `PLAN.md`, whose milestones are all closed and whose build
order stopped at Phase 3.

Last updated 2026-08-25.

**Every defect below was found by reading the code against the 13 runs in
`runs/`, and every one carries the evidence that proves it.** That matters more
than the list: a finding with a reproduction is a fix waiting to happen, and a
finding without one is an opinion. Where a claim here is not yet measured, it
says so.

---

## Part 1 · Defects

Ranked by what they cost. The first three are the same shape — **a check that
reports success while looking at nothing** — which is worth seeing as one
pattern rather than three bugs.

### 1. `find_text` truncates to 40 matches and drops the end of the recording

`server/evidence/store.py:336` sorts matches by event id and then caps at
`MAX_MATCHES = 40`. Event ids are zero-padded, so alphabetical order is
chronological order, and the cap **systematically discards the latest events** —
which is where a test's verdict lives.

Measured on `rec_MT7MXBS9B2VB`:

```
'Medium Wicker Basket'  at evt_024:  40 matches  RESOLVES=True   <-- AT THE CAP
'Wicker Basket'         at evt_032:  40 matches  RESOLVES=False  (index stops at evt_009)
'18'                    at evt_032:  40 matches  RESOLVES=False  (index stops at evt_021)
```

Those strings are at evt_032 in the recording. `assertion_grounding`
(`validators/grounding.py:200`) rejects on `not any(m.eventId == cited)`, so a
**true, correctly cited claim is rejected as ungrounded**. `bind._best_literal`
makes the same call to *choose* candidates, so on any recording long enough to
hit the cap the deterministic pass is biased toward early events. One bound
claim in that run sits exactly on the cap and resolved by luck.

This is the failure CLAUDE.md already documents for the URL gap — *"if a claim
you believe is true gets rejected, check what got indexed"* — arriving through
truncation rather than through a missing source. **Both validators are right;
the index is incomplete.**

**Fix.** A presence check must not read a globally capped list. Either cap per
event, or give the store an uncapped `contains_at(literal, event_id)` for the
validator and the binder and leave the cap on the agent-facing tool, where it
exists to bound a response size.

### 2. `no_pruned_assertion` has never run — 0 pass, 13 skip

`validators/grounding.py:281` resolves pruned events through `omitted.segmentId`
→ `ctx.segments`. Under draft-then-bind nothing sets `segmentId`; omissions on
disk carry `eventIds` only:

```
2 omissions across runs/, keys: (afterStepId, eventCount, eventIds, reason, summary)
```

So `pruned_events` is always empty, the validator returns early, and its skip
message still reads *"decomposition is Phase 2"* — from before Phase 2 shipped.
`rec_MT7MXBS9B2VB` omitted `evt_034` and the validator reported "no subject".

`event_coverage` received exactly this migration and reads `omitted.eventIds`
with the segment path as a fallback (`validators/consistency.py:195`). This
sibling was missed.

**Fix.** Read `omitted.eventIds` first, keep the segment path for omissions
written the old way. One `for` loop, and it should be a copy of the one in
`event_coverage`.

### 3. `criticFindingsRaised` is not measuring the critic

Wrong in 10 of 13 runs, in both directions:

| recording | `critic.json` findings | metric reports |
|---|---|---|
| `MSYWWJBVQOM8` | 2 | **4** |
| `MT7VTN7ZRJPO` | 3 | **2** |
| `MT7MXBS9B2VB` | 1 | **0** |
| `MT8TEM57CRGS` | 1 | **0** |

`run.py:1687` sets it from `RepairOutcome.findings_raised` (`repair.py:110`),
which counts distinct `(stage, targetStepId, finding)` over **repair attempts**.
So it:

* counts **validator**-triggered repairs as critic findings — `mutation_claimed`
  routes to two stages, so one validator failure contributes 2;
* counts **zero** for any finding with no repair route, which is `coherence` and
  `state_jump` — the two deliberately empty rows, and the two most important
  kinds.

`repairConvergenceRate` shares that denominator. The `Findings` / `Converged`
pair was introduced specifically to avoid the vacuity trap, and it is measuring
something else.

**Fix.** Count from `CriticResult.findings` across every attempt, not from
repair attempts. Report repair attempts as their own number if they are wanted —
they are a different fact.

### 4. The drafter has never made a single retrieval

Every tool call across all 13 runs, by stage:

```
assert     50      (binding)
coverage   15
```

Zero from `decompose` (drafting), zero from critic, zero from bugmode.
`inv_draft` reads `used=0/8` on every run, including the 34-event commercial
one. `find_text` — "the grounding index" — has been invoked by an agent **0
times**; 5 of the 12 tools have ever been used at all.

`draft.py` has `DRAFT_BUDGET = 12`, an entire prompt section on "Looking things
up", and the line *"making no tool calls at all is a perfectly good outcome"*.
The model has taken that invitation 13 times out of 13. **The stage described as
the home of SS3.3's decide-retrieve-observe loop is empirically a single-shot
prompt.**

This reframes the ablation: A0/A1/A2 differ by tool availability, but the
drafter uses no tools in any of them. The only adaptive retrieval in the system
is binding's contested path, which fired in 2 runs of 13.

**Not obviously a bug, and that is why it is here rather than in Part 3.** Zero
retrieval on a legible session is the designed outcome and costs nothing. Zero
retrieval on `rec_MT7MXBS9B2VB` — where the drafter then discarded the verdict
as `abandoned` and wrote three near-duplicate steps — is the design not
delivering. The question to answer before changing anything: **does the drafter
decline to retrieve because the index is sufficient, or because the prompt made
declining easy?** Run one recording with the "no tool calls is fine" sentence
removed and compare the documents. That is a one-recording experiment and it
decides whether the retrieval budget at this stage is real.

### 5. Per-step effort has a floor of exactly 1 per bound claim

```
9 of 13 runs have range 0 — every step reads exactly 1
rec_MT7MXBS9B2VB: {step_002: 1, step_003: 1, step_004: 1}
```

Those investigations are `budgetUsed=1, budgetMax=0` (`bind.py:767`): the
deterministic pass's one mandatory `get_snapshot`. That is a **process-mandated
call, not effort** — precisely what `ROUTINE_TOOLS` exists to exclude, left
unapplied to the stage that replaced `search_step_library`. CLAUDE.md quotes
`{step_002: 1, step_003: 4, step_004: 1}` as SS3.3's variance; on the flagship
recording the column is flat and the `1`s are constants.

`budgetMax=0` is also just wrong on its own terms — the review UI renders "used
1 of 0".

**Fix.** Either exclude the deterministic pass's call the way `ROUTINE_TOOLS`
excludes a routine one, or stop giving it a `stepId` and let it appear only in
`toolCallsTotal`. Set `budgetMax` to something true either way.

### 6. `Background` can contain `When` and `Then`, and no validator looks

`narrative._leading_setup_count` (`narrative.py:288`) cuts on `role != setup`.
`narrative._opening_block` cuts on `role != setup` **or the step carries an
accepted assertion**. Background is built from the first while keywords come
from the second, so they disagree. Reproduced:

```gherkin
Background:
  Given the tester signs in
  When the tester opens the checkout page
  Then the confirmation banner appears
```

`gherkin_style._scenarios` (`validators/style.py:324`) skips the Background
block entirely; its comment says *"it is shared setup, it never asserts"*, which
nothing enforces. Real Gherkin runners reject this, and an Xray import would
choke on it.

**Latent only because no run has ever produced two scenarios.** The scenario
break fix (Part 2) makes it reachable, which is why it is on this list rather
than filed as a curiosity.

Related and in the same area: `renderers/gherkin.py:110` passes
`lift_background=siblings > 1`, while `sync_keywords`, `trace_md`, `xlsx`,
`jira`, `qase` and `review.py` all take the default `False`. The evidence
sidecar and the review UI therefore describe a different layout from the
`.feature` file they document — the trap `sync_keywords` exists to prevent.

**Fix.** `_leading_setup_count` should defer to `_opening_block`. Then teach
`_scenarios` to read the Background block and fail it on any `When` or `Then`,
so the comment becomes a check.

### 7. `effort_difficulty.py` declares sufficiency at two edited steps

`scripts/effort_difficulty.py:145` — `enough = points >= 12 and runs >= 3 and
edited >= 2`. Current state:

```
steps 104   reviewedRuns 26   stepsEdited 2   sufficient TRUE
pearson -0.0566   meanEffortEdited 1.0   meanEffortUntouched 1.412
```

Two positives out of 104 cannot support a correlation, the reported `r` is
noise, and its sign currently points **against** SS3.4's thesis. CLAUDE.md
advertises the script as one that "refuses to overclaim"; it refuses below two.

**Fix.** Raise the bar to something that can distinguish signal from nothing,
and say what it is in the caption. Until then the honest output is "not enough
data", which the script is already able to print.

### 8. A hard-failed run still writes its opt-in exports

`_erase_output` removes `.feature`, `.trace.md` and `.bug.md` when
`no_placeholder_leak` hard-fails. Then `cli.py:234` calls `export_all(result.ir,
...)` unconditionally, and xlsx / jira / qase render **the same IR the leak was
detected in** — `no_placeholder_leak` scans `case.model_dump()`
(`validators/output.py:70`), so the leaked value is in the IR by definition.

Latent because `exports: []` is the default. That is luck, not design.

**Fix.** Gate `export_all` on `result.report.ok`, or move the export inside the
pipeline behind the same check that erases the other artifacts.

### 9. `event_coverage` checks "at least once", not "exactly once"

`validators/consistency.py:191` unions into a set. The drafting prompt says
every event id must appear **EXACTLY ONCE**; a drafter that assigns one event to
two steps passes the net that exists to make its freedom safe, and ships two
steps describing the same action.

**Fix.** Count occurrences rather than unioning, and reject a duplicate with the
event id named.

### Carried from the prompt review, still open

* **`coherence` and `state_jump` have no repair route.** `CRITIC_REPAIR`
  (`repair.py:84`) is deliberately missing both, because acting on either means
  re-drafting and re-drafting can change the step count. The consequence, on the
  flagship recording: the critic said *"this covers three separate upgrade
  behaviours and reaches three distinct verdicts, making it three test cases in
  one"* — correct, specific, actionable — and the artifact shipped unchanged. A
  scenario **split** on existing step boundaries changes no step's identity and
  would resolve the common case without touching the reproducibility guarantee.
* **The critic's worked example is lifted from the recording it is judged on.**
  `critic.py:68-74` embeds the Fortnum hamper scenario verbatim — `Morocco`,
  `Small Wicker Basket`, `hampers category page is loaded`. CLAUDE.md's own rule
  is that worked examples outweigh rules and contradict them silently. The
  drafting prompt gets this right with a neutral domain; the critic does not,
  and its finding on that recording cannot be told apart from recall.
* **Bug mode still asks the model for a `toolCallId`.** `bugmode.py:362`. Every
  other stage was rebuilt so a fabricated citation is *inexpressible*; this is
  the one place the model still supplies the pointer, checked after the fact in
  `grounding.py`. CLAUDE.md claims the bug report's `actual` is "bound exactly
  as tightly as any assertion". It is bound one tier weaker, and it is the
  sentence a developer reads before deciding whether to go and reproduce
  something.
* **The drafter is handed 12 tools and told about 5.** `query_element`,
  `get_full_snapshot`, `get_neighbouring_segments`, `get_objective` and
  `search_step_library` are unmentioned in the prompt. `search_step_library`'s
  tool description still reads *"Search before inventing new wording"* — a
  directive from the deleted naming stage, now loose in every agent's tool list,
  and exactly the mandatory-effort pattern that collapsed Spread to 0.16.
* **`draft.py` and `digest.py` have no tests of their own.**
  `tests/test_bind.py` now covers the binding pass; the other two Phase 4 stages
  are exercised only end to end through `ScriptedModelClient` fakes in
  `test_pipeline.py`, while the three stages they replaced each had a module.

---

## Part 2 · Fixed on 2026-08-25

Recorded so nobody does it twice. All under `bash scripts/check.sh`, 443 tests
passing.

**Evidence must witness what the claim checks.** `COVERAGE_FLOOR` measures how
much of the *literal* the claim accounts for; nothing measured the reverse, and
the reverse is the guarantee. `bind._unwitnessed` now requires every value the
claim **quotes** and every **number** in it to appear in the evidence — not a
claim-side coverage floor, which would reject honest verbose claims. Calibrated
against all 21 (claim, literal) pairs the pipeline actually produced: zero false
positives, both known-bad pairs caught. Deterministic pass declines to the
agent; the agent's own answer is refused.

**A claim that the interface appeared is refused.** `bind._existence_only`. The
drafting prompt forbids these in bold and `rec_MT7VTN7ZRJPO` closed its scenario
on one anyway, bound to a panel heading.

**The declared scenario break had never fired.** A `scenario_break` carries no
`eventId` — `export.ts` attaches an annotation to an event only when it is a
fact about that event — and `_split_on_declared_breaks` filtered on `a.eventId`,
so it returned on its first line on every recording since it was written. Every
test of that path used the factory to set an `eventId` the recorder never sets.
`segment.break_openers` is now the one resolution, shared. The digest also never
mentioned the break at all, so the drafter merged across it; it now prints
`-- THE TESTER DECLARED A NEW TEST CASE HERE --` and the prompt says a scenario
begins there.

**`MAX_BEATS` is stated in the drafting prompt as a number.** The gate rejects at
five and `gherkin_style` has no repair route, so it was a gate the author could
not aim at.

---

## Part 3 · Remaining work

### Re-run the ablation — do this before quoting any number

The table in CLAUDE.md is from the **old** pipeline and says so. The seven
fixtures have since been re-recorded and the generator replaced. Nothing in this
repo currently reports a measured A0/A1/A2 comparison.

Fix Part 1's #3 and #5 first, or the re-run will bake the wrong `Findings` and a
flat effort column into the number everyone quotes.

### SS18 milestone 21 · multi-tab / popup capture

Deferred, and the reason still holds: SS4's own table puts cross-tab stitching
*beyond* Phase 3, and the SS4 row points at SS6.6, which is about narration.
There is no spec section behind it to build against. Write the spec section
before writing the code.

### SS18 milestone 22 · the eval harness and golden set

Deferred on SS17.1's own argument — *"evals written against imagined failure
modes measure the wrong things, and a golden set built after watching the
pipeline fail on real recordings is far better."* Keep every recording; they are
that set. `runs/` now holds 13, two of them commercial, and the commercial ones
are where the prompt's own prohibitions get violated. **That is enough material
to start.**

### The fixtures no longer contain the thing

The finding worth carrying: on the fixture recordings the pipeline produces
clean, correctly shaped scenarios. On the two commercial recordings it violates
its own bolded prompt rules and ships. A fixture suite that passes while real
recordings fail is the `CRITIQUE.md` finding arriving a second time, one layer
up. `twoflows` *contained* a scenario break and produced one scenario, and no
test noticed, because every fixture is checked for what it holds rather than for
what it produced.

---

## Part 4 · Carried from PLAN.md

The milestones there are closed. These two sections are not, and exist nowhere
else.

### Considered and rejected

**Playwright Agents (1.56+) — planner / generator / healer.** The closest thing
to this project that exists. If the goal were generating Playwright specs for
developers they would win outright. Three functional gaps keep them from
replacing anything here:

* *No input surface.* Their planner explores the app itself, which needs reach,
  credentials and permission to click. Nothing in the toolchain observes a human
  using their own browser, so there is no recording to work from.
* *No access to intent.* The best run in `runs/` grounds on the literal `Orders
  over EUR500 require approval` because the tester stated that objective. An
  agent exploring the same checkout page cannot know which rule on it the
  business cares about.
* *Verification answers a different question.* Their generator checks that an
  assertion passes against the live app. Whether the assertion is about what the
  tester was checking is not the same question, and the slow-validation run
  shows the two coming apart: both its assertions were true, grounded, and about
  the wrong thing.

The real overlap is their **healer**, which repairs selector failures at
runtime — adjacent to replay. Keep replay deterministic; an LLM inside a
measurement harness is nondeterminism in the instrument. If self-healing ever
becomes a product feature rather than a metric, use theirs.

Cite them in the writeup. "Why not just use Playwright Agents" is the obvious
question and it has a good answer.

**Playwright MCP and Chrome DevTools MCP cannot replace any part of the
recorder**, for architectural rather than featural reasons: both drive a browser
*they* control, with no "watch what the human did" surface. Their network and
console tools are scoped since the last navigation — pull-based debugging
queries, not a durable session log — so a multi-page recording cannot be
reconstructed from them. `chrome-devtools-mcp` is CDP, which SS6.1 rejected on
purpose and which managed browsers block. Worth stealing: Playwright's
ARIA-snapshot serialisation is a compact, diffable role+name format, and it is
the shape to test against if prompt size ever becomes the constraint.

**rrweb solves a different problem.** It serialises the DOM, not the
accessibility tree — it records that `<div class="btn-x9f">` mutated and cannot
tell you the node is `button "Save invoice"`. It exists so a human can *watch* a
session. Revisit only if reviewers start asking what happened between two steps,
and then as a review-UX feature, never as a pipeline input.

**Groq's free tier cannot run this workload** — 8,000 TPM against ~35k prompts
means a single request is unsendable regardless of its 30 rpm. Local models are
not a fallback either: the best small tool-callers sit in the high 80s on
tool-call correctness, which over a 16-call chain is a near-certain failure per
run, and a model that hallucinates a citation is worse than one that
rate-limits.

**Worth stating plainly in the writeup:** nothing in the prior art records a
browser session into an accessibility-semantic structured format. Session replay
tools record pixels; test recorders record selectors. Recording role +
accessible name + evidence is the actual novelty.

### Verification invariants

Run at each change, not at the end:

```bash
bash scripts/check.sh
.venv/Scripts/python -m server.cli run tests/fixtures/checkout.recording.json --offline
.venv/Scripts/python -m server.cli run tests/fixtures/hardpaths.recording.json --offline
.venv/Scripts/python scripts/prove_grounding.py
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
pnpm e2e
```

Four things must not move:

1. `prove_grounding.py` stays green.
2. The grounding rate must not **fall** when a provenance change lands. If it
   does, the cause is a model that was inflating provenance — that is the
   finding, not a regression.
3. The grounding rate must not **rise** because of the repair loop. A repair
   that lifts it by teaching a model to cite better is the finding; one that
   lifts it by weakening what counts as grounded is the bug the whole
   architecture exists to prevent.
4. `Valid1st` stays frozen at attempt 1. Read it beside `ValidFin`, and read
   `Converged` beside `Findings`.

And one judgement no script makes: **read the two rendered `.feature` files and
confirm the expected results are about the thing under test rather than an
incidental change.** That is the check every automated gate in this repo exists
to approximate and none of them replaces.
