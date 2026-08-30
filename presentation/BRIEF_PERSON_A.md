# Person A — study guide

**Read `BRIEF_SHARED.md` first.** This file covers only your half.

**You own:** the problem, month 1 and its ceiling, the announcement, and
everything about **what the tool sees** — the recorder. You finish with a live
recording, which is also the handoff.

**Slides 1–9. About 10 minutes.**

Your job in one sentence: make the audience believe that the old tool hit a wall
that no amount of tuning could get past, and then show them that the new recorder
finally gives the AI something real to look at.

---

# PART 1 — WHAT YOU NEED TO UNDERSTAND

## 1. Why the old tool couldn't be fixed

This is the most important thing in your half, so get it exactly right.

The old tool worked like this: the extension recorded the session, wrote it into
a **text log**, and handed that log to a language model, which wrote a test case
from it. The log was good — it had page titles, timings, what the tester said,
even a short "here's what the app did back" line after some actions.

But notice what's missing: **once the model has written a sentence, nothing can
go back and check it.** The log is a summary. If the model wrote *"Then an
'Invalid credentials' error is displayed"*, there was no mechanism to ask "did
that actually appear on the page?" You could check the *shape* of the output — is
this valid JSON, does every step have a description — but not the *truth* of it.

So there were two defences, and both were weak by construction:
- A **critic**: plain Python checks. It could notice that a captured value was
  missing from the test data. It could not judge whether an assertion was true,
  because judging a sentence with a regex is a losing game.
- A **judge**: a second model that read the output and gave an opinion. An
  opinion, clamped to a warning, that blocked nothing.

**Both were advisory. Neither could reject anything.** That's the ceiling. And
the root cause underneath it: the model was *told about* the session rather than
being able to *look at* it.

There was a second, more physical version of the same problem, which is your
slide 7: the recorder often hadn't captured the evidence at all, so even a
perfect model would have had nothing to work from.

**How to say it without trashing month 1:** the old tool's design decisions were
reasonable, they were verified live against real Jira and a real model, and the
second half of the month added the dashboard, versioning and the eval set. It
shipped. It just had a ceiling that wasn't a prompt away.

## 2. The accessibility tree, and why it beats the DOM

**The DOM** is the raw structure of a web page as HTML: `<div class="ProductCard
ProductCard--grid" data-cy="pc-14">` and so on. It's markup. It's mostly styling
and framework noise. A product card is roughly 1.5 KB of class names and CDN
URLs, and the part a human cares about — `"Nike Air Max 90 · €120.00"` — is a
fraction of that.

**The accessibility tree** is a second structure the browser builds from the same
page, for screen readers. Every element that matters appears as:

- a **role** — `button`, `link`, `textbox`, `heading`, `list`, `alert`
- an **accessible name** — the text a screen reader would read: `"Add to basket"`
- sometimes a **value** — what's typed in a field

So the same button is `<button class="btn btn--primary btn--lg" id="a17">…` in
the DOM and `button "Add to basket"` in the accessibility tree.

**Three reasons that's the right layer, and you should be able to give all three:**

1. **It's already meaning, not markup.** No extraction step to get wrong. The old
   tool had to *derive* a description from the HTML and could get it wrong; here
   the browser has already done it.
2. **It's how a tester talks.** "The Add to basket button" is what goes in a test
   case. `div.btn-primary--lg` is not.
3. **It's stable.** A designer restyling the site changes the DOM completely and
   changes the accessibility tree not at all. Test cases written against it don't
   rot as fast.

**And it's black-box.** We read the live tree from the browser. We need no access
to the source of the app being tested, no cooperation from its developers, no
special build. If the app happens to have `data-testid` attributes we use them,
but the normal case is role + name and it works on any site.

**If someone pushes back — "isn't the a11y tree incomplete on badly-built
sites?"** — the honest answer: yes, an app with poor accessibility gives us a
poorer tree, and that's a real limit. But it's the same information a screen
reader user would get, so it's a floor the app should be meeting anyway; and we
also capture screenshots, which is the fallback when the tree doesn't settle a
question.

## 3. "The page, not the keyhole" — your strongest slide

This is a real defect that was found and fixed, and it's the most concrete thing
in your half. Understand the mechanics.

**What it used to do.** When the tester clicked something, the recorder captured
the *landmark region around that element* — the nearest surrounding section,
form, or navigation area. The reasoning was budget: don't send a whole page when
you only need the part that was clicked.

**Why that was wrong.** Two separate failures:

1. **The keyhole.** The thing that *changes* is very often not the thing you
   clicked. A tester clicks a filter checkbox in a sidebar. The sidebar gets
   captured — 1.2 KB, nothing changed in it. The product list, which is the whole
   point of the test, is somewhere else on the page and was never captured at
   all. **On real sites, 30–50% of events recorded no observed change
   whatsoever.** Not a small change — none.

2. **The moving root.** The "before" and "after" snapshots were each worked out
   independently. So if a click caused its own surrounding section to be replaced,
   "before" and "after" were rooted at different places, every element path
   changed, nothing lined up, and the diff read something like *"+408 added, −405
   removed"* on a 405-element page. Downstream that was read as "the whole product
   grid re-rendered", which was false.

**What it does now.** Capture the whole page. Take "before" and "after" from the
**same fixed root**, so the two are comparable by construction rather than by
luck. Now every action carries a real answer to *"what changed when I did that?"*

**The bit that makes it a good story:** there was also a cap on how much of the
page got captured, and it was set low enough that most events on real sites were
hitting it on both sides. So all the measurements that "proved" narrow capture
was affordable were measuring the cap, not the pages. Widening the scope without
raising the cap would have changed nothing. Both had to move together.

**If asked "isn't a whole page expensive?"** — yes, and Person B has the numbers
on slide 16. Storing it is fine; a big recording on a local disk is nothing. What
costs is sending it to the model, and that's a separate decision made later, per
retrieval. Capture generously, send carefully — two decisions, two places.

## 4. Redaction — what never leaves the browser

**The rule:** redaction happens **in the page, before anything is stored.** There
is deliberately no path anywhere in the system that writes a raw value to disk and
cleans it up afterwards, because that path always eventually leaks.

**Two different kinds of rule, and this distinction is the thing to understand:**

- **By context** — "this is a password field, so whatever is in it is a secret."
  This cannot be wrong. A password field's contents are secret regardless of what
  they look like.
- **By shape** — "this string looks like a phone number / a card number, so hide
  it." This *can* be wrong, and it was: on one storefront the shape scan produced
  **214 hidden values, every one classified as a phone number**, and what it had
  actually matched was dates on the page — `"Updated 2026-08-28 14:32"`. A date on
  a page is routinely the exact thing a test asserts on, so the scan was
  destroying the evidence in order to protect a value nobody had ever typed.

**So the tester picks a level, in the recorder popup:**
- **full** — both kinds of rule.
- **secrets_only** (the default) — keeps the context rule, drops the shape scan.
- **off** — keeps nothing.

**Why the level lives in the recorder and not in a server config** — this is the
good answer and it's worth giving: by the time a server could read a setting, the
recording already exists and the decision has already been taken. It can't be
revisited. And it's genuinely per-recording: one session against a demo app and
one against a system whose order references happen to look like card numbers are
different situations, in the same project, on the same afternoon. The person who
knows which is which is the tester, at the moment they press record.

**One honest limit, and say it if the topic comes up:** a secret that the
*application displays* and the tester never types cannot be recognised by
anything here — nothing distinguishes it from ordinary page text. Two answers
only: name it in the project config up front, or don't put it on the page.

**Narration is the one exception.** Speech can't be redacted before it's
understood, and understanding it *is* transcription. So audio reaches disk raw.
What makes that acceptable: it never leaves the machine — the transcription runs
locally, in-process — and the tester is told outright that anything said out loud
is written down. Everything *typed* still obeys the rule without exception.

## 5. The objective sentence

Before recording, the tester types one sentence saying what they're checking.
It's the single strongest signal the tool ever gets, because it's the one thing
the app can never observe for itself: the recording shows what happened, not what
the tester was *trying to find out*.

**And the sharpness of it measurably decides the output.** A **vague** objective
names a *mechanism* — "check the filters work correctly". A **sharp** one names an
*outcome* — "filtering by 'in stock' should drop the list from 24 products to 9".
When the objective is vague, the mechanism is what the test gets written about,
instead of the thing the tester was actually checking. In the recordings on disk,
four out of four vague objectives produced output that was judged bad; five out of
five sharp ones were acceptable.

So the recorder classifies the sentence **as the tester types it** and tells them
which they've written. And a vague one is dropped on the way in to the model —
worse than none, because it actively misdirects.

**The subtlety, if asked:** the recorder never *rewrites* the tester's sentence.
It's stored exactly as typed, forever. The tester's own words outrank anything
the tool infers, so silently "improving" the objective would invert that. It only
warns.

## 6. Narration

The tester can talk while recording. Audio is transcribed locally and each phrase
is anchored to the moment it was spoken, so *"it should show an error here"*
attaches to the click it describes by measurement, not guesswork.

**What to tell testers:** narrate *why* and *what should happen* — not "now I
click the blue button", which the recorder already captures better than you can
describe it.

**One honest caveat worth knowing:** narration is the only evidence source that
is lossy. Everything else — element names, URLs, responses — is read exactly. A
transcript is a reconstruction, so a misheard number can produce a claim that is
technically well-evidenced and still false. There's a confidence floor that stops
a low-confidence phrase from supporting a verdict, and the audio is kept so a
human can listen. Don't put this on a slide; know it.

## 7. Things you'll be asked

- **"Does it work on our app?"** — it's black-box, so technically yes on any site.
  Whether we're *allowed* to point it at a real internal app is a licensing
  question and it's Person B's slide 16.
- **"What about pages that need login?"** — the tester just logs in while
  recording; the password is redacted in the page. For repeated automated runs
  there's a way to save a signed-in session once, by hand, rather than replaying
  the login every time.
- **"What if the page keeps changing — ads, chat widgets, animations?"** — we
  capture before/after around each deliberate action with a settling window, not
  a continuous stream, so background churn doesn't drown the signal.
- **"Multiple tabs?"** — a tab opened *from* a recorded tab joins the recording; a
  tab with no connection to it doesn't. A tester checking their email mid-session
  isn't part of what they were testing.
- **"How big is a recording?"** — big, and that's fine. It's a local disk. The
  cost that matters is what gets sent to the model, which is decided separately.

---

# PART 2 — WHAT TO SAY

Not a script to memorise — a talk track. Timings are for speaking freely.

### Slide 1 — Title (15 sec)

> "Last month we showed you a tool that turns a recorded browser session into a
> test case. This month we're showing you the one we rebuilt — and, more usefully,
> why we rebuilt it."

### Slide 2 — The problem (1 min)

> "Start with the thing that hasn't changed. A tester writes up a test case by
> hand and it costs ten to twenty minutes — and they've already done the work,
> because they just clicked through the flow to check it.
>
> But here's the part that matters. The steps are the easy half. Anyone can list
> clicks. The part you actually judge a test case by is the `Then` — the expected
> result. That's what makes it a test rather than a description of somebody using
> a website. Hold on to that, because everything I show you for the next ten
> minutes is about that one line."

### Slide 3 — Month 1 (1 min)

> "Quick recap of where we got to last month, because it's the reason we knew
> what to build next.
>
> We had a Chrome extension recording sessions. Sessions stored raw before any AI
> ran, so a bad prompt could never destroy a recording. A structured test case in
> the database — never a pre-formatted string — so Gherkin, Excel and Jira were
> all just renderings of one shape. Since the last presentation we'd added a
> proper dashboard: review, edit, export, with every edit kept as a new version so
> nothing overwrites the model's original. A deterministic critic raising review
> questions. And an evaluation set, so changes were measured instead of eyeballed.
>
> It worked end to end. It was verified live against a real Jira and a real model.
> This isn't a slide about a failure."

### Slide 4 — The ceiling (1.5 min) — **slow down here**

> "So what stopped us.
>
> The model was *told about* the recording. We wrote the session into a text log —
> a good log — and handed it over, and the model wrote a test case from it. And
> once it had written a sentence, **nothing in the system could check whether that
> sentence was true of the recording.** We could check the shape of the output. We
> could not check the truth of it.
>
> Which meant the expected result — the one field that matters — had one thin
> source, the narration, and anywhere that was thin, the model filled the gap by
> inventing. And our two defences were a set of regex checks and a second model's
> opinion. Both advisory. Neither could reject anything.
>
> This is not a prompt you can fix. It's not a better model. There was no
> mechanism, even in principle, to ask 'did that actually happen?' — and that is
> the ceiling."

*(Pause here. This is the pivot of the whole presentation.)*

### Slide 5 — The rebuild (1 min) — **the announcement**

> "Which is why we decided to rebuild it. And this is AITC."

*(Beat. Let the slide sit.)*

> "One rule, and the entire architecture exists to serve it:
>
> **A claim is admissible only if it can point at the retrieval that produced it.**
>
> In plain terms: the tool is not allowed to write an expected result unless it
> can name the thing it looked at — and then we go and re-check that thing. And
> note what it does *not* say. It's not 'the text exists somewhere in the
> recording' — that's a weaker, different check. It has to have come back from a
> lookup the model actually performed, while writing this document.
>
> Everything from here is either making sure there's something real to look at —
> that's my half — or enforcing that rule, which is my colleague's."

### Slide 6 — The accessibility tree (1.5 min)

> "So: what the tool sees.
>
> The old recorder scraped text out of the HTML. The new one reads the
> accessibility tree — the same structure a screen reader uses. On the left
> there's the raw markup for a button: class names, wrappers, a CDN URL. On the
> right, the same button in the accessibility tree: `button`, `"Add to basket"`.
> A role and a name.
>
> Three reasons that's the right layer. It's already meaning, so there's no
> extraction step to get wrong. It's how a tester actually talks — 'the Add to
> basket button' is what goes in a test case, `div dot btn-primary` is not. And
> it's stable: restyle the site completely and the accessibility tree doesn't
> move, so the test cases don't rot.
>
> And it's black-box. We read the live tree from the browser. We need no access
> to the source of the app being tested, no cooperation from its developers, no
> special build. If there are test ids we'll use them, but the normal case needs
> nothing from you."

### Slide 7 — The page, not the keyhole (1.5 min) — **your number**

> "Now the defect that was underneath most of the output problems.
>
> The old recorder captured the region *around the element you clicked*. Which
> sounds sensible — why send a whole page when you clicked one button.
>
> Here's why it isn't. The thing that changes is usually not the thing you
> clicked. A tester ticks a filter in the sidebar. We captured the sidebar. The
> product list — the entire point of the test — is somewhere else on the page, and
> we never captured it at all. On real sites, **thirty to fifty percent of
> recorded events had no observed change whatsoever.** Not a small change. None.
> So for a third to a half of everything the tester did, the model had nothing to
> look at, and it guessed.
>
> Two changes. We capture the whole page. And we take the before and the after
> from the same fixed root, so the two are comparable by construction — previously
> they were worked out independently, so a click that replaced its own section
> produced a diff reading four hundred added, four hundred removed, on a page of
> four hundred elements. Which downstream was read as 'the product grid
> re-rendered'. It hadn't.
>
> Now every action carries a real answer to: what changed when I did that."

### Slide 8 — What never leaves the browser (1 min)

> "Three things about privacy, quickly, because you'll want to know before you
> record anything real.
>
> Redaction happens in the page, before anything is stored. There is deliberately
> no path in this system that writes a raw value to disk and cleans it up later,
> because that path always eventually leaks.
>
> The tester picks the level, in the recorder — not in a config file on the
> server. And that's deliberate: by the time a server could read a setting, the
> recording already exists and the decision can't be revisited. It's also genuinely
> per-recording — a session against a demo app and a session against a system whose
> order numbers happen to look like card numbers are different situations, and the
> person who knows which is which is the tester, at the moment they press record.
>
> And the objective: one sentence, before recording, saying what you're checking.
> It's the strongest signal the tool ever gets, because it's the one thing the app
> can never observe for itself. And how sharp it is decides the output — 'check
> the filters work' gets you a test about filters; 'filtering by in-stock should
> drop the list from 24 to 9' gets you a test about the thing you were actually
> checking. So the recorder tells you which one you've typed, while you type it."

### Slide 9 — Demo, and handoff (1.5 min)

*(Switch to the browser. Talk while you do it — don't narrate mouse movements.)*

> "Let me just record one.
>
> Objective first — see, it's telling me that's a sharp one.
>
> Start. And now I'm just… using the site. Nothing special. It's capturing the
> whole page before and after each of these, from the accessibility tree."

*(Say one sentence out loud so they see narration working.)*

> "And stop.
>
> That's it — that's the whole cost to a tester. About forty seconds of deliberate
> effort: one sentence up front, say what you're expecting rather than what you're
> clicking, one flow per recording.
>
> And that recording is what my colleague's half now receives."

*(Hand over.)*

---

## Rehearsal checklist

- [ ] Demo app open, extension loaded and pinned, mic permission already granted
- [ ] Recording demo rehearsed cold, twice — it is **90 seconds**, not three minutes
- [ ] Screen-recorded fallback of the recording flow, in case the extension misbehaves
- [ ] You can say slide 4 without the slide
- [ ] You can define "accessibility tree" in one sentence to someone who's never
      heard of it
- [ ] You know the three numbers in your half: **10–20 min**, **30–50%**, **~40 seconds**
