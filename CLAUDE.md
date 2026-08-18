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
bash scripts/check.sh          # drift + ruff + pytest + vitest. Run before finishing.
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

**The recorder is black-box.** It reads the live accessibility tree and needs no
access to the target app's source. `data-testid` is used when present, but the
role+name fallback is the normal case. Do not add anything that assumes
cooperation from the app under test.

## Layout

```
schema/          JSON Schema -> Pydantic (server) + TS types + Ajv validators (extension)
extension/       Chrome MV3 recorder. content script + MAIN-world patch + worker + export page
fixtures/        demo app, built to trigger every hard capture path on demand
server/
  evidence/      store.py = the recording, indexed. tools.py = the 12 tools + ToolRunner
  pipeline/      segment.py (code) -> name.py (agentic) -> validators/ (code) -> run.py
  renderers/     gherkin.py
  ablation/      A0/A1/A2 and the metrics table
  llm/           ModelClient seam: gemini, cassette, chain, scripted
tests/           pytest; tests/e2e/ is Playwright
```

Stage order is deliberate: deterministic where possible, agentic where
necessary. Segmentation and validation are code so the same recording always
produces the same step count. Do not "improve" the segmenter by adding a model.

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
Config   Assert   Grounded    Yield   Fabric.   Calls/step   Spread
A0            2        0.0      0.0         2          0.0      0.0
A1            2        1.0   0.2222         0        0.444    0.495
A2            2        1.0   0.2222         0        0.444    0.495
```

A0 fabricated both citations; A1/A2 grounded both. A1 and A2 are identical
because the critic and repair loop are Phase 3 — the harness says so rather than
implying a difference it did not measure.

Not built: decomposition into N test cases, ranked multi-candidate assertions,
review UI, step library, Excel/Jira renderers (Phase 2); critic + repair loop,
coverage suggestions, bug mode, eval harness (Phase 3). `server/api/` and
`server/library/` are empty placeholders for those.

**Read grounding rate together with yield.** Rate alone is vacuously 100% when a
configuration abstains, which is exactly what a well-behaved model does with no
tools — it makes A0 look identical to A2.
