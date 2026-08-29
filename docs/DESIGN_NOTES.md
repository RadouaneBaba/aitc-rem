# Design notes — the reasoning behind the rules

[CLAUDE.md](../CLAUDE.md) is the rules you need in order to change things
safely. This is *why* each of them exists: the defect that produced it, the
measurement that settled it, and the experiments that failed.

It was split out of CLAUDE.md on 2026-08-26. CLAUDE.md had grown to 64KB and
loaded into every session and every agent spawn, most of it argument rather
than instruction. **The text below is moved verbatim, not rewritten** — every
rule keeps the story that earned it.

Read this when you want to argue with a rule, when a rule seems wrong for your
case, or when you are writing about the project. Read CLAUDE.md when you are
about to change code.

---

## What the 2026-08-29 follow-up changed, and the measurement behind each

[COMPLAINT.md](COMPLAINT.md) is the review this answers. Its §1 is the finding
everything else follows from, and it is worth stating in full because it is this
project's own most-repeated law broken in the most literal way available:

> **No model in this pipeline had ever seen a `.feature` file.**

The author emitted JSON, `narrative.py` composed the body, a renderer wrote the
file. The output read like an assembled array because it *was* one. Two of four
shipped features carried the tell — *"When the order is not processed"*, a state
written as an action with no verdict; a verdict repeated as both an `And` and a
`Then`. And the worked example that was supposed to teach a model to write
Gherkin contained no Gherkin at all.

**The author writes the file now**, and three things about how were each a way
to ship it broken:

* **The join is by the line each annotation echoes, not by ordinal.** The first
  real model wrote six lines and returned five annotations, having forgotten a
  `Given`. Under a positional join that is not one line losing its events — it
  is every later line silently attributed to its neighbour, which is worse than
  a degraded run because it is wrong and quiet.
* **A format slip falls back and costs no revision round.** Prose-first
  emission was rejected once on exactly that objection (COMPLAINT §7), and the
  objection was right; the fallback is what answers it.
* **A style is a worked example, not a rule.** Three styles were cut once on
  the argument that prompt rules measure near-zero uptake here. That argument
  dies when the model writes the file: a style becomes *here is a good feature
  file in this style*, which is the one mechanism that has always worked. Adding
  one is writing a `.feature`.

**A claim now says WHAT it claims.** The gate was substring containment, so
*"Then the first product is 'The Autumnal Hamper'"* was proved by that string
appearing anywhere: the sentence said FIRST and the check said PRESENT. The
judge caught it three times and the revision could not fix it, because there was
nothing to fix it with. `order()` and `count()` as TOOLS were proposed and
killed (COMPLAINT §7) — a response listing twelve products contains the name
whether it is first or last, so the claim passes while wearing a tool named
`order`, which launders a presence check and puts a green badge on it. It had to
be a check the validator performs.

*Seen working, live, first run:* the author wrote *"the product list contains 3
items"* with a `count` predicate, which held — and *"contains 9 items"* citing
the wrong event's snapshot, which the predicate refused with *"the list holds 3
here, not 9"*. Under the old gate the second would have passed, because
`"Showing 9 of 24 products"` is somewhere in the session.

**And two holes that were invisible precisely because everything was green:**

* **A refused claim reached nobody.** When the author quotes a literal it never
  retrieved, the claim is dropped and a `whyNot` written — so it never becomes
  an assertion, so `evidence_retrieved` has nothing to reject, so the loop sees
  a clean gate and stops. Measured on `keyhole`: two correct verdicts, **zero**
  tool calls, both silently refused, scenarios shipped ending on a `When`. Every
  validator was right. The author simply never learned that the one thing it had
  to do, it had not done.
* **The oracle was unreachable in practice.** 14 expectation sets on disk, all
  14 still `inferred`. The screen opened only on `?confirm=<id>`, read once,
  linked from one place, cleared on dismiss. Everything downstream had only ever
  read guesses nobody checked.

**The nudge is the one addition that is code where a prompt would be natural**,
so it is worth defending. The prompt already said, at length, that a verdict
costs a retrieval. The model read that, saw the string it wanted to quote
printed in the session index, and reasonably concluded it had evidence — the
index is a SUMMARY, which is exactly why a claim resting on it points at
nothing. `investigate`'s `needs_retrieval` is the mirror of the budget nudge
that had always been there: a model going past its budget was told to stop, and
a model that never started was told nothing. It counts verdicts, counts
retrievals, and where there are some of the first and none of the second says go
and look. It fires on nothing else — a document of pure refusals is a legitimate
answer, and forcing a call out of it would be the mandatory-tool-call
anti-pattern that lifted calls/step 1.56 → 2.17 and flattened the effort spread
from 1.08 to 0.16.

---

## Layout

```
schema/          JSON Schema -> Pydantic (server) + TS types + Ajv validators (extension)
extension/       Chrome MV3 recorder. content script + MAIN-world patch + worker
                 + export page + offscreen mic (offscreen/)
fixtures/        demo app, built to trigger every hard capture path on demand
config/          allowed_origins.yaml (the pre-send gate) + project.yaml (house style)
server/
  api/           app.py = the endpoints, jobs.py = the JobRunner seam,
                 review.py = every human edit, and the record of it
  config/        ProjectConfig: style, voice, tags, sidecar, parameter rendering
  evidence/      store.py = the recording, indexed. tools.py = the six tools + ToolRunner
                 (twelve until 2026-08-29; six were offered to no stage at all)
  pipeline/      segment.py (code, hints only) -> digest.py (code, the session
                 index) -> draft.py (agentic, writes the whole document) ->
                 split.py (agentic, only when a scenario is over a size floor)
                 -> bind.py (agentic per contested claim, proves or deletes each)
                 -> narrative.py (code) -> validators/ (code)
                 -> critic.py + repair.py (agentic, bounded) -> bugmode.py
                 -> coverage.py -> run.py
                 investigate.py = the shared decide-retrieve-observe loop
                 transcribe.py = narration audio -> text, before any of it
  renderers/     gherkin.py + trace_md.py (sidecar) + bug_md.py are always
                 written; xlsx/jira opt in behind base.py's Exporter seam
  ablation/      A0/A1/A2 and the metrics table
  llm/           ModelClient seam: gemini, cassette, chain, scripted
  library/       SS12's approved phrasing, on rapidfuzz + one SQLite file
  runners/       does the generated test case actually run? base.py + playwright.py
  importers/     devtools.py = a Chrome Recorder export; transcript.py = a
                 WebVTT/SRT/JSON transcript as narration
scripts/         check.sh, prove_grounding.py, effort_difficulty.py, replay.mjs
docs/            RECORDING.md -- for the tester, no terminal
tests/           pytest; tests/e2e/ is Playwright
```

Stage order is deliberate: deterministic where possible, agentic where
necessary. Segmentation and validation are still code, and `segment.py` still
runs -- but its boundaries are now HINTS in the index (idle gaps, URL changes,
the tester's checkpoints), not step boundaries. A step is an intent, and five
consecutive clicks on "Increase Quantity" are one; only something reading the
whole session can say that. Do not put a model inside `segment.py` itself: what
it produces has to be the same every time, because the drafter reads it.

The net under that freedom is `event_coverage`. The drafter decides what a step
IS, so every recorded event must land in a step or in an explicit `omitted`
entry naming it, EXACTLY once -- counted per test case, because a bug report
retraces the same session on purpose (SS14.2) and a rule reading "no event twice
in the IR" turns the fixture built to contain a 500 into a rejection with
nothing wrong in it. That validator is the reason the freedom is safe to grant.

**It cannot tell a step from a step that swallowed something, and nothing can.**
On `wander` the drafter put a two-click detour to the reports page inside *"adds
an item to the cart and proceeds to checkout"* -- every event accounted for,
gate green, and a step whose sentence covers neither event. The counter-measure
is in the drafting prompt, which now shows the bad and the good shape side by
side, and the check is `wander` producing an omission that `no_pruned_assertion`
actually reads.

**Every review edit goes through `server/api/review.py`.** Not because it is
tidy, but because SS13.5's record is the project's only source of difficulty
labels -- the ablation's `steps edited by a human` column and SS3.4's y-axis.
An endpoint that mutated the IR directly would cost that silently. A reviewer
can reject a claim or delete a step, but never edit `toolCallId` or `literal`:
making an ungrounded assertion grounded is not theirs to do (SS3.2).

**`Step.keyword` is derived, and `sync_keywords` keeps it honest.** It is a
denormalisation of role plus position, so deleting or merging a step changes the
keyword of the one after it. Both `ir.json` and the feature file get it from
`build_narrative`, so a reviewer never sees `Given` in the UI and `And` in the
file.

**A new output format is a new file in `server/renderers/`, never a pipeline
change.** That is SS11's claim and it only stays true while every format
implements `base.Exporter` and reads a finished `IRDocument`. Gherkin and its
sidecar are always written because the validation gate reads the rendered
feature; xlsx and jira are opt-in per project.

**The Jira EXPORT builds an issue and does not send it; `jira-push` sends it.**
Posting needs a site, a project key and an API token, and a run that silently
required credentials would be a run most people cannot make -- so the export
writes to disk, inspectable and testable with no account. Posting is a separate
command reading `JIRA_SITE` / `JIRA_EMAIL` / `JIRA_API_TOKEN` from the
environment, never from `project.yaml`, which is committed.

**Draft first, then bind. Never the other way round.** `draft.py` writes the
whole document -- steps, keywords, scenario names, and the SENTENCE of every
expected result -- with the session index in front of it and no obligation to
have retrieved anything yet. `bind.py` then proves each claim or **deletes** it.

The order is the point, and it is the reverse of what the pipeline used to do.
An author that may only claim what it has already retrieved writes about
whatever was easy to retrieve, which is how the old assert stage came to emit
"the hampers category page is loaded" -- an assertion that the browser works.
Letting the drafter propose freely is what lets the document have a shape;
deleting what will not bind is what keeps it honest. Yield drops before it
rises, and that is the correct trade.

**The drafter never supplies a `toolCallId`.** It names a literal it says it
saw; `bind._resolve_call` searches the retrievals the agent actually made for a
response containing that string. A fabricated citation is not something the
model can express, which is strictly stronger than catching one after the fact.
`find_text` is excluded as evidence of its own query -- its response echoes the
search term, so binding to one would be true for any string whatsoever.

**An expected result is about what CHANGED.** `bind._candidates` offers only
what the event added or altered, plus a transient node that was not there
before. Without that rule it bound "a file containing the order details is
downloaded" to `Export the order` -- the label on the button the tester had
just pressed, two shared words, a clean grounding trail, and the export had in
fact returned a 500.

**The tester's own input is not evidence of an outcome.** `bind._own_input`
refuses a literal that is the name or the value of the control operated at that
event. Found on a French storefront, past the whole gate:

```
claim:   the product list updates to show lower-priced items first
literal: "Prix bas à haut"     <- the option selected in the sort dropdown
```

`Export the order` again -- the label on the button just pressed -- reaching the
candidate set through a door `_changed_at` cannot close, because choosing an
option really does change the page. **And the agent had the discriminating
evidence and cited the other thing**: its recorded reason was *"The URL changed
to include `order:ASC` (ascending price) and the combobox value..."*, so this is
not a retrieval failure and more budget does not fix it.

Two tiers, the same shape as `_unwitnessed`: `_Candidate.conclusive` DECLINES to
the agent, because "the quantity field shows 3" after typing 3 is thin but not
false and only something reading the page can tell those apart;
`bind._own_input` REFUSES the agent's own answer, because a prompt that asks is
not a guarantee.

**One literal may not be the whole evidence for two different claims.**
`evidence_discriminates`, the fourteenth validator. Grounding proves a claim
points at a retrieval; it cannot prove the retrieval is ABOUT that claim rather
than the one next to it, and this is the cheapest test of the difference there
is. The same storefront shipped:

```
the product list is filtered to show only available items      <- "Results updated."
the product list updates to show items matching the processors <- "Results updated."
```

an aria-live region announcing that *something* changed -- the bare number of
`_Candidate.conclusive` in another costume. `_unwitnessed` cannot see it,
because neither claim quotes a value or contains a digit and prose framing is
deliberately untouched there. Language-independent by construction, which
matters: a wordlist of status phrases would have been useless on this recording.

A **warning**. It can say two claims cannot both be right about this evidence;
it cannot say which, and on `twoflows` one of the two was a good claim while the
other restated the scenario name. Rejecting would have punished both.

**Noise suppression is code, not a prompt line.** An assertion about a
timestamp or a uuid passes `evidence_retrieved` perfectly and still breaks the
moment somebody runs the test. `NOISE` in `bind.py` refuses them and records
why, so a suppressed claim is visible rather than silently absent. It now
includes SS9.5's ad/analytics rule, which the spec asked for and the old table
never had -- on a commercial site that is the one that matters, because
third-party beacons are where most of the retrievable strings come from.

**The deterministic pass declines rather than guesses.** A literal that is one
bare number ("5 / 5") supports "the basket is full at 5 of 5 items" and would
equally "support" a claim about something else entirely; no scoring separates
those. `_Candidate.conclusive` sends that claim to the agent instead. That is
the line where provenance stops being able to speak for correctness, and
spending a call there is what makes retrieval effort track difficulty.

**The evidence must witness what the claim CHECKS, and `COVERAGE_FLOOR` asks
the opposite question.** It measures how much of the LITERAL the claim accounts
for. Nothing measured the reverse, and the reverse is the guarantee: a sentence
asserting two things while citing evidence for one is half inadmissible, and
the half nobody looked at is free to be wrong. It shipped on a real run,
through a green gate:

```
claim:   the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"
literal: Small Wicker Basket
```

`"5 / 5"` is the whole numeric content of that sentence -- the one part a broken
capacity counter would break. `conclusive` exists to stop exactly this and
cannot see it: it declines a claim resting on a BARE number, and a conjunction
slips past by giving it something else to rest on. Both grounding validators
passed, because both were asked about the literal.

`bind._unwitnessed` is the fix, and its shape matters. **Not** a floor on how
much of the claim the literal covers -- that rejects "the system displays an
error message indicating that the order requires approval" against "Orders over
EUR500 require approval", which is correct and merely verbose. What it requires
is that every value the claim QUOTES and every NUMBER in it appears in the
evidence. Both are the drafter's own marks for what matters: the drafting prompt
asks for quotes on the values that identify the case, and a digit is checkable
by construction. Prose framing asserts nothing and is untouched. Checked in the
deterministic pass (which declines to the agent) and again on the agent's own
answer (which is refused), for the reason `critic._collect` and `repair.targets`
both enforce the protected-step rule.

**A claim that the interface APPEARED is refused, whatever it quotes.**
`bind._existence_only`. The drafting prompt forbids these in bold and a real
recording closed its scenario on one anyway -- *the shopping bag panel opens,
displaying the item(s) previously added to the cart*, bound to the literal
"Shopping Bag", the panel's own heading. Perfectly grounded evidence that a
heading exists. A prompt line is not an enforcement; that lesson is the whole
reason `NOISE` is code. The rule is narrow on purpose -- a container noun
reaching a visibility verb, and only when the sentence carries no other
checkable content -- so "the message ... is shown" and "the payment panel shows
a total of "615"" are untouched. `run._second_chance` then re-asks when this
leaves a scenario with no verdict, which is the right outcome: the step
deserves a real one.

Both rules are pinned in `tests/test_bind.py` against **every** (claim, literal)
pair the pipeline actually produced across `runs/`, because the value of the
check is the ratio. A rule that rejects the bad pairs and any of the good ones
is not a fix, it is a yield cut wearing a fix's name.

**`Given` belongs to the opening block only.** The drafter can legitimately
call a later step `setup` -- going to the checkout page is setup for what
follows -- but rendering that as `Given` after a `Then` produces an order no one
writes and reads as the scenario restarting. `narrative._opening_block` ends the
block at the first non-setup step AND at the first setup step that carries an
accepted expected result; `gherkin_style` catches a regression.

**A scenario must end on a `Then`.** `gherkin_style` checks this PER SCENARIO,
because the file-level "is there a Then anywhere" check passed while a real
recording shipped a scenario ending on a dangling `When` -- an action with no
verdict, nothing to pass or fail. The same check counts action/outcome blocks:
more than `MAX_BEATS` and the scenario is several test cases sharing a heading.

**A scenario left with no verdict gets one second chance.** `run._second_chance`
re-asks for an expected result when binding deleted every claim in a scenario,
handing back the REASON it failed. On a session that ended in an error the
answer is usually that the error is the expected result, and the drafter cannot
know that until binding has looked.

It asks in the other case too, and used to decline. When the drafter proposed
nothing for a scenario at all there is no failed claim to hand back -- which is a
weaker question, not an absent one. Declining produced, on `twoflows`, a
scenario named *"An order exceeding the approval threshold cannot be placed"*
whose entire body was a sign-in: a name promising a verdict over a body with
none. `repropose_expectations` may still answer with an empty list, and for a
genuinely all-setup scenario that is correct.

**One author sees everything.** The feature name, the scenario name, tags,
roles, keywords, where one step ends and the next begins, which outcome is
worth checking -- all of it needs the whole session in view, and all of it is
`draft.py`. It used to be split across three stages that never saw each other's
work, and the output read like a document written by three people who never
met, because it was.

**Merging is the drafter's, and `merge_repeats` is the net.** The drafter
groups events into a step directly, so there is no merge pass to run. What
survives is the guard against two adjacent steps coming back with identical
sentences, which is a defect wherever it comes from. A merged sentence may not
drop a redaction placeholder -- those are the test's parameters (SS7.2), and
the guard is `narrative._keeps_parameters`.

**Splitting is the drafter's too.** `segment.py` deliberately does not end a
step on a 4xx -- a rejected submit usually means a typo being fixed, still one
attempt. When the rejection is what the test is ABOUT, that rule would put two
attempts in one step and the result contradicts itself: *"submits with manager
approval / Then the order requires manager approval"*, every literal true, the
test case wrong. Only replay caught it. The drafter has the objective and the
whole session, so it decides; the segmenter stays deterministic and advisory.

**A scenario break is deterministic, not a suggestion.** SS6.7 says it
overrides the model, and override means override. The agentic stage answered
differently on two consecutive runs of the same recording, once putting the
tester's own boundary inside a single case. Where the tester pressed the
button, `run._split_on_declared_breaks` cuts and no model is consulted. It
splits and never joins, and only where the break opens a STEP -- cutting
through the middle of one would leave two halves whose sentences describe work
neither of them does.

**A `scenario_break` carries no `eventId`, and reading one is how that override
came to never fire.** `export.ts` attaches an annotation to an event only when
it is a fact ABOUT that event, and a boundary sits between two of them, so a
break has a timestamp and nothing else. `_split_on_declared_breaks` filtered on
`a.eventId`, got an empty set and returned on its first line -- on every
recording, since the split was written. `twoflows` exists to prove two test
cases come out of one session and had been shipping a single scenario with both
flows inside it, and the suite agreed with it: every test of this path used the
factory to set an `eventId` the recorder never sets, so they exercised an input
that cannot occur. `segment.break_openers` resolves the timestamp FORWARD to
the event the break opens, and is now the one implementation, shared -- the same
argument as `supports_narrated`.

**Fixing the resolution was not enough, and the second half is the real one.**
The index never mentioned the break at all, for the same reason: `_event_block`
walks `event.annotations`, and a session-level annotation is not in any of them.
So the ONE author that decides where scenarios begin was never told the tester
had already decided. On `twoflows` it merged the events either side of the
boundary into one step, and the deterministic net then correctly declined to cut
through the middle of a step. Both halves behaved. `digest.py` now prints
`-- THE TESTER DECLARED A NEW TEST CASE HERE --` in the position the pause hint
uses, and the drafting prompt says a scenario begins there. The split stays as
the net behind it.

**A third thing splits a scenario, and it is asked only when size says to ask.**
`split.py` sits between the drafter and `bind.py`, and exists because "a drafter
that returns one scenario is the last word" was the last word thirteen times out
of thirteen. On the 34-event commercial recording the critic diagnosed it
exactly -- *"this covers three separate upgrade behaviours and reaches three
distinct verdicts, making it three test cases in one"* -- and nothing happened,
because `coherence` has no row in `CRITIC_REPAIR` and cannot have one: a
post-assembly re-draft can change the step COUNT, which SS3.6 promises it does
not.

The trigger is deterministic and disjunctive: more than `MAX_BEATS` beats **or**
more than `SPLIT_EVENT_FLOOR = 12` events, and never on a scenario with fewer
than two steps. A beats-only trigger misses the case it was built for -- that
scenario has three beats, under the limit. It is long, not beat-heavy. No
fixture reaches the floor (the largest is 10 events), so a well-shaped document
costs nothing and no fixture output moves.

**The answer is taken whole or discarded whole, and `accept` is the rule.** The
agent returns only an ordered regrouping of the existing step ids into named
groups; it may not invent, reorder, drop, merge or re-word a step, and
`step_id` and `eventIds` are untouched by construction because step ids come
from a document-global counter. Four ways an answer is refused: it is not an
ordered regrouping, a group is empty, the cut falls between two steps whose
normalised text is identical -- `merge_repeats` runs per scenario, so that cut
would change the step count -- or there is only one group, which is a complete
and correct answer meaning "this is one test case". A refusal is recorded with
its reason; a wrong trigger costs one model call and never a wrong document.

**The trigger is deterministic; the ANSWER is not, and that is measured rather
than feared.** On `rec_MT7MXBS9B2VB` the trigger fired identically on two runs
-- *33 events in one scenario, over the floor of 12* -- and the agent returned
two named groups on one and ONE group on the other. Nothing in this stage
changed between them; the DRAFT it reads did, because an unrelated prompt line
moved the step wording toward a more continuous narrative and the splitter read
that as one flow.

So the same recording produced one test case and two, which is a
reproducibility problem of the kind SS3.6 cares about. Be precise about the
scope: a tester's DECLARED break still overrides deterministically, and `accept`
is deterministic. Only "is this long scenario one behaviour or several" varies,
which is the part that is genuinely a judgement. Before adding any prompt line
to `draft.py`, note that it perturbs this stage's input, and this stage is the
one least able to absorb it.

Gated on `tools_enabled`, so A0 still makes no retrieval of any kind. It runs
under A1 and A2 alike: it is a generation capability, not a critic capability,
and SS3.5 defines A1 vs A2 as *critic and repair loop* and nothing else. Its
investigation carries a `segment_id` and **no** `step_id`, so a scenario-level
decision lands in `toolCallsTotal` and stays out of `toolCallsPerStep`.

So the set is three: the drafter's judgement, the tester's declared break, and
this. Each surviving scenario becomes one `TestCaseIR` and one `Scenario:`.
`MAX_BEATS` now genuinely rejects at the gate -- `gherkin_style` returns
`ValidatorStatus.fail` for its two structural findings and has no row in
`VALIDATOR_REPAIR`, so that rejection is terminal. The prompt states `MAX_BEATS`
as a number, because a gate the author was never told about is a gate it cannot
aim at.

**`server/runners/` is to correctness what `renderers/` is to readability.** A
new one is a new file reading a finished `IRDocument`, never a pipeline change.
It does not execute the `.feature` and cannot: no Gherkin runner in any language
binds a step to anything but a hand-written step definition. Constraining the
model to a closed step vocabulary would buy executability by giving up the
readable prose that is the product, so replay drives the IR and the recording
directly. The prose is for humans; `eventIds` and `selectorHints` are what runs.

**The step library recommends; it never substitutes.** `Match.reuse` is advice.
"adds a widget to the cart" scores 95 against the approved "adds a Blue Widget
to the cart", and the widget may not have been blue -- only something reading
the evidence can tell. `libraryRef` is set from an EXACT match, or
`library_verbatim` could not fail. A step enters the library on human approval
only (SS12.2), which is what makes it a record of accepted work rather than an
average of generated work.

The per-step search is gone with the naming stage, and that is a fix rather
than a loss: mandating `search_step_library` on every step lifted calls/step
1.56 -> 2.17 and collapsed SS3.3's Spread from 1.08 to 0.16. The tool is still
there for an agent that wants it. Reviving reuse properly wants embeddings
(SS12.4) and a corpus that does not exist yet.

**The critic reports; it never edits.** A finding is a sentence about what is
wrong. `repair.py` decides which stage re-runs, and that stage retrieves its own
evidence. Letting the critic supply a `literal` or a `toolCallId` would be a
path to a grounded-*looking* fabrication, which is the one thing SS3.2 exists to
make impossible. It also may not touch a step named from a tester's intent note
(SS6.7) or one carrying `libraryRef` (SS12.2) -- both are enforced twice, in
`critic._collect` and again in `repair.targets`, because a prompt that asks is
not a guarantee.

**Which stage repairs a finding is a table, not a judgement.** `VALIDATOR_REPAIR`
and `CRITIC_REPAIR` in `repair.py`, and two rows are deliberately empty.
`event_coverage` rejects when `_assemble` dropped an event -- a model cannot fix
that and a re-run might produce different text and make the failure *look*
different, which turns a structural bug into a haunting. `no_placeholder_leak`
is a redaction hole, and a repair that happened to produce a clean sentence
would hide it rather than close it. Nothing that reaches the "nothing" rows is
silently dropped: it becomes `criticNotes` and a `Warning`.

**Repair may change a step's text and its assertions. Never its `eventIds` or
its `step_id`.** That one constraint is what keeps `event_coverage` and the
scenario grouping stable across attempts, and it is why `rewrite_steps` walks
the drafted steps rather than re-running the drafting stage with a filter -- the
latter would re-decide boundaries and quietly change the step count mid-run.
`split.py` inherits the same guarantee for free: it repartitions scenarios and
never touches either field.

**Coverage suggestions are quarantined three times over.** Their own IR block,
an UNVERIFIED heading in every renderer, and `suggestions_quarantined` at the
gate. They are also gated on `suggestions_enabled` rather than on
`critic_enabled`: SS3.5 defines A1 vs A2 as differing by "critic, repair loop"
and nothing else, so attaching coverage to the A2 flag would make the thesis
comparison measure two changes at once.

**A step's text says what the TESTER did; an expected result says what the
APPLICATION did.** Only the second is a claim that state changed, and
`mutation_claimed` now tells them apart with `RESULT_CLAUSE`. This is a
correctness fix and not a loosening, and the difference is worth being able to
defend: "the tester submits the payment method" describes pressing a button,
and reading it as a claim about persistence produced a rejection NO rewrite
could satisfy -- every honest verb for that action is a mutation word. The
repair loop spent its whole budget making the sentence worse, hedging it to
"attempts to save" and then to "clicks Save", which is the mechanics language
SS11.1 exists to keep out. Every true positive still fires: an expected result
claiming a change is checked on any mutation word, and a step whose own text
asserts an outcome ("and it is saved") is checked too.

**The same conflation arrives one level up, and there it is a deadlock.**
`hardpaths` shows a status message reading "Payment method saved".
`bind._unwitnessed` requires a claim to quote the value it rests on, so every
admissible sentence about that message contains the word "saved" -- and the one
sentence that does not, *a confirmation appears*, is refused by
`bind._existence_only`. Between the two rules nothing could be said, and the run
was rejected for a claim that was true, grounded and about the screen.

`DISPLAY_CLAIM` is the fix and **the discriminator is order, which is why it is
not a loosening**: a display verb must come FIRST. *"the order is shown as
placed"* asserts what the page says; *"the order is placed and a confirmation is
shown"* asserts persistence in its first clause and still has to prove a
successful request. Both cases are pinned in `tests/test_validators.py`, the
negative one deliberately.

**Bug detection is code, and its threshold is load-bearing.** Medium signals
never reach it at any quantity. Four fixtures contain a 4xx on a state-mutating
POST and in every one of them that 4xx *is* the thing the test is about --
"orders over EUR500 require approval" is the objective, not a defect. Turning
those four into bug reports would be a louder failure than detecting nothing. It
takes the tester's marker, a 5xx, or an uncaught exception. Every signal that
fired is still recorded, so "why is this not a bug" has an answer.

**A bug report's `actual` is bound exactly as tightly as any assertion**
(SS14.2). It is yielded into `_assertions` in `grounding.py` rather than checked
by a branch of its own, because a second implementation of evidence binding is a
second thing that can be wrong -- and it is the one sentence a developer reads
before deciding whether to go and reproduce something. When the model cannot
cite what it claims, no report is written. That is the correct outcome.

## Things that bit us, so you do not repeat them

**Pydantic copies the list you hand it, so `trace.toolCalls` is not
`runner.calls`.** `AgentTrace(toolCalls=runner.calls)` reads like an alias and
is a snapshot. Every stage that retrieves *after* the trace was built is
therefore invisible to `evidence_retrieved`, which then rejects a citation that
is true, resolvable and correct -- the most confusing failure this codebase can
produce, and it took a real run to find. `_sync_calls` exists for that, and any
new stage placed after the last `_draft` has to call it before the gate reads
the trace.

**`merge_repeats` makes a step rewrite dangerous.** It folds adjacent steps
whose normalised text matches exactly, so a repair prompted with "this name is
too vague" can produce a name identical to its neighbour and *delete a step* --
changing the step count mid-run, which SS3.6 promises does not happen, and
moving `Yield`'s denominator, which is worse because the metric then improves.
`narrative.would_collapse` refuses the rewrite; the repair is marked unresolved
rather than silently accepted.

**`lift_background` lifted steps into a list nothing rendered.** The leading
setup steps went to `narrative.background` and `_background` rendered
`case.preconditions` instead, so every multi-scenario recording lost its sign-in
from the *feature file* while `ir.json` still had it. Nothing caught it:
`event_coverage` reads the IR, not the rendered output, and a file missing a
step still parses. If you add anything to `Narrative`, check that a renderer
reads it.

**A sibling test case is not necessarily a sibling scenario.** Adding a bug
report made `len(ir.testCases) > 1` true and lifted a `Background` out of a
feature with one scenario -- straight into the bug above. Anything reasoning
about "how many scenarios are in this file" must count `test_cases(ir)`, not
`ir.testCases`.

**Worked examples outweigh rules, and will contradict them silently.** The
naming prompt said twice to start with the subject, and its examples were
written without one. The model copied the examples: *"submits an order totalling
\"615\""*, nobody submitting anything. Examples are rendered in the project's
voice now, and `with_subject` is the deterministic net.

**A mandatory tool call is not investigation.** Search-before-invent runs on
every step by construction, so counting it as effort lifted calls/step 1.56 ->
2.17 and collapsed SS3.3's Spread from 1.08 to 0.16 -- an agent that looked like
it had stopped adapting when nothing had changed.

*The mechanism is gone, 2026-08-29.* `ROUTINE_TOOLS` was the exclusion list that
kept those calls out of `_calls_per_step`, and it went with the step library it
existed for. `_calls_per_step` attributes a call to a step by the `eventId` in
its arguments and filters by no name at all. The lesson is what to keep: an
author obliged to call something is not investigating.

**Grounding is provenance, not correctness, and `Executes` alone is vacuous.**
A test case that asserts nothing cannot have an assertion fail -- the same trap
as reading `grounding_rate` without `Yield`, met for a third time. Read
`Executes` with `Rechecked`. On the first ablation A0 appeared to execute BETTER
than A1/A2, purely by claiming less.

**`hash()` is salted per process.** An entry id built with it differs between
runs, so `libraryRef` stops resolving across exactly the session boundary the
library exists to cross. `hashlib.sha256`.

**The picker's own click was recorded as a step that never happened.** Both it
and the recorder listen on `document` in the capture phase, and the recorder
registers at module load, so it sees the click first no matter what the picker
does with `stopPropagation`. The recorder ignores events while `picker.active`.

**Attribution direction is not the same for every annotation.** An assertion
annotation comes AFTER what it points at; an intent note comes BEFORE the step
it names -- the fixture proves it, landing between the sign-in click and the
add-to-cart click while describing the latter. Both are attributed with the
whole session in view, like network calls, never in the frame.

**An imported recording is not redacted.** Chrome's DevTools Recorder writes
what was typed, and the first import put a plaintext password on disk through a
path SS7.1 exists to make impossible. `server/importers/devtools.py` redacts
before constructing the `Recording`, and says that it is pattern-based.

**`input[type=password]` has no implicit ARIA role.** Left at `''` it was
treated as a structural wrapper and dropped from snapshots entirely — a login
step with no password field in it. `INPUT_ROLE_FALLBACK` in `content/a11y.ts`
handles it; form controls are never flattened.

**`composedPath()[0]` is the innermost node.** For `<button><span/></button>`
that is the span, so the step describes an icon rather than a control.
`targetOf` walks outward to the enclosing interactive element.

**`performance.now()` is per-document.** Mixing it with the worker's wall-clock
start silently flattens every timestamp to zero, which kills the idle-gap
boundary rule. Convert with `performance.timeOrigin`.

**The offscreen document is a third clock, and the microphone starts late.**
Same trap, third time. `offscreen.ts` reports `Date.now()` at
`MediaRecorder.start()`, the worker stores the delta from the session start as
`audioOffsetMs`, and `transcribe()` adds it to every segment — because Whisper's
timestamps are relative to the *audio*, not the session, and the mic takes a
moment to open. Drop the offset and nothing fails: every spoken sentence shifts
by that delay onto the neighbouring step, and you get a plausible, grounded,
wrong expected result. The same hazard is why `--narration-offset` prints the
window it mapped onto instead of applying it silently.

**Audio does not travel through `chrome.runtime.sendMessage`.** Extension
messages serialise as JSON, so a Blob does not survive and base64 would add a
third of a megabyte per megabyte of speech. The offscreen document and the
worker share the extension's IndexedDB, so `offscreen.ts` writes chunks itself
with `putAudioChunk`. Order is load-bearing and the chunks are not independent:
only the first carries the WebM header, so a gap or a reorder produces a file no
decoder opens.

**An offscreen document cannot show a permission prompt.** Chrome suppresses it
there, so `getUserMedia` succeeds only if permission already exists and fails
with `NotAllowedError` if not — silently, from the tester's point of view.
`mic.html` exists solely to ask, once, from a real tab on a real user gesture.
The grant is against `chrome-extension://<id>`, which is also why the mic lives
in an offscreen document at all: a content script would need the permission from
the application under test, and the recorder is black-box.

**Network attribution belongs at assembly, not in the frame.** A frame does not
know when the next action starts, so a request landed on every event still
settling; and a request outliving its own settle window was never recorded at
all. Frames report observations; `export.ts` attributes them.

**In-flight requests must be scoped to the action.** One never-completing
request made every later step wait the full 5s and falsely flag
`settle_timeout`.

**Retry must sit INSIDE the fallback chain.** The chain converts `RateLimited`
into `AllProvidersExhausted`, so wrapped the other way the retry never sees a
rate limit and a 44-second pause ends the run. Pinned by
`test_retry_must_sit_inside_the_chain_to_see_a_rate_limit`.

**The model can only cite what it was shown.** Tool results are wrapped as
`{"toolCallId": ..., "result": ...}` because providers keep the id in an
envelope the model never sees. Without it, a real run invented `find_text_0`
against an otherwise true claim.

**`find_text` is the grounding index, and a gap in it looks like a validator
bug.** A URL assertion passed `evidence_retrieved` (the string really was in
the tool response) and then failed `assertion_grounding`, because the index
covered node names, request URLs, console and narration -- but not the page the
tester was on, which is where a page URL actually lives. Both validators were
right. If a claim you believe is true gets rejected, check what got indexed
before you touch the gate.

**Bash heredocs turn `` into a literal backspace.** A regex written that way
compiles fine and matches nothing — `gherkin_style`'s conjunction check shipped
as `(and|then)` and silently passed everything. Use the Write/Edit
tools for any file containing a regex, and give every regex a test with a
negative case.

**Asking for values in step text invites a run-on.** Telling the model to quote
what the tester typed produced *"enters "PO-4471" as the purchase order number,
sets the order total to "615", checks "Manager approval obtained", and submits
the order"* — one segment read out action by action. The prompt now asks for one
intent and only the values that matter; `_is_run_on` in the style validator
catches a regression.


---

## Status

Phases 1 and 2 are closed. Phase 3's three "Smart" milestones -- the critic and
its bounded repair loop, coverage suggestions, and bug mode -- are built and
verified against `gemini-3.1-flash-lite`.

**Phase 4 replaced the generator.** `docs/archive/CRITIQUE.md` is the hostile read that
prompted it, and the finding worth keeping in view is that it was found on a
REAL recording and hidden by every fixture. On `rec_MT7MXBS9B2VB` -- 34 clicks,
no annotations, no narration, which is what a tester's first recording actually
looks like -- the old pipeline produced a scenario with no `Given`, a dangling
`When` at the end, six unrelated beats, and a confidently wrong number the run's
own warnings said was ungrounded. All seven fixtures passed. Every one of them
carried an annotation, a narration track or a scenario break, and SS6.7 says in
bold that those are optional.

`name.py`, `assertions.py` and `compose.py` are gone. In their place:
`digest.py` builds a session index (2,064 tokens for those 34 events),
`draft.py` writes the whole document from it in one investigation, and
`bind.py` proves every claim or deletes it. That is the architecture, and
`toolCallsPerStep` on the `checkout` fixture reads `{step_002: 1, step_003: 4,
step_004: 1}` -- SS3.3's variance arriving on the step that was actually hard
rather than being spread evenly and subtracted back out. The critic, which
found nothing three times on this recording, now returns a specific finding.

**Phase 5 closed the four findings that recording produced.** What
`rec_MT7MXBS9B2VB` shipped, and what it ships now, side by side:

```gherkin
# before -- three near-duplicate beats under one heading
Scenario: Hamper size upgrades automatically as items are added
  Given the tester navigates to the "Create Your Own Hamper" page
  When the tester adds items until the hamper reaches its capacity
  Then the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"
  When the tester continues adding items to trigger an upgrade to a Medium Wicker Basket
  Then the hamper is shown as a "Medium Wicker Basket" with a capacity of "13 / 13"
  When the tester continues adding items to trigger an upgrade to a Large Wicker Basket
  Then the hamper is shown as a "Large Wicker Basket" with a capacity of "18 / 18"

# after -- two test cases, each with one verdict, both with the setup lifted
Scenario: A hamper automatically upgrades to a Medium Wicker Basket when capacity is reached
  ...
Scenario: A hamper automatically upgrades to a Large Wicker Basket when capacity is reached
  ...
```

The critic had caught it exactly, in one sentence: *"this covers three separate
upgrade behaviours and reaches three distinct verdicts, making it three test
cases in one."* Then nothing happened, because `coherence` has no row in
`CRITIC_REPAIR` and cannot have one. `split.py` is what happened instead: the
trigger fired on *33 events in one scenario, over the floor of 12*, the agent
returned two groups, and `accept` took them. Thirteen validators pass, three
critic findings raised and three resolved.

Two of those three assertions had also been half-proved in the way
`_unwitnessed` now refuses, and the capacity numbers are gone with them -- which
is the correct trade and worth seeing plainly. `Yield` drops before it rises.

**`rec_MT7VTN7ZRJPO` closed on the assertion the drafting prompt forbids in
bold** -- *the shopping bag panel opens, displaying the item(s) previously added
to the cart*, bound to the panel's own heading, past thirteen validators.
`bind._existence_only` refuses it now, `run._second_chance` re-asked, and
binding refused the replacement too. So that scenario ships ending on an action,
with `gherkin_style` saying so: a warning to the human rather than a claim that
was never true. That is the designed outcome and it is still not a good test
case; the recording may simply not contain a verdict for that step.

**The fixtures had stopped containing the thing, and that is now checked.**
`tests/test_fixture_outcomes.py` asserts what each fixture PRODUCED rather than
what it holds -- two test cases out of `twoflows`, an assertion ranked
`narrated`, a bound `actual` on `bugged`, an omission `no_pruned_assertion`
actually reads. Every one of those was false at the start of the session, on a
green suite.

**What the ablation measures changed, and it is worth understanding before
reading the table.** A0 used to FABRICATE: thirteen assertions, none grounded,
thirteen fabrications. It cannot any more. The model never supplies a
`toolCallId`, so with no retrieval there is nothing for a claim to rest on and
every claim is deleted -- A0's honest output is **no assertions at all**. The
A0-vs-A1 comparison is therefore about **Yield**, not about grounding rate, and
`Fabric.` is structurally zero everywhere.

That is a stronger result than the old row and a quieter one, so read it with
care: a grounding rate of 1.0 is vacuous for a configuration that claims
nothing. It is the same trap this project has now hit in five columns.

A0 must also make NO retrieval, deterministic or otherwise. The cheap binding
pass needs no model but still calls a tool and hashes a response; letting it
run under A0 produced a "no tools" row with 0.33 calls per step. Pinned by
`test_a0_makes_no_retrieval_of_any_kind`.

**Measured 2026-08-26**, on the seven fixtures re-recorded through the real
extension, against `gemini-3.1-flash-lite`. This is the first A0/A1/A2
comparison of the rebuilt generator; everything before it was the old pipeline.

```
What it claimed
Config   Assert   Grounded    Yield   Fabric.   Valid1st   ValidFin
-------------------------------------------------------------------
    A0        0        1.0      0.0         0      0.674      0.674
    A1       14        1.0   0.6087         0     0.9727     0.9727
    A2       12        1.0   0.5217         0     0.9727        1.0

What it did to get there
Config   Calls/step   Spread   Findings   Converged   PromptTok
----------------------------------------------------------------
    A0          0.0      0.0          0       0.000       24813
    A1        2.043    1.046          0       0.000      236182
    A2        2.739    0.713          9       0.111      193677
```

Against the old table (A1: 9 assertions, Yield 0.45, Spread 0.0; A2: 7
assertions, Yield 0.35, ValidFin 0.959) three things moved and each is a
different fix landing:

**A2's `ValidFin` reaches 1.0, where it used to go DOWN.** That row was the
regression `_keep_provable` was written for -- repair replacing a proven claim
before finding out whether the replacement could be proven. A2 now claims fewer
results than A1 (12 against 14) and ends with a clean gate rather than a worse
one, which is the trade the critic is supposed to make.

**A1's `Spread` is 1.046, and it used to be 0.0.** That flat column was flagged
here as *"worth watching and not yet alarming"*, with the note that if it stayed
flat on a recording with hard claims the drafter's retrieval had become
decoration. It is not flat. Calls per step went 0.8 -> 2.04 on the same
recordings, and the variance is on the steps that were actually contested.

**`Yield` is up about a third on both configurations** -- and read that beside
the deletions, because `_unwitnessed` and `_existence_only` were both added in
between and both delete claims. More survives binding than before *while* two
new refusals are running.

**`Converged` at 0.111 is the vacuity trap in its sixth costume, and the number
is not what it looks like.** Of the findings that survived to the final
critique, **five of seven are `coherence`, which has no row in `CRITIC_REPAIR`
by design** -- acting on one means re-drafting, and re-drafting can change the
step count. `repairAttempts` is 0 on four of the seven runs: the loop never
started, because there was nothing it was allowed to touch. Of findings that DO
have a route, one of two resolved within budget.

So `Converged` is currently measuring *how much of what the critic said the loop
was permitted to act on*, not how well the loop works. Read it beside the kind
breakdown, and if you change one metric here, change this one: convergence over
ROUTABLE findings is the honest denominator.

`Findings` rising from 4 to 9 is the critic having more to say, not the output
being worse -- five of those nine are it correctly identifying a scenario that
covers more than one behaviour, which is precisely what `split.py` now acts on
earlier and what the critic legitimately still notices afterwards.

**The drafter never retrieves, and that was tested rather than assumed.** 0 of
30 drafting investigations made a single call -- every one stops at
`no_investigation_needed`, including on the 34-event commercial recording. All
the per-step effort in the table above comes from `bind.py`, `split.py` and
repair.

The question that raises is whether the index is sufficient or the prompt made
declining easy, and the two have opposite fixes. Run on `rec_MT7MXBS9B2VB` with
the decision rule fixed in advance -- keep the sentence *"making no tool calls
at all is a perfectly good outcome"* unless removing it BOTH raises retrieval
AND improves the document:

| | as it is | sentence removed, "look before you write an expect" added |
|---|---|---|
| drafter retrieval | 0/8 | **0/8** |
| accepted expected results | 2 | 3 |
| validator pass, final | **1.000** | 0.889 |

Retrieval did not move at all and the document got worse. **The sentence is not
why the drafter declines** -- `digest.py` is simply enough for these recordings,
which is a result about the index rather than about the model. Do not delete
that line on the theory that it is making the agent lazy; that theory has been
tested and is false. Worth re-testing on a recording whose index is thin, with
many `(re-render; nothing named)` events.

`Executes` / `Rechecked` / `Held` are 0 in this table because `--replay` needs
the demo app running (`pnpm demo`). They are not a result.

**`_keep_provable` is why the A2 row is no longer a regression, and the story is
worth keeping.** A2 used to claim *fewer* expected results than A1 (7 against 9)
and end with a WORSE gate score (0.987 -> 0.959). One fixture caused all of it:
on `hardpaths`, A1 bound two true claims -- the status showing "Payment method
saved", and the page showing "Validating with the finance system...". The critic
said each checked "a status message rather than the successful saving" and "a
loading state rather than the completion of the validation process". Both
sentences are plausible. Both ask for something the recording does not contain,
because the slow validation never finishes inside it. Repair obeyed, binding
correctly refused the replacements, and A2 shipped a scenario with no expected
results at all.

**The critic being wrong is not the bug.** It is a second opinion; SS9.9 bounds
it precisely because it can be wrong. The bug was that repair replaced a proven
claim before finding out whether the replacement could be proven. A2 now ends at
`ValidFin` 1.0.

**`Fabric.` is structurally zero in every row, and A0's is the row to
understand.** A0 used to fabricate thirteen assertions. It emits none at all
today, because the model never supplies a `toolCallId` and with no retrieval
there is nothing for a claim to rest on. So `Grounded` reads 1.0 for a
configuration that said nothing, which is the vacuity trap in its purest form.
**Read `Grounded` beside `Yield`, always.**

A0's `ValidFin` also FELL, 0.714 -> 0.674, and that is a definition change
rather than a degradation: `gherkin_style` now rejects structurally, and a
document with no `Then` in it has more shape to be wrong about. It is the reason
the two findings that fire on every A0 run by construction -- *no Then step* and
*ends on an action* -- were deliberately left as warnings. Promoting them would
have made A0 fail the gate on every recording, and `ValidFin` would then measure
the promotion rather than the architecture.

Seven fixtures, each built because a fixture that does not contain the thing
cannot demonstrate it: `checkout`, `hardpaths`, `annotated` (an element the
tester marked, plus an intent note), `twoflows` (two test cases separated by a
scenario break), `wander` (a wrong turn, pruned), `narrated` (the tester says
what they are checking, out loud), and `bugged` (a 500, an uncaught exception,
and the bug-marker hotkey).

**Containing the thing is not the same as demonstrating it**, and that is now
checked rather than hoped for. `twoflows` contained a scenario break and
produced one scenario, and no test noticed -- the whole path was reading a field
the recorder never writes. `tests/test_fixture_outcomes.py` asserts what each
fixture PRODUCED, replaying from cassettes and skipping honestly when a prompt
change has invalidated one.

On `wander`, all fourteen validators pass and `no_pruned_assertion` is one of them
rather than a skip -- the first run in this project's history where the omission
check actually looked at something.

`prove_grounding.py` over the nine full runs: **18 of 18 assertions resolve**
to a retrieval whose stored response still contains the literal -- SS3.2,
measured rather than asserted -- and calls per step varies rather than being
flat, which is SS3.3's signature of an agent instead of a chain.

**Narration was Phase 2's last piece**, and its result is worth keeping in view
because it is the clearest thing this project has demonstrated:

```
Then the order is held for manager approval
  provenance: narrated
  evidence:   "Orders over EUR500 require approval" (semantic_node, tc_0009)
```

The claim is grounded in a *snapshot literal*, not in the transcript. Narration
decided WHICH of the outcomes mattered; the evidence stayed exact. That is the
whole intent of SS9.5's ladder, and the reason narration can raise `Yield`
without ever touching `grounding_rate`.

**Phase 3, and what it changed.** A1 and A2 had been the same pipeline since the
ablation was written -- SS3.5 defines them as differing by "critic, repair loop"
and nothing read either flag. They differ now, and two columns say how:
`Findings` (how much the critic had to say) beside `Converged` (how much of it
the repair loop resolved within budget). Bug mode produces a `.bug.md` repro
report alongside the test case, its `actual` bound to a retrieval like any
assertion. Coverage suggestions are quarantined from the artifact and checked by
a thirteenth validator, `suggestions_quarantined`.

Two real bugs surfaced while building it, both now pinned: a trace that
snapshotted its own retrieval log (so the gate rejected a true citation), and a
`Background` block that silently deleted the steps it lifted. The second had
been shipping since decomposition landed.

**Still not built:** SS18's last two milestones. **21, multi-tab / popup
capture** -- deferred because SS4's own table puts cross-tab stitching *beyond*
Phase 3 and the SS4 row points at SS6.6, which is about narration; there is no
spec section behind it to build against. **22, the eval harness and golden set**
-- deferred on SS17.1's own argument, that "evals written against imagined
failure modes measure the wrong things, and a golden set built after watching
the pipeline fail on real recordings is far better". Keep every recording; they
are that set.

**Read grounding rate together with yield**, `Executes` together with
`Rechecked`, and `Converged` together with `Findings`. A rate alone is vacuously
100% when a configuration abstains -- which is exactly what a well-behaved model
does with no tools, and what a critic does when it finds nothing. The trap has
now appeared four times in four different columns; assume it is in the next one
too.
