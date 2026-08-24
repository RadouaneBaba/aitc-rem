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

---

## While you record

**Work at your normal speed.** Slightly slower is better than faster. The tool
waits for the page to settle after each action before it looks at what changed,
and clicking the next thing before the last one finished is how outcomes get
missed.

**One intent at a time.** Fill a form, then submit it, then look at the result.
That is three things and it reads as three things. Rattling through six fields
and a submit in four seconds gets grouped into one step called something vague.

**Do not narrate out loud.** Not yet — the recorder does not capture audio.
See [Not built yet](#not-built-yet).

### Mark what you're verifying ← the important one

The green button in the popup. Press it, then click the thing on the page you
are actually checking: the confirmation banner, the total, the cart badge, the
error message.

Do it **after** the thing appears.

This is worth more than everything else on this page combined. Without it the
tool has to guess which of the changes on screen was the point, and when a page
updates a badge, a total, a timestamp and a status all at once, it sometimes
picks a true but irrelevant one. You know which one mattered. This is how you
say so.

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
per step.

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

Press **Stop & export**, then **Send to aitc-rem**. The browser opens the review
screen.

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
| `narrated` | You said it out loud | Barely. |
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

---

## Getting a better result

In rough order of payoff:

1. **Write a sharp objective.** A check, not an area.
2. **Mark what you're verifying**, at least once per test case.
3. **Slow down slightly**, and let each page settle.
4. **Use a Note** for any step the tool keeps getting wrong.
5. **Record one flow per session.** Splitting a session into several test cases
   is not built yet, so a recording covering three unrelated things comes out as
   one confused test case.

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

## Not built yet

Said plainly, so you do not go looking:

- **Narration.** Speaking while you record does nothing; no audio is captured.
- **Several test cases from one recording.** One recording, one test case.
- **Filing the Jira ticket for you.** The ticket is built and written to disk,
  ready to paste. It is not posted.
