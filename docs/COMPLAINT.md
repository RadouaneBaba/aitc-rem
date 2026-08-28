# What is wrong, and what was decided

A product review of 2026-08-28, after the owner used the tool on two real
sessions of their own, followed by a design round that was twice reviewed by an
agent with no context on this project.

[REBUILD_PLAN.md](REBUILD_PLAN.md) is what the last rebuild promised.
[REBUILD_FINDINGS.md](REBUILD_FINDINGS.md) is why. **This file is the gap
between them and what is on disk, plus the design decided in response.**

House rule, same as the other two: every claim carries the number, the file:line
or the command that produced it. Disagree by re-running it.

**This file is a handoff to a planner.** §7 is as load-bearing as §6 — it holds
the designs that were proposed, reviewed and killed, with the arguments that
killed them. Read it before proposing an architecture; two of the obvious ideas
have already been tried in this conversation and are wrong for reasons that are
not obvious.

---

## 1 · Read this first: the root cause

**No model in this pipeline has ever seen a `.feature` file.**

```bash
$ grep -c "Scenario:" server/pipeline/author.py
1        # and that hit is the `AuthoredScenario` dataclass

$ grep -c "Scenario:" server/pipeline/judge.py
1        # judge._document() renders "  When the tester places the order  [step_004; evt_008]"
         # -- a flattened step listing, not the artifact
```

The author emits JSON. `narrative.py` builds the body. A renderer writes the
file. **Nobody who wrote it has ever seen what it becomes, and the judge grades
readability it has never been shown.**

This is the cause of the defect the owner noticed first — the output reads like
an assembled array rather than a written document. It *is* an assembled array.

It is also this repo's own most-repeated law broken in the most literal way
available: *worked examples outweigh rules, and whatever is absent from the
example does not happen.* The author's worked example teaches a model to write
Gherkin without ever showing it any Gherkin.

Everything in §6 follows from this.

---

## 2 · What is NOT wrong, so nobody "fixes" it

Checked and working. Both were mis-read during this review before being
measured, so they are stated first.

* **Coverage suggestions run and are good.** 2-6 per run, every run, reaching
  the sidecar and the review UI. On the owner's own sorting recording it
  proposed *"sort products by 'Most Popular'"* — the dropdown option they never
  exercised. Do not touch this.
* **Multi-tab capture works end to end.** `rec_MTD2DLZRFCEH` carries two
  `tabId`s, `evt_010` is on the second, and `build_digest` prints *"A DIFFERENT
  BROWSER TAB. The tester moved to another window here."* The plumbing is
  correct. What the author did with that line is §4.4.
* **The judge is the best thing in the system.** On `rec_MTD0YM1XRIPH` it found,
  unprompted, both defects a human found by reading the shipped `.feature` — a
  verdict asserting the alert but never that the order was blocked, and a
  dangling `When the order is not processed` with no verdict — and phrased each
  as a fix a tester could act on. Nothing in the fourteen validators ever did
  that. **Protect it.**
* **`digest.py`.** ~1,600 tokens for 34 events, and it already prints network
  status codes, tab changes and scenario breaks. Do not touch it.

---

## 3 · Corrections to earlier drafts of this file

* **Narration is not a teaching failure.** Zero narration segments in the new
  corpus is the owner's deliberate choice while testing. They intend to narrate
  in future sessions. `get_narration` returning nothing is correct behaviour,
  not a gap.
* **`get_network` must NOT be cut.** An earlier draft argued it was redundant
  because `digest.py:285` already prints `POST /api/orders 409`. That is
  backwards: the digest is **not citable** — a claim must come back from a tool.
  Cutting it removes the only path to *proving* a status-code claim while
  leaving the only path to *inventing* one. It is why a shipped 409 assertion
  had no 409 anywhere in its evidence.
* **Only `see` is a worked-example gap.** An earlier draft lumped `see`,
  `get_network` and `get_narration` together as one finding. They have three
  different causes.

---

## 4 · What is broken — the evidence

### 4.1 Overclaiming: a sentence and its literal about different facts

Shipped in `rec_MTCVNIOD8723`:

```
claim:    "the order is rejected with a 409 Conflict status"
evidence: "Orders over EUR500 require approval"      <- a page alert. No 409 in it.
```

`evidence_retrieved` passes, because the literal really is in the retrieval.
Nothing checks that the sentence and the literal are about the same thing. The
409 came from the digest, which is not citable, and `get_network` was never
called.

### 4.2 Assembly artifacts

```gherkin
When the order is not processed          <- a state written as an action, no verdict
```
```gherkin
When the tester opens the receipt in a new tab
And the receipt displays the total amount charged for the order   <- an assertion as a step
Then the receipt displays the total amount charged                <- the same verdict, twice
```

Two of four shipped features carry one. Cause: §1.

**Note for the planner:** the first of these *was found by the judge and shipped
anyway.* It is a repair failure, not only a prevention failure. Across the runs
on disk: 11 judge findings in, 8 still open after revision, and on the sorting
run the count went **2 → 3, worse**.

### 4.3 Unprovable claims — the gate is substring containment

```python
# server/pipeline/validators/base.py:135
def contains_literal(value, literal):
    return any(literal in s for s in strings_in(value))
```

So this shipped:

```gherkin
Then the first product is 'The Autumnal Hamper' priced at £120.00
```

proved by that string appearing *somewhere*. The sentence says FIRST; the check
says PRESENT. Sorting, ranking, pagination and negative assertions ("the order
was NOT confirmed") are all inexpressible. The judge caught this three times and
the revision could not fix it, because there was nothing to fix it with.

### 4.4 A false refusal, and nothing checks refusals

`rec_MTD2DLZRFCEH` shipped:

> *"The tester navigates to a new browser tab, which is outside the scope of the
> current application session recording."*

It is not. The recorder followed the tab and the digest said so in as many
words. **The author read a correct signal and drew the opposite conclusion, then
stated it to the tester as a considered decision.** Every validator passes a
refusal, because a refusal claims nothing. It is the only output in the system
that is confident and entirely unchecked.

`judge.py:355` already receives every `whyNot`. It is simply never asked whether
one is true.

### 4.5 Dead capabilities

Every tool call ever made, across all nine runs on disk:

```
get_diff        26
get_snapshot    14
find_text        2
see              0
get_network      0
get_narration    0
```

`TestCaseIR.examples` — the `Scenario Outline` capability — is `false` on **all
ten test cases ever produced**, including the owner's sorting recording, which
is three sorts with three different expected first products and a textbook
Examples table.

Measured cause:

```
SYSTEM_PROMPT    3,421 chars    'see(' x1    'outline' x1
WORKED_EXAMPLE   3,431 chars    'see(' x0    'outline' x0
```

**Rare use of `see` is correct** — a screenshot is ~1k tokens and an author that
looks at every event is not investigating; that is the step-library failure,
which lifted calls-per-step from 1.56 to 2.17 and collapsed the effort-variance
signal from 1.08 to 0.16. **Never is the defect.**

### 4.6 The oracle goes in and nothing checks it came out

**14 expectations on disk. All 14 `inferred`. Not one has ever been confirmed by
a human.**

Cause: `ui/src/App.tsx:32` — the confirmation screen opens only on
`?confirm=<recordingId>`, read once, no link from the dashboard, no banner. Miss
the one link on the export page and it is gone forever.

Stage 1 was the headline of the entire rebuild. `REBUILD_FINDINGS` open question
5 called it *"the assumption the whole oracle layer rests on."* It is exactly as
untested as on 2026-08-27, and **A1 vs A2 — what asking a human is worth —
remains unmeasurable.**

### 4.7 Cost: one unbounded tool

Measured on the two real storefronts, nothing truncating:

| | fixture app | real commercial page |
|---|---|---|
| per event | 5.5-10.7 KB | **150-172 KB**, ~950 nodes |
| `get_diff` returns | small | **4.5-15 KB** — fine |
| `get_snapshot` returns | small | **65-72 KB, one call, ~16-18k tokens** |
| prompt tokens per run | ~29,000 | **168,690** |

**Full capture is not the mistake.** Stored bytes are fine. `get_diff` already
ranks and caps. `get_snapshot` hands back a whole page raw into a conversation
that re-sends its history every turn.

### 4.8 Smaller, verified

* **`resolved: false` is hardcoded** (`run.py:355,477,490`). On
  `rec_MTD0YM1XRIPH` the judge said *"split into two scenarios"*, named them, and
  the author produced exactly those two — recorded as unresolved. The reasoning
  is sound (what was resolved between rounds is unknowable); the `required`
  always-`False` field is not. Drop or rename it.
* **"5 checks passed" is a badge that can only say green.** All five pass on all
  nine runs; `prove_grounding.py` reports 100%; the judge raised three `fail`s on
  the one real commercial session. Keep the checks, stop rendering the count as
  a trust signal.
* **The dead step-library tool.** `server/library/` is deleted;
  `search_step_library` is still registered in `evidence/tools.py`. And
  `coverage.py:211` is the one `investigate()` caller passing no `tool_names`,
  so coverage receives **all twelve tools including that one**. Written into
  `REBUILD_PLAN` §1.7 as a one-line fix; never done. Six tools are offered to no
  stage at all: `get_console`, `get_events`, `get_neighbouring_segments`,
  `get_objective`, `query_element`, `search_step_library`.
* **`STATUS.md` Part 1 is fiction** — three pages of "open defects" about
  `_own_input`, `evidence_discriminates`, `_second_chance` and `bind`, all
  deleted. Archive it.
* **111 uncommitted files**, including 15 deletions of major modules.
  CLAUDE.md's own `git checkout --` warning applies at full force. Git is the
  owner's to run.

---

## 5 · Promised and not built

Swept item by item against both rebuild documents.

| promised | reality |
|---|---|
| `see` reaching the model | **0 calls**, ever (§4.5) |
| `Scenario Outline` "already shipped" | **0 of 10 test cases** |
| Three Gherkin styles | cut. The data-driven claim of "already shipped" is false |
| The how-to as a page the tester can reach | it is `docs/HOWTO.md`, a markdown file. **The owner asked for a route in the dashboard with visuals** |
| Read acceptance criteria **from** Jira | not built |
| Jira export (build the issue) | **0 payloads ever produced** |
| Excel export "keep, but test it" | **landed** — 7 `.xlsx` files produced |
| Redaction off behind a config flag | not built |
| Invert the origin gate | not done; `origin_policy: warn`. §11b argued it low-value — fine, but the plan still lists it |
| Cut the narration confidence ladder | **kept in full.** Plan said cut, code kept, CLAUDE.md now defends it. **Nobody recorded that reversal as a decision** |
| Cut the step library | module deleted, tool still live (§4.8) |
| `coverage.py` `tool_names` — a one-line fix in the plan | not done |
| `storageState` for authenticated replay | built, `.auth/` never created, never used |
| A tester on the confirmation screen | **0 of 14** (§4.6) |
| A tester on the review UI | **0 review edits, ever.** `effort_difficulty.py` still refuses to report SS3.4 |

---

## 6 · The decided design

**One change dominates: the author writes the feature file.**

Today it emits JSON and a script assembles the artifact. That is §1, and it is
why the output reads like assembly and why the judge grades something it cannot
see.

### The pipeline

| stage | what it does | who |
|---|---|---|
| **digest** | the session as a readable map — unchanged | code |
| **expectations** | *what should have happened?* — guesses, **with tools**, so the guesses are specific enough to tick | model |
| **confirm** | ✓ / ✗ / edit, one screen | **human** |
| **author** | investigates, then **writes the `.feature`**, then tags each line with its events and evidence | model + tools |
| **validators** | facts only | code |
| **judge** | *would a QA lead sign this?* — reads **the actual rendered file** | model + tools |
| **revision** | author rewrites, max 2 rounds — unchanged | model |
| **coverage** | what else should be tested — unchanged, quarantined | model |
| **renderers** | xlsx / Jira / bug, from the annotations | code |

Four model stages. Same count as today. **No new stages and no new agents.**

`narrative.py` stops building the body. It keeps one job: re-deriving keywords
**after a human edits in the review UI**, so deleting a step does not leave a
dangling `And`. `would_collapse` stays.

### The tools — six, each a question a tester asks

| tool | the question |
|---|---|
| `diff(event)` | what changed here? |
| `snapshot(event, when, container?)` | what was on the page — or in this one list, in document order? |
| `find(text)` | where does this appear? |
| `network(event)` | what did the server say? |
| `see(event)` | let me look at it — last resort, ~1k tokens |
| `narration(range)` | what did the tester say out loud? |

Delete the six offered to no stage (§4.8) and constrain `coverage.py`'s set.

### Evidence — four forms, not one

Today evidence is a literal and the check is substring containment (§4.3).
Assertions gain forms the validator **re-evaluates against the stored
response**:

```
contains(text)                    today's default
first_of(container)               order
count(container, role) == n       quantity
absent(text)                      negative assertions
```

`absent()` is the judge's most frequent unmet ask in the runs on disk.

**Three constraints on this, all found by review and all non-negotiable:**

1. **Predicates address `ref` + role/name, not CSS ids.** The node model is
   `ref` / `role` / `name` / `value` / `children`
   (`schema/recording.schema.json:282-301`). There are no CSS ids anywhere. And
   `ref` is stable *within* a snapshot, so a predicate is bound to one stored
   response and cannot be re-pointed the way `contains_at` re-points a literal.
2. **Store the full response; render only the capped one.** `_rank`
   (`tools.py:97`) does `ordered = named + rest` — it **reorders**. Cap
   `get_snapshot` the way `get_diff` is capped and then evaluate `first_of()`
   against the stored response, and you get the first *named* node, not the
   first in document order — and on a product grid the nameless wrapper nodes
   are exactly the ones ranked to the back. It would confidently return the
   wrong answer and pass the gate. Storing full also keeps `evidence_retrieved`
   honest under capping, or true claims whose literal fell into the hidden tail
   start being rejected.
3. **A predicate has three outcomes.** true / false / **cannot-evaluate**
   (container absent, response truncated, role mismatch). Cannot-evaluate must
   land in `whyNot` — *your predicate did not resolve; say why or claim less* —
   never in pass (that builds the laundering machine) and never in reject (a
   re-render silently kills true claims).

### The judge gains two questions

- **does any sentence claim more than its evidence shows?** (§4.1)
- **is any refusal true?** (§4.4 — `whyNot` is already in front of it)

**These are not prompt lines.** `judge.py:85` `CHECKS` is a closed 5-tuple and
`judge.py:381` does `if check not in CHECKS: continue` — findings from an
unlisted check are **silently discarded at parse**. Adding the questions without
extending `CHECKS` ships a no-op that looks like a clean result. Extending
`CHECKS` desynchronises `evals/RUBRIC.md`'s vocabulary, which is real work to
budget.

**Do not add a third question** ("did the document address what the tester
confirmed?") until §4.6 is fixed and a confirmation actually exists. It cannot
fire on 0 of 14 and would dilute the five that can.

### The worked example

Rewrite it to contain, at minimum:

* **a rendered `.feature` body beside the JSON** — the single highest-value line
  in this document (§1)
* **one `Examples` table** on a flow that repeats
* **one `see()` call** at a moment the accessibility tree genuinely cannot
  settle — *the situation*, never a routine step
* **one `get_network` citation**

### Gherkin styles become achievable

Business (few steps, one `Then` at the end) / Automation (every action, specific
values) / Data-driven (`Scenario Outline`). These were cut on the argument that
prompt rules measure near-zero uptake here.

**That argument dies once the model writes the file.** A style stops being a
rule and becomes a worked example — *here is a good feature file in this style*
— which is the one mechanism that has always worked in this project. One worked
`.feature` per style, selected in `project.yaml`.

### And two routing fixes

* **Put a link to the confirmation screen on the dashboard** (§4.6). Everything
  downstream that reads expectations is currently reading unconfirmed guesses.
* **Stop rendering "5 checks passed" as a trust badge** (§4.8).

---

## 7 · Rejected, with the arguments that killed them

**Read this before proposing an architecture.** Each of these was proposed
during this review, reviewed by an agent with no context, and killed. They are
the obvious ideas.

### A separate tool-less writer agent

*Proposed:* an investigator with tools produces a findings sheet; a writer with
no tools turns findings into Gherkin and cannot invent, because it has no
evidence access.

*Killed by four things:*

1. `author.py:34`, already in the code, is a direct objection: *"an author that
   may only claim what it has already retrieved writes about whatever was easy
   to retrieve."*
2. The findings sheet is a **new lossy interface** — a model-written summary
   between the agent holding the evidence and the agent writing the sentence,
   and nothing validates it. The gate checks `proof`; nothing checks `what`.
   Overclaiming relocates rather than disappears.
3. It does not fix the 409 anyway. The 409 was an *inference over* the digest,
   which the writer still reads. Removing tools does nothing to an inference.
4. It bypasses `narrative.py`, which owns `would_collapse` — the guard that
   stops a rewrite silently deleting a step.

### `order()` and `count()` as tools

*Proposed:* new tools returning list order and item counts, to make sorting
provable.

*Killed:* the gate is substring containment (§4.3). An `order()` response
listing twelve products *contains* `"The Autumnal Hamper"` whether it is first
or last. The claim passes **while wearing a tool named `order`** — laundering a
presence check as an order check and putting a green badge on it. Strictly worse
than today, where the judge catches it. The fix is an assertion form the
validator re-evaluates (§6), not a tool.

### Prose-first emission inside the same agent

*Proposed:* the author emits each scenario's Gherkin body as tagged prose first,
then decomposes it into structured steps.

*Killed:* `sync_keywords` (`narrative.py:242`) overwrites `Step.keyword` from
`role` on every run, so a line written as `Then` ships as `And` — guaranteed
divergence in a field the reconciliation check does not cover. Assertions render
as their own lines, so a verdict line has no step id to be tagged with.
`apply_intent_notes` rewrites `step.text` *after* both are written. And its
failure mode spends the single revision round on a **format error**, in a loop
measured at 11 findings in / 8 out that made the sorting run worse.

Superseded by the simpler and stronger fix: the author writes the whole file,
and both models see it.

### A validator for "every confirmed expectation is answered"

*Killed twice, independently.* It is either vacuous (satisfied by a `cant_tell`)
or a mandate to overclaim (if `cant_tell` does not count). And
`REBUILD_PLAN` cut ten of fourteen validators on the rule *keep a deterministic
check only where it cannot be wrong.* "Did this document address what the tester
asked for" is a judgement. It belongs to the judge, and only once §4.6 is fixed.

### More design rounds without evidence

Two people reasoning about what might work is a loop with no exit condition, and
this repo already measured the equivalent: A2's critic raised 9 findings and the
loop resolved 1. **A fresh-context critic pointed at the architecture would
repeat that.** Pointed at the *output* it works — that is `qa-judge`, and it has
caught things nothing else did.

---

## 8 · Out of scope, and later

* **MCP / live-browser agent.** The owner's plan, after the tool is finished: a
  Playwright agent explores the app and proposes the case the tester missed —
  *"you tested two sorts and forgot one"* — with the option to generate the
  completed test case.

  `coverage.py` already does the recording-only half, and already made exactly
  that suggestion on the owner's own sorting recording. The seam exists:
  suggestions have their own IR block, an UNVERIFIED heading in every renderer,
  and `suggestions_quarantined` at the gate.

  **Carry this into that build:** an MCP client's tool calls bypass
  `ToolRunner`, so they never land in `trace.toolCalls` — which is the substrate
  `evidence_retrieved` resolves against. Live retrievals must be recorded
  through the same seam, or the one rule the architecture exists to enforce has
  a hole in it.
* **Reading acceptance criteria *from* Jira.** Never built. The oracle is
  already written by a human in the ticket the tester works from.
* **The how-to as a dashboard route with visuals**, replacing `docs/HOWTO.md`.

---

## 9 · Prerequisite: there is no instrument

**Nothing in this repo can currently answer *did the change help*, and this is
not solved by anything in §6.**

* `REBUILD_FINDINGS` §13 names the number to beat: held-out `0 good / 0
  needs-work / 3 bad`. **Those three recordings were captured through the
  keyhole recorder** — `scopeRoot` is set on every snapshot and 30 of 34 events
  on one are truncated at the old 400-node cap. Re-running them measures the new
  pipeline against broken evidence. **Moving that row requires re-recording
  those three sessions**, which no document says.
* The current corpus is 5 of 7 demo app, **with sharp objectives**
  (*"Check that filtering to in-stock items cuts the list from 24 products to
  9"*), while every `bad` run in the baseline had a vague objective. A good
  result there would measure the objective coach, not the architecture.
* `eval_packet.py` has **no expectations section**, so the judge cannot see the
  oracle — the biggest thing the last rebuild added.
* `evals/RUBRIC.md`'s layer table names `bind`, `split`, `_second_chance` and
  `CRITIC_REPAIR`, all deleted. A judge asked to name the failing layer will
  name one that does not exist.
* Extending `CHECKS` (§6) breaks the by-check comparison in `LEDGER.md` that
  would otherwise be the only before/after. Sequence accordingly.

**Also a scheduling fact:** `cassette_key` is a sha256 of the request payload
(`llm/cassette.py:36`). Every prompt change, tool-list change and tool-response
change invalidates the cassette library. Anything touching the author's prompt
turns iteration into live runs against a documented 20/day ceiling. Batch prompt
work and re-record once.

---

## 10 · Reading order for the planner

1. **§1** — one finding, and most of §6 follows from it.
2. **§7** — the dead ends, so they are not re-proposed.
3. **§4.6 and the confirmation-screen link in §6** — everything downstream reads
   unconfirmed guesses until this is fixed. Two cold reads reached this
   independently.
4. **§6's three predicate constraints** — each would ship broken without its
   constraint.
5. **§9** — whether this is a prerequisite or a parallel track is the owner's
   call, but *blocking* and *ship six changes anyway* cannot both be true.

Everything else is cleanup, and none of it is a surface a tester touches.
