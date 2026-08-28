# What is broken, and what is left

The working document. [SPEC.md](SPEC.md) is the design and does not change;
[CLAUDE.md](CLAUDE.md) is the rules you need in order to change things safely;
this is the list of things that are wrong right now and the things not yet
built. It replaces `PLAN.md`, whose milestones are all closed and whose build
order stopped at Phase 3.

Last updated 2026-08-26. **Superseded on 2026-08-28 by
[docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md).**

> An architecture review found the cause underneath most of what is listed
> below: **the recorder never captures the page**, only the landmark around the
> clicked element. Every empty diff, every "grounded and vacuous" claim, and
> every scenario that ships without a verdict traces back to it. The evidence is
> in [docs/REBUILD_FINDINGS.md](docs/REBUILD_FINDINGS.md); the replacement
> architecture is in [docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md).
>
> **Read the defects below as symptoms, not as a work list.** Several were fixed
> correctly and were still fighting downstream of the real cause; several of the
> stages they fix are being deleted. This file stays because the reasoning in it
> is the record of how the cause was finally found.

**Every defect listed here was found by reading the code against real runs, and
every one carries the evidence that proves it.** That matters more than the
list: a finding with a reproduction is a fix waiting to happen, and a finding
without one is an opinion. Where a claim here is not yet measured, it says so.

[docs/GHERKIN_BEFORE_AFTER.md](docs/GHERKIN_BEFORE_AFTER.md) holds the output
itself, the same recordings before and after. `runs/` is gitignored and is
cleared between milestones, so that file is the only durable record of what the
pipeline produced.

---

## Part 0 · Rebuild progress

### Stage 0 — capture — **done, 2026-08-28**

The recorder captures the page. What was actually built, and what it cost:

| | |
|---|---|
| full-page capture, one root for `before` and `after` | `content/snapshot.ts` |
| `MAX_NODES` 400 → 3000, `nodeCount` on every snapshot | ditto, and the schema |
| root node pinned (it was hoisted when `body` had one child) | ditto |
| page content no longer pattern-scanned; exact known secrets are | `redaction/redact.ts` |
| parameters that point at nothing are dropped | `export/export.ts` |
| the last action survives an immediate Stop | `content/index.ts`, `serviceWorker.ts`, `export.ts` |
| `get_diff` ranks and counts; `get_full_snapshot` deleted | `evidence/tools.py`, `store.py` |
| `scripts/capture_cost.py` | the gate, re-runnable |

**The proof is a run, not an assertion.** `fixtures/demo-app/src/pages/Storefront.tsx`
reproduces the defect exactly: a filter checkbox inside its own `region`, and a
results count outside it. Under the old capture that click produced an empty
diff. The pipeline on `tests/fixtures/keyhole.recording.json` now produces:

```gherkin
When the tester applies the "In stock" filter to the product list
Then the product list updates to display 9 items

When the tester filters the list by the brand "Kestrel"
Then the list of products updates to show 3 items from the brand Kestrel
```

resting on `"Showing 9 of 24 products"` and `"Showing 3 of 24 products"` —
literals that **did not exist anywhere in the recording** before. Break the
filter and both fail, which is `evals/RUBRIC.md`'s first check.

**Cost, measured rather than inferred:** 5.5–10.7 KB per event across the
regenerated corpus, nothing truncated. The old *scoped* capture was 37–56 KB per
event because it was hitting its cap. A commercial page is still unmeasured.

### What Stage 0 turned up that was not in the plan

**`mutation_claimed` now fails on correct output.** Both keyhole assertions are
grounded, discriminating and would fail on a broken build, and the validator
rejects them because no mutating request is attributed — the filter is
client-side. It assumes a state change arrives over the network. This is
corroboration for the plan's cut of 10 of 14 validators, not a new decision, and
it is deliberately **not** being weakened in the meantime.

**The e2e suite was green on a path that had never run.** `annotate()` in
`tests/e2e/record.spec.ts` answered a `window.prompt` that the popup stopped
using when the intent note got its own textarea, so `intent_note` was never
saved and the assertion below it passed on an empty list. `pnpm e2e` is not part
of `scripts/check.sh`, which is how it stayed hidden. Same shape as the
`scenario_break` factory trap already in CLAUDE.md.

**A checkbox or radio is already toggled in its own `before` snapshot.** The
HTML spec's pre-click activation steps set checkedness *before* the click event
is dispatched, so a capture-phase listener can never see the pre-state. Three
`hardpaths` events record no observed change and this is one of them — verified
pre-existing, not a Stage 0 regression (the other two are the closed shadow root
and the canvas, both documented as uninspectable). Deliberately **not** fixed:
the control's own checkedness is the tester's INPUT, which `bind._own_input`
refuses as evidence of an outcome anyway. The outcome is what the toggle caused
elsewhere on the page, and that is what full capture now records.

**`setSession` has a lost-update race.** `ingest` reads the session, awaits
`framePathFor`, `putEvent` and a screenshot, then writes the whole stale object
back — so anything added meanwhile (an annotation, a parameter) can be silently
dropped. Seen as `eventCount` reporting 3 while four events existed. Not yet
fixed; it wants one serialised read-modify-write for every session mutation.

### Stage 1 — the oracle — **done, 2026-08-28**

The pipeline can now say what SHOULD have happened, which is the thing neither
of its two inputs contained.

| | |
|---|---|
| `expectations.json` beside the recording | `schema/expectations.schema.json` |
| one model call, no retrieval, over the digest | `pipeline/expectations.py` |
| `GET`/`POST /api/recordings/{id}/expectations` | `api/app.py` |
| the confirmation screen — `Right` / `Not right` / `Edit` over the screenshot | `ui/src/components/Confirm.tsx` |
| the export page links straight to it | `extension/src/export/export.ts` |

**Two jobs, not a paused one.** `POST /api/recordings` guesses, runs, and
produces a draft on the guesses alone; answering the screen enqueues a *second*
run. The skip path is the tested one, because it is what happens when nobody
clicks. A guess nobody looks at stays `inferred`.

**Layer 1 was already built** — `popup/objective.ts` has coached the objective
live since before the rebuild, with a measured four-of-four-vague ablation in its
own docstring. The plan listed it as work.

Measured on `checkout`: three expectations, each checkable, each with what was
observed beside it.

### Stage 2 — one author — **done, 2026-08-28**

`author.py` replaced `draft.py` + `bind.py` + `split.py` + `_second_chance` +
`bugmode.py`, and the critic, the repair loop and the step library went with
them. 1855 lines of `run.py` became 1124; six tools instead of twelve; five
validators instead of fourteen.

**What is new rather than merely smaller:**

* **Refusal is written, not done.** `Step.whyNot` says *why* a step has no
  verdict, in language a tester can act on. Verified live: the author claimed
  *"the count drops from 9 to 3"* — true — and it was refused with
  *"nothing this run retrieved contains 'Showing 3 of 24 products'"*.
* **`see(eventId)`.** Screenshots reach the model. Needed image parts on
  `Message`, an image path in the Gemini adapter (a function response cannot
  carry bytes, so the picture follows as its own turn) and a cassette key that
  hashes by digest. **The screenshot decides; the text still cites.**
* **`Scenario Outline` the author asked for.** `TestCaseIR.examples`, distinct
  from the `parameters: outline` rendering setting.
* **A bug report is a failed expectation.** A rejected expectation is stamped
  onto its step deterministically, the way an intent note is.
* **The ablation arms mean something again.** A0 no retrieval no oracle, A1
  retrieval, A2 retrieval and oracle — so A1 vs A2 measures what *asking* is
  worth, which this project has never been able to measure.

**Effort attribution had to change or it would have died silently.** With one
investigation, `StepInvestigation.stepId` puts every retrieval in one bucket and
SS3.4's x-axis becomes a constant. `_calls_per_step` now attributes by the
**event a call asked about**, which works because every tool takes an `eventId`
and `event_coverage` guarantees every event belongs to one step. Live on
`checkout`: `{step_001: 0, step_002: 2, step_003: 1, step_004: 0, step_005: 1}` —
SS3.3's signature, from a real run.

**One live-run finding worth keeping.** The first author run refused a true
claim because it quoted a literal from the session INDEX rather than from a
retrieval. The index is context, not evidence. The prompt now says so in as many
words, and the second run produced both verdicts. That rule is the single
highest-leverage line in the prompt.

**Cost:** `checkout` runs in 67s with 4 tool calls; `keyhole` in 15s with 3.
Against 189s and 7 for the old pipeline on `keyhole`.

### Stages 3–6a — execute, judge, revise — **done, 2026-08-28**

**Stage 3 was five validators and a missing sentence.** *"Failures go straight
back to the author"* was never implemented: `ValidatorAction.reject` was emitted
at eight sites and acted on nowhere. It is one trigger with the judge's now.

**Stage 6a ran, for the first time.** `server/runners/playwright.py` and
`scripts/replay.mjs` were complete, wired to `ablate --replay`, and had never
executed — every `executionRate` in the repo was `0.0` and read as a
measurement. All eight local fixtures are `click` + `input` at
`localhost:5173`, exactly what the runner drives, so the first number was one
command away.

**It immediately found a defect all five validators passed**, which is the
argument for the whole stage:

> `evt_007` (enter an order total) and `evt_008` (press Place order) are **2 ms
> apart** with a 317 ms quiet window. Nothing bounded a settle window by the
> next action — `inFlightFor` bounds request *attribution*, not this — so
> evt_007's `after` snapshot contained the rejection evt_008 caused. The author
> cited a literal that really was in evt_007's stored snapshot;
> `evidence_retrieved` and `contains_at` both passed; the assertion was false
> about the moment it named.

`capture()` now cancels open settles with `superseded` as its first synchronous
act. On the regenerated fixture evt_007 ends at 1 ms and the literal first
appears at evt_008, where it belongs — and the pipeline moves the verdict to the
step that earns it.

| | |
|---|---|
| settle bounded by the next action | `content/index.ts`, `settle.ts`, the schema |
| `ReplayResult.passed` false on zero steps — the **seventh** vacuity column | `runners/base.py` |
| unsupported events stop the step instead of vanishing | `runners/playwright.py`, `replay.mjs` |
| `keypress` (the branch tested `keydown`, which is not an `EventType`) | ditto |
| preconditions replay first, or a `Background` scenario fails falsely | ditto |
| `network`/`console` dropped from `CHECKABLE` — the driver never observed them | ditto |
| `run --replay`, `--base-url`, replay failures recorded not swallowed | `cli.py`, `ablation/` |
| the driver exercised at all, including a negative case | `tests/test_replay_live.py` |

Measured: `checkout` replays **2 of 2 scenarios green, 2/2 assertions held**,
mean selector rank 0.0 — on the role+name path, since the demo app has no
`data-testid`.

**Stages 4 and 5 — the judge, and one revision.** `pipeline/judge.py` on
`investigate()`, four read-only tools, fresh context. Live on `checkout` it
raised a finding no validator can express:

> *the verdict asserts the presence of an alert, but the test does not verify
> that the order was actually blocked* — fix: assert the URL is still
> `/checkout`, or that `Order confirmed` is absent.

Bounded at two author rounds; only `fail` buys one; a revision that would let
`merge_repeats` swallow a step is refused whole. `Converged` and
`criticFindings*` are replaced by `judgeFindings` / `judgeFails` /
`revisionRounds` — counts, never a rate, for the reason the sixth column taught.

**And a latent bug the worked example had been inviting since Stage 2.**
`Step.eventIds` was `minItems: 1` while `author.py`'s example showed a
verdict-only step with `"events": []`. The prompt taught a shape the schema
rejected, and it surfaced only when a real model took the example at its word —
as a Pydantic error during assembly. The example was right; the constraint is
gone.

### Stage 2b — multi-tab — **done, 2026-08-28**

Smaller than it looked, exactly as the plan said. The content script was already
in every tab, the worker already read `sender.tab.id`, and the expensive problem
— ordering events from separate documents on one clock — was solved when
`performance.now()` was converted through `timeOrigin`. What was missing was a
set instead of a number.

`session.tabIds`, `chrome.tabs.onCreated` following `openerTabId`, `event.tabId`
finally kept, and a line in the digest — without which the author writes *"the
tester continued"* when a payment window opened. The `twotabs` fixture records
across two tabs and the pipeline produces *"the tester opens the receipt in a
new tab"* with an assertion on a total that appears nowhere else in the app.

`openerTabId` is the whole test: a tab the flow opens for you is part of the
session; a tab you open to check your email is not.

### Stage 8 — the tester-facing finish — **done, 2026-08-28**

**`whyNot` reached nothing.** The most valuable thing the author writes — *"the
product list was never captured before or after this click"* — was in the IR,
the sidecar and `trace.json`, and the review UI printed a generic *"nothing to
check here"* over it. Fixed, and it now also drives the run list's
needs-attention count, which was still keyed on the deleted critic.

**The review screen opens on the test case, not on the pipeline.** The evidence
pane defaulted to the retrieval chain — tool calls, budgets, investigation
records. That serves whoever is auditing the tool; the tester is there to read
what came out of their own session, which is also what the tool is judged on.

**[docs/HOWTO.md](docs/HOWTO.md)**, written from what actually runs rather than
from SPEC.md, and `RECORDING.md` gained the confirmation screen it never
documented.

### What is left

Deferred deliberately, and none of it is a surface a tester touches:

* **The live-browser agent** (REBUILD_PLAN stages 6b and 7). Whether it is a
  real MCP client or live-page tools on the existing `ToolRunner` seam is a
  decision to make then, not now. One thing to carry into it: an MCP client's
  tool calls bypass `ToolRunner`, so they never land in `trace.toolCalls` —
  which is the substrate `evidence_retrieved` resolves against.
* **The eval instrument.** `eval_packet.py` needs `author.json`'s `refused` and
  per-step `whyNot`, and an expectations section — the oracle is the biggest
  thing the rebuild added and is invisible to the judge. Its metric rows and its
  critic and splitter blocks are already fixed. `evals/RUBRIC.md`'s five checks
  are sound; its *layer* table still names `bind`, `split` and `_second_chance`.
* **The post-rebuild `LEDGER.md` row.** The only number that answers *did this
  help*, and it needs the packet first.
* **Deeper runner tests.** `tests/test_replay_live.py` exercises the driver end
  to end including a negative case; the rest of `replay.mjs` is still uncovered.

Read [docs/REBUILD_FINDINGS.md](docs/REBUILD_FINDINGS.md) §11b before trusting a
number from the plan — four of its claims were re-measured while Stage 0 was
built and three were measuring something else.

---

## Part 1 · Open defects

**None of the nine defects from 2026-08-25 remain.** They are listed as closed
in Part 2 with what was actually done. What follows is what the re-run found
afterwards and has not been resolved.

### The scenario name and the verdict can disagree

On `twoflows`, the drafter named its first scenario *"An order exceeding the
threshold requires approval"* and gave it one step: signing in and adding an
item. `_second_chance` then correctly earned it a verdict — *the cart badge
updates to show 'Cart contains 1 items'* — and the result is a scenario whose
name promises approval and whose body proves a badge count.

Both halves behaved. The name was written for a scenario the split later cut in
two, and nothing re-reads a name against the verdict its scenario ended up
with. `gherkin_style` has no rule for it and probably should not: "does this
name describe this body" is a judgement, and the critic's `coherence` finding is
the right home for it. It is not routed there today.

### An expected result can read as a title rather than a sentence

Same run: `Then Order requires approval` — capitalised, and a restatement of the
scenario name rather than a statement about what the application did. Bound to a
real literal, so every grounding check passes; it simply says nothing.

`_clean` normalises whitespace and a trailing full stop and does not touch case,
deliberately — lowercasing a leading proper noun would be worse than the
capital. The checkable half is the restatement: an expected result identical to
its scenario's name adds no verdict. That is a `gherkin_style` warning waiting
to be written, and it has a clean negative case (a name derived FROM the
assertion, which `_scenario_from` does legitimately).

### Grounded and vacuous: two ways found on one real recording

`rec_MTA7A2XHHH22` — a French storefront, 15 events, sort and filter controls,
objective *"check if filters are working correctly"*. **Thirteen validators
green, 4 of 4 claims grounded, and three of the four proved nothing.** Both
mechanisms are now caught; both are worth knowing about because neither is a
grounding failure.

**1. The claim rested on the tester's own input.**

```
claim:   the product list updates to show lower-priced items first
literal: "Prix bas à haut"     <- the option they selected in the sort dropdown
```

It proves the dropdown says what they set it to, and reads identically if the
list came back sorted the wrong way. This is `Export the order` again — the
label on the button just pressed — reaching the candidate set through a door
`_changed_at` cannot close, because choosing an option really does change the
page.

**The agent had the discriminating evidence and cited the other thing.** Its
recorded reason: *"The URL changed to include `order:ASC` (ascending price) and
the combobox value..."*. It found `order:ASC`, reasoned about it correctly, and
quoted the label. So no amount of extra retrieval budget fixes this.

Fixed in two tiers, the shape `_unwitnessed` already uses: `_Candidate.conclusive`
DECLINES to the agent (because "the quantity field shows 3" after typing 3 is
thin but not false, and only something reading the page can tell those apart),
and `bind._own_input` REFUSES the agent's own answer. Calibrated against every
accepted claim with a recording on disk: 2 refused of 26, both the same bad
claim.

**2. Two claims rested on the same generic announcement.**

```
the product list is filtered to show only available items      <- "Results updated."
the product list updates to show items matching the processors <- "Results updated."
```

An aria-live region saying that *something* changed. It is the bare number of
`_Candidate.conclusive` in another costume — a literal that supports any claim
of its shape whatsoever. `_unwitnessed` cannot see it: neither claim quotes a
value or contains a digit, so there is no checkable content to compare, and
prose framing is deliberately untouched there.

`evidence_discriminates` is the fourteenth validator and the check is
language-independent by construction: **if one literal is the whole evidence
for two claims that say different things, it tells them apart from nothing.**
A warning, not a rejection — it can say two claims cannot both be right about
this evidence, not which. Measured over every run on disk: 4 hits, all four
genuine defects (three are the `twoflows` restatement below, one is this).

**Outcome on the same recording, re-run.** 4 grounded-and-vacuous claims became
3 that each rest on distinct, discriminating evidence:

```
the product list is filtered to show only available items
  <- https://setupgame.ma/.../meta/_stock_status:instock/...     (the URL)
the product list updates to show items matching the processors
  <- "Results updated."
the product list updates to show all products
  <- "9 produits affichés"
```

Refusing the dropdown label pushed the agent to the URL, which is the evidence
it had already found and not cited — and that in turn dissolved the
`Results updated.` collision, because only one claim still needs it. Retrieval
went 18 calls to 32, concentrated on the contested steps
(`{step_003: 5, step_004: 7, step_006: 10, step_007: 10}`), which is SS3.3's
signature.

The sorting scenario now ships with **no verdict at all**, warned twice by
`gherkin_style`. Both attempts to bind one were refused, and that is the honest
answer: the recording may simply not show that the list re-sorted. A visible gap
beats an invisible falsehood, and it is the reviewer's to close.

**And a third defect fell out of it, which had been latent.**
`run._second_chance` re-proposes for a verdictless scenario and then re-binds —
but re-binding runs over the WHOLE document, so every step that had already
bound cleanly bound again, and assembly emitted both. It shipped as `Then the
product list is filtered to show only available items` immediately followed by
`And the product list is filtered to show only available items`, same step,
differing only in the evidence behind them. `merge_repeats` folds duplicate
STEPS and never looked at this.

`BindResult.for_step` is a SELECTION and `claims` is a HISTORY; conflating them
was the bug. It now keys on the drafter's original sentence, last attempt wins,
and the full history stays for the reviewer and for SS3.4.

### The size-triggered split is not stable across drafts

The trigger is deterministic; the ANSWER is a model call, and on the same
recording it has now given two different answers.

Measured while testing an unrelated prompt change on `rec_MT7MXBS9B2VB`. The
trigger fired identically both times — *33 events in one scenario, over the
floor of 12* — and the agent returned two named groups on one run and ONE group
(meaning "this is a single test case") on the other. Nothing about the split
stage changed between them. What changed was the draft it was reading: the step
texts were worded as a more continuous narrative the second time, and the
splitter read that as one flow.

That is a reproducibility problem of the kind SS3.6 cares about — the same
recording produced one test case and two — and it is worth being precise about
what it is NOT. A tester's DECLARED break still overrides the model
deterministically (`_split_on_declared_breaks`), and the net on the answer
(`accept`) is deterministic. Only the judgement of "is this long scenario one
behaviour or several" varies, which is the one part that is genuinely a
judgement.

Options, none of them free: seed the split call with the scenario's own
`expect` sentences rather than only its step texts (verdicts are what the
decision is about, and they are more stable than prose); or run it twice and
take a split only when both agree, which doubles the cost of the one stage
that fires rarely; or accept it and let the critic's `coherence` finding catch
the miss, which is what happened here — it fired, correctly, and had nowhere to
go.

### The value-preference rule was tried and reverted

**The experiment, and it failed.** The flagship's verdicts assert basket NAMES
(*the hamper is shown as a "Medium Wicker Basket"*) rather than the capacity
counter, which is the thing a broken feature would break. Note first what this
is not: nothing was rejected. `_unwitnessed` played no part — the drafter simply
never proposed the capacity, and binding took what it was given.

So the lever has to be the prompt, because choosing which value to assert on is
content. Added to the drafting prompt: *"Assert the value that would BREAK if
the feature broke"*, with a label-versus-state worked example.

Result on `rec_MT7MXBS9B2VB`:

| | before | with the rule |
|---|---|---|
| capacity values asserted | 0 of 3 | **1 of 3** |
| accepted expected results | 2 | 3 |
| test cases | **2** | 1 |
| splitter | cut into two | returned one group |

It half-took, and the run came back as a single scenario with three beats under
one heading — the exact defect the splitter exists for. The loss cannot be
cleanly attributed to the rule (see the instability above; the splitter reads
the draft, and the draft changed), which is itself the finding: **a prompt
change to the drafter perturbs every stage downstream of it, and the splitter
is the stage least able to absorb that.**

Reverted. One capacity number is not worth losing the split, and a rule with
1-of-3 uptake is a prompt line rather than a guarantee. Retry it after the
splitter is stable, not before.

### The drafter never retrieves, and the experiment says that is fine

0 of 30 drafting investigations made a single retrieval — every one stops at
`no_investigation_needed`, including on the 34-event commercial recording. The
per-step effort the ablation reports comes entirely from `bind.py`, `split.py`
and repair.

The open question was whether the drafter declines because the index is
sufficient or because the prompt made declining easy. **Run, on
`rec_MT7MXBS9B2VB`, with the decision rule fixed in advance:** keep the sentence
*"making no tool calls at all is a perfectly good outcome"* unless removing it
BOTH raises retrieval AND improves the document.

| | prompt as it is | the sentence removed, and "look before you write an expect" added |
|---|---|---|
| drafter retrieval | 0/8 | **0/8** |
| accepted expected results | 2 | 3 |
| validator pass, final | **1.000** | 0.889 |
| critic findings | 3 | 2 |

Retrieval did not move at all, and the document got worse — it lost the
quoted values in its step text and reached two verdicts under one scenario
name, which `gherkin_style` caught as a voice inconsistency. The sentence
stayed.

So the answer is the first one: the index really is sufficient for these
recordings. That is a result about `digest.py` being good rather than about the
drafter being lazy, and it means SS3.3's effort variance lives in binding, which
is where the genuinely contested claims are. Worth re-running on a recording
where the index is thin — one with many `(re-render; nothing named)` events.

### `Converged` needs an honest denominator

Measured on 2026-08-26: A2 raised 9 critic findings and resolved 1 within
budget, which reads as a repair loop that barely works. **Five of the seven
findings that survived to the final critique are `coherence`, which has no row
in `CRITIC_REPAIR` by design** — acting on one means re-drafting and re-drafting
can change the step count. `repairAttempts` is 0 on four of the seven runs: the
loop never started, because there was nothing it was permitted to touch.

So the column currently measures *how much of what the critic said the loop was
allowed to act on*. Convergence over ROUTABLE findings is the honest
denominator. Changing it means re-running the ablation, so it was left as
measured and documented rather than adjusted after the fact.

This is the sixth column in which this project has met the same trap. Assume it
is in the next one too.

### SS3.4 has no data, and only a human can supply it

`effort_difficulty.py` now requires eight edited and eight untouched steps
before it reports a coefficient, and prints *not enough data* until then. That
is the honest state: the correlation needs review activity, and the only run in
the repo that ever had an edited step was deleted with the rest of `runs/`.

Not a code defect. Open a few drafts in the review UI, change what is wrong with
them, and the number appears. Nothing else will produce it.

---

## Part 2 · Closed

### 2026-08-26 — the nine defects, the splitter, and the console errors

All under `bash scripts/check.sh`: drift, ruff, 543 pytest, 49 vitest, ui types.

**1. `find_text` truncated to 40 matches and dropped the end of the recording.**
Ids are zero-padded and it sorted before capping, so the cap always discarded
the newest events — which is where a verdict lives. Split into an uncapped
`_scan` generator plus a capped public `find_text` (the cap belongs on the
agent-facing tool, where it bounds a response). `contains_at` and
`events_containing` are the uncapped yes/no forms, and `assertion_grounding`,
`bind._best_literal` and `bind._from_answer` use them. `scope=` was honoured by
only one of the five match loops; all five honour it now.

**2. `no_pruned_assertion` had never run — 0 pass, 13 skip.** It resolved an
omission through `omitted.segmentId`, which draft-then-bind never sets. It reads
`omitted.eventIds` first now, with the segment path as a fallback. On the
re-recorded `wander` it **passes**: *no assertion rests on any of 2 pruned
event(s)*. First time in the project's history.

**3. `criticFindingsRaised` was not measuring the critic.** It came from
`RepairOutcome.findings_raised`, which counted repair ATTEMPTS — so
`mutation_claimed` counted 2 (it fans out to two stages) and `coherence` counted
0. The run now accumulates every `CriticResult` and unions findings by
`(case, step, kind, message)`; `repairAttempts` is its own metric;
`repairConvergenceRate` is resolved over raised. `server/ablation` moved with it,
or the rate could have exceeded 1.

**4. Per-step effort had a floor of exactly 1 per bound claim.** The
deterministic binding pass records its one mandatory `get_snapshot` as an
investigation, and `ROUTINE_TOOLS` filters by tool NAME, which cannot catch it —
`get_snapshot` is genuine effort elsewhere. `_calls_per_step` now skips
investigations whose `stopReason` is `no_investigation_needed`, and the record
carries `budgetMax=1` so the review UI stops printing *"used 1 of 0"*.
`toolCallsTotal` still counts it, because it is a real call against real quota.

**5. `Background` could contain `When` and `Then`.** Two cut rules disagreed:
`_leading_setup_count` cut on role, `_opening_block` cut on keyword AND on
whether the step carried an accepted expected result. `_leading_setup_count`
defers to `_opening_block` now, and `gherkin_style` **rejects** a resolved
`When`/`Then` inside a `Background:` — the comment asserting it never happens
became a check.

**6. `lift_background` deleted inherited preconditions.** `renderers/gherkin.py`
returned early after rendering lifted lines, so a case whose own steps began
with setup lost the sign-in it inherits from case 1. The same shape as the bug
CLAUDE.md already documents, one layer up. Both render now, first lifted `Given`
demoted to `And`. Visible on the re-run: `twoflows` case 2 carries its
`Background`.

**7. `effort_difficulty.py` declared sufficiency at two edited steps.** The `2`
was the only one of three thresholds with no name and no comment, and the
reported `r = -0.057` was noise pointing against the thesis. `MIN_EDITED_STEPS`
and `MIN_UNTOUCHED_STEPS` are both 8, both named, and both required.

**8. A hard-failed run still wrote its opt-in exports.** `no_placeholder_leak`
erases the `.feature`, the sidecar and the bug report; the IR survives by
definition, and `export_all` ran unconditionally. Gated in the CLI, and the
`/export` endpoint — which had no check at all — now answers 409.

**9. `event_coverage` checked "at least once", not "exactly once".** `covered`
was a set, so an event assigned to two steps satisfied the net whose whole job
is to make the drafter's freedom safe. Counted now, per test case: a bug report
retraces the same session on purpose (SS14.2), so the rule is per document, and
two repro steps describing one action is still the defect.

**Automatic scenario splitting.** `server/pipeline/split.py`, between the
drafter and `bind.py`. Triggered deterministically at more than `MAX_BEATS`
beats **or** more than 12 events; the agent returns an ordered regrouping of
existing step ids and nothing else; `accept` takes it whole or discards it
whole. See CLAUDE.md for the argument, including why `coherence` is still not a
repair route. No fixture reaches the trigger, so the fixtures cost nothing.

**Bug mode could not be turned on.** `bug_mode_enabled` defaults to False for a
reason argued in `PipelineOptions`, and not one caller anywhere set it — the
CLI, the API and the ablation all took the default, so a built and documented
stage was unreachable. `--bug-mode` now exists on `run` and `serve`.

**Bug mode asked the model for a `toolCallId`.** Every other stage was rebuilt
so a fabricated citation is inexpressible; this one took the pointer from the
model and checked it afterwards. It returns a `literal` only now, resolved
through `bind._resolve_call` — the same implementation, not a second one.

**The critic's worked example was the recording it judges.** The Fortnum hamper
scenario, verbatim. Rewritten in a neutral domain, as the drafting prompt
already does.

**The drafter was handed 12 tools and told about 5.** All twelve are listed,
grouped by the question each answers. `search_step_library`'s description no
longer reads *"Search before inventing new wording"* — a directive from the
deleted naming stage, loose in every agent's tool list, and the mandatory-effort
pattern that collapsed Spread to 0.16.

**A detour swept into a neighbouring step is not accounting for it.** Found on
the re-recorded `wander`: the drafter put the Reports detour inside *"adds an
item to the cart and proceeds to checkout"*, passing `event_coverage` while the
sentence covered neither event. `event_coverage` cannot tell the difference and
nothing can. The drafting prompt now shows the bad and good shape side by side,
and `wander` prunes correctly.

**A scenario the drafter never proposed a claim for got no second chance.**
`_second_chance` declined when there was no failed claim to feed back, on the
ground that there was no evidence to hand over. What that produced on `twoflows`
was a scenario named *"An order exceeding the approval threshold cannot be
placed"* whose entire body was a sign-in. It asks now, with the weaker question,
and the fixture finally demonstrates the two flows it was built for.

**Coverage suggestions could not cite a request.** `get_network` hands the model
requests identified as `net_0002`, and `suggestions_quarantined` rejected a run
for resting on one — so the rule was measuring which id the model happened to
quote rather than whether anybody observed the thing. Network and console ids
join events, retrievals and steps, and the prompt says which ids are citable.

**The console errors on `serve`, which were three real bugs.** All swallowed by
the UI, which is why the app still functioned:

* `steps/{id}/narration` returned **500** on first paint and every step click.
  It read the recording through a bare `.read_text()`, and `runs/` outlives
  `recordings/` — most runs on disk have no recording beside them. It answers
  with no segments now.
* `recordings/{id}/screens/{evt}` returned **404** per step click. The pane
  rendered an `<img>` for every step and hid it `onError`, which the browser
  logs anyway. The run body carries a `screens` manifest and the pane asks once.
* `/favicon.ico` returned **404** per load. `ui/public/favicon.svg` exists and
  `index.html` links it.
* And `Storage.run()` mkdirs, so a GET for a run that does not exist created
  empty directories the review UI then listed. `existing_run()` is the read
  path.

**A re-run left the previous shape on disk.** A feature filename carries the
case id and a case id carries the scenario NUMBER, so a re-run producing a
different number of test cases left the old files beside the new ones —
`checkout` held `tc_..._01.feature`, `tc_..._02.feature` and `tc_....feature` at
once, two of them describing a document that no longer existed, all servable
through `/files/{name}`. `_write_output` clears the three suffixes it writes,
scoped to the run's own directory and never wide enough to reach `ir.json`.

**Tests for what had none.** `test_draft.py` (25), `test_digest.py` (17),
`test_split.py` (17), `test_fixture_outcomes.py`. The last one is the answer to
*the fixtures no longer contain the thing*: it asserts what each fixture
PRODUCED — two scenarios out of `twoflows`, an assertion ranked `narrated`, a
bound `actual` on `bugged`, an omission `no_pruned_assertion` actually checks.
It replays from cassettes and skips when a prompt change has invalidated them,
which is honest: the alternative is a scripted model, and a scripted model
cannot tell you what the pipeline produces.

### 2026-08-25

**Evidence must witness what the claim checks.** `bind._unwitnessed` requires
every value the claim **quotes** and every **number** in it to appear in the
evidence — not a claim-side coverage floor, which would reject honest verbose
claims. Calibrated against all 21 (claim, literal) pairs the pipeline had
produced: zero false positives, both known-bad pairs caught.

**A claim that the interface appeared is refused.** `bind._existence_only`. The
drafting prompt forbids these in bold and `rec_MT7VTN7ZRJPO` closed its scenario
on one anyway, bound to a panel heading.

**The declared scenario break had never fired.** A `scenario_break` carries no
`eventId`, and `_split_on_declared_breaks` filtered on `a.eventId`, so it
returned on its first line on every recording since it was written. Every test
of that path used the factory to set an `eventId` the recorder never sets.
`segment.break_openers` is the one resolution now, shared. The digest also never
mentioned the break, so the drafter merged across it; it prints
`-- THE TESTER DECLARED A NEW TEST CASE HERE --` and the prompt says a scenario
begins there.

---

## Part 3 · Remaining work

### SS18 milestone 21 · multi-tab / popup capture

Deferred, and the reason still holds: SS4's own table puts cross-tab stitching
*beyond* Phase 3, and the SS4 row points at SS6.6, which is about narration.
There is no spec section behind it to build against. Write the spec section
before writing the code.

### SS18 milestone 22 · the eval harness and golden set

Deferred on SS17.1's own argument — *"evals written against imagined failure
modes measure the wrong things, and a golden set built after watching the
pipeline fail on real recordings is far better."* Keep every recording; they are
that set, and `docs/GHERKIN_BEFORE_AFTER.md` is the beginning of one: the same
recordings, two points in time, with the numbers beside the text.

`tests/test_fixture_outcomes.py` is the shape a harness would take — assert what
a recording PRODUCED, replay from cassettes, skip rather than lie when the tape
is stale.

### Review a few drafts, so SS3.4 has a y-axis

See Part 1. Nothing in the code will produce this.

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
