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

## Things that bit us, so you do not repeat them

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

Phase 1 (§18 milestones 1–10) is complete and verified against a real model.
Latest ablation over both fixtures:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Calls/step   Spread
A0            3        0.0      0.0         3     0.7525          0.0      0.0
A1            4        1.0   0.4444         0        1.0        1.556    1.083
A2            4        1.0   0.4444         0        1.0        1.556    1.083
```

A0 fabricated both citations; A1/A2 grounded both. A1 and A2 are identical
because the critic and repair loop are Phase 3 — the harness says so rather than
implying a difference it did not measure.

Phase 2 has started. Composition (`compose.py`) landed first because the
`.feature` file is what the tool gets judged by and it did not read as a test
case: the Feature and Scenario were both the objective string, every step was
`When`, and `!!` was glued to sentences a step definition has to match. That is
fixed, verified against `gemini-3.1-flash-lite` on both fixtures.

Still not built: splitting one recording into N test cases, pruning
exploratory/abandoned segments, step library (Phase 2); critic + repair loop,
coverage suggestions, bug mode, eval harness (Phase 3). `server/library/` is an
empty placeholder for the first of those.

SS9.5's ranked assertion stage has landed. Both fixtures now carry two grounded
expected results where they carried one, and the ranking machinery is in place
for annotations and narration -- but neither fixture contains any, so every
assertion is still `inferred`. That is the honest limit of the current output:
with no annotation, no narration and a vague objective, nothing tells the agent
which of the changes on screen is the one under test, and it sometimes picks a
true but incidental one. Wiring the recorder's annotation UI and narration
(milestone 16) is what moves those rows up the ranking.

**Read grounding rate together with yield.** Rate alone is vacuously 100% when a
configuration abstains, which is exactly what a well-behaved model does with no
tools — it makes A0 look identical to A2.
