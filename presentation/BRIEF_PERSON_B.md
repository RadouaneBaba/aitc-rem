# Person B — study guide

**Read `BRIEF_SHARED.md` first.** This file covers only your half.

**You own:** what happens to the recording — the pipeline, the agentic author,
the gate, refusals, the judge, the review screen — then the output demo, the
limits, and MCP.

**Slides 10–18. About 12 minutes.**

Your job in one sentence: show that the one rule from slide 5 is not a slogan —
it is mechanically enforced, and you can see it working.

---

# PART 1 — WHAT YOU NEED TO UNDERSTAND

## 1. The chain, and which parts are code

```
recording → session index → expectations → AUTHOR → gate → judge → outputs
              (code)         (agentic,     (agentic) (code) (agentic)
                              small)
```

**The principle: deterministic where possible, agentic where necessary.** That's
a design position, not an accident, and it's worth stating out loud — the parts
that must be identical every time are plain code, and the model is used only
where judgement is genuinely required.

- **Session index** — plain code. A structured summary of the recording: what
  happened in what order, where the tester paused, where the page or the tab
  changed, where they pressed the "new scenario" button, what they said out loud.
  This is what the author reads first. It **has** to be deterministic, because the
  author reads it and the same recording must produce the same starting point.
- **Expectations (the oracle)** — a small agentic step. It guesses what *should*
  have happened, and one screen asks the tester to confirm or correct it. See §2.
- **Author** — the interesting one. §3.
- **Gate** — five deterministic checks. §4.
- **Judge** — a second model, fresh context. §6.
- **Outputs** — `.feature` plus a `.trace.md` sidecar always; Excel and Jira
  behind a switch. Adding a new output format is one new file and no pipeline
  change.

**On slide 10, spend 45 seconds and move on.** Its purpose is to give the QA
people a "where are we" anchor; the same diagram then reappears shrunk and dimmed
on your next three slides with the current box lit.

## 2. Expectations — why this exists at all

Without it, the tool can only ever restate what the application *did*. Which
means it can't write a test that would **fail on a broken build** — and a test
that passes on any build isn't a test.

So the tool guesses what should have happened — *"the list should drop from 24
products to 9"* — and one screen shows those guesses to the tester to tick,
correct, or reject. A guess a human confirmed is worth far more than a guess.

Two things worth knowing:

- **A run never waits for that screen.** Somebody might never open it. So the
  pipeline runs on the guesses alone and produces a draft; if the tester answers,
  it re-runs in place, over the same draft, rather than piling up a second run
  beside the first.
- **This stage is allowed to retrieve**, on a small budget, and that's not a
  contradiction of the one rule. The one rule is about *claims*. This stage
  writes a **question for a human**, and the whole difference between a question
  someone can tick and one they can't is whether it names a value.

## 3. The author — the heart of your half

**One model. One conversation. It writes the whole `.feature` file itself, and
it can go and look while it writes.**

### 3a. The loop

It works in a **decide → retrieve → observe → decide again** loop. It reads the
session index, forms a view of what the test is, and then calls tools to go and
check. One tool call per turn, sequentially — it sees the answer before choosing
the next question, which is what makes it investigation rather than a data dump.

### 3b. The six tools

You should be able to name these and say what each is for:

| Tool | What it does |
|---|---|
| `get_diff` | What changed on the page between before and after an event — the whole document, not the area around the click. **The workhorse.** |
| `get_snapshot` | The full page, before or after an event. Expensive. |
| `see` | The **screenshot** — the page as the tester saw it. For when text doesn't settle the question: did the list re-sort, what did that chart show. |
| `get_network` | The network calls for an event. This is the only way to actually *prove* a status-code claim. |
| `get_narration` | What the tester said in a time window. When it exists, it's the most direct statement of the expected result there is. |
| `find_text` | Where does this exact string appear across the recording? The grounding lookup. |

**Six, deliberately.** There were twelve. More tools measurably means *worse*
tool choice, and there's a hard-won lesson behind that: an earlier design had a
tool the model felt obliged to call on every single step, which lifted the number
of calls per step from 1.56 to 2.17 while the *spread* of effort across steps
collapsed from 1.08 to 0.16. That is, it stopped investigating and started
performing. **A mandatory tool call is not investigation.** Good line if it comes
up.

### 3c. It writes the Gherkin itself, and that's newer than it sounds

The author used to emit **JSON**, and a script assembled a feature file out of
it. Which meant — and this is the sentence that landed hardest in our own review
— **no model in the pipeline had ever seen a feature file.** The one artifact the
tool is judged by was assembled by a script from parts, none of which were
Gherkin. And it read exactly like that: a state written as an action, a verdict
repeated twice, keywords that didn't follow the flow.

Now the model writes the file — the actual prose — plus a set of **annotations**,
one per line, carrying what prose can't: which recorded events that line accounts
for, which literal proves it, and where there's no verdict, why not. Then the
file is read back with the same real Gherkin parser used at the gate, so the
model can't write something that reads fine in its own head and fails on the way
out.

**If asked why the model and not a template:** a template can't decide where a
scenario turns from setup into action. An earlier design derived Given/When/Then
from each step's position, and because the model writing steps only ever saw one
step at a time, it answered "When" every time — one version shipped seven `When`s
in a row. An author with the whole session in front of it knows where the
scenario turns.

### 3d. Draft, then prove

The author decides what's worth checking **and then retrieves to prove it** —
not the other way round. That ordering matters: an agent that may only claim what
it already happens to have fetched writes about whatever was easiest to get,
rather than about what the test is for.

### 3e. This replaced five stages

The old design had draft, split, bind, second-chance and bug-mode as separate
stages, plus a critic and a repair loop. Most of that machinery existed to catch
a model guessing about things it couldn't see — and it couldn't see because of
the capture defect in Person A's slide 7. Fix the capture, and most of the
apparatus had nothing left to catch.

## 4. The gate — how the rule is actually enforced

**Say this precisely, because it's the technical core of the deck.**

1. The author names a **literal** — an exact string it says it saw. `"This coupon
   has expired"`. It **never** supplies a reference, an id, or a citation.
2. The system searches the retrievals that were **actually made in this run**,
   finds which one contains that literal, **re-hashes the stored response**, and
   confirms the string is really in it.
3. It then independently checks the claim against the recording itself, at the
   event cited.

**The design point:** because the model never supplies the reference, **a
fabricated citation is not something it can express.** There's no field for it to
lie in. Compare to the normal approach — "cite your source" — where the model can
simply write a plausible id.

**And a related rule worth knowing:** seeing a literal in the session index is
*not* enough. The index is a summary, so a claim resting on it points at nothing.
It has to have come back from a tool.

**The five checks at the gate** — you don't need to list them on a slide, but
know them:

| Check | Asks |
|---|---|
| `evidence_retrieved` | Is this exact string in this exact stored response? |
| `event_coverage` | Was every recorded event accounted for — in a step, or in an explicit "omitted" entry naming it? |
| `gherkin_parses` | Does the file actually parse? |
| `no_placeholder_leak` | Did a redacted value reach the output? |
| `suggestions_quarantined` | Could an unverified suggestion be mistaken for a real step? |

**Five, down from fourteen.** The rule for keeping one is not "deterministic vs
agentic" — it's **can this check ever be wrong?** The nine that went were
*judgements* written as regexes: is this claim vacuous, does this name match this
scenario, would this catch a regression. Across 33 runs they produced one failure
between them, and nine of the fourteen never once returned anything but a pass —
while the judge, reading the same output and asking the same questions properly,
found real defects that all fourteen had passed. A regex will always lose the
question "is this sentence meaningful" to a model reading it.

**Don't present the pass count as a trust signal.** Five checks that have never
returned anything but green tell you nothing. That's the vacuity trap from the
shared brief, and it's exactly what the AI engineer will probe.

## 5. Refusals — the trust slide

When the author wants to assert something and can't prove it, it **writes down
why**, in language a tester can act on:

> *"Could not check that the product list narrowed to 9 items — the list was
> never captured before or after this click."*

**Why this is the thing to point at:** previously a claim that couldn't be proved
was just deleted. The scenario ended silently without a `Then`, and a style
warning said something in a vocabulary nobody outside the pipeline reads. So a
test case with no verdict and a test case whose verdict was invented looked
identical on the page. Now the tool tells you which one you're looking at.

**Two subtleties worth having in your pocket:**

- **A refusal passes every automated check by definition** — it claims nothing,
  so there's nothing to check. That makes it the one output in the system that is
  confident and otherwise entirely unchecked. Which is why the judge has a
  question specifically for it (§6). And it isn't theoretical: one shipped refusal
  said the tester had left the recording's scope, when the recorder had in fact
  followed them to the new tab and the index said so in as many words.
- **Refusals go back to the author**, so it gets a chance to fix them rather than
  the gate just going green on an empty document.

## 6. The judge

A **second model**, reading the finished document, asking: would a QA lead sign
this?

**Three things about it are load-bearing:**

1. **Fresh context.** It sees the finished document, the session index and the
   expectations. It never sees the author's reasoning or its tool calls — because
   a model shown its own justification defends it.
2. **One route back.** There's no routing table. A rejected claim and a judge
   finding both reach the author as plain sentences, and it decides what to
   change, because it wrote the document.
3. **Only real failures trigger a rewrite.** Findings are graded: a "weak" one is
   something a QA lead would sign after an edit — recorded, but not worth a
   rewrite round, because every rewrite risks damage elsewhere. Bounded at two
   rounds.

**The seven questions it asks** — know at least the last two:

- Would this verdict fail on a broken build?
- Does this sentence cover the events it claims to?
- Is this one scenario about one behaviour?
- Does the scenario name match its verdict?
- Was the tester's intent kept?
- **`claim_within_evidence`** — does the sentence claim *more* than its literal
  shows? Real example: a scenario shipped saying *"the order is rejected with a
  409 Conflict status"*, proved by a page message reading *"Orders over €500
  require approval"* — no 409 anywhere in it. The gate had confirmed the literal
  came back from a real retrieval. Nothing had confirmed the *sentence* was
  actually about that literal.
- **`refusal_is_true`** — is the stated reason for not asserting something
  actually correct? See §5.

**If asked "isn't a model judging a model circular?"** — no, and the fresh
context is why. It's not asked to agree with the author's reasoning; it can't see
it. And it can't rewrite anything — it flags, and the author decides.

## 7. The review screen

Everything above is worthless if the reviewer can't see it. The screen shows, per
step:

- **the evidence** behind each verdict — what was retrieved, and what licensed
  the claim
- **the refusals**, in plain language
- **the judge's findings**, attached to the step they're about rather than as a
  score at the top

Plus a screen where the tester confirms the guessed expectations, and a help page.

**Deliberately: there is no green badge.** There used to be one, reading
something like "5 checks passed", and it was removed — a count that has never
been anything but green isn't information. What's shown instead is the numbers
that can actually move: how many retrievals were made, how many claims were
rejected, how many findings the judge raised, and how *specifically* each verdict
resolves.

**One story if you want it:** the judge had been writing its findings to a file
on every run for weeks, and nothing served them and nothing rendered them. The
only thing on screen was an unclickable red badge reading "3 a QA lead would send
back" — with no way to see which 3. That's the shape of problem the interface
rebuild fixed.

## 8. Replay — the strongest check in the system

The generated test case can be **driven against the live app**. Not "does the
output look right" — does the test we just wrote actually run.

**Two things to know:**

- It drives the structured test case and the recording, **not** the `.feature`
  text — no Gherkin runner can bind a sentence to an action without a
  hand-written step definition.
- **It fails honestly.** If the runner can't drive an action, it says so and the
  step fails, rather than quietly skipping it. An earlier version returned nothing
  for actions it didn't support, which meant a test case made entirely of those
  passed trivially — reporting green on a test that ran nothing.

**Replay is also what caught a bug nothing else could.** Two recorded actions two
milliseconds apart, where the first action's "after" snapshot had absorbed what
the *second* action caused. An assertion bound to it passed every check — because
the string really was in the stored snapshot — and was still false about the
moment it named. Only running the test case found it. That's the argument for
replay in one paragraph.

## 9. The limits slide — what to say and what not to

Three groups. Lead with quota, because it's the ask.

**Group 1 — the model tier is the binding constraint.** All numbers here are
solid, use them:
- Free-tier limits are **requests**, not tokens. The good model gives **5 per
  minute and 20 per day** — one recording exhausts a day. The default is a lite
  model because it's the only workable one, not because it's the right one.
- **Free-tier prompts are training-eligible and human-reviewable.** So the tool
  *refuses to send* anything but a demo or public app — that refusal is built in,
  not a policy on paper. Pointing this at a real internal application needs a paid
  endpoint with a no-training term. **This is a policy argument, not a quality
  one, which makes it much harder to wave away.**
- Real pages cost about 20× the demo app: **150–172 KB per event** vs 5–10 KB.
  One full-page retrieval is **16–18k tokens**, and the conversation re-sends its
  history every turn — so one real session came to **168,690 prompt tokens against
  about 29,000** for a fixture run.

**Group 2 — the assertions aren't always meaningful yet.** One line, and don't go
deeper than this on stage:
> "The tool can bind a verdict to a value that's technically present but not
> specific enough to be worth checking. It now grades that rather than hiding it,
> and feeding the grade back to the author is the next step."

That's a complete, defensible answer. If someone pushes for an example: a badge
showing a number, where that number also appears in hundreds of other places on
the page — so the check passes whether or not the feature works.

**Group 3 — we haven't tested it enough to claim it's good.**
> "We didn't have the time or the quota to run the volume of sessions that would
> settle whether the output is *good*. The architecture is right and we can show
> you it working. The quality is not yet proven, and we're not going to show you a
> green chart as if it were."

Say it plainly, don't over-apologise, and move on. In this room that sentence
buys more credibility than any chart.

## 10. MCP — your last content slide

**What was asked for:** could we use an MCP server — Playwright MCP, Chrome
DevTools MCP — so the agent drives a live browser.

**Why the obvious version breaks this tool specifically. Three reasons, and give
them in this order:**

1. **They drive a *live* browser, and this system's evidence is a session that
   already happened.** Every claim is checked against a before/after pair from the
   recording. A live agent can't retrieve the past — there is nothing to re-check
   it against. This is the deep one; lead with it.
2. **Their retrievals happen outside our runner**, so nothing is stored and
   nothing is hashed. The gate would find no evidence for any claim and refuse all
   of them — and the one rule quietly becomes decorative.
3. **More tools measurably means worse tool choice.** We went from twelve tools to
   six for exactly this reason. An MCP browser server drops twenty-plus into the
   registry at once.

**The idea — suggestions, not claims.** A live-browser agent can't be
evidence-bound, so don't let it make claims. Let it make **suggestions**. The tool
already has a channel built for precisely that: suggestions live in their own
block, render under an **UNVERIFIED** heading, and are blocked at the gate from
ever becoming assertions. So the live agent explores the app and proposes
additional test cases; a human promotes the ones worth keeping; the rule never
bends.

**And the honest close:** there's exactly one seam it would go through — the
place every retrieval is already persisted and hashed. Wrap the MCP client there
and the gate doesn't change at all. The architecture already has the hole shaped
for it. It's designed, not built; there wasn't time.

## 11. Questions you should expect

- **"Isn't a model judging a model circular?"** — §6. Fresh context, and it can't
  rewrite.
- **"What stops it hallucinating a quote?"** — it can't cite; we search the
  retrievals ourselves. §4.
- **"How much does one recording cost to process?"** — depends entirely on the
  page: a fixture run is ~29k prompt tokens, a real storefront session was ~169k.
- **"Why Gemini?"** — free tier that's actually usable for iteration; the model is
  behind a seam, so swapping it is a config change, not a rewrite. And responses
  are cached, so changing a validator or a renderer costs nothing to re-test.
- **"How do you iterate without burning quota?"** — every real model response is
  recorded and replayed. Changing code that doesn't change the model's input costs
  zero calls.
- **"Can it produce more than one scenario?"** — yes; one recording produces one
  `.feature` file that can hold several scenarios, with the shared opening lifted
  into a `Background`.
- **"What if the tester records two different things in one session?"** — there's
  a button to mark a scenario break during recording, and that break is honoured
  deterministically. No model gets a vote on it.

---

# PART 2 — WHAT TO SAY

### Slide 10 — The map (45 sec — **do not linger**)

> "So that recording comes to us. Here's what happens to it.
>
> The principle across the whole thing is: deterministic where possible, agentic
> only where it's necessary. The first two boxes are plain code. We build an index
> of the session — what happened in what order, where they paused, where they
> changed page — and then we guess what *should* have happened and ask the tester
> to confirm it, which is what lets us write a test that would fail on a broken
> build rather than one that just describes what the app did.
>
> Those are the boring boxes and they're deliberately boring. The interesting part
> is these three, and that's where I'll spend my time."

### Slide 11 — One author, six tools (1.5 min)

> "One model. One conversation. It writes the whole feature file itself — and it
> can go and look while it writes.
>
> Six tools. What changed at this step. Show me the whole page. Show me the
> *screenshot* — the page as the tester saw it, for when the text doesn't settle
> the question. The network calls. What the tester said out loud. And a text
> search across the whole recording.
>
> It works in a loop: decide what to check, retrieve, look at what came back,
> decide again. One call at a time, so it sees each answer before choosing the
> next question. That's investigation rather than a data dump — and we found the
> difference matters. An earlier version had a tool the model felt obliged to call
> on every step, and the calls went up while the *variation* between steps
> collapsed. It had stopped investigating and started performing. A mandatory tool
> call is not investigation.
>
> Two things I'd flag. First: it writes the Gherkin. It used to emit JSON that a
> script assembled into a feature file — which meant no model in this pipeline had
> ever *seen* a feature file, and the output read exactly like something assembled
> out of parts. Now it writes the prose, and we read it back with a real Gherkin
> parser.
>
> Second: it decides what's worth checking *first*, and then goes and proves it.
> Not the other way round — an agent that can only claim what it happens to have
> already fetched writes about whatever was easiest to get."

### Slide 12 — The gate (1.5 min) — **the technical core, don't rush**

> "Now the rule, mechanically.
>
> The author names a **literal** — an exact string it says it saw. It never gives
> us a reference, an id, or a citation. It just quotes the thing.
>
> Then *we* go and search the retrievals it actually made in this run, find which
> one contains that string, re-hash the stored response, and confirm it's really
> in there. And then, independently, we check the claim against the recording
> itself.
>
> The design point is that second word — *we*. Because the model never supplies
> the reference, **a fabricated citation isn't something it can express.** There's
> no field for it to lie in. Compare that with the usual approach, 'cite your
> source', where a model can write a plausible-looking id and nobody checks.
>
> And one more rule that matters more than it sounds: seeing something in the
> summary we handed it is not enough. The summary points at nothing. It has to
> have come back from a tool.
>
> One thing I want to say before anyone asks: this proves **provenance**, not
> correctness. It guarantees the claim came from something really observed. It
> can't tell you the tester was testing the right thing. I'll come back to where
> that gap still bites us."

### Slide 13 — Refusals and the judge (1.5 min) — **the trust slide**

> "This is the part I'd point at if you only remember one thing from my half.
>
> When the tool can't prove something, it says so — in words you can act on."

*(Read the quoted refusal off the slide.)*

> "Previously, a claim that couldn't be proved was just deleted. The scenario
> ended without a `Then` and there was a warning somewhere in a vocabulary nobody
> outside the pipeline reads. Which means a test case with no verdict and a test
> case whose verdict was invented looked *identical* on the page. Now you can tell
> which one you're holding.
>
> And then a second model reads the finished file, with fresh context — it never
> sees how the first one reasoned, because a model shown its own justification
> defends it. It asks seven questions, and two of them are worth calling out.
>
> One: does this sentence claim *more* than its evidence shows? We had a scenario
> that said 'the order is rejected with a 409 Conflict status', and its evidence
> was a message on the page reading 'orders over 500 euros require approval'. No
> 409 anywhere. The gate had correctly confirmed the literal came from a real
> retrieval. Nothing had confirmed the *sentence* was about that literal.
>
> Two: is the refusal *true*? Because a refusal passes every automated check by
> definition — it claims nothing, so there's nothing to check. It's the one output
> in the system that's confident and otherwise entirely unchecked. And we did ship
> one that said the tester had left the recording's scope, when the recorder had
> actually followed them and the index said so in as many words."

### Slide 14 — Where it all surfaces (1 min)

> "None of that is worth anything if the reviewer can't see it.
>
> Per step: what was retrieved and what licensed the claim — you can click through
> to the actual evidence. What was refused, and why, in plain language. And the
> judge's findings, on the step they're about, rather than a score at the top.
>
> And deliberately: no green badge. There used to be one. It got removed, because
> a count of checks that has never been anything but green isn't information —
> it can only ever say 'fine'. What's on screen instead is the numbers that can
> actually move: how many retrievals were made, how many claims were rejected, how
> many findings the judge raised, and how specifically each verdict resolves."

### Slide 15 — Demo (3 min)

> "Let me show you the output."

1. **The run** — "this is the recording from a few minutes ago, processed."
2. **The feature file** — read one scenario out loud, slowly. Let them hear that
   it reads like a test case.
3. **A proved verdict** — "this `Then` — here's the retrieval it's bound to.
   That's the actual page content we stored, re-checked."
4. **A refusal** — "and here's one it wouldn't claim, and why."
5. **Replay** — > "And this is the strongest check in the whole system. Not 'does
   the output look right'. This is the test case we just wrote, being driven
   against the live app."

*(Let it go green. Don't talk over it.)*

### Slide 16 — Limits (1.5 min)

> "Three things I want to be straight about.
>
> First, and this is the ask. Our free-tier limits are on **requests**, not tokens
> — the good model gives us five a minute and twenty a *day*, and one recording
> exhausts that. So we're running a lighter model because it's the only workable
> one, not because it's the right one. And more importantly: free-tier prompts are
> training-eligible and human-reviewable, which is why the tool **refuses** to send
> anything but a demo or a public app. That refusal is built in. So pointing this
> at a real internal application isn't a feature we need to write — it's an
> endpoint with a no-training term. And the cost scales: real pages are about
> twenty times the size of our demo app, one full-page look is sixteen to eighteen
> thousand tokens, and one real session came to a hundred and sixty-nine thousand
> prompt tokens against twenty-nine for a test one.
>
> Second: the assertions aren't always *meaningful* yet. The tool can bind a
> verdict to a value that's genuinely there but not specific enough to be worth
> checking. It now grades that rather than hiding it, and feeding that grade back
> to the author is the next step.
>
> Third, and I'd rather say this than have you find it: we did not have the time
> or the quota to run the number of sessions that would settle whether the output
> is *good*. The architecture is right, and I've just shown you it working. The
> quality is not proven, and we're not going to put a green chart in front of you
> as if it were."

### Slide 17 — MCP (1.5 min)

> "I was asked whether we could use MCP — point Playwright MCP or the Chrome
> DevTools MCP at this and let the agent drive a live browser. And the honest
> answer is that the obvious version breaks the one thing the tool is built on.
>
> Three reasons. The deepest one: those drive a **live** browser, and every claim
> here is checked against a before-and-after pair from a session that already
> happened. A live agent can't retrieve the past. There's nothing to re-check it
> against.
>
> Second: their retrievals happen outside our runner, so nothing gets stored and
> nothing gets hashed — the gate would find no evidence for any claim and refuse
> all of them. The rule would quietly become decorative.
>
> Third, and smaller but real: more tools measurably means worse tool choice. We
> cut ours from twelve to six for exactly that reason. An MCP browser server drops
> twenty-plus in at once.
>
> But here's the idea I'd want to build. A live agent can't be evidence-bound — so
> don't let it make *claims*. Let it make **suggestions**. We already have a
> channel for exactly that: suggestions sit in their own block, render under an
> UNVERIFIED heading, and are blocked at the gate from ever becoming assertions. So
> the live agent explores the app and proposes extra cases, a human promotes the
> ones worth keeping, and the rule never bends.
>
> And there's exactly one seam it would go through — the point where every
> retrieval is already stored and hashed. Wrap it there and the gate doesn't change
> at all. The architecture already has the hole shaped for it. It's designed, not
> built — there wasn't time."

### Slide 18 — Close (30 sec)

> "So — month one built a tool that could write a test case. Month two built one
> that can't write a test case it can't back up.
>
> **A claim is admissible only if it can point at the retrieval that produced it.**
>
> Thank you. Happy to take questions."

---

## Rehearsal checklist

- [ ] Pipeline diagram exists in two versions: full slide, and dimmed strip
- [ ] A real refusal copied verbatim from a run onto slide 13
- [ ] Review screen screenshot with three callouts
- [ ] The run is **pre-computed**; don't wait on a model live
- [ ] Replay command already typed in a large-font terminal, plus a
      screen-recorded fallback
- [ ] You can explain the gate (§4) without the slide, in 30 seconds
- [ ] You can say the "provenance, not correctness" sentence before being asked
- [ ] You know your numbers: **5/min and 20/day**, **150–172 KB per event**,
      **16–18k tokens**, **168,690 vs ~29,000**
