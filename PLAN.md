# Phase 3 — Smart

Working plan, kept in the repo so it travels with the code. [SPEC.md](SPEC.md)
is the design and does not change; this is where the build order lives.
[CLAUDE.md](CLAUDE.md) carries the rules you need in order to change things
safely.

Last updated 2026-08-24. Phases 1 and 2 are closed; SS18's milestones 18-20 are
done. The `Landed` sections are the record of what changed and why, and the
Phase 2 half of this file is kept below rather than deleted -- most of what it
records is why something is shaped the way it is.

---

## Milestone 18-20 · the critic, the repair loop, coverage, bug mode — DONE

**The one thing this phase was for.** SS3.5 defines `A1` as "tools available, no
critic, no repair loop" and `A2` as the full pipeline. `PipelineOptions.
for_config` had been setting `critic_enabled=True, repair_enabled=True` for A2
since Phase 1 and nothing read either flag, so the thesis table had two
identical rows and the ablation's own `finding()` said so in prose. That was the
hole; it is closed, and the two arms now differ in `Findings` and `Converged`.

**Almost all of the scaffolding already existed**, which is worth saying because
the phase looked larger than it was. `PipelineStage.critic` and `.coverage` were
in the enum. `RepairAttempt`, `RunConfig.criticEnabled/repairEnabled/
maxRepairAttempts`, `RunMetrics.repairConvergenceRate`, `Step.criticNotes`,
`Warning{source:"critic"}`, `CoverageSuggestion`, `TestCaseKind.bug_report` and
`BugDetail` were all in `schema/` and generated into both languages. Three
renderers already printed coverage suggestions and critic notes;
`narrative._absorb` already merged `criticNotes` across a merge. The extension
already emitted the bug-marker annotation and `docs/RECORDING.md:119` already
promised the tester it "flags the session and the step" -- a promise nothing
server-side kept, the same class of bug as the intent note that went unread
until Milestone 8. Phase 3 was mostly filling declared holes.

**What the plan got right.** The trigger-to-stage mapping being a table rather
than a model decision; the two deliberately empty rows (`event_coverage` is an
assembly bug a model cannot fix and could disguise, `no_placeholder_leak` is a
redaction hole a clean re-roll would hide); coverage gated on its own flag so
the A1/A2 comparison keeps measuring one thing; and the bug threshold set so
that medium signals never reach it, because four fixtures contain a 4xx that is
the thing the test is ABOUT.

**What the plan missed, and it is the interesting part.** Two bugs that only a
real run could surface, both of which had been sitting in the tree:

*`AgentTrace(toolCalls=runner.calls)` does not alias the runner's list.*
Pydantic validates the field and copies it. Every stage that retrieves after the
trace is built is therefore invisible to `evidence_retrieved`, which rejects a
citation that is true, resolvable and correct -- the most confusing failure this
codebase can produce. It surfaced as the bug describer citing `tc_0013` against
a trace holding twelve calls. `_sync_calls` is the fix and the docstring says
why it exists.

*`lift_background` lifted steps into a list nothing rendered.* `_background`
rendered `case.preconditions`; `build_narrative` put the lifted steps in
`narrative.background`. So every recording that produced more than one test case
silently lost its sign-in **from the feature file** while `ir.json` still had
it. Nothing caught it: `event_coverage` reads the IR rather than the rendered
output, and a file missing a step still parses. `twoflows` had been shipping
that way since decomposition landed. Phase 3 only *found* it, by making
`len(ir.testCases) > 1` true for a single-scenario feature when a bug report was
added beside it.

**A third guard the plan did not anticipate.** `merge_repeats` folds adjacent
steps whose text matches exactly, so a repair prompted with "this name is too
vague" can produce a name identical to its neighbour and delete a step --
changing the step count mid-run against SS3.6, and moving `Yield`'s denominator,
which is worse because the metric then *improves*. `narrative.would_collapse`
refuses the rewrite and the finding stays unresolved.

**The metric trap, for the fourth time.** `repairConvergenceRate` is vacuously
1.0 when the critic found nothing, exactly as `groundingRate` is vacuously 1.0
for a configuration that abstains. It ships with `criticFindingsRaised` as its
denominator and both are columns. Separately, `validatorFirstPassRate` is frozen
at attempt 1 and `validatorFinalPassRate` added beside it: letting the first
number absorb the repair loop's improvement would have the loop report itself
working by hiding that it had to work.

**Demonstrated** on `bugged.recording.json`, a real capture through the real
extension, with a real model:

```
## Actual

the export fails with an error indicating an inconsistent order state

> Grounded in `Uncaught Error: Export failed: order state is inconsistent`
> (console, evt_006, retrieved as `tc_0013`).
```

That is the citation that was failing before `_sync_calls`, which is a neat
demonstration of why the gate is worth having.

**And one more metric bug, found only because the table looked wrong.** A1
scored *higher* than A2 on first-attempt pass rate over identical attempt-1
output, which is impossible. Two causes stacked: `first_report` was the same
object as the live report when nothing repaired, so the coverage stage's
in-place edit backdated a later result into the first-attempt number; and
`suggestions_quarantined` skips on attempt 1 (coverage has not run) and passes
at the end, which shifts the denominator between the two measurements and
manufactures a delta the repair loop did not earn. `first_report` is a snapshot
now, and the final rate is measured over the validators that judged the first
draft -- so only a repair can move it.

That is the fourth time a rate has been read without its denominator in this
project, and the second time in this phase.

**Deliberately not built:** SS18's milestones 21 and 22. See the Status section
of [CLAUDE.md](CLAUDE.md) for the reasoning, which is the spec's own.

---

## Already done (Phase 2a)

| Landed | What |
|---|---|
| `pipeline/compose.py` | Agentic document composition: feature title, scenario name, description, tags, per-step role, merge groups |
| `pipeline/narrative.py` | Deterministic layout: roles to Given/When/Then, `And` collapsing, assertion placement |
| `pipeline/investigate.py` | The shared decide-retrieve-observe loop |
| `pipeline/assertions.py` | Ranked assertions with the provenance ladder and noise suppression |
| `renderers/` | Gherkin rewrite, `trace_md.py` sidecar, `xlsx.py`, `jira.py`, all behind `base.Exporter` |
| `server/api/` + `ui/` | Zero terminal: post a recording, run as a job, review in a browser, every edit recorded |
| `config/project.yaml` | House style: voice, tags, sidecar, parameters, exports |

Ablation at the end of that work:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Calls/step   Spread
A0            3        0.0      0.0         3     0.7525          0.0      0.0
A1            4        1.0   0.4444         0        1.0        1.556    1.083
A2            4        1.0   0.4444         0        1.0        1.556    1.083
```

---

## Context

Phase 2's first half landed: composition, ranked assertions, the review UI, Excel
and Jira export. The `.feature` file reads like a test case now, and the ablation
holds at 100% grounding for A1/A2 against A0's three fabrications.

This plan covers what a real-browser run and a close read of the code turned up.
Three things forced a change of course:

**1. The provenance ladder runs on unverified self-report.** `assertions.py:443`
parses whatever string the model wrote into `Provenance` and `PROVENANCE_RANK`
sorts on it. Nothing checks it. A model can write `"provenance": "annotated"` on
a pure guess and outrank every genuinely-supported candidate. For a project whose
whole claim is *a claim is admissible only if it points at a retrieval*, having
the ranking decided by an unchecked assertion about where the claim came from is
the one gap that undercuts the argument.

**2. The top of that ladder is unreachable.** The `assertion` annotation — "click
an element, mark this is what I'm verifying" — is in the schema, has an
`AnnotationTarget` shape waiting for it, and is advertised to the model in the
assert prompt. There is no UI for it anywhere. Every assertion this tool has ever
produced is `inferred`, which is the honest ceiling on output quality: with
nothing but inference, the agent sometimes picks a true but incidental outcome.

**3. Two dead retrieval paths, both the class of bug already in CLAUDE.md.**
`assertions.py:121-123` tells the model to fetch annotations with `get_events`;
`tools.py:140-159` builds that response with no annotations field. And `find_text`
never indexes annotation text or targets, so an annotation-grounded assertion
would pass `evidence_retrieved` and fail `assertion_grounding` — exactly the page-URL
bug already documented under "a gap in the index looks like a validator bug."

Plus a scope addition the schema turns out to have been built for: nothing has
ever executed a generated test case. `SelectorSet.role` already stores
`getByRole('button', { name: 'Submit' })`; `SelectorHint.strategy` is
`testId|role|text|css`, a 1:1 map to Playwright locators; `Evidence.kind` says how
to re-check each literal. Replaying a generated case against the app gives the
ablation the correctness column it lacks — and answers empirically whether A0's
fabricated citations are also *false*.

## Standing principle

*(your call)* — **if a tool does it better, use the tool.** Build only where
building offers materially more. Applied here:

| Job | Tool used | Not built |
|---|---|---|
| Near-duplicate step matching | `rapidfuzz` | a hand-rolled similarity score |
| Running the replay + assertions | `@playwright/test`, its `expect` and JSON reporter | a bespoke runner or assertion layer |
| Gherkin validity | `gherkin-official` (already a dep) | a regex parser |
| TestRail import | `trcli import_gherkin`, official CLI | a TestRail exporter |
| Qase | official `qaseio` client | a hand-written REST client |
| Xray | one documented `curl` against its feature-import endpoint | a client library |
| Transcription (milestone 8) | `faster-whisper` | anything custom |

Two places where building still wins, and why:

- **The replay harness itself** (milestone 5). Playwright's healer repairs
  selector failures with an LLM at runtime. That is the right tool for
  self-healing tests and the wrong one for a measurement harness — nondeterminism
  in the instrument. ~250 lines of deterministic driving, using their runner.
- **The element picker** (milestone 2). No library does this against a page's
  accessibility tree, and the four values it needs already come from
  `roleOf`/`nameOf`/`rawValueOf`/`selectorsFor`. Roughly 80 lines of glue.

## Decisions taken

| Decision | Choice | Why |
|---|---|---|
| Playwright replay scope | Ablation metric only, demo app | *(your call)* — a shipped `.spec.ts` makes live-app flakiness something you support |
| Narration | Annotations this phase, audio next | *(your call)* — the picker is most of the quality win at a fraction of the cost |
| Step library | This phase, on rapidfuzz | *(your call)* — merged with the cross-session memory idea; §12.2 already says a step enters the library on human approval, which *is* that idea |
| Origins | `origin_policy` in config, default `warn` | *(your call)* — the API path already never refuses; this just makes the CLI agree and makes it a setting rather than a flag |
| CI | Delete it | *(your call)* — the cause was one line, but an unwatched workflow is not worth the maintenance. `scripts/check.sh` is the real gate |
| Jira MCP | No | Atlassian's server is markdown-in/markdown-out; open bugs #189 (ignores the documented `adf` format) and #42 (fails on valid ADF). We already build correct ADF. It also does not solve the credential problem |
| Gherkin execution | Replay from the IR, never from the `.feature` | No Gherkin runner in any language executes without hand-written step definitions. The workaround — constrain the model to ~10 fixed step templates — trades away the readable prose that is the product |

## Landed (2026-08-20)

Milestones 1-4 are done. What the numbers did, over three fixtures now that
`annotated.recording.json` exists:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Calls/step   Spread
A0            5        0.0      0.0         5     0.8222          0.0     0.0
A1            9        1.0     0.75         0     0.9667        2.167   0.424
A2            9        1.0     0.75         0     0.9667        2.167   0.424
```

Yield 0.444 -> 0.75 with grounding still at 100%, and A0 still fabricating every
citation it makes. Three validators that had never once run -- `library_verbatim`,
`provenance_supported`, and the annotation half of the ladder -- are live.

The output that motivated all of it, before and after, same recording:

```gherkin
# before
When the tester signs in as "<<user_email_1>>" with "<<password>>"
Then the user is redirected to the catalog page
When the tester navigates to the checkout page
And the tester saves the payment method and submits the order for slow validation
Then the payment method is confirmed as saved

# after
Given the tester signs in as "<<user_email_1>>" with "<<password>>"
And the tester navigates to the checkout page
When the tester submits the order for slow validation
Then the order is being validated with the finance system
```

Things learned along the way, all now pinned by tests:

- **The picker's own click was being recorded as an application action.** Both it
  and the recorder listen on `document` in the capture phase, and the recorder's
  listeners are registered at module load, so `stopPropagation` cannot help.
  Pointing at a banner produced a step that never happened.
- **An intent note names the step that starts NEXT.** Attribution needs every
  segment in view, like network calls; the fixture proves the timing.
- **Worked examples outweigh rules.** Prompt examples written without a subject
  produced steps with no subject, twice over, while the rule above them said to
  include one. `with_subject` is the deterministic net.
- **A mandatory tool call is not investigation.** Search-before-invent lifted
  calls/step 1.56 -> 2.17 and collapsed Spread 1.08 -> 0.16, which reads as an
  agent that stopped adapting. Excluded from the effort metric, still counted as
  cost.
- **An inferred assertion on a setup step is noise.** Checking that signing in
  reached the catalog page, in a test about the EUR500 rule, is true and beside
  the point. Still proposed and still counted; no longer accepted by default.

---

### Milestone 5 also landed: replay

`server/runners/` mirrors `renderers/`. Python builds a job from the IR and the
recording; `scripts/replay.mjs` drives it with the `@playwright/test` already in
the repo; both the job and the result stay on disk. `--replay` on `ablate`,
off by default.

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Spread   Executes   Rechecked    Held
A0            5        0.0      0.0         5     0.8368      0.0     0.3333           2     0.5
A1            9        1.0     0.75         0     0.9697    0.424     0.3333           4    0.75
A2            9        1.0     0.75         0     0.9697    0.424     0.3333           4    0.75
```

**Read `Executes` with `Rechecked`, exactly as `Grounded` is read with `Yield`.**
A test case that asserts nothing cannot have an assertion fail. A0 gets two
assertions re-checked and holds one; A1/A2 get four and hold three. That is the
comparison; the `Executes` column on its own currently reports whether the
replay harness can drive the application, and on `hardpaths` -- iframes, closed
shadow roots, a canvas -- it cannot. Flat at 0.3333 for every configuration
because of that fixture, so it is measuring the harness, not the artifact.

**Replay found a defect nothing else could see.** `step_005` of the checkout
case merged five events including *two separate* "Place order" clicks -- one
without approval, which produced the 409 and the alert, and one with it. The
step reads "submits an order totalling 615 with manager approval" and its
expected result is "Orders over EUR500 require approval", which is the outcome
of the submission *without* approval. `evidence_retrieved` passes, so does
`assertion_grounding`, so does `gherkin_style`. Every literal is true of the
recording. The test case still contradicts itself.

The cause is a deliberate rule in `segment.py`:

> A 4xx or 5xx is deliberately not a boundary: a rejected submit leaves the
> tester on the same screen, still working on the same step.

Right for a typo being corrected, wrong here -- this 409 *is* the behaviour
under test, and only the objective says which case you are in. Segmentation is
intent-blind by design and must stay that way (no model in the segmenter). So
the fix belongs to composition, which already reads the whole flow and the
objective, and which can already *merge*: **it needs to be able to split.**
Folded into milestone 7.

Two harness bugs found and fixed on the way: assertions grounded on an
accessible name were being checked as visible text (the annotated fixture's
literal is `Cart contains 1 items`, its rendered text is `1`), and a mandatory
search-before-invent call was being counted as investigation effort.

---

### Milestone 9 also landed: the effort/difficulty chart

`scripts/effort_difficulty.py`. Joins `trace.metrics.toolCallsPerStep` against
`review.json` edits, computes Spearman and Pearson, writes an SVG and the JSON
behind it. No plotting dependency -- the data is a few dozen points and a
self-contained SVG opens anywhere, diffs in review and drops into a document.

**It refuses to report a correlation it cannot support**, which is most of its
value right now: two points make a perfect line, and a chart that looks like
evidence when it is not is worse than no chart. Current state, said plainly:

```
Steps:            15 from 3 reviewed run(s)
Edited by a human:   1
No correlation reported. Needs 12 steps from 3 reviewed runs with at least two
edited steps; have 15 steps from 3 run(s) with 1 edited.
```

One fix on the way in: 37 of 38 runs had no `review.json` at all, because only
the API wrote one. `cmd_run` now writes an empty review, since "never reviewed"
and "reviewed and nobody changed anything" are different facts and the second is
the untouched half of the correlation -- the more common half. The data
accumulates passively from here, which is what SS3.4 assumed all along.

---

### Milestone 6 also landed: where QA teams actually live

**Qase** is the one built, because it is the only commercial tool with a free
tier that includes API access -- somebody reviewing this can open a workspace
and run it end to end without paying anyone. `server/renderers/qase.py`, one
bulk-create body per run, both `classic` (the action/expected grid the Qase UI
shows) and `gherkin` step types. Built and written to disk like Jira, with the
exact `curl` in the warnings.

**Xray** needed no exporter at all: its feature-file import takes the
`.feature` this project already emits. What it needed was `@TEST_<KEY>`, the tag
that makes a re-import update an existing Test rather than create a second one.
Off unless `xray.test_key` is set. **TestRail** has `trcli parse_gherkin` and
needed nothing. Both commands are in `config/project.yaml` where a QA lead will
find them.

**Chrome DevTools Recorder import** — `server/importers/devtools.py`,
`python -m server.cli import <file.json>`. Chrome emits `aria/Name` selectors,
which is an accessible-name strategy and therefore this project's own primary
key, so the mapping is close to lossless in the direction that matters.

Two things it surfaced, both worth keeping:

- **An imported recording proves the admissibility rule bites.** No network, no
  console, no DOM, so nothing for `find_text` to index and no claim that could
  cite anything. The pipeline produced a clean, readable test case with **zero**
  expected results, and `gherkin_style` said why: *"no Then step: this describes
  what the tester did but never what should be true afterwards, which is a
  transcript rather than a test case."* Exactly right, and better than inventing
  one.
- **Chrome does not redact, and the first import put a plaintext password on
  disk.** SS7.1 says redaction happens before anything is persisted, and this
  path went around it. Now redacted at import, emitting proper parameters --
  best-effort and pattern-based, since there is no DOM to ask whether a field
  was `type=password`, and the command says so.

---

### Milestone 7, part one: composition can split

The defect replay found is fixed, and fixed where it belonged. `segment.py`
still does not end a step on a rejected request -- that rule is right, and a
model in the segmenter is still forbidden. What changed is that composition,
which has the objective and the whole flow, can now undo it.

Composition is shown each step's requests *and whether they were rejected*:

```
step_005  the tester submits an order totalling "615" with manager approval
      (events evt_006..evt_010; evt_008: POST 409 (rejected); evt_010: POST 201 (succeeded))
```

A rejection followed by a success on the same endpoint is two attempts, and it
returns `split`. `narrative.apply_splits` cuts the step; **each expected result
follows its own `evidence.eventId` into the half that produced it**, so nothing
has to guess which claim belongs where.

One ordering consequence, found and fixed: assert runs before compose, so a step
created by a split was never asked about. The successful retry inherited
nothing and `Order confirmed` -- the outcome the test exists to reach -- went
unmentioned. The two halves are now re-asserted, and only when a split happened.

```gherkin
# before                                    # after
When ... with manager approval              When ... which is rejected for requiring manager approval
Then the order requires manager approval    Then the order is rejected because it requires manager approval

                                            When the tester obtains manager approval and submits it again
                                            Then the order is confirmed
```

Replayed: **PASSED, 4/4 assertions held.** The ablation moved with it:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Spread   Executes   Rechecked    Held
A0            6        0.0      0.0         6     0.7902      0.0     0.6667           3     1.0
A1           10        1.0   0.7692         0     0.9444    0.412     0.6667           5     1.0
A2           10        1.0   0.7692         0     0.9444    0.412     0.6667           5     1.0
```

Everything now holds on replay in both arms; what separates them is `Rechecked`
-- A1/A2 make five checkable claims where A0 makes three. Which is the same
lesson as `Grounded` needing `Yield`, arriving a third time.

---

### Milestone 7, part two: one recording, N test cases

`twoflows.recording.json` is a new fixture -- one sitting, two things checked,
with the tester pressing **New scenario** between them. That button has been in
the popup since the beginning and nothing downstream had ever read it.

```gherkin
# tc_..._01                                # tc_..._02
Feature: Order approval                    Feature: Order approval

Scenario: The Blue Widget is added to      Background:
          the cart                           Given the tester signs in as "<<user_email_1>>" ...
  Given the tester signs in as ...           And the tester adds a "Blue Widget" to the cart
  When the tester adds a "Blue Widget" ...
  Then the Blue Widget is added to the     Scenario: The order requires manager approval
       cart                                   When the tester tries to place an order totalling "900"
                                              Then the order requires manager approval
```

The second case carries the first's setup as **preconditions**, which the
renderer emits as a `Background`, so it can be run on its own. Preconditions
rather than steps on purpose: they carry no step identity, so `event_coverage`
still accounts for each of the eight events exactly once.

Four things this shook out:

- **A declared scenario break is not the model's to overrule.** SS6.7 says it
  overrides decomposition; composition answered differently on two consecutive
  runs of the same recording, once putting the tester's own boundary inside a
  single case. Now: composition may propose cases, and where the tester declared
  a break the split is deterministic and no model is consulted.
- **The break marked every later segment, not the one it opened.** "Starts after
  the break" is true of all of them. Resolved once, to the first event following
  each break.
- **Composition was told to honour a break and never shown where one was.** The
  instruction was in the prompt and the fact was not.
- **A step said "places an order" for a submission the server refused**, and
  `mutation_claimed` correctly failed it. The fix was upstream, in what naming
  was shown: a rejected request now reads `-> 409  <-- REJECTED` rather than a
  number to skim past, and the prompt says not to describe a refused action as
  completed. It now writes "tries to place an order totalling \"900\"".
  `mutation_claimed` then had to learn that a step whose point is a refusal is
  not a false claim -- checked on evidence (a rejected mutating request plus an
  accepted expected result grounded in the same step), never by reading the
  sentence, because "tries to place" contains "place".

Four fixtures, with replay:

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Spread   Executes   Rechecked    Held
A0           10        0.0      0.0        10     0.7628      0.0        0.6           3     1.0
A1           11        1.0   0.6111         0      0.975    0.584        0.6           6     1.0
A2           11        1.0   0.6111         0      0.975    0.584        0.6           6     1.0
```

Yield falls against the three-fixture run because `twoflows` adds six steps and
few assertions; A0's fabrications rose to ten. `Spread` recovered to 0.584 --
more recordings, more variance in how hard the steps were.

---

## ~~Milestone 1 · Housekeeping~~ — DONE

Hours, not days, and it unblocks the rest.

**CI — delete it.** Remove `.github/workflows/ci.yml`. *(your call)* The cause
was one line (`pnpm/action-setup@v4`'s `version: '10'` disagreeing with
`packageManager: pnpm@10.6.1`), but a fix nobody asked for is not worth the
maintenance. `scripts/check.sh` is the real gate and is unaffected — it just has
to be run deliberately. What is lost: the only automated check that the repo
builds on a machine that isn't this one, which matters because everything under
`server/models/generated/` and `extension/src/types/` is regenerated from
`schema/`. Mitigation: run `bash scripts/check.sh` first thing on any new
machine, before trusting anything.

**`pyproject.toml`.**
- Pin `datamodel-code-generator==0.74.0` and `ruff==0.16.3` in the `dev` extra —
  unpinned floors mean CI resolves a newer generator than yours and the drift
  check in `scripts/check.sh:38` fails spuriously.
- Bound `gherkin-official>=33,<43` (nine majors shipped recently; an open pin
  silently changes the AST and therefore the parse-failure metric) and `mcp>=1.2,<2`.
- Add `rapidfuzz>=3.14` as a required dependency. Zero dependencies of its own.
- Delete the `library` extra's `sentence-transformers` and `sqlite-vec`.
  `sqlite-vec` ships an explicit "pre-v1, expect breaking changes" warning, which
  is a live reproducibility risk for an ablation meant to re-run later.

**Origin policy.** Add `origin_policy: allowlist | warn | off` to
`config/project.yaml` and `ProjectConfig` (`server/config/project.py:38-93`),
default `warn`. `check_origins` (`server/cli.py:70-92`) reads it instead of
hard-refusing; `--allow-any-origin` stays as a per-run override. `app.py:362-370`
already reports rather than refuses — leave that behaviour, just honour `off` by
staying silent.

**Staying on the free tier.** *(your call)* — no sensitive data is being recorded,
so the training-eligibility exposure is acceptable. Document the paid option
rather than taking it: Google's pricing page distinguishes the tiers explicitly
(free-tier content *is* used to improve their products, paid-tier content is
*not*), and at 16 calls × ~35k prompt tokens `gemini-3.1-flash-lite` runs **about
$0.16 per recording**. So if the company later wants real customer data recorded,
one billing switch removes both the training exposure and the pacing delay. That
belongs in `docs/RECORDING.md` as a stated condition of use, not as a default.

**Measured, and the plan was wrong about this.** The prompt is *not* the
constraint. Across all 145 cassettes the median request is ~2,050 tokens and the
largest is ~4,650 -- the "35k" figure was prompt tokens summed over a whole run
(11-16 requests), not per call. An unpaced run would peak near 33k tokens per
minute against a free ceiling several times that, so tokens are nowhere near
binding and shrinking prompts would not save a second.

What binds is requests: 16 of them at `--rpm 5` is 3.2 minutes of waiting by
construction. Two ways out, in order of cheapness:

1. **Check the actual limit and raise `--rpm`.** Google no longer publishes a
   free-tier table; the real number for a project is at
   `aistudio.google.com/rate-limit`. Our 5 is a conservative guess inherited
   from CLAUDE.md's note. If the account allows 15, `--rpm 15` cuts the wait to
   about a minute for nothing.
2. **Pay.** At ~2,050 prompt tokens x 16 calls, `gemini-3.1-flash-lite` is well
   under a cent per recording -- the earlier $0.16 estimate was built on the
   same 35k-per-call error and is roughly 15x too high. Billing also moves the
   account off the training-eligible tier, which is what the origin allowlist
   exists for.

Neither is code. Both belong in `docs/RECORDING.md` as stated conditions of use.

**Progress feedback.** The 3-minute wait you saw is the rate limiter, not the
code: ~16 model calls at 5 rpm. `Job.detail` exists for exactly this
(`jobs.py:39-40`) and never moves past `"running the pipeline"` (`jobs.py:103`),
and the UI never polls jobs at all — `RunPicker` is a `<select>` of finished runs.

- `PipelineOptions` gains `on_stage: Callable[[PipelineStage], None] | None`.
- `run.py` calls it at each of the six `stages.append` sites.
- `app.py` wires it to `job.detail`.
- New `ui/src/components/JobBanner.tsx` polls `GET /api/jobs/{id}`, shows the
  current stage, and says plainly that pacing is a free-tier limit.

**Three deterministic output fixes**, from reading the real-browser output in
`runs/rec_MSYWWJBVQOM8/qa_f_002/`:

1. *A step with an accepted assertion cannot render as `Given`.* That run
   produced `Given the tester signs in …` immediately followed by
   `Then the user is redirected to the catalog page` — an assertion made during
   the preconditions, before any `When`. `style.py:104` treats `Given` as
   satisfying "an action came first", so the existing check never fires. The rule
   is cleaner stated the other way round: if a step is worth asserting about, it
   is not a precondition. Promote it to `When` in `narrative._lay_out`, and
   tighten `style.py:96-107` to catch a regression.
2. *Actor voice must be the configured one.* The same file says "the tester" in
   its steps and "the user" in an assertion. `ProjectConfig.voice` exists and
   assertions never consult it. A `gherkin_style` warn is enough — this is the
   cheap half of the consistency problem the step library solves properly.
3. *Assertion phrasing.* `Then the confirmation message that the item was added
   to the cart appears` and `Then the system displays an approval requirement
   alert` both read like a description of the UI rather than an expected result.
   Prompt-side, in `assertions.py`: state the outcome, not the mechanism, and
   drop "the system displays".

**Resolve a spec/prompt contradiction about candidate counts.** Every step in
every recent run carries zero assertions or exactly one — `assertions.json`
confirms it at the stage output, with `suppressedAsNoise` empty, so nothing is
being filtered away. `ir.schema.json` says *"Each step gets 2-3 ranked
candidates, never one"*; the prompt says *"Give two or three candidates when the
step genuinely produced more than one checkable outcome. Give one when only one
thing mattered."* The model is obeying the prompt.

The prompt is right and the schema comment is wrong. Forcing a second candidate
on a step with one obvious outcome invites exactly the weak, incidental
assertion the same prompt warns against two paragraphs earlier. Fix the schema
comment, not the behaviour.

But two real consequences follow, and both belong in the plan rather than being
waved away:

- **§9.5's ranking is inert on current output.** With one candidate there is
  nothing to rank, so neither the provenance ladder nor milestone 2's
  verification can be *demonstrated* — only asserted. Annotations fix this
  naturally: a marked element produces an `annotated` candidate alongside the
  `inferred` one the model would have found anyway, and that is the first time
  the ladder does visible work. Note it as milestone 2's acceptance criterion.
- **Rejecting the only candidate leaves the step with no expected result.**
  `StepDetail.tsx:110-114` renders candidates as checkboxes, built for a list.
  With one, the reviewer's only move is to uncheck it. `review.set_assertion`
  exists — the UI should let a reviewer write their own sentence against an
  existing grounded literal (never editing `toolCallId` or `literal`, per §3.2).
  Small UI addition, milestone 1.

## ~~Milestone 2 · Annotations, end to end~~ — DONE

The quality lever. No new dependency.

**Element picker** — new `extension/src/content/picker.ts`. Overlay div,
`document.elementFromPoint` on mousemove, outline on hover, Esc cancels. On click
it reads the element with the helpers that already exist: `roleOf`, `nameOf`,
`rawValueOf` (`content/a11y.ts:42,71,138`) and `selectorsFor`
(`content/selectors.ts:27`) — which is exactly the `{role, name, value, selectors}`
shape `AnnotationTarget` requires. The value goes through the existing `Redactor`
(`redaction/redact.ts:26`) before it is stored; nothing raw is persisted.

**Popup** gains a fifth button, "Mark what I'm verifying", which toggles picker
mode in the active tab (`popup/popup.html:38-43`, `popup/popup.ts:33-56`).

**Binding.** `serviceWorker.ts:230-252` currently stores annotations with only
`{id, kind, timestamp}` — no `eventId`, no `target`. Attribution to the owning
event belongs at assembly, not in the frame, for the reason already learned with
network calls: `export.ts:104-129`'s `attributeObservations` is the pattern to
copy. Populates `CapturedEvent.annotations`, which nothing writes today.

**`intent_note` becomes real.** `popup.ts:40` promises "It will be used word for
word" and no server code reads it — grep for `intent_note` under `server/` returns
nothing. `name.py` short-circuits to the note's text when one covers the segment.

**The two dead paths.**
- `tools.py:134-159` — `get_events` returns an `annotations` field, so the
  retrieval the assert prompt instructs actually returns something.
- `store.py:200-307` — `find_text` indexes annotation `text` and `target.name` /
  `target.value`. Needs `annotation` added to `EvidenceKind` in
  `schema/ir.schema.json`, then `pnpm codegen`.

**Verified provenance.** In `assertions.py`, replace `_provenance()` with a
checked version that downgrades a claim the evidence does not support:
`annotated` with no assertion annotation covering the step, `narrated` with no
overlapping narration, `objective` with no stated objective. Deterministic, at
parse time, before ranking — the same posture as `NOISE` (§ "Noise suppression is
code, not a prompt line"). New validator `provenance_supported` in
`validators/grounding.py`, action `warn`, as the regression net; add it to
`ValidatorName` in `schema/trace.schema.json`.

**Fixture.** A new Playwright spec recording a session *with* annotations, writing
a **new** fixture file. Do not regenerate `checkout`/`hardpaths` — 145 cassettes
are keyed on their exact content.

## ~~Milestone 3 · The tester guide~~ — DONE

Written after milestone 2 so it documents something that exists.

`TESTING.md` is the nearest thing today and is developer-facing and stale — it
claims "No review UI", "No Excel or Jira export", "at most one expected result per
step", all now false (`TESTING.md:185-196`). Split it:

- **`docs/RECORDING.md`** — for a QA tester, zero terminal. What to write in the
  objective and why it is the strongest signal in the system; how to record (one
  intent at a time, let the page settle); what each annotation button does and
  when to use it; what "mark what I'm verifying" is for and why it beats letting
  the tool guess; what redaction will and will not catch; how to read the review
  UI and what the provenance badges mean. A narration section lands with
  milestone 7 — it cannot be written honestly before then.
- **`TESTING.md`** — keep as the developer runbook, with the false claims fixed.

Also: inline help in the popup for what each annotation does (there is none), and
reword `export.ts:221-224`, which tells a tester to run
`python -m server.cli serve` — a terminal instruction in the zero-terminal path.

## ~~Milestone 4 · Step library / cross-session memory~~ — DONE

`server/library/` is an empty directory — not even `__init__.py`.

- `server/library/store.py` — SQLite: step text, role, project, approving run,
  approved-at.
- `server/library/search.py` — `rapidfuzz.process.extractOne(text, entries,
  scorer=fuzz.WRatio, score_cutoff=...)`. Policy: ≥90 reuse verbatim, 75–90
  surface as a suggestion in the review UI, below that invent.
  Lexical rather than semantic is the *right* call here: the requirement is
  near-duplicate wording reuse, not paraphrase matching, and it stays
  deterministic and explainable.
- `tools.py:186-195` — `search_step_library` currently returns a hardcoded
  constant, ignoring `store`, `query` and `limit`, while being advertised to the
  model with a real description. Give it the real implementation.
- `name.py` — the response JSON gains `libraryRef`; without it the model has no
  way to report reuse even when the search works. `NamedStep.library_ref`
  (`name.py:130`) is never assigned today.
- `review.py:259-261` — approval feeds the library. The hook is already there.
- `ValidationContext` gains `library`; `consistency.py:197-264`'s
  `library_verbatim` has 47 lines of working logic that have never run because
  `reused` is always empty.

Cassette cost: the naming prompt changes, so budget one re-record of both
fixtures.

## ~~Milestone 5 · Replay: does the generated test actually run?~~ — DONE

**Prerequisite nobody knew about:** `SelectorHint` is never constructed anywhere
in `server/` — only in `tests/factories.py:307`. `selector_resolvable` has been
permanently skipping. So step one is populating `Step.selectorHints` in
`_assemble` from each event's `target.selectors`, ranked testId → role → text →
css. That un-skips a validator as a side effect.

**`server/runners/`**, a seam mirroring `renderers/base.py:43-54`: a `name`
attribute, a no-arg constructor, one keyword-only method over a finished
`IRDocument`, returning files and warnings.

Python writes a job JSON (actions + ranked selector candidates + the assertions to
re-check); a small Node script drives it with the `@playwright/test` already in
the repo; the result comes back as JSON. Subprocess rather than `playwright-python`
— the Python package ships its own driver and downloads its own browsers, ~1 GB
duplicated, and the test *runner* is Node-only anyway.

Assertions re-check by `Evidence.kind`: `semantic_node`/`a11y_node` → visible
text, `url` → `toHaveURL`, `network` → response wait, `console` → message check,
`narration` → not mechanically checkable, reported as such rather than skipped
silently.

**Ablation gains two columns** (`ablation/__init__.py:105-124`): `Executes` and
`MeanSelectorRank` — the latter free, because the replay records which selector
candidate succeeded, and the demo app has zero `data-testid`, so it exercises the
role+name fallback that is the normal case.

Demo app only, behind a `--replay` flag, off by default. Replay against a live
third-party site is flaky and that flakiness is not a metric.

## ~~Milestone 6 · Where QA teams actually live~~ — DONE

Jira issues are not where test cases go — test management tools are. Each of
these is an `Exporter`, which is the claim §11 makes and this is the test of it.

**Qase — build this one.** It is the only commercial tool with a real free tier
that *includes API access*, and it has both a bulk-create endpoint
(`POST /v1/case/{code}/bulk`, an array of cases in one call) and a native
`steps_type: "gherkin"`. Single `Token:` header. That makes it the honest demo:
a reviewer can open a free workspace and run the exporter end to end without
paying anyone. Official `qaseio` client exists; `httpx` is fine.

**Xray — document, do not build.** `POST /api/v2/import/feature?projectKey=X`
takes a plain `.feature` over multipart and creates a Jira Test per scenario.
Your pipeline already emits the wire format; the whole integration is
authenticate-then-POST. Tag conventions are worth supporting in the renderer
behind config, since they are how round-tripping works: `@TEST_<KEY>` updates an
existing test rather than creating a duplicate, `@REQ_<KEY>` links a requirement,
and any other tag becomes a Jira label. No free tier, so it cannot be tested here.

**TestRail — document, do not build.** `trcli import_gherkin` is an official,
maintained CLI that already does this. Worth noting that TestRail's
`custom_steps_separated` grid (`{content, expected}` pairs) is arguably a better
target for manual QA than Gherkin is, and maps cleanly onto our steps.

**Skip:** Zephyr Scale (two calls per case, no feature-file ingest), Zephyr Squad
(per-request JWT signing), qTest (Gherkin only via a separate paid app), Testmo
(beta API, no free tier), TestLink (dormant).

Keep the disk-write discipline throughout: the deliverable is the payload plus
the exact command, so a run still needs no credentials. Posting stays behind an
explicit flag.

**Import: Chrome DevTools Recorder.** Cheap and worth having. Its JSON carries a
ranked `selectors` array where `aria/Name` is an accessible-name selector — near
enough to our role+name primary key that the mapping is close to lossless in the
direction that matters. An importer is JSON parsing, no dependency.

What it cannot bring is network, console, DOM snapshots or screenshots — so an
imported recording produces a strictly weaker evidence set and a whole class of
assertions becomes inadmissible. That is the rule working, not a limitation to
paper over. Say so in the docs rather than degrading quietly.

## ~~Milestone 7 · Full decomposition (§9.3)~~ — DONE

One recording → N test cases, `Background` lifted from shared setup,
`exploratory`/`abandoned` pruned into `omitted` with markers. Most machinery
exists: `SegmentRole` covers all five roles, `DecompositionDecision` is in the
trace schema, `build_narrative` takes `lift_background`, `OmittedSegment` renders
in every format. `event_coverage` already accepts events covered by an `omitted`
segment and `no_pruned_assertion` currently skips.

The cost is a new multi-flow recording, not the code — both fixtures are
single-scenario, so the split cannot be demonstrated on them.

## Milestone 8 · Narration — built

Both halves landed together. What the plan above got wrong, and what changed:

**The transport was over-built.** This said multipart, touching extension,
server and schema at once. It is one endpoint taking a raw body —
`POST /api/recordings/{id}/audio`, ~15 lines each side. There is exactly one
file and the recorder already knows its own id, so multipart bought a parser and
a form-field name in exchange for nothing. Audio is posted **before** the
recording, because `post_recording` enqueues the job immediately and
transcription has to have something to read.

**Chrome's on-device Web Speech API was considered and rejected**, having first
looked like the obvious simplification: no audio stored, no dependency, no
transport. It loses on the thing that turned out to matter. A transcript is a
*reconstruction*, and keeping the audio is the only way a human can ever check
one — with Web Speech, whatever the browser heard is all anyone would ever have.
SS7.5 had already designed for this ("audio files are stored alongside the
recording and are never uploaded"), and with a `127.0.0.1` server the upload
question never arose.

**`faster-whisper` stands, now for reasons rather than inertia.** Parakeet TDT
v3 is faster and marginally better on WER, but covers 25 European languages (no
Arabic) and needs NeMo's PyTorch stack; faster-whisper is one pip dependency on
CTranslate2 with 99+ languages. Our audio is ~60s of clean close-mic speech
after VAD, so Parakeet's speed edge buys nothing and its language gap costs
something. Default `small`, and the choice is visible: on the fixture clip
`tiny` hears *"that **in** order this size"* where `small` gets *"that **an**
order this size"*. That one word is the whole argument for the default.

**"Cannot be verified the way everything else here has been" was wrong.**
`scripts/make_narration_wav.ps1` writes the spoken fixture with Windows' own
speech synthesiser — no network, no model download, nobody's voice — and
Playwright feeds it through `--use-file-for-fake-audio-capture`. The WAV is
committed, so CI never depends on which voices a machine has. `narrated.recording.json`
ships with its narration already transcribed, so the ablation and the server
suite need no Whisper install at all: the same economics as the cassettes.

**What the plan missed entirely, and is the most interesting part.** Narration
is the only **lossy** evidence source in this project. Every other one is read
exactly; a transcript is a reconstruction. So a mis-heard number becomes a
literal that passes `evidence_retrieved` *and* `assertion_grounding` and is
still false — both validators right, the claim admissible and wrong. That is
provenance meeting the first input where provenance and correctness come apart
by construction. Two deterministic guards: Whisper's `avg_logprob` and
`no_speech_prob` fold into `NarrationSegment.confidence` (a field the schema had
all along), and `supports_narrated` stops a low-confidence segment supporting
the `narrated` rank — in `_supported_provenance` **and** in
`provenance_supported`, which must not diverge. The audio is kept so the review
UI can play the clip beside the claim.

**Still true from the original plan:** narration evidence is `not_checkable` on
replay. A browser cannot confirm something a tester said out loud, so narration
improves *which* assertion is chosen and can never move `Executes` or `Held`.
Read `Yield`, not the correctness column.

**Demonstrated**, on `narrated.recording.json`, twelve validators with one skip:

```
Then the order is held for manager approval
  provenance: narrated
  evidence:   "Orders over EUR500 require approval" (semantic_node, tc_0009)
```

Grounded in a snapshot literal rather than in the transcript, which is the
point: narration chose which outcome mattered, the evidence stayed exact.

**One real bug this shook out, worth keeping in mind.** `from` is a Python
keyword, so codegen emits `from_ = Field(..., alias="from")` on `UrlChange`.
Writing a `Recording` back with `model_dump_json()` and no `by_alias=True`
produces a file that saves fine and then fails to validate on every later read
-- silently poisoned, with the error surfacing somewhere unrelated. It was
already latent in `cmd_import` and would have hit every recording with a
navigation in it. The correct dump now lives in `Storage.save_recording`, which
takes a model rather than a dict so a call site cannot get it wrong, and
`test_a_recording_written_back_out_still_validates` pins it.

~~**Deferred on purpose:** re-running `ablate` over all five fixtures.~~ Done in
Phase 3, over seven, which is what the deferral was waiting for.

## ~~Milestone 7's last piece · pruning~~ — DONE

`wander.recording.json`: the tester goes looking for the order total, opens the
Reports page, reads it, leaves, and then does the actual test. `Reports.tsx` has
said in its own docstring since Phase 1 that it exists to be wandered into, and
nothing had ever wandered there.

```gherkin
Scenario: An order over EUR500 is held for manager approval
  Given the tester signs in as "<<user_email_1>>" with "<<password>>"
  And the tester navigates to the catalogue page
  When the tester adds a "Blue Widget" to the cart
  Then the item is added to the cart

  When the tester proceeds to checkout
  And the tester tries to place an order totalling "750"
  Then the order requires manager approval

  # 1 exploratory action(s) omitted after step_001 - the tester navigates to
  # the reports page. See the review UI.
```

Pruned from the narrative, reported where it happened. Deleting it silently
would be worse than transcribing it: a reader would trust the test for a session
it never covered.

Almost all of this existed. `SegmentRole` had all five roles, `OmittedSegment`
rendered in every format, `event_coverage` already accepted an event covered by
an omission. What was missing was two things: composition was never offered
`exploratory` or `abandoned` as roles, and `_assemble` had nowhere to put a step
that carried one.

One trap: `OmittedSegment.segmentId` is a SEGMENT id, and a step id resolves to
nothing -- which would have reported every pruned event as unaccounted for and
failed `event_coverage` for a reason nobody could trace back here.

**Twelve validators, twelve passes, zero skips** on this fixture.
`no_pruned_assertion` had skipped on every run this project has ever made.

## Considered and rejected

**Playwright Agents (1.56+) — planner / generator / healer.** The closest thing
to this project that exists, and the honest position is: if the goal were
generating Playwright specs for developers, they would win outright. Three
functional gaps keep them from replacing anything here:

- No input surface. Their planner explores the app itself, which requires reach,
  credentials and permission to click. Nothing in the toolchain observes a human
  using their own browser, so there is no recording to work from.
- No access to intent. The best run in `runs/` grounds on the literal `Orders
  over EUR500 require approval` because the tester stated that objective. An
  agent exploring the same checkout page has no way to know which of the rules on
  that page is the one the business cares about.
- The generator verifies that an assertion passes against the live app. That is
  a different question from whether the assertion is about what the tester was
  checking — and the slow-validation run shows those coming apart: both its
  assertions were true, grounded, and about the wrong thing.

Where the overlap is real: their **healer** repairs selector failures at runtime,
which is adjacent to milestone 5's replay. Keep milestone 5 deterministic — an
LLM inside a measurement harness is nondeterminism in the instrument. But if
self-healing tests ever become a product feature rather than a metric, use theirs
rather than building one.

Cite them in the writeup. "Why not just use Playwright Agents" is now the obvious
question and it has a good answer.

**Playwright MCP and Chrome DevTools MCP cannot replace any part of the
recorder**, and the reason is architectural rather than featural: both are
agent-driven drivers of a browser *they* control, with no "watch what the human
did" surface. Their network and console tools are scoped "since the last
navigation" — pull-based debugging queries, not a durable session log, so a
multi-page recording cannot be reconstructed from them. `chrome-devtools-mcp` is
CDP, which §6.1 rejected on purpose and which managed browsers block.

Both are useful as *development* tools, and one thing is worth stealing:
Playwright's ARIA-snapshot serialisation is a compact, diffable role+name format,
which is the shape to test against if prompt size turns out to be the constraint.

**rrweb solves a different problem.** It serialises the DOM, not the
accessibility tree — it records that `<div class="btn-x9f">` mutated and cannot
tell you the node is `button "Save invoice"`. It exists so a human can *watch* a
session. Revisit only if reviewers start asking what happened between two steps,
and then as a review-UX feature, never as a pipeline input.

**Groq's free tier cannot run this workload at all** — 8,000 TPM against ~35k
prompts means a single request is unsendable, regardless of its 30 rpm. Local
models are not a fallback either: the best small tool-callers sit in the high 80s
on tool-call correctness, which over a 16-call chain is a near-certain failure per
run, and a model that hallucinates a citation is worse than one that rate-limits.

**Worth stating in the writeup:** nothing in the prior art records a browser
session into an accessibility-semantic structured format. Session replay tools
record pixels; test recorders record selectors. Recording role + accessible name
+ evidence is the actual novelty, and it is worth saying plainly rather than
leaving a reader to infer it.

## Verification

Run at each milestone, not at the end:

```bash
bash scripts/check.sh
.venv/Scripts/python -m server.cli run tests/fixtures/checkout.recording.json --offline
.venv/Scripts/python -m server.cli run tests/fixtures/hardpaths.recording.json --offline
.venv/Scripts/python scripts/prove_grounding.py
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
pnpm e2e
```

Two things must not move: `prove_grounding.py` stays green, and the ablation keeps
showing A0 fabricating where A1/A2 ground. A third now joins them — **the grounding
rate must not fall when provenance verification lands.** If it does, the cause is
a model that was inflating provenance, which is the finding, not a regression.

A fourth, from Phase 3: **the grounding rate must not RISE because of the repair
loop either.** A repair that lifts it by teaching a model to cite better is the
finding; one that lifts it by weakening what counts as grounded is the bug the
whole architecture exists to prevent. `Valid1st` is frozen at attempt 1 for the
same reason — read it beside `ValidFin`, and read `Converged` beside `Findings`.

Milestone 2 needs a judgement call no script makes: read the two rendered
`.feature` files and confirm the expected results are about the thing under test
rather than an incidental change.

