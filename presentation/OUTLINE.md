# Presentation outline — AITC, month 2

**Audience:** the QA team + one AI engineer.
**Slot:** 20–25 min speaking, questions after. Two presenters.
**Tone:** a product launch, not a status report. Benefit first, mechanism second.
**Slides:** 18 (16 of them carry speaking time; title and closing cost nothing).

**The frame for the whole deck:** same problem, second architecture — and the
first architecture is what told us what was wrong. Month 1 is the diagnosis, not
discarded work.

**The one sentence everything hangs off, and it appears twice (slide 5 and slide 18):**

> A claim is admissible only if it can point at the retrieval that produced it.

---

## Timing map

| | Slides | Owner | Approx |
|---|---|---|---|
| Act 1 — the problem and the ceiling | 2–4 | **A** | 3.5 min |
| Act 2 — the rebuild: what the tool sees | 5–8 | **A** | 5 min |
| Demo 1 — record a session (handoff) | 9 | **A** | 1.5 min |
| Act 3 — what happens to the recording | 10–14 | **B** | 6.5 min |
| Demo 2 — the output | 15 | **B** | 3 min |
| Act 4 — limits and what's next | 16–17 | **B** | 3 min |
| Close | 18 | both | 0.5 min |

≈ 23 min. Slide 14 is the one to shorten if you're running long; slide 4 and
slide 12 are the two that must never be rushed.

---

# PERSON A

## Slide 1 — Title

**On the slide:** the tool's name, both names, the date. Nothing else.

**Say:** one sentence only — "last time we showed you a tool that turns a
recorded browser session into a test case; this time we're showing you the one
we rebuilt, and why."

---

## Slide 2 — The problem (1 min)

**On the slide:** three lines, big.
- A QA tester writes a test case by hand: 10–20 minutes.
- They already did the work — they clicked through the flow.
- The field they judge the result by is the assertion. The `Then`.

**Say:** the tester's session already contains the test. The cost is
transcribing it into the format the team uses. And the part that decides whether
the output is worth anything is not the steps — anyone can list clicks — it's
whether the expected result is *true*.

**Note:** this slide is deliberately identical in both architectures. Say so.
It's what makes the comparison on slide 4 legible.

---

## Slide 3 — Month 1: what shipped (1 min)

**On the slide:** a short honest list of what the first tool actually did.
- Chrome extension records the session; nothing is lost — stored raw before any
  model runs
- Structured test case in the database, never a formatted string — Gherkin,
  Excel and Jira are renderings of one shape
- A **dashboard** (new since the first presentation) — review, edit, export,
  and every edit kept as a new version
- A deterministic critic raising advisory review questions
- A three-pass pipeline (analyse → author → judge), not one blind call
- An evaluation set, so changes were measured rather than eyeballed

**Say:** be generous here. It worked end to end, it was verified live against
real Jira and a real model, and the second half of month 1 added the dashboard,
versioning and the critic — real progress on the first presentation. This slide
exists so the next one isn't read as "the first attempt was bad".

---

## Slide 4 — The ceiling (1.5 min) — *the hinge of the deck*

**On the slide:** one root cause, stated once, large.

> The model was **told about** the session, in a text log.
> Nothing could check whether what it wrote was **true of the recording**.

Then three consequences, small:
- The assertion had one thin source — the narration — and gaps got filled by
  inventing
- The two defences were a regex critic and a second model's opinion. Both
  advisory. Neither could reject anything
- No amount of prompt tuning reaches this. It's structural

**Say:** this is the slide to slow down on. The first tool's failure wasn't a
bad prompt or a weak model — it was that there was no way, even in principle, to
ask "did that actually happen?" We could check the *shape* of the output. We
could not check the *truth* of it. Everything on the next twelve slides exists
because of that one sentence.

---

## Slide 5 — The rebuild (1 min) — *the launch slide*

**On the slide:** the name, and the rule. Nothing else on it.

> **A claim is admissible only if it can point at the retrieval that produced it.**

**Say:** "which is why we decided to rebuild it — and this is AITC." Then read
the rule out loud, slowly. Explain it in one breath: the tool is not allowed to
write an expected result unless it can name the thing it looked at, and we
re-check that thing. Not "the string was somewhere in the recording" — that's a
weaker, different check. It has to point at the *retrieval it made, in this run*.

Everything from here is either (A) making sure there's something worth looking
at, or (B) enforcing that rule.

---

## Slide 6 — What it sees: the accessibility tree, not the DOM (1.5 min)

**On the slide:** a small side-by-side. Same button, two representations.
- DOM: a wall of class names, wrapper divs, CDN URLs
- Accessibility tree: `button "Add to basket"`

**Say:** the old tool scraped text out of the DOM and tried to describe elements
from markup. The new recorder reads the accessibility tree — the same structure
a screen reader uses. Three reasons that's the right layer:
- It's what a *tester* would say: "the Add to basket button", not `div.btn-primary--lg`
- It's stable. A CSS refactor changes the DOM and doesn't change the a11y tree
- It's already meaning, not markup — no extraction step to get wrong

And it's **black-box**: we read the live tree, we need no access to the app's
source. A `data-testid` is used when it's there, but the normal case is role +
name. Nothing about this asks the application under test to cooperate.

**Asset:** one screenshot of a real a11y node next to the raw HTML of the same
element.

---

## Slide 7 — The page, not the keyhole (1.5 min) — *A's strongest number*

**On the slide:**

> **30–50%** of events on real sites recorded **no observed change at all.**

Plus a before/after sketch: previously we captured the landmark region around
the clicked element; now we capture the whole page, from a fixed root, before
and after every action.

**Say:** the tool used to capture only the part of the page around the click.
Sounds reasonable — it isn't. A tester clicking a filter widget captured the
filter widget, while the product list they were actually testing was never
captured at all. On real sites that was a third to a half of every event with no
evidence behind it, which meant the model had nothing to look at and guessed.

Two things fixed it: capture the whole page, and capture before and after from
the **same fixed root**, so the two are comparable by construction. Now every
action carries a real answer to "what changed when I did that?"

**If asked why this wasn't obvious:** the numbers that justified the narrow
capture were measuring a size cap, not real pages.

---

## Slide 8 — What never leaves the browser (1 min)

**On the slide:** three items.
- **Redaction happens in the page**, before anything is stored. There is no path
  that writes a raw value to disk and cleans it up later
- **The tester chooses the level**, in the recorder — not in a config file on
  the server. By the time a server could read a setting, the decision has already
  been made and can't be revisited
- **The objective**: one sentence, typed before recording. The strongest signal
  the tool ever gets, and the one thing it can never observe for itself

**Say:** passwords are redacted in the browser; the real characters reach
neither our disk nor the model. The level is per-recording because one session
of a demo app and one of a system whose order numbers look like card numbers are
genuinely different situations, and the person who knows which is which is the
tester, at the moment they press record.

The objective matters more than it sounds: a sharp one ("an expired coupon is
rejected at checkout") produces a good test; a vague one ("check the filters
work") produces a test about the *mechanism* instead of the outcome. The tool
tells the tester which one they've typed, as they type it.

---

## Slide 9 — Demo 1: record a session (1.5 min) — *the handoff*

**On the slide:** nothing. Switch to the browser.

**Do:**
1. Type an objective sentence — let them see the tool react to it
2. Press record, click through 4–5 steps of the demo app
3. Say one sentence out loud (narration)
4. Press Stop

**Say, as the last line:** "…and that recording is what my colleague's half now
receives." → hand over.

**Prep:** demo app already open, extension already loaded, popup pinned, mic
permission already granted. Rehearse this cold; it is 90 seconds and it must not
become three minutes.

---

# PERSON B

## Slide 10 — The map (45 sec — do not linger)

**On the slide:** the whole chain, one diagram, left to right:

```
recording → session index → expectations → AUTHOR → gate → judge → .feature / Excel / Jira
            (code)          (asks the      (agentic)  (code) (agentic)
                             tester)
```

Colour-code deterministic vs agentic.

**Say:** deterministic wherever possible, agentic only where it's necessary. The
first two boxes are plain code — they build an index of the session and guess
what *should* have happened so the tester can confirm it. Nothing surprising
there. The interesting part is the middle three, and that's what I'll spend my
time on.

**Reuse:** this same diagram appears as a small dimmed strip along the top of
slides 11–13 with the current box lit. It's the audience's "where are we"
anchor — don't draw it again, shrink it.

---

## Slide 11 — One author, six tools (1.5 min)

**On the slide:** the six tools as icons/labels, and the loop:
**decide → retrieve → observe → decide again.**

**Say:** one model writes the whole feature file, in one conversation, with the
entire session in front of it — and it can **go and look** while it writes. Six
tools: what changed at this step, the full page, a screenshot, a text search,
the network traffic, the narration.

Two things worth knowing:
- It **writes the Gherkin itself.** It used to emit JSON that a script assembled
  into a feature file, which meant no model in the pipeline had ever seen a
  feature file — and the output read exactly like something assembled from parts
- It **decides what's worth checking first, then retrieves to prove it.** An
  agent that may only claim what it happens to have already looked at writes
  about whatever was easiest to fetch

This replaced five separate stages from the old design. Those stages existed to
catch a model guessing about things it couldn't see — and once the recorder
started capturing the page, most of them had nothing left to catch.

---

## Slide 12 — The gate (1.5 min) — *do not rush this one*

**On the slide:** the mechanism in three steps.
1. The author names a **literal** it says it saw — never an id, never a citation
2. We search the retrievals it **actually made**, re-hash the stored response,
   and confirm the literal is really in it
3. We also check it against the recording itself, independently

**Say:** the key design decision is that the author never supplies the reference.
It quotes a value; *we* go and find which retrieval contains it. **A fabricated
citation is not something the model can express** — there's no field for it to
lie in.

And it's two independent checks, not one: what the agent was shown, and what's
true of the session. Seeing something in the summary we handed it isn't enough
— a summary points at nothing. It has to have come back from a tool.

**If asked what it can't do:** it proves *provenance*, not correctness. It
guarantees the claim came from something really observed. It can't tell you the
tester was testing the right thing. Say this before they ask it.

---

## Slide 13 — Refusals, and the judge (1.5 min) — *the trust slide for QA*

**On the slide:** a real refusal, quoted verbatim from a run. Something like:

> Could not check that the product list narrowed to 9 items — the list was never
> captured before or after this click.

Then, below: **the judge** — reads the finished document with fresh context,
never the author's reasoning, and asks whether a QA lead would sign it.

**Say:** this is the part I'd point at if you only remember one thing. When the
tool can't prove something, it **says so, in words you can act on** — it doesn't
quietly drop the assertion and hand you a scenario that checks nothing. The old
tool had no way to express that. A test case with no `Then` and a test case
whose `Then` was invented look identical on the page.

Then a second model — with no access to how the first one reasoned, because a
model shown its own justification defends it — reads the finished feature file
and flags what a QA lead would send back. Including: does this sentence claim
more than its evidence shows, and **is the refusal itself true**. That last one
matters because a refusal passes every automated check by definition — it claims
nothing — so it's the one output that would otherwise be confident and entirely
unchecked.

---

## Slide 14 — Where it all surfaces (1–1.5 min)

**On the slide:** screenshot of the review screen, three things annotated.
- Each step, and the evidence behind each verdict — click through to what was retrieved
- What was refused, and why
- The judge's findings, on the step they're about

**Say:** everything on the last four slides is only worth something if the
reviewer can see it. The review screen shows, per step, what was retrieved and
what licensed the claim; the refusals in plain language; and the judge's
findings attached to the step they concern rather than as a score at the top.

Deliberately, there's **no green badge**. A pass count that has never once been
anything but green isn't information. What's shown is the numbers that can
actually move.

**Asset:** one clean screenshot with three callouts. Don't tour the UI live —
that's what the demo is for.

---

## Slide 15 — Demo 2: the output (3 min)

**On the slide:** nothing. Switch to the machine.

**Do, in this order:**
1. The run that came out of A's recording (or a pre-baked one — decide by clock)
2. The `.feature` file. Read one scenario out loud
3. **One proved verdict** — click through to the retrieval behind it
4. **One refusal** — the thing the tool declined to claim
5. **`--replay`** — the generated test case driven against the live app, going green

**Say, on step 5:** this is the strongest check in the system. Not "does the
output look right" — does the test case we just wrote actually run.

**Prep:** app running, run already computed, terminal font large, the replay
command already typed and ready. Have a screen-recorded fallback for step 5.

---

## Slide 16 — Limits (1.5 min)

Three groups. Lead with the quota one, because it's the ask.

**On the slide:**

**1. The model tier is the binding constraint**
- Free tier limits are *requests*, not tokens: the good model is **5/min and
  20/day** — one recording exhausts a day. The default is a lite model because
  it's the only workable one, not because it's the right one
- Free-tier prompts are **training-eligible and human-reviewable**, so the tool
  **refuses to send** anything but a demo or public app. Pointing this at a real
  internal application needs a paid endpoint with a no-training term
- Real pages cost ~20× the demo app: **150–172 KB per event** vs 5–10 KB, and one
  full-page retrieval is **16–18k tokens**. One real session came to **168,690
  prompt tokens against ~29,000** for a fixture run

**2. The assertions aren't always meaningful yet**
- One line only: *the tool can bind a verdict to a value that's technically
  present but not specific — it now grades that rather than hiding it, and
  feeding the grade back to the author is the next step.*

**3. We haven't tested it enough to claim it's good**
- Not enough time and not enough quota to run the volume of sessions that would
  settle it. The architecture is right; the output quality is **not yet proven**,
  and we're not going to present a green chart as if it were

**Say on group 1:** this is the concrete ask. The quota isn't a nuisance — it
decides what we're *allowed to point the tool at*. The origin restriction is a
policy consequence of the free tier, not a technical limit, and a paid endpoint
lifts it.

**Say on group 3:** say it plainly and don't over-apologise. In front of an AI
engineer, "we know what we haven't measured" is worth more than any dashboard.

---

## Slide 17 — MCP (1.5 min)

**On the slide:** three beats.

**1. What was asked for** — use an MCP server (Playwright MCP, Chrome DevTools
MCP) so the agent drives a live browser.

**2. Why those don't fit this tool**
- They drive a **live** browser. Every claim here is checked against a
  before/after pair from a session that already happened. A live agent can't
  retrieve the past — there's nothing to re-check it against
- Their retrievals happen outside our runner, so nothing is stored and nothing is
  hashed. The gate would refuse *every* claim, and the one rule quietly becomes
  decorative
- More tools measurably means worse tool choice. An MCP browser server drops 20+
  tools into the registry at once

**3. The idea — suggestions, not claims**
A live-browser agent can't be evidence-bound, so don't let it make claims — let
it make **suggestions**. The tool already has a channel for exactly that:
suggestions live in their own block, render under an **UNVERIFIED** heading, and
are blocked at the gate from ever becoming assertions. So the live agent explores
the app and proposes additional cases; a human promotes the ones worth keeping;
the rule never bends.

**Say:** "I was asked whether we could use MCP, and the honest answer is that
the obvious version breaks the one thing this tool is built on — so here's the
version that wouldn't. It's designed, not built; there wasn't time."

Close with: there's exactly one seam it would go through, and the architecture
already has the hole shaped for it. What's missing is time, not a design.

---

## Slide 18 — Close (30 sec)

**On the slide:** the rule again, and "thank you — questions".

> A claim is admissible only if it can point at the retrieval that produced it.

**Say:** month 1 built a tool that could write a test case. Month 2 built one
that can't write a test case it can't back up. Thank you.

---

# Assets to prepare

| # | Asset | Owner |
|---|---|---|
| 6 | Screenshot: a11y node vs raw HTML, same element | A |
| 7 | Before/after sketch: keyhole vs full page, fixed root | A |
| 9 | Demo environment: demo app + extension loaded + mic granted | A |
| 10 | Pipeline diagram, full slide + dimmed strip variant | B |
| 13 | A real refusal, quoted verbatim from a run | B |
| 14 | Review screen screenshot, three callouts | B |
| 15 | Pre-computed run + replay ready; screen-recorded fallback | B |

# Rehearsal notes

- **Both demos are on a clock.** 1.5 min and 3 min. Rehearse them cold, twice.
- **Slide 4 and slide 12 are the two that carry the argument.** If you're
  running long, take it out of slides 3, 8 and 14 — never those two.
- **Don't present any metric as proof of quality.** A grounding or pass rate of
  100% is vacuously 100% when the tool abstains. If a number goes on a slide, the
  number that qualifies it goes next to it.
- **Questions you should expect:** "how long does it take a tester?" (about 40
  seconds of deliberate effort per recording), "what if it's wrong?" (the
  reviewer is the final authority; nothing is auto-filed), "can we point it at
  our app?" (that's slide 16, group 1), "why not just use an existing MCP?"
  (slide 17).
