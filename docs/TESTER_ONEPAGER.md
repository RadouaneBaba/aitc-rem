# Recording a test case — the one page

Print this. [RECORDING.md](RECORDING.md) is the long version; you should not
need it.

---

## Before you press Start

**Type one sentence saying what you are CHECKING.** Not what you are going to
do — the recorder can already see that.

| Write this | Not this |
|---|---|
| Check that an order over €500 requires manager approval | Test the checkout page |
| Check that removing the last item empties the cart | Cart stuff |
| Check that an expired card is rejected at payment | Check if payment works correctly |

The box tells you when it reads as a topic rather than a check. It never stops
you, and it never rewrites what you typed.

> **If you cannot say it in one line, leave it blank.** This is measured, not a
> preference: the same recording with a woolly objective produced a *worse* test
> than the same recording with none. A vague sentence steers the tool toward the
> thing it names and away from the thing you were actually checking.

**Tick "Talk while I record" if you can.** It is the single best thing you can
do for the result, and it costs you nothing. Everything you say is written
down — including before you click anything, so say your objective out loud.

---

## While you record

**Work at your normal speed, slightly slower if anything.** The tool waits for
each page to settle before it looks at what changed. Clicking the next thing
too early is how an outcome gets missed.

**One intent at a time.** Fill the form, *then* submit it, *then* look at the
result. Three things, and it reads as three things.

**Say what you are checking, as you check it.** *"Now I'm making sure an order
this size needs approval."* That sentence decides which of the twenty things on
screen the test is about.

### The four buttons, and what each is for

| | | What it does |
|---|---|---|
| **Mark what I'm verifying** | — | You click an element on the page; the tool records *that* as the thing under test. Use it when the outcome is a specific number or message. |
| **Checkpoint** | `Alt+Shift+C` | "Something worth checking just happened here." |
| **New scenario** | `Alt+Shift+S` | "I am finished with that test; the next one starts now." This **overrides** the tool — it will split here, whatever it thinks. |
| **Mark a bug** | `Alt+Shift+B` | "That was wrong." You get a defect report alongside the test case. |
| **Note…** | — | Names the step in your own words, used **verbatim**. Nothing rewrites it. |

---

## After you press Stop

Press **Stop & export**, check what it says is leaving your browser, and send
it. A draft appears in the review page in a couple of minutes.

### Reviewing, with the keyboard

`j` / `k` next and previous step · `a` accept · `r` reject · `e` edit the
wording · `⌘↵` approve · `?` shows this list

Press `?` in the review page for the full list and what the marks mean.

### How much to trust each line

The strip at the top says how many checks the test makes and how many of them
trace back to something the tool actually retrieved. Then, per expected result:

| Badge | Means |
|---|---|
| `annotated` | You marked this element. The strongest kind. |
| `narrated` | You said it out loud, and the tool then found it on the page. |
| `objective` | It follows from the sentence you typed before recording. |
| `inferred` | The tool worked it out. **Read this one properly.** |
| `confirmed` | You answered a question the tool asked. |

Every claim shows the exact text it rests on and lets you open the retrieval
that found it. **If it cannot show you that, the claim was deleted before you
ever saw it** — that is the whole design.

### Your three jobs

1. **Reject anything that would still pass if the feature broke.** That is the
   one thing the tool cannot check for itself.
2. **Fix wording freely.** Save is explicit; `Esc` puts it back.
3. **Approve** when it reads like a test case you would run.

A scenario with no expected result is not a failure — it means the tool would
not invent one. Add it yourself, or leave the gap.

---

## Getting a better result next time

The review page tells you what your recording cost you — which claims were
dropped and why. In order of impact:

1. A sharp objective, or none.
2. Talking while you record.
3. Marking the element you are verifying.
4. Pressing **New scenario** between separate tests.
5. Going slightly slower.

## When something looks wrong

- **No draft after a few minutes** — the server may not be running. The export
  page says so.
- **A step describes an icon, not a button** — it read the innermost thing you
  clicked. Rename it.
- **An expected result is about the wrong thing** — reject it. That is a signal
  worth more than a correction.
- **Something was not captured** — the step says so in plain words. It is
  telling you, not hiding it.
