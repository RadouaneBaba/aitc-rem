# What is actually wrong, and how we know

A working record of the architecture review of 2026-08-27/28. This file holds
the **evidence and the reasoning**; [REBUILD_PLAN.md](REBUILD_PLAN.md) holds
what to build. Read this one before arguing with that one.

Everything below was measured against the repo as it stood on 2026-08-28: 13
recordings, 33 runs in `runs/`, the ablation table, and the judge verdicts in
`evals/`. Every claim carries the command or the number that produced it, so a
later session can re-run it and disagree.

---

## 1. The finding that reframes everything

**The recorder never captures the page. Only the area around the clicked
element.**

`extension/src/content/snapshot.ts`:

```ts
/**
 * Scope per SS6.3: the target's nearest landmark or dialog ancestor. [...]
 * The expensive view is available on demand through the
 * get_full_snapshot tool -- cheap by default, costly on request, which is
 * itself an agentic decision.
 */
```

```bash
$ grep -rn "full: true" extension/src
$          # nothing. Nobody ever asks for the full view.
```

And `get_full_snapshot` on the server is `return store.merged_view(...)` over
data that was never recorded. **The escape hatch that justifies the scoping does
not exist, and cannot** — the page is gone by the time the server runs.

What that does to a real session. `rec_MTA7A2XHHH22`, objective *"check if
filters are working correctly"*:

```
evt_009  click checkbox "En stock"
  before.scopeRoot: region "Statut des Stocks"    <- the filter widget
  after.scopeRoot:  region "Statut des Stocks"    <- the filter widget
  diff: {added: [], removed: [], changed: [],
         urlChanged: {... meta/_stock_status:instock ...}}
```

The product list — the entire object of the test — was never captured, before
or after. The diff is empty.

Measured across every recording on disk:

| recording | events | snapshots | empty diffs |
|---|---|---|---|
| rec_MTA7A2XHHH22 | 15 | 100% scoped | **8** |
| rec_MT7MXBS9B2VB | 34 | 100% scoped | 5 |
| rec_MTA1O4R3SSR5 | 10 | 100% scoped | 3 |
| rec_MTAO4QYMIG16 | 8 | 100% scoped | 3 |
| *(all 13)* | | **100% scoped, 0 full** | |

**30–50% of events on real sites record no observed change at all.**

### The mechanism, measured exactly

`scopeRootFor` walks up to the *nearest landmark*. On a real page that lands
somewhere different depending on where the tester clicked — and the difference
is total. Per event on `rec_MTA7A2XHHH22`:

| event | scope root | snapshot | diff |
|---|---|---|---|
| evt_006 | `region` | 29 KB | 153 changes |
| evt_007 | `region` | 29 KB | 153 changes |
| **evt_008** | **"Statut des Stocks"** | **1.2 KB** | **EMPTY** |
| **evt_009** | **"Statut des Stocks"** | **1.2 KB** | **EMPTY** |
| evt_010 | `region` | 29 KB | 813 changes |
| **evt_011–014** | **"Modèle processeur"** | **1.9 KB** | **EMPTY** |
| evt_015 | `region` | 29 KB | 814 changes |

**Every empty diff is an event where the tester clicked inside a small filter
widget that happens to be its own landmark.** Click in the page body and the
product grid is captured with hundreds of changes. Click inside the control that
*causes* the change and you capture the control and nothing else.

Which is most of what testing is.

### Full capture is nearly free — measured, not estimated

Average scoped snapshot size on the two real commercial recordings:

| recording | events | avg snapshot | ~tokens | largest |
|---|---|---|---|---|
| rec_MT7MXBS9B2VB | 34 | 28.1 KB | ~7,200 | 31.8 KB |
| rec_MTA7A2XHHH22 | 15 | 18.3 KB | ~4,700 | 30.7 KB |
| rec_MTAO4QYMIG16 | 8 | 3.8 KB | ~970 | 18.3 KB |
| *(demo fixtures)* | 4–10 | ~1.2 KB | ~300 | ~2.8 KB |

A full page is ~29 KB / ~7.4k tokens — **which is already what the large events
cost today.** Capturing full everywhere adds roughly 7k tokens on the handful of
small-scope events per recording, and that is *stored* data. What reaches the
model is only what it retrieves through a tool.

The context-volume fear that justified scoping does not survive the
measurement. **This closes the open question about whether full capture is
affordable: it is.**

### What this explains

`bind._candidates` offers "what this event added or altered". On those events it
is offering the empty set. So:

- The agent cited `"Prix bas à haut"` — the dropdown label — because it was one
  of the few strings that existed in the captured subtree. It was not being
  lazy. It was answering from a keyhole.
- `evidence_discriminates`, `_own_input`, `_existence_only`, `_unwitnessed`:
  every one of these is a refusal rule added to catch a symptom of nothing
  having been captured.
- The 27 `gherkin_style` warnings of the form *"scenario ends on an action, it
  has no verdict"* are not a validator catching a defect. They are a readout of
  the capture problem.

**Do not read the last milestone's work as wasted.** The refusal rules are
correct; they were just fighting downstream of the real cause.

---

## 2. Screenshots exist and the model has never seen one

```
recordings/rec_MTA7A2XHHH22/screens/evt_001.png … evt_015.png
```

Full-viewport PNGs, one per event, captured by
`extension/src/background/serviceWorker.ts` via `chrome.tabs.captureVisibleTab`.

The product list that was missing from every snapshot is **in those images**.
Gemini is multimodal. The pipeline uses it as a text-only model and renders the
PNGs as thumbnails in the review UI.

---

## 3. Redaction is eating the evidence

`rec_MTA7A2XHHH22` (a Moroccan PC parts storefront):

```
parameters: 214
categories: {'phone'}
occurrences per parameter: 12–24
```

**214 distinct values on one product listing page, every one classified as a
phone number.** Those are prices and product codes.

The cause: `Redactor` runs its regexes over *observed page content*, not only
over what the tester typed. On a commercial site the numbers it eats are exactly
the numbers a discriminating assertion needs.

The rule "redaction happens in the browser before anything is persisted" is
right. Its **scope** is wrong.

---

## 4. The validator layer catches almost nothing

33 runs, 455 validator executions:

| validator | pass | warn | fail | skip |
|---|---|---|---|---|
| gherkin_style | 20 | **27** | 0 | 0 |
| evidence_discriminates | 9 | 1 | 0 | 1 |
| mutation_claimed | 8 | 0 | **1** | 25 |
| assertion_grounding | 25 | 0 | 0 | 8 |
| evidence_retrieved | 25 | 0 | 0 | 8 |
| provenance_supported | 24 | 0 | 0 | 9 |
| element_exists | 33 | 0 | 0 | 0 |
| event_coverage | 33 | 0 | 0 | 0 |
| gherkin_parses | 33 | 0 | 0 | 0 |
| no_placeholder_leak | 33 | 0 | 0 | 0 |
| selector_resolvable | 33 | 0 | 0 | 0 |
| suggestions_quarantined | 24 | 0 | 0 | 9 |
| no_pruned_assertion | 5 | 0 | 0 | 28 |
| **library_verbatim** | **0** | 0 | 0 | **33** |

**One failure in the project's history. Nine of fourteen have never produced a
non-pass. One has never executed at all.**

The validators are not expensive — they are deterministic and cost no tokens.
The cost is *conceptual*: fourteen gates is what makes this read as a compliance
system rather than a QA tool, and it is where design attention went that should
have gone to capture.

---

## 5. The critic/repair loop makes the output worse

| | A0 | A1 | A2 |
|---|---|---|---|
| assertions | 0 | **14** | 12 |
| grounded yield | — | **0.61** | 0.52 |
| tool calls | 0 | 47 | 63 |
| critic findings raised | 0 | 0 | 9 |
| findings resolved | — | — | **1** |

A2 costs 16 more retrievals than A1, asserts **two fewer things**, and resolves
one finding in nine — because five of the seven survivors are `coherence`, which
has no repair route by design.

`bind.py` is the opposite case and must not be cut: A0 produces **zero**
assertions. Binding is what produces expected results at all.

---

## 6. Roughly half the codebase has never run against a real recording

| feature | evidence |
|---|---|
| step library (`server/library/`) | `libraryRef` **never set** on any step, in any run; `_library.db` holds 2 rows; `library_verbatim` never executed |
| xlsx export | no `.xlsx` file exists anywhere in `runs/` |
| jira export / push | no payload ever produced |
| review UI edits | **0 edits recorded, ever**, across every `review.json` |
| §3.4 difficulty correlation | no data, and cannot have any without review edits |
| narration | present in **2 of 13** recordings (5 segments and 1) |
| tester annotations | **4 across all 13 recordings** |
| bug mode | 2 reports ever, after being unreachable for a whole phase |
| replay / runner | `executionRate: 0.0`, `meanSelectorRank: 0.0` — never run |
| coverage suggestions | **alive** — 82 produced, and the output is good |

This is not sloppiness. It is what happens when features are built from a spec
rather than from runs. It is the strongest argument for keeping the new system
small.

---

## 7. The judge already said the output is bad

`evals/LEDGER.md`, baseline 2026-08-26:

```
                        good  needs-work  bad
dev (7 fixtures)          3       2        2
held-out (3 real)         0       0        3
```

Nine of ten runs reported grounding rate 1.0. Six reported validator pass 1.0.

> The gate is doing its job and the author is not.

**This is the number to beat.** Any claim that the rebuild worked has to be
measured against it, on the same recordings, by the same judge.

---

## 8. What is NOT wrong

Worth stating, so a later session does not "fix" these.

**`digest.py` is the best-engineered thing in the pipeline.** 34 events and 50
seconds of a commercial site in ~1,600 tokens. The context-volume fear that
justified the six-stage retrieval architecture does not exist at this density.
Do not touch it. The loss is entirely at capture, upstream of digest.

**Draft-then-bind was the right ordering** and its reasoning survives — but see
§9: the reason it mattered was itself a symptom of the keyhole.

**The refusal semantics are the most sophisticated behaviour in the system.**
They just need evidence to work on, and they need to be visible.

**Structured output → rendered Gherkin is correct.** Each assertion has to carry
its evidence and there is nowhere in a `.feature` body to put it.

---

## 9. The diagnosis

Two statements, and the second is the one that decides what to build.

### There is no oracle

An oracle is whatever tells you what the app **should** have done, independent
of what it **did**. The pipeline has two inputs and neither one is an oracle:

1. **The recording** — says what the application *did*. By construction not an
   oracle.
2. **The objective** — real ones on disk: `"check if filters are working
   correctly"`, `"check if hamper sizes change correctly"`, `"check if i can add
   cafe products correctly to the bag"`. These name a *feature*, not a
   behaviour. `evals/LEDGER.md` notes it is *"the fourth 'correctly'/'working'
   objective to produce a bad run out of four"*.

The core rule — *a claim is admissible only if it can point at the retrieval
that produced it* — therefore guarantees the output can only restate observed
behaviour. **The tool is structurally incapable of producing a test that fails
on the build it recorded.** `verdict_fails_on_broken_build` being the largest
finding class is the architecture working as designed.

CLAUDE.md says *"grounding is provenance, not correctness"* as a metrics caveat.
It is not a caveat. It is the product boundary.

### The model is blind, not shackled

The instinct that the pipeline over-constrains the model is right about the
symptom and wrong about the cause. Nothing is shackling it. It was handed a
keyhole, and then 1,213 lines of `bind.py` and fourteen validators were built to
catch it guessing about what lay outside.

This distinction decides the fix. *"Remove the guardrails"* gets a fluent
hallucination machine — the model still cannot see the product list, it just
stops being stopped. **Open the aperture and most of the apparatus becomes
redundant, and gets deleted because it has nothing left to catch — not because
it was wrong.**

### Corroborating evidence: rules do not take, context does

Every recorded prompt experiment points the same way.

| change | result |
|---|---|
| Phase 1, simple prompt, **per segment** | seven `When`s in a row |
| fix: give the model **the whole session** | the current drafter |
| add rule *"assert the value that would BREAK"* | **1-of-3 uptake**, and it broke the splitter. Reverted |
| remove *"no tool calls is fine"*, add *"look before you write an expect"* | retrieval **0/8 → 0/8**; validator pass 1.000 → 0.889 |

**Every improvement in this project came from more context. Every content rule
added to a prompt had at-or-near-zero uptake.** `draft.py` is 1,067 lines and
the measurable return on the rules in it is not distinguishable from zero.

CLAUDE.md already knows this: *"worked examples outweigh rules, and will
contradict them silently."*

---

## 10. Positions taken, and what was rejected

**Deterministic vs agentic is the wrong line. The right line is: can this check
ever be wrong?**

- *Facts* — is this exact string in this exact response, does this parse, was
  every event used. Cost nothing, cannot be wrong, do not constrain the model.
  **Keep.**
- *Judgements* — is this claim vacuous, does this name match this scenario,
  would this catch a regression. Currently answered by **regexes**
  (`_existence_only`, `_unwitnessed`, `RESULT_CLAUSE`, `DISPLAY_CLAIM`). A regex
  guessing whether a sentence is meaningful will always lose to a model reading
  it. **Move to a model.**

**Self-critique in a loop does not work with the same model and the same
context.** Proven in this repo: A2's critic raised 9 and the loop resolved 1. A
judge with *fresh context and a different question* does work — `qa-judge` found
defects all fourteen validators passed. **The judge must not be the author.**

### Rejected

| idea | why not |
|---|---|
| *"Just tell the model to write good Gherkin, then check"* | The check has nothing to check against. That is how you get fourteen validators of increasing subtlety, each a doomed attempt to derive *should* from *did*. |
| Drop Gherkin for another format | It is the judged criterion. Keep it; use more of it (`Scenario Outline`). |
| A separate interviewer **agent** | A form with pre-filled guesses gets the same answer for one model call. Only worth an agent if it uses tools to ask a *specific* question. Revisit if the rest of the app turns out short on real agency. |
| MCP for the main pipeline | Own tools are cheaper, offline, cassette-able, and return exactly the right shape. Playwright MCP advertises ~25 tools — more tools means worse tool choice. |
| Worked examples drawn from own runs | Anchors the model to a past result instead of giving it a target. The project already learned this once — the critic's example *was the recording it judged*, and was rewritten neutral. |
| Requiring an expected result on every step | Only the **scenario** needs a verdict. `When … And … And … Then` is normal and often better. Make it a style setting. |

### Why Playwright MCP "didn't work"

The obvious idea is *let the agent test the app*. It fails on the oracle
problem: the agent can click everything and report what it saw, but cannot tell
you whether that was right. **A human recording themselves supplies intent.**
That is not a limitation of the design — it is what makes the output mean
anything.

MCP's real strength is elsewhere, and it was under-sold at first:

| | who | why |
|---|---|---|
| record | human, the extension | supplies intent — MCP cannot |
| author the test | agent, own tools | fast, offline, cassette-able |
| **run the test** | **MCP agent** | selectors like `#brxe-40688d > … > label:nth-of-type(1)` will break; a script fails, an agent re-finds the element |
| **find gaps** | **MCP agent** | sees the whole app; the recording cannot |

MCP owns everything that needs a **live page**. Own tools own everything about
the **recorded session**.

---

## 11. Open questions

1. ~~Do the unused parts have to stay?~~ **Answered: no objection to cutting
   them.** The per-item decision list is in
   [REBUILD_PLAN.md](REBUILD_PLAN.md) under *Decide at planning time*.
2. ~~Re-recording.~~ **Answered: a clean corpus is preferred over keeping old
   runs for comparison.** `evals/LEDGER.md` and
   `docs/GHERKIN_BEFORE_AFTER.md` are the only "before" that must survive — they
   hold the baseline the rebuild is measured against.
3. ~~Measure full-page snapshot cost before committing.~~ **Answered above: a
   full page is ~29 KB / ~7.4k tokens, which the large events already cost.
   Full capture is affordable.**
4. ~~Can a tester be asked to use the review UI?~~ **Answered: yes, a real
   tester is available.** Use them for two things, not one: the review edits
   (which unlock §3.4's correlation) *and* a first real test of the confirmation
   screen, which is the assumption the whole oracle layer rests on.
5. **Does the confirmation screen actually get used**, or do testers click
   through it? That decides whether the oracle layer works.
6. **How large are page-wide diffs in practice?** `evt_010` produced 813 changed
   nodes when the product grid re-rendered. That is real information, but a
   retrieval returning 800 nodes is not readable. The diff tool probably needs a
   summary form (*"the product grid replaced 24 items with 9"*) alongside the
   full list. Decide when building Stage 0.

---

## 11b. Corrections, from re-measuring before building (2026-08-28)

Stage 0 was built against this document, and four of its claims did not survive
being checked. The diagnosis holds -- the recorder was the problem, and opening
the aperture was the right call -- but three of the numbers used to argue it
were measuring something else.

### The "~29 KB full page" was a node cap, not a page

`MAX_NODES` was **400** (`extension/src/content/snapshot.ts`). Measured:

| recording | events | `truncated: true` on both sides |
|---|---|---|
| `rec_MT7MXBS9B2VB` | 34 | **30** |
| `rec_MTA7A2XHHH22` | 15 | **9** |

So SS1's *"a full page is ~29 KB / ~7.4k tokens -- which is already what the
large events cost today"* described the cap. **Raising the cap was not optional:
setting `full: true` while it stayed at 400 would have changed nothing on
exactly the pages that matter.** Worse, the budget is spent depth-first in
document order, so the cut lands at the bottom of the page -- where a product
grid lives. That is a second, independent way to record an empty candidate set,
and this document attributed all of it to scoping.

`scripts/capture_cost.py` exists so the number is never guessed at again. It
refuses to report a truncated recording's sizes as a measurement.

**Measured after the change**, at `MAX_NODES = 3000`, nothing truncating:

| corpus | per event |
|---|---|
| fixture app (7 recordings) | 5.5 - 7.2 KB |
| the keyhole storefront page | 10.7 KB |
| saucedemo, signed in | 8.5 KB |

Against 37-56 KB per event for the old **scoped** capture, which was hitting its
cap. Full capture is affordable -- but that is now a measurement rather than an
inference, and it is still a measurement of small pages. A commercial page stays
unmeasured until someone records one.

### "813 changed nodes" was a scope-instability artifact

SS1 cites `evt_010 | region | 29 KB | 813 changes` as evidence that a wide
capture yields rich diffs, and open question 6 asks how to summarise 800 nodes.
Measured:

```
evt_010  before.scopeRoot = region      after.scopeRoot = generic
evt_015  before.scopeRoot = region      after.scopeRoot = generic
```

`scopeRootFor` was re-evaluated for `after`. The click re-rendered the target's
ancestors, no landmark was found, it fell back to `document.body`, and every
node's `path` changed -- so `identity()` matched nothing and the diff read
**+408 added / -405 removed on a 405-node tree**. Noise, not the product grid.
Same shape on `rec_MT7MXBS9B2VB` evt_017/028/034, where a dialog's accessible
name empties on close.

There is a third mechanism in the same family, found while fixing it: the root
node was HOISTED when `body` had a single child, so appending anything to body
(a modal, a toast, a React portal) re-pathed the whole document. The root is
pinned now.

The honest data point for a genuine content change is `evt_006`: **+77 / -76**,
readable as it stands. So the diff summariser was built for legibility --
informative nodes first, exact counts always -- and not because of the 813.
**Open question 6 is answered: it was measuring a bug.**

### The origin allowlist does not block anything

SS10 and the plan's Stage 0 argue for inverting a gate that *"refuses to send"*.
`config/project.yaml` ships `origin_policy: warn`, `check_origins`
(`server/cli.py`) prints and returns, and the API path never refused at all.
There is still a tidy-up available; there is no daily friction to remove, and it
does not belong in a capture rewrite.

### The 214 parameters never reached the recording

SS3 says redaction *"eats the numbers a discriminating assertion needs"*. The
mechanism is real and the fix was right, but the damage was differently shaped:
**not one of those 214 placeholders appears anywhere in `rec_MTA7A2XHHH22`** --
the only 214 occurrences of `<<` in the file are the parameters array describing
itself. What the phone rule actually matches in page text is dates
(`"Updated 2026-08-28 14:32"`), not prices, which never reach its 9-digit floor.

So the harm was the artifact, not the evidence: 214 junk parameters flow into
the IR, the prompt, the feature file and the redaction preview a tester
approves. A test case with 214 parameters is unusable. `liveParameters` in
`export.ts` now drops any placeholder that points at nothing.

### And one thing this document did not know about

Capturing the whole page made a case reachable that scoped capture never saw:
**an application that displays a secret.** The fixture app's own login page
printed `Demo credentials: tester@example.com / hunter2`, which was outside
every scoped snapshot and is inside every full one. Half of it is closable --
`Redactor.redactKnownSecrets` replaces exact values already known to be secret,
so a "show password" toggle or a confirmation screen echoing an email is covered
-- and half of it is not: a secret the tester never types cannot be told from
ordinary page text. Pinned in `redact.test.ts`, and the fixture app stopped
printing its password.

---

## 12. Token and cost expectations

Honest, not optimistic.

- **Prompt tokens: roughly flat, possibly higher.** One long agent conversation
  re-sends its history every turn, costing about what fifteen short stages cost.
  Full-page snapshots are bigger than scoped ones. Deleting critic/repair/split
  saves ~6 model calls; richer tool results give it back.
- **Requests: down hard.** ~15 model calls per run → ~4–5.
- **Requests are the binding constraint.** CLAUDE.md already establishes this:
  the free tier limits *requests*, not tokens. Fewer, bigger, smarter calls is
  the right trade.
- **Cache the system prompt + example + digest.** That is the part re-sent every
  turn.
- **Screenshots are cheap** — roughly a thousand tokens each, fetched on demand
  when text evidence is thin. Two or three per run, not thirty. Do not cut them.

---

## 13. The claim to test

The rebuild is justified if, on the same recordings and by the same judge,
`evals/LEDGER.md` moves off:

```
held-out (3 real sessions):  0 good / 0 needs-work / 3 bad
```

Nothing else — not grounding rate, not validator pass rate — is evidence that it
worked. Both of those were already 1.0 while the output was bad.
