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

# Replay needs the demo app running (`pnpm demo`) and the test's parameters:
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json --replay     --replay-param user_email_1=tester@example.com --replay-param password=hunter2
```

Windows paths: the venv binary is `.venv/Scripts/python.exe`. Bash and
PowerShell are both available; Bash heredocs mangle backslash escapes in this
environment, so use the Write/Edit tools for files containing regexes.

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

**Keywords are derived, never chosen per step.** Given/When/Then is a property
of a scenario. The model supplies a step's *role* (`setup`/`test_step`/
`teardown`); `narrative.py` turns roles into keywords, collapses runs into
`And`, and places assertions. Asking a model for the keyword while showing it
one segment is how the output came to be seven `When`s in a row.

**The recorder is black-box.** It reads the live accessibility tree and needs no
access to the target app's source. `data-testid` is used when present, but the
role+name fallback is the normal case. Do not add anything that assumes
cooperation from the app under test.

## Layout

```
schema/          JSON Schema -> Pydantic (server) + TS types + Ajv validators (extension)
extension/       Chrome MV3 recorder. content script + MAIN-world patch + worker + export page
fixtures/        demo app, built to trigger every hard capture path on demand
config/          allowed_origins.yaml (the pre-send gate) + project.yaml (house style)
server/
  api/           app.py = the endpoints, jobs.py = the JobRunner seam,
                 review.py = every human edit, and the record of it
  config/        ProjectConfig: voice, tags, sidecar, parameter rendering
  evidence/      store.py = the recording, indexed. tools.py = the 12 tools + ToolRunner
  pipeline/      segment.py (code) -> name.py -> assertions.py -> compose.py
                 (agentic) -> narrative.py (code) -> validators/ (code) -> run.py
                 investigate.py = the shared decide-retrieve-observe loop
  renderers/     gherkin.py + trace_md.py (sidecar) + xlsx.py + jira.py,
                 all behind base.py's Exporter seam
  ablation/      A0/A1/A2 and the metrics table
  llm/           ModelClient seam: gemini, cassette, chain, scripted
  library/       SS12's approved phrasing, on rapidfuzz + one SQLite file
  runners/       does the generated test case actually run? base.py + playwright.py
  importers/     bring a Chrome DevTools Recorder export in
scripts/         check.sh, prove_grounding.py, effort_difficulty.py, replay.mjs
docs/            RECORDING.md -- for the tester, no terminal
tests/           pytest; tests/e2e/ is Playwright
```

Stage order is deliberate: deterministic where possible, agentic where
necessary. Segmentation and validation are code so the same recording always
produces the same step count. Do not "improve" the segmenter by adding a model.

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

**The Jira exporter builds an issue and does not send it.** Posting needs a
site, a project key and an API token. A run that silently required credentials
would be a run most people cannot make, so the payload goes to disk where it is
inspectable and testable with no account.

**Naming writes the step; the assert stage writes the expected result.** They
were one prompt in Phase 1 and the output showed it -- roughly one `Then` per
scenario. Splitting them lets the assert stage apply SS9.5's ranking
(annotated > narrated > objective > inferred), which is the ordering that
decides whether an assertion is about the thing under test or about one of the
other forty things that changed. Do not move assertions back into naming.

**Noise suppression is code, not a prompt line.** An assertion about a
timestamp or a uuid passes `evidence_retrieved` perfectly and still breaks the
moment somebody runs the test. `NOISE` in `assertions.py` drops them and records
why, so a suppressed candidate is visible rather than silently absent.

**`Given` belongs to the opening block only.** Composition can legitimately call
a later step `setup` -- going to the checkout page is setup for what follows --
but rendering that as `Given` after a `Then` produces an order no one writes and
reads as the scenario restarting. `narrative._lay_out` demotes it to `When`;
`gherkin_style` catches a regression.

**Naming sees one segment; composition sees the whole flow.** That split is the
point. Anything that needs every step in view — the feature name, the scenario
name, tags, step roles, folding two segments into one intent — belongs in
`compose.py`, and asking naming for it produces exactly the output Phase 1 had.
Composition never touches assertions, so it cannot move the grounding rate; a
model failure there degrades to a deterministic fallback rather than costing the
run.

**Merging happens once, in `_assemble`.** `ir.json` and the rendered feature
must show the same steps. `apply_merges` folds the groups composition asked for;
`merge_repeats` is the net for an exact repeat it missed. A merged sentence may
not drop a redaction placeholder — those are the test's parameters (§7.2), and
the guard is in `narrative._keeps_parameters`.

**Splitting is composition's too, and evidence places the assertions.**
`segment.py` deliberately does not end a step on a 4xx -- a rejected submit
usually means a typo being fixed, still one attempt. When the rejection is what
the test is ABOUT, that rule puts two attempts in one step and the result
contradicts itself: *"submits with manager approval / Then the order requires
manager approval"*, every literal true, the test case wrong. Only replay caught
it. Do not put a model in the segmenter; composition has the objective and can
`split`. `apply_splits` sends each assertion to the half its `evidence.eventId`
came from, so nothing guesses. A split step is re-asserted, because it is not
the step the assert stage was asked about.

**A scenario break is deterministic, not a suggestion.** SS6.7 says it overrides
decomposition. Composition answered differently on two consecutive runs of the
same recording, once putting the tester's own boundary inside a single case.
Where the tester pressed the button, `_split_on_declared_breaks` cuts and no
model is consulted.

**`server/runners/` is to correctness what `renderers/` is to readability.** A
new one is a new file reading a finished `IRDocument`, never a pipeline change.
It does not execute the `.feature` and cannot: no Gherkin runner in any language
binds a step to anything but a hand-written step definition. Constraining the
model to a closed step vocabulary would buy executability by giving up the
readable prose that is the product, so replay drives the IR and the recording
directly. The prose is for humans; `eventIds` and `selectorHints` are what runs.

**The step library recommends; it never substitutes.** `Match.reuse` is advice
to the naming stage. "adds a widget to the cart" scores 95 against the approved
"adds a Blue Widget to the cart", and the widget may not have been blue -- only
something reading the evidence can tell. `libraryRef` is set from an EXACT
match, or `library_verbatim` could not fail. A step enters the library on human
approval only (SS12.2), which is what makes it a record of accepted work rather
than an average of generated work.

## Things that bit us, so you do not repeat them

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
`server/util/env.py`. Nothing before the naming stage needs it.

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

## Status

Phase 1 and most of Phase 2 are done and verified against `gemini-3.1-flash-lite`.
Four fixtures, with replay against the demo app:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Spread   Executes   Rechecked    Held
A0           10        0.0      0.0        10     0.7628      0.0        0.6           3     1.0
A1           11        1.0   0.6111         0      0.975    0.584        0.6           6     1.0
A2           11        1.0   0.6111         0      0.975    0.584        0.6           6     1.0
```

A1 and A2 are still identical because the critic and repair loop are Phase 3.
`Executes` is flat across all three arms because `hardpaths` defeats the replay
harness, not the test case -- read `Rechecked` beside it, which is where the
comparison actually lives.

Fixtures: `checkout`, `hardpaths`, `annotated` (an element the tester marked,
plus an intent note), `twoflows` (two test cases separated by a scenario break),
`wander` (a wrong turn, pruned). The last three exist because a fixture that
does not contain the thing cannot demonstrate it -- SS9.5's upper tiers, SS9.3's
decomposition and its pruning each needed one built for them.

On `wander`, twelve validators pass and none skip.

Built since the last honest version of this section: the assertion annotation
and its element picker, verified provenance, the step library, replay,
decomposition, Qase/Xray/TestRail, the DevTools import, and the effort chart.
`library_verbatim`, `selector_resolvable`, `provenance_supported` and
`no_pruned_assertion` all run for the first time.

**Still not built:** narration (no audio is captured at all -- not "captured
but unused"), and all of Phase 3 (critic, repair loop, coverage suggestions, bug
mode).

**Read grounding rate together with yield**, and `Executes` together with
`Rechecked`. Rate alone is vacuously 100% when a configuration abstains, which
is exactly what a well-behaved model does with no tools -- it makes A0 look
identical to A2. The same trap has now appeared three times in three different
columns; assume it is in the next one too.
