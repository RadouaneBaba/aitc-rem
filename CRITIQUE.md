# Reality check: aitc-rem as a QA tool

*A hostile read of the current build, written to be planned against.*
Date: 2026-08-25. Revision 3. Revision 1 was written without reading `SPEC.md`
or `PLAN.md`; revision 2 fixed that. Revision 3 removes the planning — this is
a critique, not a roadmap — and corrects three places where revision 2 pulled
its punch. Corrections are marked **[corrected]**.

**Ground rules.** You told me I could set `CLAUDE.md` aside and use it as
context rather than as law. I did. Several findings below attack things it lists
under "Non-negotiables", and several attack `SPEC.md` decisions directly. I have
not changed a line of code.

**What changed in revision 2.** Reading the spec made the critique *harder*, not
softer. The most damaging findings in this document are no longer my opinions
about your architecture — they are **your own specification's requirements,
unmet**, and one of them is a requirement the spec calls mandatory in bold.

**What changed in revision 3.** Three softenings, removed:

- Revision 2 called evidence binding "the crown jewel" and told you to protect
  it. That is the project's own framing, adopted rather than tested. §8 now says
  what it actually is: a **build-time filter** worth keeping, wrapped in ~800
  lines of display machinery serving an audience of one.
- Revision 2 said "prototype draft-then-bind *beside* the current pipeline."
  That was a hedge to avoid writing the consequence. §3.1 now writes it:
  **3,098 lines of `server/pipeline/` are on the block**, plus ~2,000 lines of
  their tests.
- Revision 2 oversold per-stage model config as re-scoping everything. It does
  not. A better model writes better sentences; it fixes **none** of the five
  structural defects in §2. §5.4 is corrected.

And one question this document had not asked at all, now §7: **whether the
premise holds.**

---

## 0. The verdict

You have built an **evidence-provenance research instrument** that emits Gherkin
as a side effect. It is unusually rigorous at the thing it chose to be rigorous
about, and that thing is not what a QA team buys.

The tell is arithmetic, not taste. Against your seven hand-built fixtures the
output is good. Against the two recordings you made yourself on real sites, the
output is a click log with no `Given`, a dangling `When`, a fabricated bug
report, and eleven phantom parameters — and **the Phase 3 critic, asked three
times, found nothing wrong with it.**

So: yes to your first concern, and worse than you framed it. It is not that
secondary things got polish. It is that the primary question — *"is this a test
case a QA engineer would accept?"* — has **no automated measurement anywhere in
the repo**, by design. `scripts/compare_features.py` prints the right questions
("Is the expected result about the thing under test?") and asks a human to
answer them. `PLAN.md`'s own Verification section ends: *"Milestone 2 needs a
judgement call no script makes."* You knew. It never got built, and everything
that did get built measures something adjacent.

**And §6.7 of your own spec says, in bold:**

> **The tool must be fully usable with zero annotations.** They raise quality;
> they are never required.

`rec_MT7MXBS9B2VB` has zero annotations, zero narration, and 34 clicks. That is
the spec's stated support case, and the tool fails it. Every good output in
`runs/` comes from a fixture carrying an annotation, a narration track, or a
scenario break. **The quality you have demonstrated is conditional on inputs the
spec promises are optional.**

---

## 1. What I read this time

| | |
|---|---|
| `SPEC.md` | 1,288 lines, all 19 sections |
| `PLAN.md` | 56 KB, incl. *Considered and rejected* and *Verification* |
| `README.md`, `TESTING.md`, `docs/RECORDING.md` | in full |
| Code | 20,201 lines (server + extension, excl. generated) |
| Tests | 8,023 lines, 409 tests |
| Runs | `rec_MT7MXBS9B2VB`, `rec_MT7VTN7ZRJPO`, `rec_MT7EYKIKMXY0`, `rec_MT77MABWW6VH`, fixtures |
| Model spend | `runs/_budget.json`: 145 / 164 / 187 / 219 requests per working day |

---

## 2. The forensic walkthrough: `rec_MT7MXBS9B2VB`

**34 events, all clicks, 50.5 seconds, fortnumandmason.com. 8.71 MB. Zero typed
input, zero annotations, zero narration.** That is what a real tester's first
recording looks like — nobody presses the checkpoint hotkey on day one.

```gherkin
Scenario: Upgrading hamper size and adjusting item quantities
  When the tester navigates to the hampers category and starts creating a hamper
  Then the hampers category page is loaded
  And the delivery destination is confirmed as available

  When the tester selects "Morocco" as the delivery country and proceeds
  Then the hamper selection options are displayed
  ...
  When the tester dismisses the hamper capacity warning     <- ends here
```

### 2.1 There is no `Given`, and it is a one-line bug

`server/pipeline/narrative.py:299`:

```python
if keyword == GIVEN and (acting or _asserts(step)):
    keyword = WHEN
```

Step 1 is `role=setup` → `Given`. It carries two accepted assertions → demoted
to `When`. Every later step then inherits `acting = True`. **The scenario can
never contain a `Given` again.**

The rule was written to fix a real problem (`Given … Then …` asserts on
preconditions). It fixed it on the wrong side. The correct fix is *the assert
stage should not have produced an expected result for a navigation step* —
"Then the hampers category page is loaded" asserts that the browser works.
Instead the keyword got mutilated, and the failure is silent and total.

Both real recordings hit it. None of the seven fixtures does, because in every
fixture step 1 is a sign-in the assert stage declines to assert on. **That is
the overfit, in one line.**

### 2.2 The scenario ends on an action with no outcome

A scenario ending on `When` has no verdict — nothing to pass or fail.
`gherkin_style` checks eight properties; this is not one. It only requires that
*some* `Then` exists somewhere in the file.

### 2.3 Six `When`/`Then` beats is six test cases in a trench coat

Navigate, set country, pick basket, upgrade size, change quantity, dismiss
warning — seven assertions across six unrelated beats. No QA engineer writes
that; they write *"Scenario: Upgrading a hamper increases its capacity"* with
three steps and one `Then`.

**Grounding is a filter on admissibility. Nothing in the architecture is a
filter on relevance.** The output reads like a transcript because it *is* a
transcript, filtered for citability.

### 2.4 The critic — Phase 3's headline feature — found nothing. Three times.

```
critic.json           → {"findings": [], "discarded": []}
critic.attempt2.json  → {"findings": [], "discarded": []}
critic.attempt3.json  → {"findings": [], "discarded": []}
```

§9.9 says the critic exists to judge exactly this:

> - Is this step name meaningful, or is it "User clicks the button"?
> - Is this assertion testing something that matters, or incidental noise?
> - **Does the scenario read as a coherent test to a human?**

It read a file with no `Given`, a dangling `When`, six unrelated beats and a
suspicious number, and said it was fine. The `Findings: 3` in your ablation
table came from fixtures. **On real input the critic is silent**, which means
A2's entire claimed advantage over A1 is fixture-conditional too.

*(The two `warn_critic_*` entries in `ir.json` are validator-shaped findings
routed through the critic's warning channel, not judgments the model made.)*

### 2.5 A wrong number shipped, against the spec's explicit instruction

`ir.json` warnings:

```
assertion_grounding: '18' does not appear at evt_033 in the recording
(it does appear at evt_001, evt_005, evt_006, evt_007, evt_008)
```

Delivered feature file:

```gherkin
Then the quantity of the tea selection increases to 18
```

§9.7's table gives `assertion_grounding` the action **Reject**. §9.5 says *"An
assertion whose evidence cannot be retrieved is not emitted."* It was emitted.
It is not even tagged `@needs-review`, because `needs_review()`
(`gherkin.py:295`) looks at escalation, confidence and fidelity flags and **not
at unrepaired findings**.

This is not the honest "provenance ≠ correctness" caveat you already documented.
This is two components disagreeing about grounding and the disagreement
resolving in favour of shipping. The tester sees a specific, confident, wrong
number with a clean evidence trail behind it.

### 2.6 The bug report is a false positive

```
Title:  Hamper creation -- fails
Actual: an uncaught error occurred when navigating to the hampers category
Grounded in: `Uncaught [object Object]`
```

That is third-party JavaScript on a commercial homepage — ad tags, consent
managers, analytics. The threshold ("a tester marker, a 5xx, or an uncaught
exception") was tuned on a fixture where the only script running was yours.

**One false bug report costs more trust than fifty good test cases earn.** A dev
spends ninety minutes, finds nothing, and the tool is dead in that org. There is
no first-party check, no dedup, no "was this thrown by the app or by something
sitting on it".

### 2.7 Eleven phantom `phone` parameters, from zero typed input

`redactBody()` runs `VALUE_RULES` over every request and response body (4,000
chars each) across every origin. Eleven numeric strings in analytics payloads
matched the phone pattern. They are now published as required test parameters in
the bug report, under a heading telling the reader to supply real values.

The rule's own comment says *"deliberately conservative. A false positive is not
free."* Correct, and untrue in practice, because it was never run against a real
payload.

### 2.8 8.71 MB for 50 seconds — and the spec predicted this exact miss

Per event: **~16 KB of snapshots, ~96 KB of network.** §6.3 budgets semantic
snapshots at 2–6 KB and they are roughly on target. **§6.4 specifies what
network capture records and never budgets it at all** — no size cap beyond
20,000 chars per body, no origin filter, no sampling. `evt_001` alone carries 33
requests, 12 of them "mutating" POSTs, essentially all analytics beacons.

So the bloat is not "the recorder is heavy". It is precisely: **snapshots were
designed and network was not.** And §17.2 lists *"Snapshot performance on large
enterprise apps"* with the note **"Validate early on a real heavy app — this is
the main unvalidated capture assumption."** You validated it by accident, it
failed, and nothing moved.

---

## 3. The root intellectual error, stated precisely

§3.6 justifies the whole retrieval architecture on context volume:

> **Context volume.** A six-minute session with full snapshots far exceeds any
> context window. A single agent burns context on retrieval and loses the thread
> by step 40.

And §1.2, the founding argument:

> When a model is handed a fixed payload and asked to produce a test case in one
> shot, and the payload does not contain the evidence for step 7's expected
> result, the model has exactly two options: invent, or refuse. **It cannot
> ask.**

**Both premises are load-bearing and both are wrong now.**

**On volume — I measured it.** A digest of the entire 34-event session — event
id, type, target role and name, URL, network summary, diff summary — is **6,539
characters, ≈1,634 tokens.** A six-minute session at that density is ~12k
tokens. It fits in any modern context window with room to spare.

The §3.6 argument was written against *raw DOM*, and §6.3 then solved that
problem by making snapshots semantic — and §3.6 was never re-examined. The
sentence says "with full snapshots", which nobody needs in a drafting prompt.
**The architecture's central justification was invalidated by a decision made
three sections later in the same document.**

**On invention — §1.2 offers a false dichotomy.** Retrieve-before-speaking is
one defence against invention. **Verify-after-speaking is another, and it is
strictly stronger,** because it does not depend on the model behaving. Let the
model draft freely; then bind every claim to a retrieval deterministically and
**delete what will not bind.** The model never supplies a `toolCallId` at all,
so it cannot fabricate one. §3.2's guarantee survives intact — arguably
hardened.

What §1.2 actually rules out is a *single-shot pipeline with no verification
pass*. That is not the only alternative to what you built, and treating it as
such is why the pipeline has six stages that never see each other's work.

### 3.1 The concrete alternative

1. **Digest** the session deterministically (~2k tokens / 50s).
2. **One drafting call**, whole session in view: scenarios, steps, keywords,
   proposed expected results as plain sentences. This is where the test case
   gets its *shape* — the thing that is currently missing.
3. **Bind deterministically.** For each proposed expected result, search the
   evidence store for a supporting literal. Found → bind with a real
   `toolCallId` + hash. Not found → **delete the claim.**
4. **Targeted retrieval only where binding fails on a load-bearing claim.** This
   is where the agent earns its calls — a handful of focused investigations, not
   2.5 calls on every step of every run.

Honest cost: a model drafting first proposes plausible claims that will not
bind, and you delete them. **Yield drops before it rises.** That is the correct
trade and it is measurable. Benefit: 5–10× fewer calls, which is the whole
free-tier problem, and a document written by *one* author instead of six.

### 3.2 What that costs, stated plainly **[corrected]**

Revision 2 said "prototype it beside the current pipeline", which was a way of
not writing this paragraph.

If draft-then-bind wins, the following are dead, not refactored:

| File | Lines |
|---|---|
| `pipeline/name.py` | 815 |
| `pipeline/assertions.py` | 747 |
| `pipeline/compose.py` | 633 |
| `pipeline/critic.py` | 363 |
| `pipeline/investigate.py` | 281 |
| `pipeline/repair.py` | 259 |
| **total** | **3,098** |

Plus their tests (`test_naming`, `test_assertions`, `test_compose`,
`test_critic` ≈ 2,000 lines), plus the keyword-derivation half of
`narrative.py`, plus most of `run.py`'s 1,557 lines of stage orchestration —
because with one drafting call there are no stages to orchestrate.

That is the real size of the claim in §3, and a critique that recommends the
architecture change without stating it is not a critique, it is a suggestion.
Whether the trade is worth making is a question the output answers, not this
document. But it should be read knowing the number is ~5,000 lines and not
"a new module beside the old one".

---

## 4. Spec-versus-implementation: the gap list

Every row below is your specification, unbuilt or contradicted. I am listing
them because a reviewer will find them and because several are exactly the
levers that would fix §2.

| § | Spec says | Reality |
|---|---|---|
| **6.7** | **"The tool must be fully usable with zero annotations"** (bold, in the spec) | Zero-annotation recordings produce the §2 output. Every good result depends on an annotation, narration, or a scenario break. |
| **9.7** | `assertion_grounding` → **Reject** | The `'18'` claim shipped as a warning (§2.5). |
| **9.5** | Noise suppression hard-excludes **"Ad / analytics containers"** | `NOISE` in `assertions.py` covers timestamps, relative times, dates, uuids, hex ids, placeholders. **No ad/analytics rule.** On a commercial site that is the one that matters. |
| **9.5** | "Each step gets **2–3 ranked candidates, never one**… presented as checkboxes **over the step screenshot**" | Candidates exist; **screenshots appear in no UI and no export**, though the recorder captures them. |
| **9.12** | `models.yaml`, per-stage model selection: *"`decompose` and `critic` carry the judgment load and **should be upgraded first**"* | **No `models.yaml`. No per-stage model config.** One model for everything. The escape hatch the spec designed for exactly your quality problem was never built. |
| **9.12** | *"**Quality first, cost later.** Premature cost constraints remove the signal needed to tell a pipeline bug from a weak model."* | You are on `gemini-3.1-flash-lite` — the weakest thing with a free allowance — and cannot currently tell a pipeline bug from a weak model. **The spec predicted this failure by name.** |
| **12.2** | Library stores *"an embedding of its text"*; §12.4 says the same semantic index later makes duplicate detection *"a query, not new infrastructure"* | `rapidfuzz`, lexical. `ModelClient.embed()` exists and the library never calls it. **The foundation §12.4 says is being laid is not being laid** — lexical fuzz will not answer "steps 1–3 match your existing Admin Login test". |
| **13.1** | Evidence pane shows `[screenshot]`, and rejected candidates (`☐ Timestamp is 14:03 ← noise`) | Neither. |
| **13.2** | Required: accept/reject, edit, **merge / split (drag)**, reorder, move | `merge_steps` and `move_step` exist. **No split. No drag.** |
| **6.8** | Fidelity flags "rendered prominently" with tester-facing copy: *"I can only tell you the tester clicked at (x, y)."* | UI renders the raw enum: `rapid_sequence`. The spec wrote the human copy; the code ships the symbol. |
| **11.3** | Jira: API-token auth, attachments (`.feature`, screenshots, `recording.json`) | Payload written to disk, never posted, no attachments. |
| **4 / 18.11** | Phase 2 demo: *"a tester records **fifteen minutes**, gets **three coherent test cases**, reviews and exports **without touching a terminal**"* | Longest real recording: **50 seconds**. Never demonstrated. You are still running CLI commands. |
| **17.2** | *"Validate early on a real heavy app — **this is the main unvalidated capture assumption**"* | Validated by accident (§2.8). Failed. Unaddressed. |

---

## 5. Your questions, answered

### 5.1 "Why not replace the deterministic parts with agent decisions?"

Not "replace" — **move the boundary.** The split is on the wrong axis.

| Stage | Now | Should be |
|---|---|---|
| Segmentation | **code** (idle gap, URL change, 12-event cap) | judgement. Five identical "Increase Quantity" clicks are one intent; an idle gap is a tester thinking, not a boundary. |
| Keyword (G/W/T) | **code** (role + position + the §2.1 demotion) | judgement, and cheap — it is the *shape of the test*, exactly what a model with the whole flow in view is good at. |
| Which outcome is worth asserting | model, **per step, blind to the rest** | judgement with the whole flow in view. This single decision determines whether the file reads as a test. |
| Literal binding / hash verification | code | **code. Never a model.** This is the part worth defending. |
| Style / structure checks | code | code |

Code should own **verification**; models should own **composition**.

The stated reason for the current split is reproducibility — "the same recording
always produces the same segment count". §3.6 lists it as a user-facing concern
("QA artifacts are audit material"). **No QA team has ever asked for a
deterministic step count.** They ask for a good test case. And the determinism is
partly illusory anyway: `apply_merges` and `apply_splits` run on top of the
segmenter from a model's judgment, so the *step* count already moves between
runs. You are paying full price for a property you do not actually deliver.

### 5.2 "Why not just give the data to an LLM and ask for Gherkin?"

See §3 — measured, not argued. The retrieval loop is not solving a context
problem; there isn't one at this scale. It is buying provenance, and paying with
the product, because **no single call ever sees the whole story while writing
the sentences.** Naming sees one segment. Assertions see one step. Composition
sees the flow and is forbidden from touching assertions. It reads like a
document written by six people who never met, because it is.

Keep the guarantee. Invert the order.

### 5.3 "Can we remove the allowlist?" **[corrected]**

**I overstated this in revision 1.** I wrote that you edited the file to make a
gate stop blocking you. Not true: `origin_policy` already defaults to `warn`,
`PLAN.md`'s *Decisions taken* records that choice explicitly, and the API path
never refused at all. **Nothing was ever blocked.**

What remains is smaller and still worth doing. Today `config/allowed_origins.yaml`
reads:

```yaml
  # Public demo applications, safe to send anywhere.
  - https://www.fortnumandmason.com/
  - https://www.nespresso.com/
```

Two commercial production sites filed under "public demo applications" — you
edited the file to silence a warning about a real concern. That is a gate
providing no protection and some friction, which is the worst configuration
available. Either enforce it or delete it; do not keep a list that lies.

**Recommendation:** delete `allowed_origins.yaml`, the `--allow-any-origin`
flag, and `check_origins`. Keep `origin_policy` reduced to two states — `off`
(default) and `warn`, where `warn` just prints the origins a run is about to
send. ~100 lines of dead ceremony gone. The genuine risk (free-tier training
eligibility) is a deployment decision, and §5.4 has more to say about it.

### 5.4 "Google ADK — is what we use the best option?"

**Do not adopt ADK.** It would take your loop, budget ledger, cassette cache and
`ToolInvocation` record and hide them behind a session runtime — and that record
*is* your product. Same answer for LangChain, LangGraph, CrewAI. Your seam is
good; `PLAN.md`'s standing principle ("if a tool does it better, use the tool")
already points the same way, and its *Considered and rejected* section shows you
have done this analysis properly for Playwright Agents, Playwright MCP, rrweb
and Groq.

**The framework is not the question. The model is.**

`gemini-3.1-flash-lite` is a primary cause of the output you dislike, and your
own §9.12 says so in advance: *"premature cost constraints remove the signal
needed to tell a pipeline bug from a weak model."* The architecture compounds it
by making dozens of small calls where a few good ones would do.

The unbuilt `models.yaml` is the cheapest missing piece in the repo — §9.12
already says where to spend (**composition and critic first, bulk naming last**),
and a paid endpoint moots the allowlist question entirely, since it carries a
no-training term.

**But do not expect it to fix the output. [corrected]** Revision 2 implied a
better model would re-scope most of this critique. It will not. Sort §2 by
cause:

| Defect | Cause | Would a better model fix it? |
|---|---|---|
| No `Given` anywhere | `narrative.py:299` | **No.** Code bug. |
| Scenario ends on a dangling `When` | missing check in `gherkin_style` | **No.** |
| Six unrelated beats in one scenario | nothing sees the whole flow while writing | **No.** Architecture. |
| Bug report on third-party JS | threshold in `bugmode.py` | **No.** Heuristic. |
| Eleven phantom `phone` parameters | regex over third-party payloads | **No.** |
| Vague step sentences | model | **Yes.** |
| Critic silent on real input | model, and possibly prompt | **Probably.** |

Five of the seven things you would actually notice are unaffected by model
choice. The value of building `models.yaml` is that it **removes a variable** —
after it, a bad sentence is provably the pipeline's fault and not the tier's.
That is worth a day. It is not a fix, and revision 2 was wrong to imply it
re-scoped anything.

### 5.5 UX

You are right, and §13 of the spec agrees with you more than the build does.

In front of a tester, right now:

> Stopped: `no_investigation_needed` after 0 of 8 retrievals.
> `get_objective({})` -> `tc_0001`
> WHAT THE RECORDER COULD NOT DETERMINE: `rapid_sequence`

That is your debugger in the primary pane. §13.3 justifies it ("trust *and*
proof — both load-bearing"), and §13.5 explains why edits must be form-shaped:
the review record is the y-axis of §3.4's chart and a column of §3.5's table.
**The research instrument is dictating the UX.** That trade was defensible while
the ablation was the deliverable. It is not defensible in a tool for testers.

Concretely missing:

- **No dashboard.** Runs are a `<select>`. Fifteen recordings, no list, no
  status, no warning counts, no search.
- **No editable feature text.** There is a "Feature file" tab that *displays* it.
  Every edit must go through a step-shaped form.
- **No screenshots** — spec'd in §13.1, captured by the recorder, rendered
  nowhere.
- **Internals unconditional.** Grounding, retrievals, tool-call ids, event ids,
  fidelity enums — always visible, never collapsed. §13.4 mandates
  *"warnings are never collapsed by default"*, which is right for warnings and
  wrong for retrieval telemetry.
- **No bulk actions**, no keyboard flow, no next-unreviewed.
- **No run-level verdict.** Nothing says *"2 unrepaired findings and an unbound
  literal — look at step 9 first"*, though `ir.json` knows.

The register is wrong throughout, and §6.8 proves the project knows better: it
wrote tester-facing copy for every fidelity flag (*"I can only tell you the
tester clicked at (x, y)"*) and the UI ships the enum. The same gap runs through
the whole evidence pane — `tc_0023` where the sentence *"'You have successfully
upgraded to Medium Wicker Basket' was on the page after the tester clicked
Upgrade"* was available for free.

The one constraint that looks structural and is not: §13.5 requires form-shaped
edits so review data can label step difficulty. A diff between the generated
file and the approved file yields the same labels. **Nothing about §3.4 actually
requires the UI to be shaped this way** — that was an assumption, and it cost
the editable feature file.

### 5.6 Outputs

| Output | Verdict |
|---|---|
| **`.feature`** | The product. Everything else is downstream. Currently the weakest. |
| **Jira** | Keep and **finish**. §11.3 spec'd token auth and attachments; a `.json` nobody can post is a demo. |
| **Excel** | Keep, reshape. §11.2 itself offers *"one row per step in a flat sheet"* as an alternative — take it, and add **empty Pass/Fail and Notes columns**. That is the difference between an export and a test script someone executes. |
| **`.trace.md`** | Not an output. A debug artifact dressed as a deliverable. Keep the file; stop treating it as a format. |
| **`.bug.md`** | Right idea, not ready. Fix §2.6 first; until then default bug mode **off**. |
| **Qase / Xray / TestRail** | Your config already handles Xray and TestRail correctly by *not* building exporters. Apply the same reasoning to Qase and delete it unless someone asked. |

**Missing and worth more than any of the above:**

- A **plain-language test case** renderer — numbered steps and expected results,
  no Gherkin keywords. §2.2 says the wedge is *"manual QA testers who write test
  cases in Excel, Jira, or Gherkin"*. Two of those three are not Gherkin, and
  the non-Gherkin population is the larger one.
- **Screenshots in the review UI and the exports.** Captured already, spec'd in
  §13.1 and §11.3, rendered nowhere. Cheapest large improvement in the repo.
- **Test data / parameters as a fillable table.**

### 5.7 What to cut

1. **The ablation harness** (`server/ablation/`, 460 lines) and
   `scripts/effort_difficulty.py`. Thesis apparatus. It produced exactly one
   product insight in its life (A1 ≡ A2), which a two-line assert would have
   caught. *Keep the recordings; delete the machinery.*
2. **The provenance *display* machinery — ~800 lines. [corrected]** Revision 2
   left this off the list because it had just called evidence binding the thing
   worth protecting. The binding is worth protecting; **showing it to a tester
   is not.** `renderers/trace_md.py` (325), `scripts/prove_grounding.py` (~200),
   `ui/src/components/EvidencePanel.tsx` (255) and the narrative half of
   `StepInvestigation` exist so a human can audit a retrieval chain. No tester
   will. See §8.
3. **The origin allowlist** (§5.3).
4. **The step library** (`server/library/`, 328 lines + SQLite) — **[corrected
   framing]**. §2.2 ranks it the *second most durable differentiator*, so
   "cut it" was too glib. But it is empty until a team has approved hundreds of
   steps, it costs a tool call on **every step of every run** today, and §12.4's
   justification for building the foundation now is void because the foundation
   built is lexical, not semantic. **Suspend it**: stop the per-step search,
   keep the schema and `libraryRef`, and revive it on embeddings when a corpus
   exists.
5. **The Qase exporter**, unless it has a user.
6. **Fidelity enums in the UI.** Keep capture, replace display with §6.8's copy
   or hide it.
7. **Coverage suggestions**, or demote. Three quarantine layers were built for
   output like *"attempt to downgrade the hamper size"* — plausible,
   unverifiable, already known to the tester.

**Do not cut:** the hash-checked evidence binding, `canonical_json`,
`no_placeholder_leak`, redaction (fix it, don't remove it), the cassette cache
(genuinely excellent), schema-as-source-of-truth codegen.

---

## 6. Questions you did not ask, that you will be asked

- **"How long, and what does it cost per recording?"** 145–219 requests per
  working day in the ledger; nobody has measured wall-clock or spend for one
  recording. This is the second question in any demo.
- **"What happens on a ten-minute recording?"** Unknown. Your longest is 50
  seconds → 8.7 MB. Your own Phase 2 demo criterion is *fifteen minutes*.
- **"What about an app behind a login?"** Every real recording is anonymous
  browsing. Real QA is behind auth, with session state, MFA and test accounts.
- **"Can it record a form?"** Your real recordings are 34 clicks and no typing.
  The typed-input path — the one redaction exists for — has never run outside
  the fixture app.
- **"What if I recorded the wrong thing?"** No trim, no drop-first-10-seconds,
  no re-run from a marker.
- **"Firefox? Safari? My locked-down corporate Chrome?"** Unpacked MV3
  extension. Distribution is unsolved and is a real adoption blocker.
- **"Where do my recordings live?"** One machine, no accounts, no sharing. Fine
  for now — name it before someone else does.

---

## 7. The question this document had not asked

Everything above criticises the *execution*. None of it questions the premise,
and the premise is where the largest risk sits.

**Is a reviewed generated test case actually faster than a written one?**

§2.3 already flinches at this and deserves credit for it:

> The speed argument is weaker than it first appears. A tester writing a test
> case from memory is not slow; realistic saving is roughly **2×**, not 10×.
> **The stronger claim is consistency and completeness.**

That estimate was made in a design document, before the review UI existed, and
before anyone had reviewed real output. Look at what review actually costs
today: read every step, judge every expected result, accept or reject each
candidate, catch the wrong `18` that the tool shipped with a clean evidence
trail behind it. **That is most of the thinking involved in writing the test
case in the first place.** The transcription the tool saves is the cheap part.

If the honest multiplier is 1.2×, then §2.3's fallback — consistency and
completeness — has to carry the entire product. And on the evidence in §2 it
currently carries neither: the output is *inconsistent* (no `Given`, actor drift
between stages) and *incomplete* (a scenario with no closing `Then`). The
fallback claim is not yet true, so nothing is holding the value proposition up
except the speed claim the spec itself already discounted.

This is measurable this week, for free, and it does not require writing any
code: hand-write the hamper test case, timed; then review the generated one to
the same standard, timed. If hand-writing wins, that is the most important thing
this project could learn, and every finding in §2–§6 is downstream of it.

**A related premise, also unexamined:** `PLAN.md` records that a Gherkin file
cannot be executed without hand-written step definitions, and the decision was
correctly made not to sacrifice readable prose for executability. The
consequence is rarely stated, though: **the output is a document, not a test.**
That is a legitimate product — manual QA teams do write documents — but it means
the tool competes on writing quality against a human writer, with no
executability advantage to fall back on. Everything in §2 is therefore not a
polish issue. It is the entire competitive surface.

---

## 8. What is actually worth keeping **[corrected]**

Revision 2 called evidence binding the crown jewel and told you to protect it.
That was the project's own framing, adopted rather than tested. The sharper
version:

**Evidence binding is a build-time filter, not a product feature.**

Its value is that it can *delete* a claim the model cannot support. That is
real, it is rare, and it is the mechanism that keeps a generated document
honest. Keep it. Keep `canonical_json`, which makes it work. Keep the cassettes,
which are genuinely excellent engineering.

But **no tester will ever audit a `toolCallId`**, and the project has built a
great deal on the assumption that they will. §13.3 asserts the panel does
"double duty — trust and proof, both load-bearing". Only one of those is
load-bearing for a tester. Trust comes from the output being *right*, which they
judge by reading it, not by inspecting a retrieval chain. The proof half serves
an audience of one: whoever is defending the thesis. That is `trace_md.py`,
`prove_grounding.py`, `EvidencePanel.tsx`, and the narrative half of
`StepInvestigation` — roughly 800 lines built for a reader who does not exist in
the product.

`PLAN.md` is right that recording a session into an accessibility-semantic
structure is real novelty; nobody else does it. That, and the binding used as a
filter, are what survive.

What has to change is what the guarantee is built *around*. Right now provenance
is the skeleton and the test case is draped over it, so the test case comes out
skeleton-shaped. Invert it: **write the test case the way a person would, then
refuse to ship any sentence you cannot bind.** Same guarantee, readable output,
a fraction of the calls — and §1.2 rejected that only because it assumed
verification had to come *before* generation. It doesn't.
