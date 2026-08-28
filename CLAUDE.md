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
path that writes a raw value to disk and redacts later. `no_placeholder_leak` is
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

**The `.feature` body is prose, and nothing else.** No comments, no ids, no
review markers, no fidelity flags. It is the artifact the tool gets judged by,
and a traceability line under every step made it unreadable. All of that lives
in the `.trace.md` sidecar (`server/renderers/trace_md.py`); the machine-readable
form is in `ir.json` and `trace.json`, which is what the validators actually
read. Putting anything back in the body will trip `gherkin_style`.

**The author chooses the shape; `narrative.py` lays out what it chose.**
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
  config/        ProjectConfig: voice, tags, sidecar, parameter rendering
  evidence/      store.py = the recording, indexed. tools.py = the tools +
                 ToolRunner. citation.py = which retrieval licenses a claim
  pipeline/      segment.py (code, hints only) -> digest.py (code, the session
                 index) -> expectations.py (agentic, one call: what SHOULD have
                 happened) -> author.py (agentic, one conversation: the whole
                 document, cited) -> narrative.py (code) -> validators/ (code,
                 five checks) -> judge.py (agentic: would a QA lead sign it)
                 -> coverage.py -> run.py
                 investigate.py = the shared decide-retrieve-observe loop
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
docs/            RECORDING.md (for the tester, no terminal), HOWTO.md (for
                 whoever runs it: every feature and its command), DESIGN_NOTES.md
                 (why every rule exists), archive/

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

*The module is gone; `search_step_library` is still registered in
`evidence/tools.py` and still reachable.* It degrades to "no library
configured" rather than crashing, so nothing has failed -- but `coverage.py`
passes no `tool_names`, which is the one `investigate()` caller that does not
constrain its set, so the coverage stage is handed all twelve tools including
that one. Delete the tool with the module, and give coverage its set. Six tools
are currently offered to no stage at all (`get_console`, `get_events`,
`get_neighbouring_segments`, `get_objective`, `query_element`,
`search_step_library`); more tools measurably means worse tool choice, which is
the whole reason `tool_names` exists.

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

**A mandatory tool call is not investigation.** `ROUTINE_TOOLS` is excluded from
`_calls_per_step`; `toolCallsTotal` still counts them.

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

Phases 1-5 are closed. The phase history and the earlier architecture are in
[docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

**What was open before the rebuild is [STATUS.md](STATUS.md)**, and it is the
only file that tracks it. The phase history, the A0/A1/A2 ablation tables, the measured
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
cannot be wrong, and **stop rendering "5 checks passed" as a trust signal** --
it can only ever say green.

**And the LEDGER row that would answer *did the rebuild work* cannot be
produced from the recordings it names.** Its three held-out sessions were
captured through the keyhole recorder, so the capture defect is inside the JSON;
re-running them measures the new author against old broken evidence. **Moving
that row requires re-recording those three sessions**, which nothing in
`docs/REBUILD_PLAN.md` says. Until then the rebuild is built and green and
unproven, and no metric in this section changes that.
