# Recording a test case

For the person doing the testing. You will not need a terminal.

You record yourself using the application the way you normally would. The tool
watches, and turns what you did into a test case — a `.feature` file, an Excel
sheet, a Jira ticket. You then read the draft, fix what is wrong, and approve it.

It works with no help from you at all. Everything below is about making the
output good rather than merely correct, and the two are not the same thing.

---

## Before you press record: the objective

The popup asks **"What are you checking?"** before anything else. One line.

This is the single most valuable thing you will type, and it is the one thing
the recorder can never work out for itself. It can see that you clicked Place
order. It cannot see that you were checking the €500 approval rule rather than
the discount calculation, and a checkout page changes twenty things at once.

Write what you are **verifying**, not what you are going to do:

| Write this | Not this |
|---|---|
| Check that an order over €500 requires manager approval | Test the checkout page |
| Check that removing the last item empties the cart | Cart stuff |
| Check that an expired card is rejected at payment | Payment flow |

This is not a style preference. Two real recordings, same tool, same day:

- Objective: *"Check that an order over €500 requires approval"* → expected
  result: **"Orders over EUR500 require approval"**. Correct, and about the
  thing under test.
- Objective: *"Verify the checkout handles slow server-side validation"* →
  expected results: *"the user is redirected to the catalog page"* and *"the
  payment method is saved"*. Both true. Neither about slow validation.

The second objective describes an area. The first describes a check. That
difference is most of the quality gap.

**And a vague objective is worse than none at all.** That is worth saying
plainly, because it is the opposite of what most people expect. The same
34-click recording of a hamper builder, run three times with nothing changed
but this one line:

| What was typed | What came out |
|---|---|
| *"check if hamper sizes change correctly"* | Three checks about sizes changing. Ends on the hamper reaching 18 of 18 items. Never notices that the tester then hit the ceiling. |
| *(nothing)* | Three checks, ending on **"no bigger hampers are available"** — the thing the session was actually about. |
| *"check that a hamper cannot be upgraded past the largest size"* | Two steps and one check: **"Unfortunately, there are no bigger hampers available"**. Exactly the test, nothing else. |

The vague objective did not fail to help. It actively steered the test toward
the mechanism it named — sizes changing — and away from the outcome. With no
objective the tool read the session and found the interesting part on its own.

So: a sharp objective is the best input you can give it, and a woolly one is a
worse input than silence. If you cannot say in one line what you are checking,
leave it blank and record carefully instead.

---

## While you record

**Work at your normal speed.** Slightly slower is better than faster. The tool
waits for the page to settle after each action before it looks at what changed,
and clicking the next thing before the last one finished is how outcomes get
missed.

**One intent at a time.** Fill a form, then submit it, then look at the result.
That is three things and it reads as three things. Rattling through six fields
and a submit in four seconds gets grouped into one step called something vague.

### Talk while you record ← turn this on

Tick **Talk while I record** in the popup before you press Start. Chrome asks
for the microphone once, ever.

Then just say what you are checking, as you do it:

> *"Now I'm checking that an order this size needs manager approval."*

That sentence becomes the expected result. Without it the tool has to work out
which of the changes on screen was the point, and when a page updates a badge, a
total, a timestamp and a status all at once it sometimes picks a true but
irrelevant one. Saying it out loud costs you nothing and settles it.

You do not have to narrate everything. Say something when the step matters and
stay quiet the rest of the time.

**Two things to know, and they are the same thing twice.**

**It is written down.** Everything you say is transcribed and kept. Typed values
are redacted because the recorder can see that a field was a password; it cannot
hear that a sentence was one. Treat talking like typing into the page. The
**Mute** button in the popup silences the microphone mid-recording without
ending the session — use it before you read a password aloud, not after.

**It can mishear you.** Speech is transcribed, not read. "Six fifteen" comes
back as "six fifty" often enough to matter, and a wrong number in an expected
result is worse than no expected result. So:

- The recording is kept, and the review screen **plays back what you actually
  said** next to the sentence it produced. If something looks off, listen.
- Anything the transcriber was unsure of is shown greyed out and is not used to
  decide what the step is checking. You will see it; it just does not get a
  vote.

Nothing leaves your machine. The audio is saved next to the recording and
transcribed there.

### Mark what you're verifying ← the other important one

The green button in the popup. Press it, then click the thing on the page you
are actually checking: the confirmation banner, the total, the cart badge, the
error message.

Do it **after** the thing appears.

This is still the strongest single thing you can do, and it beats narrating:
pointing at an element is exact, where a spoken sentence has to be transcribed
first. Use both — say what you are checking, then point at it. They agree with
each other and the tool takes the pointed-at one.

You can mark several things in one recording. Marking nothing is fine; you will
just get the tool's best guess instead.

Your click does not affect the page. It is captured as a mark, not as an action,
and it will not appear in the test case as a step.

### The other four

| Button | Shortcut | What it does |
|---|---|---|
| **Checkpoint** | `Alt+Shift+C` | Ends the current step here. Use it when two separate things are about to be run together. |
| **New scenario** | `Alt+Shift+S` | A separate test case starts from this point. |
| **Mark a bug** | `Alt+Shift+B` | Something went wrong here. Flags the session and the step. |
| **Note…** | — | Type the step name yourself. Used **word for word** — no model rewrites it. |

A **Note** is the escape hatch for a step the tool keeps describing badly. Type
it just before you do the thing. What you type is what appears in the file,
exactly, including your punctuation.

None of these are required. The tool must be usable with zero annotations, and
it is.

---

## What gets recorded, and what does not

The recorder reads the page the way a screen reader does — roles and labels,
not pixels. It also captures network requests, console errors, and a screenshot
per step, which you will see beside each step when you review it.

Requests to other companies' servers — advertising, analytics, chat widgets —
are noted but their contents are not kept. They say nothing about the
application you are testing, and on a real site they are the overwhelming
majority of what a page does.

**Passwords, emails, card numbers and phone numbers are replaced before anything
is written to disk.** Not redacted afterwards — replaced in the browser, so the
real value never reaches a file. They come back as parameters:

```gherkin
Given the tester signs in as "<<user_email_1>>" with "<<password>>"
```

Which is more useful than the real value anyway: whoever runs the test supplies
their own.

**What redaction will not catch:** a customer name in a table, an internal
hostname, an order reference, a comment you typed into a free-text field. It
matches patterns, and prose is not a pattern.

**And it barely applies to anything you say.** Redaction works on typed values
because the recorder can see that a field was `type=password`. It cannot hear
that a sentence was one. A spoken email address or card number read straight off
the screen is caught; *"I'm signing in as john at example dot com"* is not.
Anything you narrate should be treated as written down, because it is.

Before anything is sent, you get a screen listing exactly what will leave the
browser, with the replacements shown. Read it the first time. If something is
on it that should not be, stop and say so.

### A condition of use, while we are on the free tier

The tool currently talks to a free model tier, and **free-tier providers may use
what is sent to improve their products, and may have humans review it.**

So: **demo applications and public test sites only.** Not a customer instance,
not production data, not a staging environment with real records in it.

This is a billing setting, not a permanent limitation — a paid key is not used
for training, and costs well under a cent per recording. If you need to record
something real, that switch has to happen first. Ask before assuming it has.

---

## After you press Stop

Press **Stop & export**, then **Send to aitc-rem**. The browser opens the
confirmation screen.

### The confirmation screen ← the most valuable minute you will spend

This is the one place the tool asks you something, and it is deliberately not an
open question. It shows you a guess and two buttons:

> **You filtered the list to in-stock products.**
> *(screenshot of the moment)*
> **Should have:** the list should drop from 24 products to 9
> **Actually:** the count changed from 24 to 9
>
> `Right`  `Not right`  `Edit`

**Why it exists.** The recording can only tell the tool what the application
*did*. It cannot tell it whether that was *correct* — so without you, every
expected result is a restatement of what happened, and a test made of those
passes on a broken build. One click each is the whole cost of fixing that.

- **Right** — the guess becomes `confirmed`, and the test case is written
  against it.
- **Not right** — this is the valuable one. It becomes a **bug report**, with
  what should have happened beside what did.
- **Edit** — correct the sentence and it is yours.

**You can skip it,** and nothing breaks: every guess stays `inferred`, the
scenarios get `@needs-review`, and a draft appears anyway. Skipping is the
default and the tested path. But a screen you clicked through is the difference
between a test that describes your application and one that checks it.

Answering it starts a second run, so the draft you end up with is the one
written against your answers.

### Then the review screen

**A draft takes a couple of minutes.** That is not the tool struggling — the
free model tier allows five requests a minute and one recording needs about
sixteen. The banner tells you which stage is running. Go and do something else;
it will be there when you come back.

### Reading the draft

Left is the test case, middle is the selected step, right is the evidence.

**Every expected result carries a badge** saying where it came from. This is the
part worth understanding, because it tells you how much to trust the line:

| Badge | Meaning | How much to check it |
|---|---|---|
| `annotated` | You pointed at this element while recording | Barely. It is what you said. |
| `narrated` | You said it out loud | **Check the number.** It is what you said, as far as the transcriber could tell. Play the clip if it looks odd. |
| `objective` | It comes from your stated objective | Skim it. |
| `inferred` | The tool worked it out from what changed | **Read it properly.** It is true, but it may be about the wrong thing. |
| `confirmed` | You answered a question the tool asked | It is yours. |

If everything on screen says `inferred`, that is the tool telling you it was
guessing throughout — usually because the recording had no marks and a vague
objective.

**The literal underneath each expected result** is the exact text the tool found
in the recording. That is what makes the line checkable. You can reword the
sentence above it however you like; the literal stays fixed, and you cannot edit
it. That is deliberate — the sentence is yours, the evidence is not.

### What to actually do

- **Reject an expected result that is true but pointless.** "A timestamp
  appeared" is worth less than nothing.
- **Reword anything clumsy.** Click the sentence and type. The evidence stays
  attached.
- **Answer any question the tool asks.** A step marked with a question means it
  genuinely could not tell — usually a canvas, a closed component, or a download.
  Your answer becomes part of the test case.
- **Merge two steps** that are obviously one thing.
- **Approve** when it reads like something you would hand to a colleague.

Approving matters beyond this one test: approved steps are what the tool reuses
next time, so a suite ends up phrased consistently instead of ten ways.

### Three things under the test case

They appear when there is something to say, and none of them is part of the test
case itself.

**Warnings.** Things the tool could not resolve, stated rather than hidden. Some
come from the recorder ("this control had no label"); some come from the tool
reviewing its own draft and failing to fix what it found. Either way it is
telling you where not to trust it.

**What this session did not cover — UNVERIFIED.** Things the recording revealed
about the application that nothing exercised: a field with a rule you only
satisfied, an error the server clearly knows how to produce, a threshold you
went over but never landed on. **Nothing here has been checked.** It is a prompt
for your next recording, not a claim, and it is never part of the file you hand
over. Ignore any of it freely.

**A bug report**, if something actually broke — a server error, a crash, or you
pressed **Mark a bug**. You get it *alongside* the test case, not instead of it,
and you choose which to keep: the steps that reached the failure are a usable
test either way. It states what should have happened and what did, and the
second one quotes the application's own words back, with a link to where they
were found. If the tool could not find anything that said what went wrong, it
writes no report rather than guessing.

A rejection your test is *about* — "orders over €500 need approval" — is not
treated as a bug. That is the tool knowing the difference between a refusal you
were checking for and one you were not.

---

## Getting a better result

In rough order of payoff:

1. **Write a sharp objective.** A check, not an area.
2. **Mark what you're verifying**, at least once per test case.
3. **Talk while you record.** Say what each check is for as you do it.
4. **Slow down slightly**, and let each page settle.
5. **Use a Note** for any step the tool keeps getting wrong.
6. **Press New scenario** when you move on to checking something else. One
   recording becomes several test cases, and that is where it splits them.

## When something goes wrong

**The recording came out empty.** The extension only injects into pages loaded
after it was installed. Reload the tab and record again.

**A step describes an icon instead of a button.** The control has no label in
the page's markup. Use a **Note** to name the step yourself, and tell whoever
owns the application — a control with no accessible name is a real accessibility
bug, not just an inconvenience for this tool.

**A step is marked with a warning.** The tool is telling you what it could not
determine, on purpose. Read it and either answer it or accept the reduced
confidence. It does not hide these.

**"Could not reach the server."** The review server is not running. Somebody has
to start it — it is a local program, it is not something you have done wrong.

**Nothing you said was picked up.** The popup shows a level meter while you
record; if it never moves, the microphone is not being heard. Check that **Talk
while I record** is ticked, that you are not muted, and that Chrome has the
microphone — the padlock in the address bar of the permission tab resets it.

**The tool misheard a number.** Play the clip in the review screen to confirm,
then reword the expected result. If it happens often, a bigger transcription
model is one line in `config/project.yaml` — ask whoever set this up.

## Not built yet

Said plainly, so you do not go looking:

- **Filing the Jira ticket for you.** The ticket is built and written to disk,
  ready to paste. `jira-push` will post it if it has been given credentials.
- **A tab you open yourself.** A tab the flow opens *for* you — an OAuth
  sign-in, a payment window, a PDF receipt — is now recorded and reads as part
  of the same session. A tab you open from scratch, to check your email
  mid-session, is deliberately not: it is not part of what you were testing.
- **A secret the application shows you that you never typed.** Anything you type
  is redacted in the browser before it is stored. A password the *page* prints,
  which you never entered, cannot be told apart from ordinary text — so either
  do not put it on the page, or have it named up front in the project's
  redaction settings.
