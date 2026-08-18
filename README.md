# AITC-REM

**Recorded browser session → structured, formal test case.**

Every claim the system makes is licensed by evidence it went and retrieved.
See [SPEC.md](SPEC.md) for the design; this file is how to run it.

Phase 1 (the provable spine) is implemented: recorder, evidence store,
deterministic segmentation, agentic naming, the validation gate, the Gherkin
renderer and the ablation harness.

---

## Setup

```bash
pnpm install
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # .venv/bin/python on macOS/Linux
```

Optional, and only needed once you want to call a real model:

```bash
.venv/Scripts/python -m pip install -e ".[models]"
echo "GEMINI_API_KEY=..." > .env    # aistudio.google.com/apikey
```

Everything up to and including the validation gate runs with no API key at all.

## Record something

```bash
pnpm demo                        # the fixture app on http://localhost:5173
pnpm --filter @aitc-rem/extension build
```

Then load `extension/dist` at `chrome://extensions` (Developer mode → *Load
unpacked*), open the app, click the extension, state what you are checking, and
press **Start recording**. **Stop & export** writes `recording.json` and the
screenshots to your Downloads folder, after showing you exactly what will leave
the browser.

The recorder needs no access to the application's source. It reads the live
accessibility tree, so it works the same against a site you do not own — which
is the normal case.

## Run the pipeline

```bash
.venv/Scripts/python -m server.cli run recordings/<id>/recording.json
.venv/Scripts/python -m server.cli run <recording.json> --config A0    # no tools
.venv/Scripts/python -m server.cli run <recording.json> --offline      # cassettes only
```

Artifacts land in `runs/<recordingId>/<runId>/`: `segments.json`, `ir.json`,
`trace.json`, one `.feature` file, and `tools/tc_*.json` — one file per
retrieval, hashed.

## Prove the grounding claim

```bash
.venv/Scripts/python scripts/prove_grounding.py
```

Walks every assertion in every run, resolves its `toolCallId` in the trace,
re-hashes the stored response and confirms the literal is in it. Prints a
pass/fail number rather than a diagram (§3.2).

## The ablation

```bash
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
```

Runs A0 (no tools) / A1 (tools) / A2 (full) over the same recordings with one
provider and one model pinned, and prints the §3.5 table. Fallback routing is
disabled here on purpose: it is fine in daily use and fatal to a comparison,
which would otherwise measure provider variance instead of architecture.

Latest result over both fixture recordings, on `gemini-3.1-flash-lite`:

```
Config   Assert   Grounded    Yield   Fabric.   Calls/step   Spread
A0            2        0.0      0.0         2          0.0      0.0
A1            2        1.0   0.2222         0        0.444    0.495
A2            2        1.0   0.2222         0        0.444    0.495
```

With no tools the model invented both citations, and the gate caught both. With
tools it grounded both. A1 and A2 are identical because the critic and repair
loop are Phase 3 — the harness reports that rather than implying a difference it
did not measure.

Read grounding **rate** together with **yield**. Rate alone is vacuously 100%
when a configuration abstains, which is what a well-behaved model does with no
tools — it would make A0 look equivalent to A2.

## Checks

```bash
bash scripts/check.sh            # schema drift, ruff, pytest, vitest
pnpm e2e                         # Playwright drives the real extension (headed)
```

`scripts/check.sh` is the load-bearing one. The schema is a single source of
truth generating into two languages, so drift means the extension writes a field
the server silently drops — the check regenerates and diffs on every run.

`pnpm e2e` rebuilds the extension, drives it against the fixture app in a real
browser, and rewrites `tests/fixtures/*.recording.json`. The server-side tests
consume those, so the whole pipeline is exercised against a genuine recording
rather than a hand-written one.

## A note on the free tier

Two separate constraints, both real.

**Data.** Google uses content submitted on the unpaid Gemini tier to improve its
products, and human reviewers may read it. So free-tier runs are for demo and
public applications only. `config/allowed_origins.yaml` makes that mechanical:
the pipeline refuses to send a recording whose origins are not listed, and
`--allow-any-origin` is the escape hatch for a paid endpoint carrying a
no-training term. Moving a real application onto this is a billing change, not a
code change.

**Quota.** The binding limit is requests, not tokens, and it moves. Checked in
August 2026: `gemini-2.5-flash` and `2.5-flash-lite` are no longer served to new
keys at all, and the current flagship `gemini-3.7-flash` allows five requests a
minute and *twenty a day* on the free tier — one recording exhausts that before
it finishes. The default is therefore `gemini-3.1-flash-lite`, which has a
workable allowance and does reliable multi-turn tool calling. Pass `--model` to
override and `--rpm` to change the pacing.

The cassette cache (`runs/_cassettes/`) records every real model response and
replays it, so re-running after a change to a validator, the renderer or the
segmenter costs nothing. That is what keeps a day of prompt iteration inside a
free-tier daily request limit.

## Layout

```
schema/      JSON Schema -- the single source of truth, generates both languages
extension/   Chrome MV3 recorder (TypeScript)
fixtures/    demo app, built to trigger every hard capture path on demand
server/
  evidence/  the recording as a queryable store, plus the 12 logged tools
  pipeline/  segment -> name -> validate
  renderers/ gherkin
  ablation/  A0/A1/A2 and the metrics table
  llm/       ModelClient seam: gemini, cassettes, fallback, budget guard
tests/       pytest + the Playwright end-to-end recorder suite
```
