# CLAUDE.md

Guidance for working in this repo. Read [SPEC.md](SPEC.md) for the design and
its reasoning; this file is what you need in order to change things safely.

## What this is

A QA tester records themselves using a web app; the pipeline turns that into
Gherkin/Excel/Jira test artifacts. The whole architecture exists to serve one
rule:

> **A claim is admissible only if it can point at the retrieval that produced
> it, in this run.**

Not "the string exists in the recording" — that is a separate, weaker check.
`evidence_retrieved` resolves an assertion's `toolCallId` in the trace,
re-hashes the stored response, and confirms the literal is in it. If you find
yourself making that easier to satisfy, stop: it is the product.

## Commands

```bash
bash scripts/check.sh          # drift + ruff + pytest + vitest + ui types. Run before finishing.
.venv/Scripts/python -m server.cli serve   # local server + review UI on :8000
pnpm e2e                       # Playwright drives the real extension (headed, ~20s)
pnpm demo                      # fixture app on :5173
pnpm codegen                   # regenerate from schema/ after editing a .schema.json

.venv/Scripts/python -m server.cli run <recording.json> [--config A0|A1|A2] [--offline]
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
.venv/Scripts/python scripts/prove_grounding.py
.venv/Scripts/python scripts/effort_difficulty.py        # SS3.4, refuses to overclaim
.venv/Scripts/python -m server.cli import <recorder.json>  # Chrome DevTools Recorder

# Narration (SS6.6). Audio is transcribed locally; a transcript can also be
# supplied from anywhere, which is how an imported recording reaches `narrated`.
.venv/Scripts/python -m server.cli transcribe <recording.json> --in-place
.venv/Scripts/python -m server.cli run <recording.json> --narration notes.vtt --narration-offset 0
pip install -e ".[transcription]"          # faster-whisper; the run says so if it is absent
powershell -File scripts/make_narration_wav.ps1   # the committed fixture audio, once

# Replay needs the demo app running (`pnpm demo`) and the test's parameters:
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json --replay     --replay-param user_email_1=tester@example.com --replay-param password=hunter2
```

Windows paths: the venv binary is `.venv/Scripts/python.exe`. Bash and
PowerShell are both available; Bash heredocs mangle backslash escapes in this
environment, so use the Write/Edit tools for files containing regexes.

**Never `git checkout -- <path>` in this repo without checking `git status`
first.** Large parts of a milestone can sit uncommitted for a long time here,
and that command destroys them with no reflog entry and no recovery. It cost a
rebuild of `run.py` once. Commit before experimenting on a file instead.

## Non-negotiables

**Never weaken a validator to make output pass.** The gate is the product. If a
true assertion is being rejected, the bug is upstream — in what the agent was
shown, or in what got stored — not in the validator.

**`canonical_json` is the only serializer for tool responses.** Any variance in
key order or whitespace between write and re-read breaks the hash and rejects a
*correct* assertion. `server/util/canonical.py`, tested in
`tests/test_canonical.py`.

**Redaction happens in the browser, before anything is persisted.** Never add a
path that writes a raw value to disk and redacts later. `no_placeholder_leak` is
the only validator whose action is `hard_fail`: the feature file is not written
at all.

*One exception, and only one: narration audio.* Speech cannot be redacted before
it is understood, and understanding it is what transcription **is**. So the
audio reaches disk raw. What makes that acceptable is narrow and worth stating:
it never leaves the machine (the server is `127.0.0.1`, `faster-whisper` runs
in-process), the transcript then gets the same best-effort pattern pass
`server/importers/devtools.py` applies, and `docs/RECORDING.md` tells the tester
outright that anything said out loud is written down. Everything **typed** still
obeys the original rule without exception. Do not widen this to a second case.

**Narration is the only lossy evidence source, and the ladder is what holds.**
Node names, URLs, response bodies and console text are read exactly. A
transcript is a reconstruction, so a mis-heard number becomes a literal that
passes `evidence_retrieved` (the string really is in the stored response) *and*
`assertion_grounding` (it really is in the index) and is still false. Both
validators are right; this is provenance meeting its first input where
provenance and correctness come apart by construction. Two guards, both
deterministic and both outside the model's reach: `transcribe._confidence` folds
Whisper's `avg_logprob` and `no_speech_prob` into `NarrationSegment.confidence`,
and `supports_narrated` stops a segment below `narration.min_confidence` from
supporting the `narrated` rank — applied in `assertions._supported_provenance`
**and** in `provenance_supported`, which must not diverge. The second guard is
that the audio is kept so a human can listen; that is why
`runners/playwright.py` marks narration `not_checkable` rather than pretending.

**The schema is the single source of truth.** Edit `schema/*.schema.json`, then
`pnpm codegen`. Never hand-edit `server/models/generated/` or
`extension/src/types/`. The drift check regenerates and diffs on every
`check.sh`.

**The `.feature` body is prose, and nothing else.** No comments, no ids, no
review markers, no fidelity flags. It is the artifact the tool gets judged by,
and a traceability line under every step made it unreadable. All of that lives
in the `.trace.md` sidecar (`server/renderers/trace_md.py`); the machine-readable
form is in `ir.json` and `trace.json`, which is what the validators actually
read. Putting anything back in the body will trip `gherkin_style`.

**The drafting stage chooses the shape; `narrative.py` lays out what it chose.**
Given/When/Then used to be DERIVED from a step's role plus its position, and
that was right while the model writing steps saw one segment at a time: asked
for a keyword with no view of the flow, it answered `When` every time, which is
how Phase 1 shipped seven `When`s in a row. An author with the whole session in
front of it knows where the scenario turns.

`draft.py` therefore emits both `keyword` and `role`, and `_reconcile` makes
them agree at parse time -- a `Given` is taken as a statement that the step is
setup. Downstream, **`role` is authoritative** (`narrative._base_keyword`),
because it is what survives a reviewer deleting a step; the stored keyword is
already `And` half the time. `narrative.py` still owns `And` collapsing, beat
layout, and the one positional rule that cannot be a matter of opinion:
`_opening_block`. Read its comment before touching it -- the running flag it
replaced reached through a whole scenario from one step's assertion, and was
invisible for months because every fixture opened with a sign-in nobody
asserted on.

**The recorder is black-box.** It reads the live accessibility tree and needs no
access to the target app's source. `data-testid` is used when present, but the
role+name fallback is the normal case. Do not add anything that assumes
cooperation from the app under test.

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
  config/        ProjectConfig: voice, tags, sidecar, parameter rendering
  evidence/      store.py = the recording, indexed. tools.py = the 12 tools + ToolRunner
  pipeline/      segment.py (code, hints only) -> digest.py (code, the session
                 index) -> draft.py (agentic, writes the whole document) ->
                 bind.py (agentic per contested claim, proves or deletes each)
                 -> narrative.py (code) -> validators/ (code)
                 -> critic.py + repair.py (agentic, bounded) -> bugmode.py
                 -> coverage.py -> run.py
                 investigate.py = the shared decide-retrieve-observe loop
                 transcribe.py = narration audio -> text, before any of it
  renderers/     gherkin.py + trace_md.py (sidecar) + bug_md.py are always
                 written; xlsx/jira/qase opt in behind base.py's Exporter seam
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
entry naming it. That validator is the reason the freedom is safe to grant.

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

**Nothing else splits a scenario, and nothing splits on length.** Those two --
the drafter's judgement and the tester's declared break -- are the whole set,
and each surviving scenario becomes one `TestCaseIR` and one `Scenario:`. There
is no event-count trigger. `MAX_BEATS` rejects an over-long scenario at the gate
and `gherkin_style` has no row in `VALIDATOR_REPAIR`, so that rejection is
terminal rather than repaired; the critic's `coherence` finding has no row in
`CRITIC_REPAIR` either. On a long recording with no declared break, a drafter
that returns one scenario is therefore the last word. The prompt now states
`MAX_BEATS` as a number, because a gate the author was never told about is a
gate it cannot aim at.

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
its `step_id`.** That one constraint is what keeps `event_coverage`,
`apply_splits` and `_case_groups` stable across attempts, and it is why
`rename_steps` walks the named steps rather than re-running `name_segments`
with a filter -- the latter takes each step's events from the SEGMENT, which
would quietly undo a split.

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
it had stopped adapting when nothing had changed. `ROUTINE_TOOLS` is excluded
from `_calls_per_step`; `toolCallsTotal` still counts them, because they are
real calls that cost real quota.

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

## Working with models

`GEMINI_API_KEY` lives in `.env` (gitignored) and is loaded by
`server/util/env.py`. Nothing before the drafting stage needs it: segmentation
and the session index are code.

`JIRA_SITE`, `JIRA_EMAIL` and `JIRA_API_TOKEN` live there too, and are read
only by `server.cli jira-push`. Never put them in `config/project.yaml`, which
is committed.

**Free-tier quotas are the binding constraint, and SPEC.md §9.12 is wrong about
which one.** It assumes tokens-per-minute; the real limits are requests. As of
August 2026:

| Model | Free tier | Verdict |
|---|---|---|
| `gemini-2.5-flash`, `2.5-flash-lite` | not served to new keys | unavailable |
| `gemini-3.7-flash` | 5/min **and 20/day** | unusable — one recording exhausts it |
| `gemini-3.1-flash-lite` | workable | **the default** |

The decorator stack is `budget(cassette(pace(chain(retry(gemini)))))` and the
order is load-bearing — see `build_model` in `server/cli.py`.

**Cassettes make iteration free.** `runs/_cassettes/` records every real
response keyed on the exact request. Changing a validator, the renderer or the
segmenter does not change the model input, so those re-runs cost nothing.
`--offline` pins a run to replay only.

**One tool call per turn.** Gemini 3 signs only the first function call of a
parallel batch, then rejects the replayed conversation because the rest are
unsigned. Sequential retrieval also matches §3.3's decide-retrieve-observe
loop. Thought signatures ride on `ToolInvocation.signature`.

**Free-tier prompts are training-eligible and human-reviewable.** Recordings
must be of demo or public apps; `config/allowed_origins.yaml` enforces it and
the pipeline refuses to send otherwise. `--allow-any-origin` is for a paid
endpoint with a no-training term.

## Testing

`ScriptedModelClient` is the only fake model, and it exists for output no real
model produces on command — a fabricated `toolCallId`, a literal absent from the
response, an unredacted password. Everything else uses real responses through
cassettes.

The Playwright suite rewrites `tests/fixtures/*.recording.json`, which the
server tests consume. That is how the pipeline gets exercised against a genuine
recording rather than a hand-written one. If you change the recorder, run
`pnpm e2e` so the fixtures follow.

Tests state *why* a behaviour matters, not just that it holds. Keep that: a test
named after a spec guarantee survives a refactor that a test named after an
implementation detail does not.

**A factory that can build an input the recorder cannot is a trap.** Every test
of the scenario-break split passed an `eventId` to `f.annotation`, and a real
`scenario_break` has none -- so the suite was green on a path that had never run.
When a builder takes a field, check what actually populates it before relying on
it in a test.

`tests/test_bind.py` covers the deterministic binding pass, which had no tests
of its own while `name.py`, `assertions.py` and `compose.py` each had a module.
That is where the half-proved-claim defect lived. `draft.py` and `digest.py`
are still only covered end to end through `test_pipeline.py`.

## Status

Phases 1 and 2 are closed. Phase 3's three "Smart" milestones -- the critic and
its bounded repair loop, coverage suggestions, and bug mode -- are built and
verified against `gemini-3.1-flash-lite`.

**Phase 4 replaced the generator.** `CRITIQUE.md` is the hostile read that
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

**The `rec_MT7MXBS9B2VB` scenario this section used to quote was not
reproducible, and the difference is the honest status of the phase.** What
`runs/rec_MT7MXBS9B2VB/run_001/` actually contains:

```gherkin
Scenario: Hamper size upgrades automatically as items are added
  Given the tester navigates to the "Create Your Own Hamper" page
  When the tester adds items until the hamper reaches its capacity
  Then the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"

  When the tester continues adding items to trigger an upgrade to a Medium Wicker Basket
  Then the hamper is shown as a "Medium Wicker Basket" with a capacity of "13 / 13"

  When the tester continues adding items to trigger an upgrade to a Large Wicker Basket
  Then the hamper is shown as a "Large Wicker Basket" with a capacity of "18 / 18"
```

Four things are wrong with it and every one is a finding about the prompts
rather than about the model. The scenario name describes what the tester did
rather than what the test proves. Three near-duplicate beats where the drafting
prompt asks for one behaviour with one verdict, and "two or three expects across
a whole scenario" became one per test step. `to trigger an upgrade to a Medium
Wicker Basket` states an outcome inside the step's own text, which the prompt
forbids. And the refusal at the end -- *no bigger hampers are available*, the
one thing on that recording worth proving -- was discarded as `omitted:
abandoned`: the drafter threw away the verdict and kept three copies of the
setup.

The critic caught it exactly, in one sentence: *"this covers three separate
upgrade behaviours and reaches three distinct verdicts, making it three test
cases in one."* Then nothing happened, because `coherence` has no row in
`CRITIC_REPAIR`. Two of the three assertions were also half-proved in the way
`_unwitnessed` now refuses.

**Read that beside the fixture runs, because the split is the finding.** The
demo-app recordings -- `rec_MT8TEM57CRGS`, `rec_MT8TF5SO6S71`,
`rec_MT8TF0TIMA6U` -- produce clean, correctly shaped scenarios today. The two
commercial recordings are where the prompt's own bolded prohibitions get
violated and ship: `rec_MT7VTN7ZRJPO` closed on *the shopping bag panel opens,
displaying the item(s) previously added to the cart*, which is the navigation
assertion the drafting prompt forbids in bold, passing thirteen validators. A
rule that holds on the fixtures and fails on real recordings is the CRITIQUE.md
finding arriving a second time, one layer up: the fixtures no longer contain the
thing.

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

The numbers below are from the OLD pipeline and have not been re-measured;
treat them as history until the ablation is re-run.

Seven fixtures, re-recorded through the real extension after the capture
changes, run through the rebuilt generator:

```
What it claimed
Config   Assert   Grounded    Yield   Fabric.   Valid1st   ValidFin
-------------------------------------------------------------------
    A0        0        1.0      0.0         0     0.7143     0.7143
    A1        9        1.0     0.45         0      0.987      0.987
    A2        7        1.0     0.35         0      0.987     0.9592

What it did to get there
Config   Calls/step   Spread   Findings   Converged   PromptTok
----------------------------------------------------------------
    A0          0.0      0.0          0         0.0      19227
    A1          0.8      0.0          0         0.0      60278
    A2          1.1    0.496          4         1.0      89568
```

**That A2 row is a regression, and it is the reason `_keep_provable` exists.**
Read it before trusting a repair loop. A2 claimed *fewer* expected results than
A1 (7 against 9) and its final gate score went DOWN (0.987 to 0.959). One
fixture caused all of it: on `hardpaths`, A1 bound two true claims -- the status
showing "Payment method saved", and the page showing "Validating with the
finance system...". The critic said each checked "a status message rather than
the successful saving" and "a loading state rather than the completion of the
validation process". Both sentences are plausible. Both ask for something the
recording does not contain, because the slow validation never finishes inside
it. Repair obeyed, binding correctly refused the replacements, and A2 shipped a
scenario with no expected results at all.

**The critic being wrong is not the bug.** It is a second opinion; SS9.9 bounds
it precisely because it can be wrong. The bug was that repair replaced a proven
claim before finding out whether the replacement could be proven.

Fixed and verified on the fixture that caused it. `hardpaths` alone, after:

```
Config   Assert   Yield   ValidFin   Calls/step   Spread   Findings   Converged
--------------------------------------------------------------------------------
    A1        2  0.6667     0.9091          1.0      0.0          0         0.0
    A2        2  0.6667     0.9091        5.333      2.5          3      0.6667
```

A2 keeps both claims and the gate score A1 has, and still raises three
findings, two resolved within budget and one surfaced to the human -- which is
SS9.9's designed outcome on exhaustion. `Spread` 2.5 against 0.0 is repair
spending its retrievals on the steps that provoked a finding.

**The seven-fixture table above predates that fix. Re-run the ablation before
quoting it.**

**`Fabric.` is structurally zero in every row now, and A0's is the row to
understand.** A0 used to fabricate thirteen assertions. It emits none at all
today, because the model never supplies a `toolCallId` and with no retrieval
there is nothing for a claim to rest on. So `Grounded` reads 1.0 for a
configuration that said nothing, which is the vacuity trap in its purest form.
**Read `Grounded` beside `Yield`, always.**

**A1's `Spread` of 0.0 is worth watching and is not yet alarming.** With no
critic, almost every claim is settled by one deterministic retrieval, so the
per-step column is flat by arithmetic rather than by inertia. The variance
shows up where claims are genuinely contested -- on `checkout` alone,
`toolCallsPerStep` reads `{step_002: 1, step_003: 4, step_004: 1}`, four
retrievals on the rejected-order step. If that flattens on a recording with
hard claims in it, the drafter's retrieval has become decoration and the design
has not delivered what it promised.

Seven fixtures, each built because a fixture that does not contain the thing
cannot demonstrate it: `checkout`, `hardpaths`, `annotated` (an element the
tester marked, plus an intent note), `twoflows` (two test cases separated by a
scenario break), `wander` (a wrong turn, pruned), `narrated` (the tester says
what they are checking, out loud), and `bugged` (a 500, an uncaught exception,
and the bug-marker hotkey).

**Containing the thing is not the same as demonstrating it.** `twoflows`
contains a scenario break and produced one scenario, and no test noticed --
the whole path was reading a field the recorder never writes. Every fixture
that carries a feature should have a check on what that feature PRODUCED, not
only on the recording holding it.

On `wander`, thirteen validators pass and none skip.

`prove_grounding.py` over every run in `runs/`: 148 of 148 assertions resolve
across 59 runs with tools, 13 of 13 are ungrounded across the 7 without --
SS3.2, measured rather than asserted -- and calls per step varies rather than
being flat, which is SS3.3's signature of an agent instead of a chain.

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
