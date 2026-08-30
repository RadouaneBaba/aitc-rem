# Shared brief — read this first, both of you

Read this before your own file. It assumes you know nothing about the project.
Everything here is knowledge you *both* need, because either of you could be
asked any of it in the Q&A.

Nothing in here is a slide. It's what has to be in your head behind the slides.

---

## 1. What the tool is for, in one paragraph

A QA tester records themselves using a web app — clicks, typing, navigation, and
optionally talking out loud about what they're checking. The tool turns that
recording into a formal test case: a Gherkin `.feature` file, an Excel sheet, or
a Jira issue. The point is that the tester already did the work when they clicked
through the flow; writing it up afterwards is the 10–20 minutes we're trying to
remove.

## 2. Gherkin, for anyone shaky on it

Gherkin is the plain-English format QA teams write test cases in. A file looks
like:

```gherkin
Feature: Checkout with an expired coupon

  Scenario: An expired coupon is rejected
    Given the tester is signed in
    When the tester applies the coupon "AUTUMN20"
    Then the message "This coupon has expired" is shown
```

- **Feature** — a capability of the app.
- **Scenario** — one way of exercising it. One file can hold several.
- **Given** — the starting state / setup.
- **When** — the actions.
- **Then** — the **verdict**. What must be true afterwards.
- **And** — continues whatever block it's under.
- **Background** — setup shared by every scenario in the file, lifted to the top
  so it isn't repeated.
- **Scenario Outline / Examples** — one flow run several times with different
  values, in a table.

**The `Then` is the whole game.** Steps are easy — anyone can list clicks. The
`Then` is what makes it a *test* rather than a description, and it's the only
part a tester actually judges you on. If you remember one QA fact for this
presentation, it's that.

## 3. The one rule

> **A claim is admissible only if it can point at the retrieval that produced it,
> in this run.**

Unpacked:

- A **claim** is a `Then` — an assertion about what the app did.
- A **retrieval** is one of the tool calls the AI made while writing the file
  ("show me what changed on the page at step 7").
- **In this run** matters. It is not enough that the string exists somewhere in
  the recording — that's a weaker, separate check. It has to have come back from
  a lookup the model actually performed while writing *this* document.

How it's enforced: the model quotes a **literal** — an exact string it says it
saw. It never supplies a reference or an id. The system then searches the
retrievals that were actually made, re-hashes the stored response, and confirms
the literal is really in it. **A fabricated citation is not something the model
can express** — there's no field for it to lie in.

## 4. What the rule does and does not buy you

**Say this out loud before anyone asks, in either half.**

- It proves **provenance**: the claim came from something really observed in the
  recording.
- It does **not** prove **correctness**: it can't tell you the tester was testing
  the right thing, and it can't tell you the assertion is *meaningful*.

The known gap between the two is on the limits slide: a verdict can bind to a
value that is genuinely present but not specific enough to be worth checking.
The tool now grades that rather than hiding it.

## 5. The two architectures, in one table

Never put this table on a slide — it turns the deck into a comparison exercise.
It's for your head, and for questions.

| | Month 1 (old tool) | Month 2 (AITC) |
|---|---|---|
| What it captured | Text scraped out of the DOM around the clicked element | The accessibility tree of the whole page, before and after every action |
| What the model got | A formatted text log of the session | A session index **plus six tools to go and look with** |
| How the model wrote | One call, later split into three passes | One agentic author, one conversation, writing the file itself |
| What it produced | JSON that a script rendered into Gherkin | The `.feature` file, written by the model, read back with a real parser |
| Could a claim be checked? | **No.** Nothing could ask "is this true of the recording?" | **Yes.** That is the entire architecture |
| Defences | A regex critic + a second model's opinion — both advisory, neither could reject | Five checks that cannot be wrong, plus a judge that can send it back |
| When it couldn't prove something | Silently dropped the assertion | Says so in words the tester can act on |

**The framing to use:** same problem, second architecture — and the first one is
what told us what was wrong. Month 1 is the diagnosis, not wasted work. It also
genuinely improved a lot in its second half (the dashboard, versioning, the
critic, the eval set, the three-pass split), and Person A says so explicitly.

## 6. The pipeline, end to end

```
recording  →  session index  →  expectations  →  AUTHOR  →  gate  →  judge  →  outputs
   (A)          (code)           (asks the      (agentic)  (code)  (agentic)
                                  tester)
```

- **recording** — what the extension captured. Person A's half.
- **session index** — plain code. A structured summary of the session the model
  reads first: what happened, in what order, where the tester paused, where they
  changed page or tab, what they said. Deterministic — it has to be identical
  every time, because the author reads it.
- **expectations** — the tool guesses what *should* have happened and one screen
  asks the tester to confirm or correct it. This is what lets the tool write a
  test that would **fail on a broken build**, rather than just describing what
  the app did. A run never waits for this — it produces a draft on the guesses
  alone and re-runs if the tester answers.
- **author** — one model, one conversation, writes the whole `.feature` file and
  retrieves evidence while it writes.
- **gate** — five deterministic checks. Where the one rule is enforced.
- **judge** — a second model with fresh context: would a QA lead sign this?
- **outputs** — `.feature` + a `.trace.md` sidecar always; Excel and Jira opt in.

## 7. Vocabulary you will both need

| Term | Means |
|---|---|
| **Accessibility tree** | The structured view of a page that screen readers use: every element as a *role* (button, link, textbox) plus its *accessible name* ("Add to basket"). Meaning, not markup. |
| **Literal** | An exact string the model quotes as proof — `"This coupon has expired"`. The only currency of a claim. |
| **Retrieval / tool call** | One lookup the model made while writing: what changed here, show me the page, search for this string. |
| **The gate** | The five automated checks run on the finished document. |
| **Refusal / `whyNot`** | The tool declining to assert something, *in writing*, with the reason. |
| **The judge** | A second model, fresh context, asks whether a QA lead would sign it. Advisory but it can trigger one rewrite. |
| **Replay** | Driving the generated test case against the live app to see if it actually runs. |
| **Session index** | The deterministic summary of the recording the author reads. |
| **Expectations / the oracle** | The guessed "what should have happened", confirmed by the tester on one screen. |

## 8. Numbers, and how to use them

Only these. Don't improvise numbers.

| Number | What it says | Whose slide |
|---|---|---|
| **10–20 min** | cost of writing a test case by hand | A, slide 2 |
| **~40 seconds** | deliberate effort the tester spends per recording | Q&A |
| **30–50%** | of events on real sites recorded **no observed change at all** under the old capture | A, slide 7 |
| **5–10 KB vs 150–172 KB per event** | demo app vs real storefront capture cost | B, slide 16 |
| **16–18k tokens** | one full-page retrieval on a real page | B, slide 16 |
| **168,690 vs ~29,000 prompt tokens** | one real session vs one fixture session | B, slide 16 |
| **5/min and 20/day** | free-tier request limit on the good model — one recording exhausts a day | B, slide 16 |

**The rule about metrics — this is the thing the AI engineer will test you on.**
Never present a pass rate or a grounding rate as evidence the output is good. If
the tool declines to assert anything, it passes every check and the rate is
vacuously 100%. Nine of ten runs scored 1.0 on grounding while a held-out
judgement said the output was bad. If a percentage goes on a slide, the number
that qualifies it goes next to it. Both of you should be able to say this
sentence.

## 9. Things not to do on stage

- **Don't run the old-vs-new comparison past slide 5.** One hinge, then the new
  product on its own terms. A deck that keeps looking backwards sounds defensive.
- **Don't demo the UI outside the demo slots.** Slide 14 is a screenshot with
  callouts for a reason.
- **Don't oversell.** "The architecture is right; the output quality isn't proven
  yet" is a stronger sentence in this room than any chart.
- **Don't guess in Q&A.** "I don't know, that's my colleague's half" and "we
  haven't measured that" are both fine answers. Making one up in front of an AI
  engineer is the only unrecoverable move.

## 10. Questions you should both be ready for

- **"How long does this take a tester?"** ~40 seconds of deliberate effort per
  recording: one objective sentence, narrate intent rather than actions, one flow
  per recording, a short review at the end.
- **"What if it's wrong?"** The reviewer is the final authority. Nothing is
  auto-filed anywhere. The review screen shows what the tool couldn't prove and
  what the judge would send back, so a reviewer knows where to look.
- **"Can we point it at our own app?"** Not on the free tier — free-tier prompts
  are training-eligible, so the tool refuses to send anything but a demo or public
  app. A paid endpoint with a no-training term lifts it. That's slide 16.
- **"Does it need access to our source code?"** No. It reads the live
  accessibility tree. It uses a `data-testid` if one is there, but the normal case
  needs nothing from the app under test.
- **"What about passwords?"** Redacted in the browser, before anything is stored.
  The real characters reach neither our disk nor the model.
- **"Why not just use ChatGPT / an existing agent?"** Because the whole value is
  the gate, and a general agent has no way to prove what it saw. That's the deck.
