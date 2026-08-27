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
.venv/Scripts/python -m server.cli import <recorder.json>  # Chrome DevTools Recorder

# Narration (SS6.6). Audio is transcribed locally; a transcript can also be
# supplied from anywhere, which is how an imported recording reaches `narrated`.
.venv/Scripts/python -m server.cli transcribe <recording.json> --in-place
.venv/Scripts/python -m server.cli run <recording.json> --narration notes.vtt --narration-offset 0
pnpm run bootstrap --with-transcription    # faster-whisper; the run says so if it is absent
powershell -File scripts/make_narration_wav.ps1   # the committed fixture audio, once

# Replay needs the demo app running (`pnpm demo`) and the test's parameters:
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json --replay     --replay-param user_email_1=tester@example.com --replay-param password=hunter2
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
scripts/         setup.sh + start.sh (one command each, _python.sh shared),
                 check.sh, prove_grounding.py, effort_difficulty.py, replay.mjs,
                 snapshot_features.py (before/after), compare_features.py (A0/A1/A2)
docs/            RECORDING.md (for the tester, no terminal), DESIGN_NOTES.md
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

**Draft first, then bind. Never the other way round.** `draft.py` writes the
whole document -- steps, keywords, scenario names, and the SENTENCE of every
expected result -- with no obligation to have retrieved anything. `bind.py` then
proves each claim or **deletes** it. An author that may only claim what it has
already retrieved writes about whatever was easy to retrieve.

**One author sees everything.** Feature name, scenario names, tags, roles,
keywords, step boundaries, which outcome is worth checking -- all of it is
`draft.py`. It was three stages once and read like three people who never met.

**It cannot tell a step from a step that swallowed something, and nothing can.**
The counter-measure is in the drafting prompt (bad and good shape side by side);
the check is `wander` producing an omission `no_pruned_assertion` reads.

**Merging and splitting are the drafter's.** `merge_repeats` is the net against
two adjacent steps with identical sentences; a merged sentence may not drop a
redaction placeholder (`narrative._keeps_parameters`). `segment.py` deliberately
does not end a step on a 4xx.

**A scenario break is deterministic, not a suggestion.** Where the tester pressed
the button, `run._split_on_declared_breaks` cuts and no model is consulted. It
splits and never joins, and only where the break opens a STEP. A `scenario_break`
carries **no `eventId`** -- `segment.break_openers` resolves the timestamp
forward, and is the one shared implementation. `digest.py` must print the break
into the index, or the one author that decides scenario boundaries is never told.

**A third thing splits a scenario, and only when size says to ask.** `split.py`,
between drafter and `bind.py`. Trigger is deterministic and disjunctive: more
than `MAX_BEATS` beats **or** more than `SPLIT_EVENT_FLOOR = 12` events, never
under two steps. Gated on `tools_enabled` so A0 makes no retrieval; its
investigation carries a `segment_id` and **no** `step_id`.

**The answer is taken whole or discarded whole** (`accept`): an ordered
regrouping of existing step ids, nothing invented, reordered, dropped, merged or
re-worded. Four refusals: not an ordered regrouping, an empty group, a cut
between two steps whose normalised text is identical, or one group (a complete
answer meaning "this is one test case"). **The trigger is deterministic; the
ANSWER is not** -- the same recording has returned one group and two. A drafting
prompt change perturbs this stage most.

**The critic reports; it never edits.** `repair.py` decides which stage re-runs,
and that stage retrieves its own evidence. The critic may not touch a step named
from a tester's intent note or one carrying `libraryRef` -- enforced twice, in
`critic._collect` and `repair.targets`.

**Which stage repairs a finding is a table, not a judgement.** `VALIDATOR_REPAIR`
and `CRITIC_REPAIR` in `repair.py`. Two rows are deliberately empty:
`event_coverage` (a model cannot fix a dropped event) and `no_placeholder_leak`
(a repair that produced a clean sentence would hide a redaction hole). Nothing
reaching those rows is dropped -- it becomes `criticNotes` and a `Warning`.

**Repair may change a step's text and its assertions. Never its `eventIds` or
its `step_id`.** That is why `rewrite_steps` walks the drafted steps instead of
re-running the drafting stage with a filter. `split.py` inherits the guarantee.

### What may be claimed

**The drafter never supplies a `toolCallId`.** It names a literal it says it
saw; `bind._resolve_call` searches the retrievals actually made. A fabricated
citation is not something the model can express. `find_text` is excluded as
evidence of its own query.

**An expected result is about what CHANGED.** `bind._candidates` offers only
what the event added or altered, plus a transient node that was not there before.

**The tester's own input is not evidence of an outcome.** `bind._own_input`
refuses a literal that is the name or value of the control operated at that
event. Two tiers: `_Candidate.conclusive` DECLINES to the agent, `_own_input`
REFUSES the agent's own answer.

**Every value the claim QUOTES and every NUMBER in it must appear in the
evidence** (`bind._unwitnessed`). Not a coverage floor on the claim -- prose
framing asserts nothing and is untouched. Checked in the deterministic pass and
again on the agent's answer.

**A claim that the interface APPEARED is refused, whatever it quotes**
(`bind._existence_only`): a container noun reaching a visibility verb, and only
when the sentence carries no other checkable content. `run._second_chance`
re-asks when this leaves a scenario with no verdict.

**The deterministic pass declines rather than guesses.** A literal that is one
bare number supports any claim of its shape; `_Candidate.conclusive` sends it to
the agent instead.

**One literal may not be the whole evidence for two different claims**
(`evidence_discriminates`, the fourteenth validator). A **warning**: it can say
two claims cannot both be right about this evidence, not which.

**Noise suppression is code, not a prompt line.** `NOISE` in `bind.py` refuses
timestamps, uuids and SS9.5's ad/analytics strings, and records why.

**A step's text says what the TESTER did; an expected result says what the
APPLICATION did.** `mutation_claimed` tells them apart with `RESULT_CLAUSE`.
`DISPLAY_CLAIM` resolves the deadlock between `_unwitnessed` and
`_existence_only`, **and the discriminator is order**: a display verb must come
FIRST. Both cases pinned in `tests/test_validators.py`.

**A bug report's `actual` is bound exactly as tightly as any assertion** -- it is
yielded into `_assertions` in `grounding.py`, never checked by a branch of its
own. When the model cannot cite what it claims, no report is written.

**Bug detection is code, and its threshold is load-bearing.** Medium signals
never reach it at any quantity. It takes the tester's marker, a 5xx, or an
uncaught exception. Four fixtures contain a 4xx that *is* the thing under test.

Both binding rules are pinned in `tests/test_bind.py` against **every** (claim,
literal) pair the pipeline has produced across `runs/`, because the value of the
check is the ratio.

### Gherkin shape

**`Given` belongs to the opening block only.** `narrative._opening_block` ends
the block at the first non-setup step AND at the first setup step carrying an
accepted expected result. `gherkin_style` catches a regression.

**A scenario must end on a `Then`**, checked PER SCENARIO. The same check counts
action/outcome blocks: more than `MAX_BEATS` and the scenario is several test
cases sharing a heading. Both structural findings return `ValidatorStatus.fail`
and have no row in `VALIDATOR_REPAIR` -- that rejection is terminal.

**A scenario left with no verdict gets one second chance.** `run._second_chance`
re-asks, handing back the REASON binding failed. It asks in the "nothing was
proposed" case too; `repropose_expectations` may still answer with an empty list.

**`Step.keyword` is derived, and `sync_keywords` keeps it honest.** Both
`ir.json` and the feature file get it from `build_narrative`.

### Seams

**A new output format is a new file in `server/renderers/`, never a pipeline
change.** Every format implements `base.Exporter` and reads a finished
`IRDocument`. Gherkin and its sidecar are always written; xlsx and jira opt in.

**`server/runners/` is to correctness what `renderers/` is to readability.** It
drives the IR and the recording, not the `.feature` -- no Gherkin runner binds a
step to anything but a hand-written step definition.

**The Jira EXPORT builds an issue and does not send it; `jira-push` sends it.**
Credentials come from the environment, never from committed `project.yaml`.

**Every review edit goes through `server/api/review.py`** -- SS13.5's record is
the project's only source of difficulty labels. A reviewer can reject a claim or
delete a step, but never edit `toolCallId` or `literal`.

**The step library recommends; it never substitutes.** `Match.reuse` is advice.
`libraryRef` is set from an EXACT match. A step enters the library on human
approval only.

**Coverage suggestions are quarantined three times over**: their own IR block, an
UNVERIFIED heading in every renderer, and `suggestions_quarantined` at the gate.
Gated on `suggestions_enabled`, not on `critic_enabled`.

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

**Worked examples outweigh rules, and will contradict them silently.** Examples
are rendered in the project's voice; `with_subject` is the deterministic net.

**A mandatory tool call is not investigation.** `ROUTINE_TOOLS` is excluded from
`_calls_per_step`; `toolCallsTotal` still counts them.

**Grounding is provenance, not correctness, and `Executes` alone is vacuous.**
Read `Executes` with `Rechecked`, and grounding rate with `Yield`.

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

`tests/test_bind.py` covers the deterministic binding pass, which had no tests
of its own while `name.py`, `assertions.py` and `compose.py` each had a module.
That is where the half-proved-claim defect lived. `draft.py` and `digest.py`
are still only covered end to end through `test_pipeline.py`.


## Status

Phases 1-5 are closed. The generator was rebuilt in Phase 4 (`digest.py` ->
`draft.py` -> `bind.py` replaced `name.py`, `assertions.py` and `compose.py`),
and Phase 5 closed the four defects that rebuild exposed.

**What is open right now is [STATUS.md](STATUS.md)**, and it is the only file
that tracks it. The phase history, the A0/A1/A2 ablation tables, the measured
experiments (including the ones that failed and were reverted), and the
before-and-after Gherkin are in
[docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md).

Still not built, both deliberately: SS18 milestone 21 (multi-tab capture --
no spec section behind it) and milestone 22 (the eval harness and golden set --
deferred on SS17.1's argument that a golden set built after watching the
pipeline fail on real recordings beats one written against imagined failure
modes). Keep every recording; they are that set.

**Read grounding rate together with yield**, `Executes` together with
`Rechecked`, and `Converged` together with `Findings`. A rate alone is vacuously
100% when a configuration abstains. The trap has appeared in five columns;
assume it is in the next one too.
