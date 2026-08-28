# The rebuild: what to build, in order

The plan agreed on 2026-08-27/28. The evidence behind every decision here is in
[REBUILD_FINDINGS.md](REBUILD_FINDINGS.md) — **read that first if you are about
to argue with a decision below.**

The one-line version:

> The pipeline asks *"what can I prove?"* and writes a test around the answer.
> A tester asks *"what should happen?"* and goes to check. Flip that question
> and the architecture falls out.

Three things change, and everything else follows:

1. **The recorder captures the page**, not a keyhole around the click.
2. **The tester supplies intent**, in one screen of clicking.
3. **One agent** with real evidence replaces five stages of refusal machinery.

---

## Stage 0 — Fix capture

**Nothing else matters until this is done.** On 30–50% of events on real sites
the pipeline currently records no observed change at all, so the agent has
nothing to look at and the assertions it writes are restatements of the click.

The mechanism is exact: `scopeRootFor` walks to the nearest landmark, so
clicking in the page body captures 29 KB and hundreds of changes, while clicking
*inside the control that causes the change* captures 1.2 KB and an empty diff.
Which is most of what testing is.

- **One full-page semantic snapshot at the start of the session.**
- **Per event, store what changed** against the previous page state — page-wide,
  not scoped to the clicked element. This diff **is** the candidate set for
  assertions.
- **Keep the small scoped subtree** around the target. It is cheap and it is
  what selectors are built from.
- **Screenshots move into the evidence path**, not the thumbnail path.
- **Redaction: input and sensitive keys only. Never scan page content.** Roughly
  20 lines. Put it behind a config flag so a controlled environment can turn it
  off entirely.

**Cost: measured, and it is nearly free.** A full page is ~29 KB / ~7.4k tokens
— already what the large-scope events cost today. Full capture adds ~7k on the
few small-scope events per recording, and that is *stored* data; only what the
agent retrieves reaches the model.

**One thing to decide while building this:** `evt_010` produced **813 changed
nodes** when the product grid re-rendered. A retrieval returning 800 nodes is
not readable. `get_diff` likely needs a summary form — *"the product grid
replaced 24 items with 9"* — with the full list available on request.

**This invalidates all 13 recordings, `runs/`, the cassettes and the eval
baseline.** That is accepted — a clean corpus is preferred. The only "before"
that must survive is `evals/LEDGER.md` and `docs/GHERKIN_BEFORE_AFTER.md`, which
hold the baseline the rebuild is measured against.

### Also in Stage 0: the origin allowlist guards the wrong thing

`config/allowed_origins.yaml` refuses to send a recording whose origins are not
on a list. The stated reason is correct — free-tier prompts are
training-eligible and human-reviewable — but the check is on **which site was
recorded** when the real risk is **where the prompt goes**. Recording a real
e-commerce site is perfectly safe against an endpoint carrying a no-training
term, and the allowlist blocks it anyway.

**Invert it: gate on the model endpoint, not the origin.**

- Paid / no-training endpoint → no origin restriction at all.
- Training-eligible endpoint → warn, name the origins, let it through.

`origin_policy` in `project.yaml` is already the seam. This is a small change
and it removes a daily friction that has no security value in its current form.

---

## Stage 1 — The oracle

A test needs to know what *should* have happened. Neither the recording nor
`"check if filters are working correctly"` contains that. Four layers, cheapest
first.

**1. A better objective box.** Not a docs page — an example in the field the
tester is typing into:

> ❌ `check if filters are working correctly`
> ✅ `Selecting "In stock" should cut the list from 24 products to only available ones`

Both are from real recordings. Most of the problem dies here for free.

**2. The model guesses.** After recording, it reads the session and writes what
it thinks should have happened. Guessing is fine — testers are busy and the
guesses are decent.

**3. One confirmation screen.** The important part. **Do not ask open
questions** — testers will not answer them. Show the guesses:

> **You filtered by "In stock."**
> [before image] → [after image]
> The list went from 24 products to 9.
> Was that right?  `✓`  `✗`  `edit`

Clicking is cheap. Writing is not.

**4. Label where each expectation came from** — `stated` by the tester,
`confirmed` by the tester, or `inferred` by the model. Inferred ones get
`@needs-review`. The project already does provenance for evidence; do it for
intent.

No separate interviewer agent. One screen, pre-filled. (Revisit only if it would
genuinely use tools to ask a *specific* question.)

**Worth building if there is time:** read acceptance criteria **from** Jira. The
oracle is already written, by a human, in the ticket the tester is working from.
The tool currently pushes issues out and reads nothing in.

---

## Stage 2 — One author

Replaces `draft.py` + `bind.py` + `split.py` + `_second_chance` + `bugmode.py`.

**Context: the map. Tools: the territory.**

- **In context** — the session index (`digest.py`, ~1,600 tokens for 34 events)
  and the tester's expectations. Every event, what it was, roughly what changed.
- **Via tools** — the detail:

```
get_diff(event)         what changed on the page
get_snapshot(event)     full page state, before or after
see(event)              the screenshot — it can look
find(text)              search the whole session
get_network(event)      requests
get_narration(range)    what the tester said
```

Six tools, not twelve. Why not put everything in context: screenshots and full
snapshots across 30 events are large, and an agent that has everything stops
*choosing* — which kills both the agency and the effort signal. Why not tools
only: it would not know what exists, and its first calls would be blind and
identical every run.

**The loop is exactly what it sounds like:**

```
system:  You are a QA tester. Turn this session into test cases.
         Here is the output format. Here is one worked example.
user:    [session index]  [what the tester expected]
tools:   the six above

model → get_diff("evt_009") → result → see("evt_009") → image
      → … → outputs the document
```

**It writes the whole document** — feature, scenarios, steps, keywords, scenario
breaks, expected results — with the evidence beside each claim:

```json
{ "step": "the tester filters by \"In stock\" products",
  "keyword": "When",
  "events": ["evt_006", "evt_007"],
  "expected": "the product count drops from 24 to 9",
  "evidence": { "event": "evt_009", "literal": "9 produits affichés" } }
```

Gherkin is **rendered** from this. Same words; this form can be checked, edited
in the UI, and printed in three styles. `narrative.py` stops re-deciding
keywords the author already chose.

**Refusal becomes something the author writes**, not something done to it:

```json
{ "step": "the tester sorts products by price",
  "expected": null,
  "why_not": "The product list was never captured before or after this click.
              Nothing here shows the order changed." }
```

Today `bind.py` deletes the claim and the scenario silently ends with no `Then`.
The new form explains itself, so the tester can act on it.

**A failed expectation is a bug report.** *"Expected 9 products, saw 24"* is the
same sentence either way — a flag on a result, not a separate stage. This is
what makes the tool able to find bugs, which it currently cannot except through
bugmode's narrow 5xx trigger.

### The prompt

**Roughly 70% worked example, 30% instruction.** Every content rule added to a
drafting prompt in this project's history had at-or-near-zero uptake; every
improvement came from more context.

- **One fresh, neutral worked example** — a domain none of the recordings touch
  (a library booking system, say). One good scenario end to end: steps, one
  verdict, evidence attached. **Not** drawn from an existing run — that anchors
  the model to a past result instead of giving it a target.
- Rules only for the genuinely counter-intuitive: *an expected result says what
  the application did, not what you did.*

### Gherkin styles

Config in `project.yaml`, one prompt variation each. Same recording, three
outputs — a good demo in itself.

| style | shape | for |
|---|---|---|
| **Business** | few steps, plain language, one `Then` at the end | stakeholders |
| **Automation** | every action, specific values, checks more often | engineers writing step definitions |
| **Data-driven** | `Scenario Outline` + `Examples` where the flow repeats | repeated flows |

**Not every step needs an expected result — only the scenario needs a verdict.**
`When … And … And … Then` is normal.

The data-driven style is probably the single biggest Gherkin-quality win
available. Recordings that repeat a flow with different values currently come
out as near-identical scenarios; as an outline they read as *test design* rather
than a transcript:

```gherkin
Scenario Outline: Hamper upgrades when capacity is reached
  When the tester adds <items> items
  Then the hamper is a "<basket>" with capacity <capacity>

  Examples:
    | items | basket               | capacity |
    | 13    | Medium Wicker Basket | 13 / 13  |
    | 18    | Large Wicker Basket  | 18 / 18  |
```

---

## Stage 2b — Multi-tab (smaller than it looks)

§18 milestone 21, never built, and long assumed expensive. It is not: the
infrastructure is already in place and **the hard part is already solved.**

Already there:

```json
"host_permissions": ["<all_urls>"],
"content_scripts": [{ "matches": ["<all_urls>"], "all_frames": true }],
"permissions": ["tabs", "webNavigation", …]
```

The content script is injected into **every** tab. The service worker already
reads `sender.tab?.id` on every event. And `performance.now()` is per-document,
already converted through `timeOrigin` — **ordering events from separate
documents on one clock is the expensive problem in multi-tab, and it is done.**

What is missing is small:

- `session.tabId` is a single number and `broadcast()` messages only that tab.
  Make it a set.
- Follow `chrome.tabs.onCreated` when a tab is opened from a recording tab, and
  start recording in it.
- Store the tab id on each event — already available, just not kept.
- Tell the digest that a tab changed, so the author does not write *"the tester
  continued"* when a payment window opened.

Diffs need no special handling: the snapshot is built by whichever tab's content
script fired, so a tab switch naturally means the next before/after come from a
different document.

**The recorder is pinned to one tab by choice, not by limitation.** This is
mostly removing a restriction. Sequence it after Stage 2, once the author works
— real flows (payment providers, PDFs, confirmation pages) open tabs, so
"works on a real session" is not true without it.

---

## Stage 3 — Facts (deterministic, four checks)

**Keep a deterministic check only where it cannot be wrong.**

```
each cited literal really occurs in the cited response
every event lands in a step, or in an explicit "skipped, because…"
the file parses as Gherkin
no redaction placeholder leaked
```

A **literal** is the exact text an assertion rests on — `"9 produits
affichés"`. The check re-reads the response the model got back and confirms the
string is in it. That is how you know the claim was not invented, and it is the
one rule worth keeping above all others.

**Every event once** — the half that matters is *at least once, or explicitly
skipped*: nothing the tester did silently disappears. The *at most once* half is
a nicety; drop it if it fights the author.

Failures go straight back to the author.

**Everything else moves to the judge.** A regex guessing whether a sentence is
meaningful will always lose to a model reading it.

---

## Stage 4 — The judge

`evals/RUBRIC.md` and `.claude/agents/qa-judge.md` already exist. This is a
**promotion**, not a new invention: reimplement the same rubric as a normal
model call inside the pipeline.

| | critic (today) | judge |
|---|---|---|
| sees | pipeline state, the author's work | only the finished document + evidence |
| asks | is this coherent | **break the feature — does this still pass?** |
| output goes to | a routing table deciding which stage re-runs | back to the author as feedback |

**The judge must not be the author.** Fresh context, different prompt, does not
see the author's reasoning. Self-critique with the same model and same context
does not work — proven here: A2's critic raised 9 findings and resolved 1.

The honest risk: rename the critic and change nothing and you get the same
1-of-9. What makes it work is the question, and that question exists only
because someone measured real output against real recordings.

**The judge's findings never reach the tester.** No `coherence: weak` in the UI.
If the author could not fix something, it becomes plain language — *"this
scenario has no verdict because the list was never captured"*.

---

## Stage 5 — Revision

The judge's findings go back to **the author**, which decides what to change. It
wrote the document; it knows which part is wrong.

**No routing table.** `VALIDATOR_REPAIR` and `CRITIC_REPAIR` are exactly the
machinery this rebuild is removing.

Maximum two rounds, then stop.

---

## Stage 6 — Execute

The strongest check available, and the only claim in the system nobody can
argue with.

**6a — the simple runner first.** `server/runners/playwright.py` is mostly
written and has never produced a measurement. Generate the test, run it, report
which assertions held. Get one green `executionRate` even if the rest runs out
of time.

**Authenticated sites need one addition: saved session state.** The real target
apps have logins, and every recording on disk today is a public site without
one. Two pieces, both cheap:

- **Credentials at replay time already exist** — `--replay-param
  password=hunter2`. The recorder redacts the typed value to a placeholder and
  replay substitutes the real one. Nothing to build.
- **Session state does not.** Playwright's `storageState` is the standard
  mechanism: log in once, save the resulting cookies and local storage to a JSON
  file, and hand that file to every later run so it starts already signed in.
  Without it, every replay has to walk the login flow, which is slow, brittle,
  and can trip rate limits or MFA.

Keep the file out of git (same treatment as `.env`) and regenerate it when it
expires. This is roughly half a day and it is what makes replay possible against
the apps the team actually tests.

**6b — then the MCP agent.** The recorded selectors look like this:

```
#brxe-40688d > div.jet-smart-filters-checkboxes.jet-filter > div.jet-checkboxes-list
  > fieldset… > div…:nth-of-type(1) > label… > input.jet-checkboxes-list__input
```

That is a page-builder ID. It breaks the next time anyone edits the page, and a
script replaying it fails and reports nothing. An MCP agent reads the live page,
looks for *"the In stock checkbox"*, finds it after the markup changed, and
checks whether the count went to 9.

That is the difference between `executionRate: 0` and a number worth showing —
and it answers *"why does this need an agent?"* for the automation audience.

---

## Stage 7 — Coverage, with a live page (optional, last)

`coverage.py` works today and its output is good:

> *"record the behavior when removing items to drop below the upgrade
> threshold"* — the test confirms upgrade but not downgrade.

But it can only suggest what it can see in the recording. Everything the tester
did not scroll past is invisible.

With a live browser:

- **Easy and real:** see the whole app, not just what was recorded. On the
  storefront it would find the price slider, the brand filter, the out-of-stock
  option — none of which appear in any snapshot.
- **Real and valuable:** confirm a suggested path actually exists before
  proposing it — a checked finding instead of a guess.
- **The stretch goal:** actually walk the untested path and turn the suggestion
  into a finished test case. Needs login state, test data and a safe
  environment. Do not plan around it.

This is last because it depends on everything before it and fails gracefully:
without it the tool still works, you just do not get verified suggestions.

---

## UX

Three surfaces, two of them with a new job.

**1. Extension — record only.** Start, stop, mark a moment. Already close.

**2. After stop — the confirmation screen.** The most valuable screen in the
product, and it does not exist yet. Today this slot holds a "summary". It should
hold Stage 1's `✓ / ✗ / edit` over screenshots, at the one moment the tester
still remembers what they were doing.

**3. The result page.** Test cases, readable, screenshots beside each expected
result. Today this shows validators, warnings and tool call counts — a console.
The tester should see their work reflected back, not the pipeline's insides.
Technical detail goes behind a "details" toggle.

**Dashboard: a list of past runs.** That is all it needs to be.

### The how-to page

One page, two sections, **written from what actually works — not from
SPEC.md.** Half the codebase has never run; a how-to written from the spec would
document features that do not exist. Write it after the rebuild.

- **For testers:** how to record well. Four or five things — write a real
  objective, say what you expect out loud, mark what matters, confirm the
  guesses.
- **For the QA lead (and for you):** every feature, what it is for, how to reach
  it.

---

## Where agency earns its place

Four spots where a stronger model directly improves the product, with no code
change. This is the answer to *"does the AI earn its place here?"*

1. **How hard to look.** An obvious step gets one call; a contested one gets
   fifteen. That variance is real and already measured (`effortSpread` ≈ 1.0).
   No fixed pipeline can do it.
2. **Looking at pixels when the text fails.** When the accessibility tree does
   not say whether the list re-sorted, the screenshot does. No deterministic
   system can do this at all.
3. **Judging whether a test would catch a bug.** Not computable by any rule.
4. **Refusing, and explaining why.** Already the best behaviour in the system —
   it just needs evidence to work on, and needs to be visible.

---

## Keep / cut

### Cut

| | why |
|---|---|
| `server/library/` | `libraryRef` never set once; db holds 2 rows; `library_verbatim` never executed. It solved a problem created by the old per-segment naming stage, and it caused the mandatory-tool-call pattern that flattened effort spread. |
| `split.py` | The author sees the whole session and splits as it writes. Also documented as returning one group and two on the same recording. |
| `repair.py` routing tables | The author revises its own document. |
| `_second_chance` | The author's own loop covers it. |
| 10 of 14 validators | One failure in the project's history; nine never produced a non-pass. |
| `bugmode.py` **as a stage** | A failed expectation *is* a bug report. Merge into the author. |
| narration's confidence ladder | `_confidence` / `supports_narrated` / the provenance rank exist because narration was used as *evidence*. Point it at intent and they are unnecessary. Keep recording and transcription. |

### Keep

| | why |
|---|---|
| `digest.py` | The best-engineered thing here. ~1,600 tokens for 34 events. Do not touch. |
| Excel export | Many QA teams live in spreadsheets — for part of the audience that file *is* the deliverable. Cheap, and the `base.Exporter` seam exists. **Test it.** |
| Jira export (build the issue) | Cheap. |
| Jira push (send it) | Keep if it works; do not invest more. Mostly theatre in a demo. |
| coverage suggestions | The one optional feature that actually runs, and MCP upgrades it. |
| DevTools importer | Cheap, and "you can import an existing recording" is a good line. |
| `runners/playwright.py` | The strongest check in the system. |
| review UI | Promoted from a side feature to core — it is where the oracle confirmation lives. |

### Decide at planning time — never ran, cut unless there is a reason

These are built, documented, and have **never executed against a real
recording**. Evidence for each is in
[REBUILD_FINDINGS.md §6](REBUILD_FINDINGS.md). The owner has no objection to
cutting them; the only thing that would justify keeping one is a spec § number
that is itself a deliverable. Decide each explicitly rather than letting them
survive by inertia.

| | status | recommendation |
|---|---|---|
| `server/library/` (step library) | `libraryRef` never set once; db holds 2 rows; `library_verbatim` never executed | **cut** — it solved a problem the old per-segment naming stage created |
| xlsx export | no `.xlsx` ever produced | **keep, but test it** — spreadsheets are the working format for much of the audience |
| jira export (build issue) | never produced a payload | **keep** — cheap |
| jira push (send it) | never sent | **keep if it works**, invest nothing further |
| `bugmode.py` as a stage | 2 reports ever | **cut the stage**, keep the capability (a failed expectation *is* a bug report) |
| narration confidence ladder | narration present in 2 of 13 recordings | **cut the ladder**, keep recording + transcription, point it at intent |
| tester annotations | 4 across all 13 recordings | **keep the mechanism** — it is an oracle source that was never taught to testers. Covered by the how-to page. |
| multi-tab capture (§18 m21) | never built | **decide** — see open question below |

### Build that does not exist

- The confirmation screen (Stage 1).
- Reading acceptance criteria **from** Jira.
- The how-to page.

---

## Order of work

```
0   fix capture + redaction scope       ← nothing else matters first
    invert the origin gate (endpoint, not origin)
    re-record the corpus
1   oracle: objective hint → guess → confirmation screen → intent labels
2   one author, six tools, fresh worked example, three styles
2b  multi-tab (mostly removing a restriction)
3   four deterministic checks
4   judge (promote qa-judge into the pipeline)
5   revision, max two rounds
6a  simple runner + storageState → one green executionRate
6b  MCP adaptive execution
7   MCP coverage exploration
    UX passes alongside 1 and 2
    how-to page, written from what works
```

**Get a real tester in front of it twice** — once on the confirmation screen
(Stage 1), which is the assumption the whole oracle layer rests on, and once on
the review UI, which unlocks §3.4's correlation. Zero review edits have ever
been recorded.

---

## How to know it worked

`evals/LEDGER.md`, baseline of 2026-08-26:

```
held-out (3 real sessions):  0 good / 0 needs-work / 3 bad
```

**That is the only number that counts.** Grounding rate and validator pass rate
were already 1.0 while the output was bad, and the same trap has now appeared in
six columns of this project's metrics — assume it is in the next one too.

Re-run the judge on the same recordings after the rebuild. If that row does not
move, the rebuild did not work, whatever else improved.

### What to expect on cost

- Prompt tokens: roughly flat, possibly higher — one long conversation re-sends
  its history each turn.
- **Model requests: ~15 → ~4–5 per run.** Requests are the binding constraint on
  the free tier, so this is the trade that matters.
- Cache the system prompt, the example and the digest.
- Screenshots are cheap (~1k tokens, fetched on demand). Do not cut them.
