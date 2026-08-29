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
pnpm start                     # venv + deps + both builds if needed, then server
                               # + review UI on :8000. The whole first run.
pnpm start --demo              # the same, plus the fixture app on :5173
pnpm run bootstrap             # setup without launching (scripts/setup.sh; CI)
bash scripts/check.sh          # drift + ruff + pytest + vitest + ui types. Run before finishing.
pnpm e2e                       # Playwright drives the real extension (headed, ~20s)
pnpm demo                      # fixture app on :5173
pnpm codegen                   # regenerate from schema/ after editing a .schema.json

.venv/Scripts/python -m server.cli run <recording.json> [--config A0|A1|A2] [--offline]
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
.venv/Scripts/python scripts/prove_grounding.py
.venv/Scripts/python scripts/effort_difficulty.py        # SS3.4, refuses to overclaim
.venv/Scripts/python scripts/capture_cost.py            # what capture actually costs
.venv/Scripts/python -m server.cli import <recorder.json>  # Chrome DevTools Recorder

# Which house style the author writes in. `style:` in config/project.yaml, and
# each name is a file in server/pipeline/styles/ holding one good .feature.
#   automation  -> every action, specific values (the default)
#   business    -> few steps, plain language, one verdict per scenario
#   data-driven -> a repeated flow becomes one Scenario Outline; a flow that
#                  happened once stays a plain Scenario

# Narration (SS6.6). Audio is transcribed locally; a transcript can also be
# supplied from anywhere, which is how an imported recording reaches `narrated`.
.venv/Scripts/python -m server.cli transcribe <recording.json> --in-place
.venv/Scripts/python -m server.cli run <recording.json> --narration notes.vtt --narration-offset 0
pnpm run bootstrap --with-transcription    # faster-whisper; the run says so if it is absent
powershell -File scripts/make_narration_wav.ps1   # the committed fixture audio, once

# Replay needs the app running (`pnpm demo`) and the test's parameters. The
# strongest check in the system: does the generated test case actually run?
.venv/Scripts/python -m server.cli run tests/fixtures/checkout.recording.json --replay     --replay-param user_email_1=tester@example.com --replay-param password=hunter2
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json --replay     --replay-param user_email_1=tester@example.com --replay-param password=hunter2

# Against an application with a real login, so replay does not walk it each time.
# The output is a live session: gitignored, same treatment as .env.
node scripts/login_once.mjs https://www.saucedemo.com/ .auth/saucedemo.json
.venv/Scripts/python -m server.cli run <rec.json> --replay --storage-state .auth/saucedemo.json
```

Windows paths: the venv binary is `.venv/Scripts/python.exe`. Never resolve it
by hand in a script -- `scripts/_python.sh` is the one implementation, sourced by
`check.sh`, `setup.sh` and `start.sh`. Bash and
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
path that writes a raw value to disk and redacts later. **That is also why the
LEVEL is chosen in the recorder popup and not in `project.yaml`**: by the time a
server config could be read the decision has already been taken and cannot be
revisited, and it is genuinely per-recording -- one session of a demo app and
one of a system whose order references scan as card numbers sit in the same
project. It travels on `metadata.redaction`; absent means `full`, which is every
recording made before the setting existed.

`secrets_only` turns off ONLY the pattern scan -- the half that decides by
SHAPE, and therefore the only half that can be wrong about a value nobody typed.
`redactWholeValue` and `redactKnownSecrets` still run, because deciding by
CONTEXT (a password field is secret whatever its value looks like) cannot be.
`off` keeps nothing.

Two things follow, and both are consequences rather than weakenings:
`no_placeholder_leak` WARNS below `full` -- the same scan, the same finding, a
different consequence, because you cannot ask for raw values and also gate on
their absence, and leaving it fatal would mean the setting silently produced no
output at all. And `check_origins` REFUSES a recording below `full` unless
`origin_policy` is `off`: free-tier prompts may be used for training and read by
human reviewers, and that is the one mistake nobody can take back. `no_placeholder_leak` is
the only validator whose action is `hard_fail`: the feature file is not written
at all.

*What is scanned changed on 2026-08-28, and the narrowing is the point.* The
pattern rules (`redaction/rules.ts`) run over the tester's **input** and over
**transport** -- typed field values, request and response bodies, console text,
request URLs. They no longer run over **page content**. On one storefront
listing that scan produced **214 parameters, every one classified as a phone
number**, and what it actually matched in page text was dates:
`"Updated 2026-08-28 14:32"` became `<<phone_n>>`. A date on a page is routinely
the thing a test asserts on, so the scan was destroying evidence to protect a
value nobody had entered.

Page content instead gets `Redactor.redactKnownSecrets`, which is a different
kind of rule: not "does this look like a phone number" but "is this the exact
string the tester typed into a password field". Exact values only, minimum
length, so it cannot touch a price or a product code. It exists because
capturing the whole page made a case reachable that scoped capture never saw --
an application that DISPLAYS a value the tester also typed.

**The limit is real: a secret the application displays and the tester never
types cannot be recognised by anything here.** Nothing distinguishes it from
ordinary page text. Two answers and only two -- a project rule in
`ProjectRedactionConfig.sensitive` naming it up front, or not putting it on the
page. Pinned in `redact.test.ts`, and it is why the fixture app's login page no
longer prints its demo password.

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

**The AUTHOR writes the `.feature` file.** It emitted JSON until 2026-08-29 and
`narrative.py` composed the body from it, which meant **no model in this
pipeline had ever seen a feature file** -- the one artifact the tool is judged
by was assembled by a script from parts none of which were Gherkin. It read
like an assembled array because it was one, and two of four shipped features
carried the tell: *"When the order is not processed"* (a state written as an
action, with no verdict), a verdict repeated as both an `And` and a `Then`.

It also broke this repo's own most-repeated law in the most literal way
available: the author's worked example taught a model to write Gherkin without
ever showing it any Gherkin.

So the answer is now the body plus `annotations` -- one per step line, carrying
what prose cannot: the events a line accounts for, the literal that proves it,
why there is no verdict. `server/pipeline/featurefile.py` reads it back with
`gherkin-official`, the same parser `gherkin_parses` runs over the output, so
the author cannot write something that reads there and fails at the gate.

**The join is by the line each annotation echoes, and ordinal alone was not
enough.** The first real model wrote six lines and returned five annotations,
having forgotten a `Given`. Under a positional join that is not "one line loses
its events" -- every later line is silently attributed to its neighbour. So an
annotation carries `line`, which is a duplicate of prose used as a join key and
then discarded; the file stays the single source of the sentence.

**A format slip must never cost the run, and never a revision round.** Prose-
first emission was rejected once on exactly that objection. If the body does not
parse or the join fails, `author._parse` falls back to the old JSON path and
marks the document `degraded`.

**The `.feature` body is still prose, and nothing else.** No comments, no ids,
no review markers, no fidelity flags. All of that lives in the `.trace.md`
sidecar (`server/renderers/trace_md.py`); the machine-readable form is in
`ir.json` and `trace.json`, which is what the validators read.

**A style is a worked example, not a rule.** `style:` in `project.yaml` selects
a file in `server/pipeline/styles/` holding one good feature file written that
way. Adding a style is writing one; nothing else in the pipeline changes. That
is the only mechanism that has ever moved output here -- every content RULE
added to a drafting prompt measured at or near zero uptake.

**`narrative.py` lays out what the author chose.**
Given/When/Then used to be DERIVED from a step's role plus its position, and
that was right while the model writing steps saw one segment at a time: asked
for a keyword with no view of the flow, it answered `When` every time, which is
how Phase 1 shipped seven `When`s in a row. An author with the whole session in
front of it knows where the scenario turns.

`author.py` therefore emits both `keyword` and `role`. Downstream, **`role` is
authoritative** (`narrative._base_keyword`),
because it is what survives a reviewer deleting a step; the stored keyword is
already `And` half the time. `narrative.py` still owns `And` collapsing, beat
layout, and the one positional rule that cannot be a matter of opinion:
`_opening_block`. Read its comment before touching it -- the running flag it
replaced reached through a whole scenario from one step's assertion, and was
invisible for months because every fixture opened with a sign-in nobody
asserted on.

**The recorder captures the PAGE, and both snapshots come from the same root.**
Not the landmark around the clicked element. `scopeRootFor` still exists and
still answers "which part of the page was the tester working in", but it decides
nothing about what is captured. Two mechanisms are closed by that, and both were
producing evidence-free events:

* *The keyhole.* `scopeRootFor` walks to the NEAREST landmark, so a tester
  clicking inside a filter widget that is its own `region` captured 1.2 KB and
  an empty diff while the product list under test was never captured at all.
  30-50% of events on real sites recorded no observed change.
* *The moving root.* It was re-evaluated for `after`, so a click that detached
  its own landmark ancestor fell back to `document.body`; every path changed,
  nothing matched, and the diff read +408 added / -405 removed on a 405-node
  tree. That churn was being read downstream as "the product grid re-rendered".
  A fixed root makes `before` and `after` comparable by construction.

**`MAX_NODES` is part of that rule, not a detail.** It was 400, and 30 of 34
events on one real recording and 9 of 15 on another were truncated on both
sides -- so every "a full page is ~29 KB" figure that justified scoping measured
the CAP. The budget is spent depth-first in document order, so the cut lands at
the bottom of the page, which is where a product grid lives. Widening the scope
without raising the cap would have changed nothing. Run
`scripts/capture_cost.py` before believing any number about what capture costs;
it says out loud when a recording's sizes are its cap rather than its pages.

**A commercial page costs about twenty times a fixture page, and the number to
watch is the RETRIEVAL, not the recording.** Measured, nothing truncating:
5.5-10.7 KB per event on `fixtures/demo-app`, against **150-172 KB per event
and ~950 nodes** on the two real storefronts recorded since (`rec_MTD7TNDZXIVT`,
`rec_MTDACAHZLT2G`). Stored bytes are not the problem -- a 5 MB recording is
fine on a local disk. What travels is: `get_diff` came back at 4.5-15 KB on
those same pages, because the diff summariser ranks and caps, while
**`get_snapshot` returned 65-72 KB -- one call, ~16-18k tokens** -- and the
conversation re-sends its history every turn. Three snapshot calls took the
sorting run to **168,690 prompt tokens against ~29,000 for a fixture run.**
`get_snapshot` is the one tool that still hands back a whole page raw; it wants
what `get_diff` already has. Do not read full capture as a mistake on the
evidence -- read it as one unbounded tool.

Pinned in `snapshot.test.ts` under *the keyhole*, and end to end by the
`fixtures/demo-app` storefront page, which exists only to reproduce it.

**The last action of a session is the one most likely to carry the verdict, and
three separate things used to drop it.** `capture()` awaits settle before it
sends; settle restarts its quiet window while any request from the action is in
flight; and `inFlightFor` bounds an action's window by the start of the NEXT
action, which the last action does not have. So the final click waits out the
full 5s timeout while the tester is already pressing Stop. `stop()` now cancels
open settles (`recording_stopped`, said out loud on the event rather than
pretending the page settled), waits for in-flight captures, and only then
acknowledges; `ingest` accepts an event that happened before `stoppedAt`; and
the export page waits for `stopped` before assembling. Remove any one of the
three and the recording comes back one event short and looks complete.

**The recorder is black-box.** It reads the live accessibility tree and needs no
access to the target app's source. `data-testid` is used when present, but the
role+name fallback is the normal case. Do not add anything that assumes
cooperation from the app under test.

**A tab opened from a recorded tab joins the recording; one with no opener does
not.** `session.tabIds` is a set, `chrome.tabs.onCreated` follows `openerTabId`,
and the new tab is sent `start` with the SAME `startedAt` -- `performance.now()`
is per-document, and one shared wall-clock zero is the only thing making two
documents' events comparable. `openerTabId` is the whole test: a tester opening
their email mid-session is not part of what they were testing.

`event.tabId` was available on every event since the recorder was written and
never kept. **`digest.py` must print the tab change**, or the author writes *"the
tester continued"* when a payment window opened -- the `scenario_break` bug in a
third costume. Pinned by the `twotabs` fixture, whose receipt page shows a total
that appears nowhere else in the app, so an assertion on it can only come from a
recording that actually followed the tab.

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
  evidence/      store.py = the recording, indexed. tools.py = the six tools +
                 ToolRunner. citation.py = which retrieval licenses a claim.
                 predicate.py = WHAT is claimed about it. text.py = the one
                 containment primitive, below both
  pipeline/      segment.py (code, hints only) -> digest.py (code, the session
                 index) -> expectations.py (agentic, what SHOULD have happened,
                 retrieving on a small budget) -> author.py (agentic, one
                 conversation: the whole .feature file, cited) ->
                 featurefile.py (code, reads it back)
                 -> narrative.py (code, layout) -> validators/ (code, five
                 checks) -> judge.py (agentic, seven questions: would a QA lead
                 sign it) -> coverage.py -> run.py
                 investigate.py = the shared decide-retrieve-observe loop
                 styles/ = one worked .feature per house style, which IS the
                 specification of that style
                 transcribe.py = narration audio -> text, before any of it
  renderers/     gherkin.py + trace_md.py (sidecar) + bug_md.py are always
                 written; xlsx/jira opt in behind base.py's Exporter seam
  ablation/      A0/A1/A2 and the metrics table
  llm/           ModelClient seam: gemini, cassette, chain, scripted
  runners/       does the generated test case actually run? base.py + playwright.py
  importers/     devtools.py = a Chrome Recorder export; transcript.py = a
                 WebVTT/SRT/JSON transcript as narration
scripts/         setup.sh + start.sh (one command each, _python.sh shared),
                 check.sh, prove_grounding.py, effort_difficulty.py,
                 capture_cost.py (is full capture affordable -- ask it, do not
                 guess), replay.mjs,
                 snapshot_features.py (before/after), compare_features.py (A0/A1/A2)
ui/              the review UI. route.ts = three addresses (review, confirm,
                 help), Help.tsx = the how-to as a page a tester can reach
docs/            RECORDING.md (for the tester, no terminal), HOWTO.md (for
                 whoever runs it: every feature and its command), DESIGN_NOTES.md
                 (why every rule exists), COMPLAINT.md (what was wrong, and the
                 design decided in response), archive/

Stage order is deliberate: deterministic where possible, agentic where
necessary. `segment.py` still runs, but its boundaries are HINTS in the index
(idle gaps, URL changes, checkpoints), not step boundaries. **Do not put a
model inside `segment.py`:** what it produces has to be identical every time,
because the drafter reads it.

The net under the drafter's freedom is `event_coverage`: every recorded event
lands in a step or in an explicit `omitted` entry naming it, EXACTLY once,
counted per test case.

> Every rule below is stated without its story. The defect that produced each
> one, and the measurement that settled it, is in
> [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md). Read that before arguing with a
> rule; read this before changing code.

### Who decides what

**One author writes the document, and goes and looks while it does.** `author.py`
decides the feature name, the scenarios, the tags, the roles, the keywords, the
step boundaries, which outcome is worth checking, and where a scenario ends. It
was five stages -- draft, split, bind, second chance, bug mode -- and they were
downstream machinery for catching a model guessing about something it could not
see. It could not see because the recorder captured the landmark around the
click; on 30-50% of events the candidate set for an assertion was empty. Opening
the aperture left most of that apparatus with nothing to catch.

**Draft-then-bind survives, inside the loop.** It decides what is worth checking
and then retrieves to prove it, rather than claiming only what it happened to
retrieve first. An author that may only claim what it already has writes about
whatever was easy to get.

**Refusal is something the author WRITES, not something done to it.** `whyNot`,
in language a tester can act on: *"the product list was never captured before or
after this click"*. A claim that could not be proved used to be deleted, the
scenario ended silently without a `Then`, and a style warning said so in a
vocabulary nobody outside the pipeline reads -- 27 of those warnings turned out
to be a readout of the capture bug, and not one told a reviewer what to do.

**Nothing checks that a `whyNot` is TRUE, and a false one is worse than a
missing verdict.** On `rec_MTD2DLZRFCEH` the author refused with *"the tester
navigates to a new browser tab, which is outside the scope of the current
application session recording"* -- and it is not. The recorder followed the
tab (`evt_010` carries its own `tabId`), and the digest said so in as many
words: *"A DIFFERENT BROWSER TAB. The tester moved to another window here."*
The signal was correct and the author drew the opposite conclusion from it,
then stated that conclusion to the tester as a considered decision. Every
validator passes a refusal, because a refusal claims nothing. **Refusals belong
in front of the judge exactly as claims do** -- a wrong `whyNot` is the one
output in this system that is both confident and unchecked.

**It cannot tell a step from a step that swallowed something, and nothing can.**
The counter-measure is in the prompt (bad and good shape side by side); the net
is `event_coverage`.

**`merge_repeats` is the net against two adjacent steps with identical
sentences**; a merged sentence may not drop a redaction placeholder
(`narrative._keeps_parameters`). `segment.py` deliberately does not end a step
on a 4xx.

**A scenario break is deterministic, not a suggestion.** Where the tester pressed
the button, `run._split_on_declared_breaks` cuts and no model is consulted. It
splits and never joins, and only where the break opens a STEP. A `scenario_break`
carries **no `eventId`** -- `segment.break_openers` resolves the timestamp
forward, and is the one shared implementation. `digest.py` must print the break
into the index, or the one author that decides scenario boundaries is never told.

**The size-triggered split is gone with `split.py`.** The trigger was
deterministic and the ANSWER was not: the same recording returned one group on
one run and two on the next, because the splitter read the draft and the draft
had changed. The author decides scenario boundaries while it writes, with the
whole session in view, which is the only place that judgement was ever going to
be stable.

**The critic and the repair loop are gone, and `judge.py` is not them coming
back.** A2's critic raised nine findings and the loop resolved one, because five
of the survivors were `coherence` and it had no repair route by design. Three
things are different and all three are load-bearing:

* **Fresh context.** The judge sees the finished document, the session index and
  the expectations. Never the author's reasoning or its tool calls -- a model
  shown its own justification defends it.
* **One route.** No routing table. A rejected claim and a judge's finding both
  reach the author as sentences and it decides what to change, because it wrote
  the document.
* **`fail` only.** A `weak` finding is one a QA lead would sign after an edit;
  spending a round on it risks a step to `merge_repeats` for no gain. It is
  still recorded.

**`CHECKS` is a closed tuple and `_parse` drops anything not in it, silently.**
That is right -- a finding naming a category that does not exist reaches the
author as an instruction to change nothing -- and it is a trap: adding a
question to the PROMPT without adding it to `CHECKS` ships a change that looks
clean and does nothing. `test_judge` asserts the two lists agree in both
directions.

**Seven questions, not five.** The two added on 2026-08-29 each close a hole
nothing else looks at:

* **`claim_within_evidence`** -- does the sentence claim more than its literal
  shows? *"the order is rejected with a 409 Conflict status"* shipped proved by
  *"Orders over EUR500 require approval"*, a page alert with no 409 in it. The
  gate confirms the literal came back from a retrieval; nothing confirmed the
  SENTENCE was about the literal. `get_network` is in `JUDGE_TOOLS` for this.
* **`refusal_is_true`** -- **every validator passes a refusal, because a
  refusal claims nothing.** It is the only output here that is confident and
  otherwise entirely unchecked, and one shipped saying the tester had left the
  recording's scope when the recorder had followed the tab and the index said
  so in as many words.

`evals/RUBRIC.md` does NOT have these two, deliberately: it is the out-of-band
instrument and this is part of the machine. Wiring one to the other would mean
tuning the pipeline tunes the instrument.

Bounded at **two author rounds**, and a revision that would put two adjacent
steps with identical text in one scenario is refused whole (`_collapsing_pair`)
-- `merge_repeats` would fold them and the document would silently lose a step.

**`judgeFails` is a count and never a rate.** `Converged` reported 1-of-9 while
measuring how much of what the critic said the loop was *allowed* to act on.
Matching a round-2 finding to the round-1 one it descended from is a guess, so
what is reported is what is still true of the document that shipped.

**The pipeline judge and `evals/RUBRIC.md` are two things on purpose.** The
rubric is the *instrument* -- out of band, held-out, never edited to make a
verdict pass. `judge.py` is part of the machine and its prompt is meant to be
tuned. They share the five questions and nothing else; wiring one to the other
would mean tuning the pipeline tunes the instrument.

### What may be claimed

**The author never supplies a `toolCallId`.** It names a literal it says it saw;
`evidence/citation.py` searches the retrievals actually made. A fabricated
citation is not something the model can express. `find_text` is excluded as
evidence of its own query, and so is `see` -- a description of a picture is not
evidence that a string was on the page.

**Seeing a literal in the session index is not enough; it has to come back from
a TOOL.** The index is a summary, so a claim resting on it points at nothing.
This is stated in the prompt in as many words because it is the single rule that
decides whether a scenario gets a verdict, and the first live run without it
produced a true claim that had to be refused.

**A screenshot decides; the text cites.** `see` is how the author works out
where to look when the accessibility tree does not settle it -- whether a list
re-sorted, what a canvas showed. The claim still names a literal from a text
retrieval. This keeps the one rule intact while opening the aperture, and it is
the reason vision could be added at all without a hole in the gate.

*It has never once been called.* Across every run on disk the author has used
`get_diff` (26), `get_snapshot` (14) and `find_text` (2), and `see`,
`get_network` and `get_narration` zero times each. **Rare is correct and the
target is not "more often"** -- a screenshot is ~1k tokens and an author that
looks at every event is not investigating. Never is the defect, and the cause
is above: `see` is one line in a tool list and appears nowhere in the worked
example, so nothing has ever shown the author what a moment that needs a
picture looks like. Fix the example and the trigger condition -- *the text does
not settle the question you are actually asking* -- not the frequency.

**A claim is checked against the recording as well as against the retrieval.**
`store.contains_at` at the cited event, re-pointed when the literal turns out to
live at exactly one other event, refused otherwise. Two independent checks: what
the agent was shown, and what is true of the session.

**The nine refusal rules are gone** -- `_own_input`, `_unwitnessed`,
`_existence_only`, `evidence_discriminates`, `mutation_claimed` and the rest.
Each was catching a symptom of an author with nothing to look at, and each was a
regex guessing whether a sentence is meaningful. A regex will always lose that
question to a model reading it. **Do not add another one.** If the output is
vacuous, the judge is the instrument, and the cause is upstream.

**A claim says WHAT it claims, and the gate checks that shape.**
`Evidence.predicate` (`server/evidence/predicate.py`) -- `contains` (the
default, and what every claim written before this meant), `first_of`, `count`,
`absent`. Without it the gate was substring containment, so
*"Then the first product is 'The Autumnal Hamper'"* was proved by that string
appearing ANYWHERE: the sentence said FIRST and the check said PRESENT. Sorting,
ranking, pagination and every negative assertion were inexpressible. Three
things about it are load-bearing and each was a way to ship it broken:

* **Nodes are addressed by role and accessible name, never by a css id or a
  `ref`.** There are no ids in the node model, and `ref` is stable only WITHIN
  one snapshot -- so a predicate binds to one stored response and cannot be
  re-pointed the way a bare literal can. `_attach_claim` disables that re-point.
* **It is evaluated against the STORED response, which is the full one.**
  `ToolSpec.view` renders a smaller value to the model (see below); evaluating
  `first_of` against a RANKED view would answer "the first NAMED node", and on a
  product grid the nameless wrappers are exactly what ranks to the back. It
  would return the wrong answer confidently and pass the gate.
* **It has three outcomes, not two.** true / false / **cannot-evaluate**.
  Cannot-evaluate goes to `whyNot` -- never to pass, which builds a laundering
  machine, and never to reject, which kills true claims when a shape changes.

**`ToolSpec.view` splits what is STORED from what is SENT.** The stored value is
the evidence -- re-hashed by `evidence_retrieved`, re-read by every predicate --
so it must be complete. The sent value is a budget: `get_snapshot` returns 65-72
KB of a commercial page into a conversation that re-sends its history every
turn. `image_for` already made this split for pixels. It is also the seam a live
browser agent needs: an MCP client's retrievals must be persisted through
`ToolRunner.call` or they never reach `trace.toolCalls`.

**A refused claim must reach the author, or the gate is green and the document
is empty.** When the author quotes a literal it never retrieved,
`_attach_claim` drops the claim and writes a `whyNot` -- so it never becomes an
assertion, so `evidence_retrieved` has nothing to reject, so the loop sees a
clean gate and stops. Measured live on `keyhole`: two correct verdicts, ZERO
tool calls, both silently refused, scenarios shipped ending on a `When`.
`_revision_feedback` now carries refusals, and `investigate`'s `needs_retrieval`
nudges an author that wrote verdicts without retrieving anything -- the mirror
of the budget nudge that has always been there. **Both are bounded and neither
invents anything**; and neither fires on a document of pure refusals, because
forcing a call out of an author that claimed nothing is the mandatory-tool-call
anti-pattern.

**A bug report is a failed expectation, not a stage.** *"Expected 9 products,
saw 24"* is the same sentence either way. It reaches the IR when the tester
pressed "Not right" on the confirmation screen (applied deterministically in
`author._apply_rejections`, because a prompt that asks is not a guarantee) or
when the author marks it. `BugDetail.actual` is bound exactly as tightly as any
assertion -- yielded into `grounding._assertions`, never a branch of its own.


### Gherkin shape

**`Given` belongs to the opening block only.** `narrative._opening_block` ends
the block at the first non-setup step AND at the first setup step carrying an
accepted expected result. Read its comment before touching it: the running flag
it replaced reached through a whole scenario from one step's assertion, and was
invisible for months because every fixture opened with a sign-in nobody asserted
on.

**`gherkin_style` is gone, and so is the second chance.** Both were judgements
written as regexes -- does this scenario have a verdict, does this name match its
body, is this sentence a run-on. Across 33 runs it produced 27 warnings and zero
rejections, and the warnings were a readout of the capture bug rather than a
finding about the prose. The author now says why a scenario has no verdict
(`whyNot`) instead of a validator noticing afterwards that it does not.

**A scenario carries a `Scenario Outline` when the AUTHOR asked for one.**
`TestCaseIR.examples`, a judgement about test design: one flow exercised with
several sets of values. Distinct from `parameters: outline`, which lifts
redaction placeholders into a one-row table and is a rendering setting. An
author table wins where both exist, and `_outline_names` returns nothing then --
or `_step_text` would rewrite `<<password>>` into `<password>` in a scenario
whose table has no such column. Two rows minimum: one row is not a table.

**`Step.keyword` is derived, and `sync_keywords` keeps it honest.** Both
`ir.json` and the feature file get it from `build_narrative`.

### Seams

**A new output format is a new file in `server/renderers/`, never a pipeline
change.** Every format implements `base.Exporter` and reads a finished
`IRDocument`. Gherkin and its sidecar are always written; xlsx and jira opt in.

**`server/runners/` is to correctness what `renderers/` is to readability.** It
drives the IR and the recording, not the `.feature` -- no Gherkin runner binds a
step to anything but a hand-written step definition. Reachable as
`run --replay` and `ablate --replay`; both need the app running (`pnpm demo`)
and the test's parameters.

**A replay signs in the slow way unless it is given `--storage-state`.** Every
recording on disk is of a public site, so walking the recorded login is fine --
three events, and the redacted password comes back through `--replay-param`. On
a real application it is slow, brittle, and trips MFA. `scripts/login_once.mjs`
writes the file, headed and by hand: automating it would put a password in a
config the replay path reads, and the one rule about secrets is that they are
redacted in the browser before anything is persisted. The file is a live
session -- `.gitignore`d, treated exactly as `.env` is. **An absent or expired
file is ignored rather than fatal**; a replay that refuses to start is worse
than one that logs in.

**The Jira EXPORT builds an issue and does not send it; `jira-push` sends it.**
Credentials come from the environment, never from committed `project.yaml`.

**Every review edit goes through `server/api/review.py`** -- SS13.5's record is
the project's only source of difficulty labels. A reviewer can reject a claim or
delete a step, but never edit `toolCallId` or `literal`.

**The step library is gone.** `libraryRef` was never set once, on any step of
any run; `library_verbatim` never executed; the database held two rows. It solved
a problem the deleted per-segment naming stage created -- three stages naming
steps independently and drifting -- and created one of its own: a tool the
drafter felt obliged to call on every step, which lifted calls-per-step from 1.56
to 2.17 and collapsed SS3.3's effort spread from 1.08 to 0.16. **A mandatory tool
call is not investigation.**

*The tool went with it on 2026-08-29, and so did five others.* `TOOLS` is six
now -- `get_diff`, `get_snapshot`, `see`, `find_text`, `get_network`,
`get_narration`. The six that went (`query_element`, `get_console`,
`get_events`, `get_objective`, `get_neighbouring_segments`,
`search_step_library`) were offered to NO stage, reachable only because
`coverage.py` was the one `investigate()` caller passing no `tool_names` and so
received the whole registry by accident. Coverage has its own set now.

**More tools measurably means worse tool choice**, which is the whole reason
`tool_names` exists, and `test_evidence` asserts every registered tool is
offered to some stage -- the check that would have caught these six.
`get_network` and `get_narration` STAY: cutting `get_network` would remove the
only path to *proving* a status-code claim while leaving the only path to
*inventing* one, which is how a 409 shipped with no 409 in its evidence.

**Coverage suggestions are quarantined three times over**: their own IR block, an
UNVERIFIED heading in every renderer, and `suggestions_quarantined` at the gate.
Gated on `suggestions_enabled` and on nothing else, so a comparison never
measures two changes at once.

**The oracle belongs to the recording, not to a run.** `expectations.json` sits
beside `recording.json`, and `run._expectations` reads it rather than
regenerating: a tester who confirmed twelve guesses must not be asked again
because somebody re-ran the pipeline, and guessing afresh would silently
downgrade `confirmed` back to `inferred`. That is the one direction that file
must never move.

**The oracle retrieves, and its budget is a latency budget rather than a
grounding one.** It ran tool-less until 2026-08-29, on the argument that a
stage should not license a claim from a summary. That argument is about
CLAIMS: this stage writes a question for a human, and the whole difference
between an expectation somebody can tick and one they cannot is whether it
names a value -- *"the list should drop from 24 products to 9"*, not *"the list
should update"* -- which the session index does not always carry.
`GUESS_BUDGET` is 4 and `EXPECTATION_TOOLS` is three, because `POST
/api/recordings` guesses while the tester is still sitting there. Its
retrievals reach `trace.toolCalls` like any other, which is correct:
`_calls_per_step` attributes effort by the event a call asked about, whoever
spent it.

**The oracle has to be REACHABLE, and for months it was not.** The confirmation
screen opened only on `?confirm=<id>`, read once in a lazy initialiser, linked
from one place -- the extension's export page -- and cleared on dismiss. The
measured consequence: **14 expectation sets on disk and all 14 still
`inferred`.** Not one had ever been answered by a human, so every stage
downstream had only ever read unchecked guesses, and A1-vs-A2 -- what asking a
human is worth -- was unmeasurable.

`GET /api/expectations/pending` reports the unanswered ones (by `confirmedAt`,
which was in the schema for exactly this question and which nothing had ever
read), `ConfirmBanner` puts them on the review screen, and `ui/src/route.ts` is
a ~40-line router so `/confirm/:id` and `/help` are addresses somebody can
return to. `?confirm=` still works, permanently: it is what every recording made
before this links to.

**A run must never wait on a screen somebody might not open.** `POST
/api/recordings` guesses, runs, and produces a draft on the guesses alone.
Answering the confirmation screen enqueues a SECOND run. The skip path is the
one that has to be right, because it is what happens by default.

## Things that bit us, so you do not repeat them

Each of these shipped once. The full story of every one is in
[docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

**Pydantic copies the list you hand it, so `trace.toolCalls` is not
`runner.calls`.** Any stage retrieving after the trace was built is invisible to
`evidence_retrieved`. Call `_sync_calls`.

**`merge_repeats` makes a step rewrite dangerous** -- a repair can produce a name
identical to its neighbour and *delete a step*. `narrative.would_collapse`
refuses the rewrite.

**`lift_background` lifted steps into a list nothing rendered.** If you add
anything to `Narrative`, check that a renderer reads it.

**A sibling test case is not necessarily a sibling scenario.** Count
`test_cases(ir)`, never `ir.testCases`.

**Anything you want the model to do has to be IN the worked example, not only
in the rules.** The example outweighs the rules and will contradict them
silently, so this is a construction rule and not a warning: when you add a
capability, add the situation that calls for it to the example, or it will
never fire. Measured, on the rebuild's own prompt -- `see` and an `Examples`
table are each named exactly once in `SYSTEM_PROMPT` and appear zero times in
`WORKED_EXAMPLE`, and across ten runs each was used **zero times**. That is the
step library's failure in reverse: not a tool called out of obligation, a tool
never reached for because nothing showed the moment to reach for it.

The two halves are not the same edit. A capability the author should use
ROUTINELY goes in the example as a routine call. A capability it should use
RARELY -- `see` is the case -- goes in the example as one worked instance of
the situation that warrants it, never as a step in the happy path: teaching
routine use of an expensive tool is the mandatory-tool-call anti-pattern
wearing the opposite costume.

Examples are rendered in the project's voice; `with_subject` is the
deterministic net.

**A mandatory tool call is not investigation.** The lesson stands and its
mechanism is gone: `ROUTINE_TOOLS` was the exclusion list that kept
search-before-invent out of `_calls_per_step`, and it went with the step
library. There is no such constant in the source now, and nothing in
`_calls_per_step` filters by tool name -- it attributes a call to a step by the
`eventId` in its arguments. Do not reintroduce a tool the author is obliged to
call: mandating one lifted calls/step 1.56 -> 2.17 and collapsed SS3.3's Spread
from 1.08 to 0.16.

**Grounding is provenance, not correctness, and `Executes` alone is vacuous.**
Read `Executes` with `Rechecked`, and grounding rate with `Yield`.
`ReplayResult.passed` required `self.steps` to be non-empty for the same
reason: `ran and all(...)` over an empty list is `True`, so a test case the
runner could not express one action for reported green. **Seventh column.**

**A runner that drops what it cannot drive grades its own gaps.** `_action`
returned `None` for `select`, `dialog`, `file_select` and the tab events, so a
step made of them had no actions and passed trivially. It emits an
`unsupported` action now and the step fails honestly. The same shape hid a dead
branch for a year: it tested `keydown`, and the `EventType` member is
`keypress`.

**A second scenario can depend on the first one's TEST steps, and only its
SETUP steps are lifted.** Newly visible on 2026-08-29, because the author now
routinely produces two scenarios where it produced one. On the checkout
recording, scenario 2 opens *"the tester has an order over EUR 500 requiring
approval"* -- true, stated in prose, and carrying no `eventIds`, because the
events that established it are scenario 1's `test_step`s and `_build_case` lifts
only `setup`. The replay signs in, adds the widget, and then clicks a control on
a page it never reached.

**It fails honestly and that is the designed behaviour**, not a bug to paper
over: a set-up-less case reported green would inflate `executionRate`, which is
the vacuity trap in its mirror image. But it is worth knowing that `Executes`
now under-reports on multi-scenario documents, and the resolution is a real
choice -- lift more as preconditions (and blur what a test case independently
means), or mark such a case not-independently-replayable. Do not resolve it by
making the runner lenient.

**A replay must run the scenario's `preconditions` first.** A document with two
scenarios lifts the shared opening into a `Background`, so the second case's own
`steps` begin partway through the flow -- and `build_job` replayed only those,
clicking a control on a page it had never navigated to. That is the vacuity trap
in its mirror image: an empty case reported green inflates `executionRate`, a
set-up-less case reported red deflates it, and both make the column measure the
harness. Preconditions replay without assertions; a precondition states shared
state rather than a verdict this scenario reached.

**`hash()` is salted per process.** Use `hashlib.sha256`.

**The picker's own click was recorded as a step that never happened.** The
recorder ignores events while `picker.active`.

**Attribution direction is not the same for every annotation.** An assertion
annotation comes AFTER what it points at; an intent note comes BEFORE.

**An imported recording is not redacted.** `server/importers/devtools.py`
redacts before constructing the `Recording`.

**`input[type=password]` has no implicit ARIA role.** `INPUT_ROLE_FALLBACK` in
`content/a11y.ts`; form controls are never flattened.

**`composedPath()[0]` is the innermost node.** `targetOf` walks outward to the
enclosing interactive element.

**`performance.now()` is per-document.** Convert with `performance.timeOrigin`.

**The offscreen document is a third clock, and the microphone starts late.**
`audioOffsetMs` is added to every segment in `transcribe()`. Drop it and every
spoken sentence shifts onto the neighbouring step.

**Audio does not travel through `chrome.runtime.sendMessage`.** `offscreen.ts`
writes chunks to IndexedDB itself. Order is load-bearing: only the first chunk
carries the WebM header.

**An offscreen document cannot show a permission prompt.** `mic.html` exists
solely to ask once, from a real tab on a real user gesture.

**Network attribution belongs at assembly, not in the frame.** Frames report
observations; `export.ts` attributes them.

**In-flight requests must be scoped to the action**, or one never-completing
request makes every later step wait the full 5s.

**A settle window must be ended by the NEXT action, or an event's `after`
absorbs what the next action caused.** `inFlightFor` bounds request
*attribution* by the next action; nothing bounded the settle itself. On the
checkout fixture `evt_007` (enter an order total) and `evt_008` (press Place
order) are **2 ms apart** with a 317 ms quiet window, so evt_007's `after` held
the rejection evt_008 caused -- and an assertion bound to it passed
`evidence_retrieved` *and* `contains_at`, because the literal really was in the
stored snapshot. It was still false about the moment it named. `capture()`
cancels open settles with `superseded` as its first synchronous act, before the
application's own handlers run. **Only replaying the test case caught this**;
that is the argument for `server/runners/` in one paragraph.

**Retry must sit INSIDE the fallback chain**, or it never sees a rate limit.
Pinned by `test_retry_must_sit_inside_the_chain_to_see_a_rate_limit`.

**The model can only cite what it was shown.** Tool results are wrapped as
`{"toolCallId": ..., "result": ...}` because providers keep the id in an
envelope the model never sees.

**`find_text` is the grounding index, and a gap in it looks like a validator
bug.** Check what got indexed before you touch the gate.

**Every model is `additionalProperties: false`, so DELETING a field breaks every
artifact on disk.** Dropping `RepairAttempt.resolved` outright stopped
`prove_grounding.py` reading thirty existing runs -- extra_forbidden on a field
those traces were correct to have written. Removing a field means making it
optional and no longer writing it, not deleting it. The strictness is right and
is what catches a typo'd key; it just cuts both ways.

**A required field that is always `false` is noise wearing a measurement's
clothes.** `RepairAttempt.resolved` was hardcoded `False` at all three
construction sites and nothing ever set it `True`, because what was resolved
between two whole-document rewrites is genuinely not knowable. The reasoning was
right and the field was not. Gone; `judgeFindings` and `judgeFails` are counts
of what is still true of the document that shipped.

**A required schema field nobody passes is a crash waiting for its first
caller.** `BugDetail.environment` was required and `_bug_detail` did not pass
it, so EVERY construction raised out of `_assemble`. It was unreachable -- the
path needs a step that is both `bug=True` and carries an accepted assertion,
which needs a human to have answered the confirmation screen, and across 14
expectations nobody ever had. Making the screen reachable is what would have
shipped it.

**A CLI default silently overrides a module constant on every run.**
`--budget` defaulted to 8, in per-STEP vocabulary from the deleted architecture,
and overrode `AUTHOR_BUDGET = 24` on every CLI and server invocation. An author
that spends one retrieval per verdict then has nothing left for `see`. Check
what a flag's default actually replaces.

**A catch-all route must not swallow `/api`.** Serving `index.html` for
unmatched paths -- which the UI's real routes need -- returned 200 with HTML to
JSON clients and silently un-did the download path-traversal guard, which is how
it was caught. `/api/...` raises 404 before the fallback.

**A fixture that skips a step the real path requires keeps a test green over
code that never ran.** `judging_model` answered without retrieving, so every
verdict in every judge test was refused and those tests ran against documents
with no assertions. Same shape as the `scenario_break` factory trap, and it was
only visible once refusals started reaching the author.

**Bash heredocs mangle backslash escapes.** Use the Write/Edit tools for any
file containing a regex, and give every regex a test with a negative case.

**Asking for values in step text invites a run-on.** `_is_run_on` in the style
validator catches a regression.

**A factory that can build an input the recorder cannot is a trap.** Every test
of the scenario-break split passed an `eventId` that a real `scenario_break`
never has, so the suite was green on a path that had never run.

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

**`pnpm e2e` is not part of `scripts/check.sh`, and that is where a green
suite hid a dead path.** `annotate()` in the e2e spec answered a `window.prompt`
that the popup had stopped using when the intent note got its own textarea, so
`intent_note` was never saved and the assertion below it passed on an empty list
for as long as the textarea had existed. Same shape as the `scenario_break`
factory trap. Run the e2e suite when you touch the recorder OR the popup.

`author.py`, `expectations.py` and `digest.py` are covered end to end through
`test_pipeline.py` rather than by modules of their own.


## Status

The rebuild of 2026-08-28 landed. **[docs/REBUILD_FINDINGS.md](docs/REBUILD_FINDINGS.md)**
holds the evidence and, in §11b, the four claims that did not survive being
re-measured while it was built; **[docs/REBUILD_PLAN.md](docs/REBUILD_PLAN.md)**
holds what was planned. Read §11b before trusting a number from either.

What changed, in one line each:

* **The recorder captures the page.** Not the landmark around the click. That
  one defect was underneath most of the output problems -- 30-50% of events on
  real sites recorded no observed change at all.
* **There is an oracle.** `expectations.py` guesses what should have happened
  and one screen asks the tester to confirm. Without it the tool could only
  restate what the application DID, which is why it could not write a test that
  fails on the build it recorded.
* **One author replaced five stages.** `draft.py`, `bind.py`, `split.py`,
  `_second_chance` and `bugmode.py` are gone, along with the critic, the repair
  loop and the step library.
* **Five validators, from fourteen.** The rule is not deterministic-vs-agentic;
  it is *can this check ever be wrong*.

### And the follow-up of 2026-08-29

[docs/COMPLAINT.md](docs/COMPLAINT.md) is a product review after two real
sessions, and its §1 names one root cause: **no model in this pipeline had ever
seen a `.feature` file.** What was built in response, one line each:

* **The author writes the file.** Body plus annotations; `featurefile.py` reads
  it back with the same parser the gate uses; a format slip falls back and costs
  no revision round. A `style:` selects which worked `.feature` it is shown.
* **A claim says what it claims.** `contains` / `first_of` / `count` / `absent`,
  re-evaluated against the stored response, with cannot-evaluate as a third
  outcome. `ToolSpec.view` splits what is stored from what is sent.
* **The judge asks two more questions**, both about things every validator
  passes: does the sentence claim more than its literal shows, and is the
  refusal true.
* **A refused claim reaches the author.** It reached nobody, so the gate went
  green on a document with no verdicts in it.
* **The oracle is reachable** -- a pending list, a banner, and a router.
* **Redaction has a level**, chosen in the recorder and carried on the
  recording, with the origin gate refusing to send an unredacted one to a
  training-eligible endpoint.
* **Four live defects fixed**: `BugDetail` raised on every construction; the
  author's budget was 8 rather than 24 on every run; the default model was one
  no longer served; the SDK's AFC warning.

**Not done, and next: MCP.** `ToolRunner.call` is the seam -- a live agent's
retrievals must be persisted and hashed there or they never reach
`trace.toolCalls`, which is what `evidence_retrieved` resolves against.

**Also not done, deliberately: the eval instrument.** Nothing here writes a
LEDGER row, and `evals/RUBRIC.md` carries a note saying its validator list and
layer table name deleted stages rather than being rewritten to match.

Phases 1-5 are closed. The phase history and the earlier architecture are in
[docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

**What was open before the rebuild is [STATUS.md](STATUS.md)**, whose Part 1 is
archived: every defect in it named a stage that no longer exists. What is open
NOW is [docs/COMPLAINT.md](docs/COMPLAINT.md). The phase history, the A0/A1/A2 ablation tables, the measured
experiments (including the ones that failed and were reverted), and the
before-and-after Gherkin are in
[docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

Still not built, both deliberately: SS18 milestone 21 (multi-tab capture --
no spec section behind it) and milestone 22 (the eval harness and golden set --
deferred on SS17.1's argument that a golden set built after watching the
pipeline fail on real recordings beats one written against imagined failure
modes). Keep every recording; they are that set.

**Read grounding rate together with yield**, and `Executes` together with
`Rechecked`. A rate alone is vacuously 100% when a configuration abstains, which
is exactly what a run full of `whyNot` looks like in a metrics table. The trap
has now appeared in six columns -- `Converged` was the last, measuring how much
of what the critic said the loop was ALLOWED to act on -- so assume it is in the
next one too.

**And read none of them as evidence the output is good.** Nine of ten runs
reported grounding 1.0 and six reported validator pass 1.0 while the judge called
the output bad, held-out 0 good / 0 needs-work / 3 bad. `evals/LEDGER.md` is the
only number that answers *did this help*.

**The trap is now in its seventh column, and it is the post-rebuild gate
itself.** All five validators pass on all nine runs on disk, and
`prove_grounding.py` reports 100%, while the judge raised three `fail`s on the
one real commercial session. Five checks that have never produced a non-pass
are the fourteen in a smaller costume: keep them, because they cost nothing and
cannot be wrong, and do not render the count as a trust signal -- it can only
ever say green. **The badge is gone as of 2026-08-29**; what is shown is the
numbers that can move (retrievals, rejected claims, judge findings). It lives in
`components/StatusLine.tsx` now -- `TrustStrip`, `JobBanner` and `ConfirmBanner`
were three stacked full-width bars carrying one sentence each, which is 175px of
a 900px laptop viewport spent before the first step.

**The judge's findings reach the reviewer, and until the interface rebuild they
reached nobody.** `judge.json` has been written on every run since the judge
landed; nothing served it and nothing rendered it, so the only thing on screen
was an unclickable red badge reading *"3 a QA lead would send back"*.
`GET /api/runs/{rec}/{run}/judge` serves the file and `StepDetail` renders each
finding -- `what` and `fix` -- on the step its `stepId` names. Absent is not an
error: A0 has no judgement by construction, and neither does any run made before
the judge existed.

**And the LEDGER row that would answer *did the rebuild work* cannot be
produced from the recordings it names.** Its three held-out sessions were
captured through the keyhole recorder, so the capture defect is inside the JSON;
re-running them measures the new author against old broken evidence. **Moving
that row requires re-recording those three sessions**, which nothing in
`docs/REBUILD_PLAN.md` says. Until then the rebuild is built and green and
unproven, and no metric in this section changes that.
