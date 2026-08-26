# What is broken, and what is left

The working document. [SPEC.md](SPEC.md) is the design and does not change;
[CLAUDE.md](CLAUDE.md) is the rules you need in order to change things safely;
this is the list of things that are wrong right now and the things not yet
built. It replaces `PLAN.md`, whose milestones are all closed and whose build
order stopped at Phase 3.

Last updated 2026-08-26.

**Every defect listed here was found by reading the code against real runs, and
every one carries the evidence that proves it.** That matters more than the
list: a finding with a reproduction is a fix waiting to happen, and a finding
without one is an opinion. Where a claim here is not yet measured, it says so.

[docs/GHERKIN_BEFORE_AFTER.md](docs/GHERKIN_BEFORE_AFTER.md) holds the output
itself, the same recordings before and after. `runs/` is gitignored and is
cleared between milestones, so that file is the only durable record of what the
pipeline produced.

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
