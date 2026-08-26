# AITC-REM

**Recorded browser session → structured, formal test case.**

Every claim the system makes is licensed by evidence it went and retrieved.

| If you are | Read |
|---|---|
| a QA tester recording a session | **[docs/RECORDING.md](docs/RECORDING.md)** -- no terminal needed |
| running the pipeline yourself | this file |
| recording a real public site | [TESTING.md](TESTING.md) |
| changing the code | [CLAUDE.md](CLAUDE.md), then [SPEC.md](SPEC.md) |
| wondering what is broken or what is next | [STATUS.md](STATUS.md) |
| asking whether the output actually got better | [docs/GHERKIN_BEFORE_AFTER.md](docs/GHERKIN_BEFORE_AFTER.md) -- the same recordings, before and after |

Phases 1 to 3 are implemented: the recorder, the evidence store, the validation
gate, the Gherkin renderer, the review UI, narration, bug mode and the ablation
harness.

The generator itself was rebuilt in Phase 4, after the output was read against
a real recording rather than against the fixtures. Three agentic stages used to
write the test case between them without any one of them seeing it -- one was
shown a single segment, one a single step, and the third could not touch the
expected results -- and the file read like a document written by three people
who never met, because it was. Now a deterministic **index** summarises the
whole session, one **drafting** call writes the document from it, and a
**binding** stage proves every claim against a real retrieval or deletes it.

The guarantee got stronger in the process, not weaker: the model never supplies
a `toolCallId` at all, so a fabricated citation is not something it can
express. See [CRITIQUE.md](CRITIQUE.md) for the read that prompted the rebuild.

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

## The zero-terminal path

```bash
pnpm --filter @aitc-rem/ui build
.venv/Scripts/python -m server.cli serve
```

Then record as above and press **Send to aitc-rem** on the export page. The
pipeline runs as a background job and the draft opens at
<http://127.0.0.1:8000> for review: accept or reject each expected result, edit
any sentence, merge steps the segmenter split, answer the agent's questions,
and export -- without touching a terminal again (SS13).

The Send button lives on the export page rather than in the popup on purpose.
That page is SS7.3's pre-send screen, so the tester sees exactly what is about
to leave the browser, with redactions applied, *before* it goes.

The right-hand pane is SS13.3's "why this step": what the agent could not
determine, which retrievals it made, and the stored tool response itself --
not a summary of it. Every edit is recorded with its size, which is the
ablation's `steps edited by a human` column and SS3.4's y-axis, collected for
free from normal use (SS13.5).

## Run the pipeline

```bash
.venv/Scripts/python -m server.cli run recordings/<id>/recording.json
.venv/Scripts/python -m server.cli run <recording.json> --config A0    # no tools
.venv/Scripts/python -m server.cli run <recording.json> --offline      # cassettes only
```

Artifacts land in `runs/<recordingId>/<runId>/`: `segments.json`,
`naming.json`, `ir.json`, `trace.json`, one `.feature` file with its
`.trace.md` sidecar, and `tools/tc_*.json` — one file per retrieval, hashed.

Every stage reads a file and writes a file, so a wrong sentence can be blamed
on the stage that produced it without re-running any of the others:

```
segment (code)  -> segments.json    deterministic step boundaries
name (agent)    -> naming.json      one sentence per segment
assert (agent)  -> assertions.json  ranked expected results, evidence-bound
compose (agent) -> ir.json          feature/scenario names, tags, step roles
render          -> .feature + .trace.md
validate (code) -> trace.json       the grounding gate
```

Assertions are ranked by where the intent came from, not by how confident the
model sounds: what the tester **annotated** beats what they **narrated** beats
the stated **objective** beats anything **inferred**. Each step gets up to three
candidates; the top-ranked one is accepted and the rest ride along as proposals
in the sidecar, until the review UI turns them into checkboxes. A literal that
is a timestamp, a uuid, a date or a redaction placeholder is dropped before
anyone sees it — it would pass every grounding check and still break the next
time somebody ran the test.

### What the output looks like

The `.feature` is prose a QA lead could have written by hand:

```gherkin
# aitc-rem - rec_MSYWWF2M9EW5 - 2026-08-18 - evidence: tc_rec_MSYWWF2M9EW5.trace.md

@checkout @approval @needs-review
Feature: Order approval

  Orders above the EUR500 threshold are held for manager approval before they
  can be placed.

  Scenario: An order over EUR500 is held for manager approval
    Given the tester signs in as "<<user_email_1>>" with "<<password>>"
    And the tester adds a "Blue Widget" to the cart
    And the tester navigates to the checkout page
    When the tester places an order for "615" EUR with manager approval
    Then the order confirmation appears
```

The traceability that makes it auditable lives in `tc_*.trace.md` beside it:
which retrieval licenses each expected result, what the agent did not know,
what it went and looked at, and every fidelity flag in plain English. It moved
out of the feature body because a comment under every step made the test case
unreadable, and the test case is what gets judged. Nothing about §3.2 changed —
`evidence_retrieved` still resolves each pointer against `trace.json`.

### Other formats

```bash
.venv/Scripts/python -m server.cli run <recording.json> --export xlsx,jira
```

Or set `exports: [xlsx]` in `config/project.yaml` and every run produces one.

**Excel** (SS11.2) is what the wedge population of SS2.2 actually opens: one
workbook per run, a sheet per test case with the expected result beside the step
that produced it, plus preconditions, parameters (with an empty column to fill
in) and warnings sheets. Coverage suggestions, when they exist, get their own
sheet labelled unverified and never appear as a test row.

**Jira** (SS11.3) builds a plain issue -- no Xray or Zephyr plugin needed, which
is what makes it work for every Jira there is. The steps become an ADF table in
the description, tags become labels, and the issue type is configurable because
teams model tests as `Test`, `Task` or `Story` and none of them is wrong.

It **builds the issue and writes it to disk; it does not post it.** Sending
needs a site, a project key and an API token, and a run that silently required
credentials would be a run most people cannot make. The payload is inspectable
and diffable with no Jira account at all.

### House style

`config/project.yaml` is the one file a QA lead edits. Voice (`the tester`,
`I`, `the user`), tags applied to every case, whether to write the sidecar,
whether redaction placeholders become a `Scenario Outline` with an `Examples`
table or stay quoted inline, the feature filename template, which extra formats
to export, and the Jira issue type and project key. Deleting the
file changes nothing except that you lose the ability to disagree with the
defaults.

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

Latest result over all seven fixture recordings, on `gemini-3.1-flash-lite`:

```
What it claimed
Config   Assert   Grounded    Yield   Fabric.   Valid1st   ValidFin
-------------------------------------------------------------------
    A0       13        0.0      0.0        13     0.8253     0.8253
    A1       21        1.0   0.6176         0     0.9857     0.9857
    A2       21        1.0   0.6176         0     0.9857     0.9857

What it did to get there
Config   Calls/step   Spread   Findings   Converged   Executes   Rechecked    Held
-----------------------------------------------------------------------------------
    A0          0.0      0.0          0         0.0      0.625           6  0.8333
    A1        2.441    0.601          0         0.0     0.7778          13     1.0
    A2        2.559    0.787          3      0.6667     0.7778          13     1.0
```

With no tools the model invented every citation, and the gate caught every one.
With tools it grounded every one. Yield — grounded assertions per step — is what
doubled when the ranked assertion stage (§9.5) replaced naming's single expected
result, and the effort spread widened with it: the agent spends retrievals where
a step actually has an outcome to establish.

A1 and A2 differ from Phase 3 onward, and the columns that separate them are
`Findings` and `Converged` — how much the critic had to say, and how much of it
the bounded repair loop resolved. They are deliberately not expected to differ
much on grounding: both arms propose assertions with the same stage and the same
tools, so the critic was never going to move that number. §3.5 pre-authorises
the null result, and the harness states it whichever way it comes out.

**Read every rate together with its denominator.** Rate alone is vacuously 100%
when a configuration abstains, which is what a well-behaved model does with no
tools — it would make A0 look equivalent to A2. The same trap sits under
`Converged`, which is 100% when the critic found nothing at all. Grounded with
Yield, Executes with Rechecked, Converged with Findings.

The A0 row is the clearest illustration this project has: on `Executes` alone it
is 0.625 against 0.778, which reads as a modest gap. It re-checked **six**
assertions against thirteen, and one in six of those failed where none of the
others did. A configuration that claims less has less to get wrong.

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
  api/       FastAPI: the recorder posts here, jobs run, review happens
  config/    house style: voice, tags, sidecar, parameter rendering
  pipeline/  segment -> name -> assert -> compose -> validate
  renderers/ gherkin + the evidence sidecar, xlsx, jira -- one Exporter seam
  ablation/  A0/A1/A2 and the metrics table
  llm/       ModelClient seam: gemini, cassettes, fallback, budget guard
ui/          TypeScript / React review app -- the human gate (SS13)
tests/       pytest + the Playwright end-to-end recorder suite
```
