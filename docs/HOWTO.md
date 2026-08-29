# Everything this does, and how to reach it

For whoever runs the tool rather than records with it. The tester's half is
[RECORDING.md](RECORDING.md), which needs no terminal.

**Written from what works.** Not from [SPEC.md](../SPEC.md) — a good deal of
what that describes was designed and never ran, and a how-to written from a spec
documents features that do not exist. Everything below has been executed. Where
something is built but unproven, it says so.

**This file is the OPERATOR's document, and the split is deliberate.** `/help`
in the running tool is the how-to-USE guide: record, confirm, review, export,
and nothing a reader would need a terminal for. It is not a shorter version of
this file -- it stopped being one on 2026-08-29, because a page that was half
CLI invocations and half `project.yaml` keys was documenting the machine to
somebody who only wanted to do the task. Everything here is what you run; what
the tester does is [RECORDING.md](RECORDING.md) and `/help`; why any of it is
shaped this way is [DESIGN_NOTES.md](DESIGN_NOTES.md).

---

## The shortest version

```bash
pnpm start            # venv + deps + both builds if needed, then the server
                      # and the review UI on :8000. The whole first run.
pnpm start --demo     # the same, plus the fixture app on :5173
```

Load `extension/dist` as an unpacked extension in Chrome
(`chrome://extensions` → Developer mode → Load unpacked). Record, stop, send.

Everything after this is detail.

---

## What actually happens to a recording

```
record            the extension, in the tester's own browser
  ↓
confirm           one screen: "should this have happened?"  ← the oracle
  ↓
segment           code. Idle gaps, URL changes, checkpoints. Hints, not steps.
digest            code. The whole session as ~1,600 tokens of index.
  ↓
expectations      one model call. What SHOULD have happened, if nobody said.
author            one conversation. The whole document, retrieving as it goes.
  ↓
render            Gherkin + evidence sidecar (+ xlsx, + Jira issue)
validate          five checks that cannot be wrong
judge             a second model, fresh context: would a QA lead sign this?
  ↓ (at most once)
revise            the author rewrites, given what came back
  ↓
coverage          what this session did not cover — quarantined, never a step
replay            drive the test case against the live app  ← optional, strongest
```

Each stage reads a file and writes a file into `runs/<recordingId>/<runId>/`.
When the output is wrong, open the artifact and see which stage lied.

---

## The commands

### Run the pipeline over one recording

```bash
.venv/Scripts/python -m server.cli run <recording.json>
.venv/Scripts/python -m server.cli run <recording.json> --offline   # cassettes only, free
.venv/Scripts/python -m server.cli run <recording.json> --config A1 # no oracle
```

`--offline` replays recorded model responses and never reaches a provider.
Changing a validator, a renderer or the segmenter does not change the model
input, so those re-runs cost nothing. A prompt change invalidates its own
cassettes by construction and `--offline` will then say so rather than lie.

### Run it, then actually run the test

```bash
pnpm demo    # in another terminal — replay needs the app up
.venv/Scripts/python -m server.cli run tests/fixtures/checkout.recording.json --replay \
  --replay-param user_email_1=tester@example.com --replay-param password=hunter2
```

The strongest check in the system and the only claim in it nobody can argue
with: every other number says a claim can point at the retrieval that produced
it; this says the test **runs**, and that what it asserts is still true.

`--replay-param` supplies the values redaction replaced. A replay that cannot
fill one is reported **blocked**, never failed — "I could not run this" and
"this does not work" are different findings.

Against an application with a real login, sign in once and keep the session:

```bash
node scripts/login_once.mjs https://your-app.example.com/ .auth/app.json
.venv/Scripts/python -m server.cli run <rec.json> --replay --storage-state .auth/app.json
```

That file is a live session. It is gitignored and gets the same treatment as
`.env`. An expired one is ignored rather than fatal — the replay just signs in
the slow way.

### Compare the three architectures

```bash
.venv/Scripts/python -m server.cli ablate tests/fixtures/*.recording.json
```

| | |
|---|---|
| **A0** | no retrieval, no oracle — one shot over the session index |
| **A1** | retrieval, no oracle — isolates what **looking** is worth |
| **A2** | retrieval and oracle — isolates what **asking** is worth |

**Never read a rate on its own.** Read `Grounded` with `Yield`, `Executes` with
`Rechecked`, `Judged` with `Unsigned`. A configuration that abstains scores
100% on every rate in the table; this project has met that trap in seven
columns and should assume it is in the next one.

### Bring in a recording made elsewhere

```bash
.venv/Scripts/python -m server.cli import <chrome-recorder-export.json>
```

A Chrome DevTools Recorder export. It carries selectors and no accessibility
tree, so the output is thinner — but it is redacted on the way in, and it
reaches `narrated` if you supply a transcript.

### Narration

```bash
.venv/Scripts/python -m server.cli transcribe <recording.json> --in-place
.venv/Scripts/python -m server.cli run <recording.json> --narration notes.vtt
pnpm run bootstrap --with-transcription     # installs faster-whisper
```

Audio is transcribed **on this machine** and never uploaded. It is the only
lossy evidence source here, which is why a low-confidence segment cannot
support the `narrated` rank, and why the audio is kept so a human can listen.

### Push to Jira

```bash
.venv/Scripts/python -m server.cli jira-push <run-dir>
```

`JIRA_SITE`, `JIRA_EMAIL`, `JIRA_API_TOKEN` in `.env` (gitignored) — never in
`config/project.yaml`, which is committed. The export builds the issue and
writes it to disk; only this sends it.

For **Xray** there is nothing to build: your `.feature` file is the import
format. `config/project.yaml` has the two curl commands in a comment.
**TestRail** has an official CLI (`trcli … parse_gherkin`); likewise nothing to
build.

---

## The measuring scripts

```bash
bash scripts/check.sh                              # before finishing, always
.venv/Scripts/python scripts/prove_grounding.py    # every claim resolves, or it fails
.venv/Scripts/python scripts/capture_cost.py       # what capture actually costs
.venv/Scripts/python scripts/effort_difficulty.py  # SS3.4; refuses to overclaim
.venv/Scripts/python scripts/eval_packet.py        # one page per run, for judging
```

`capture_cost.py` says out loud when a recording's sizes are its **cap** rather
than its pages. Run it before believing any number about what capture costs —
the last time nobody did, every "a full page is ~29 KB" figure in the design
notes turned out to be measuring a 400-node limit.

`effort_difficulty.py` prints *not enough data* until eight steps have been
edited and eight left alone. That is honest rather than broken: the correlation
needs review activity, and nothing in the code will produce it.

---

## Settings worth knowing

All in `config/project.yaml`, all with a default that produces good output.

| | |
|---|---|
| `style` | which worked `.feature` the author is shown. `automation` (default: every action, specific values), `business` (few steps, plain language, one verdict per scenario) or `data-driven` (a repeated flow becomes one `Scenario Outline` with the values in an `Examples` table; anything that happened once stays a plain scenario). It changes the EXAMPLE, never what may be claimed. |
| `voice` | subject of every step. `I` switches to the classic Cucumber register. |
| `parameters` | `inline` quotes values in the step text; `outline` lifts them into an `Examples` table. |
| `exports` | `xlsx` is on by default — for a large part of the audience the workbook *is* the deliverable. `jira` builds an issue. |
| `trace` | `sidecar` writes `<case>.trace.md` beside the feature. The feature body stays prose and nothing else. |
| `narration.model` | `small` by default. `base` is noticeably worse on exactly the numbers and proper nouns a test case is made of. |
| `origin_policy` | `warn` by default. See below. |

`config/allowed_origins.yaml` lists sites a recording may touch before being
sent to a **training-eligible** endpoint. The thing being guarded is a property
of the model tier, not the provider: free-tier prompts may be used for training
and read by human reviewers, so record demo and public applications on one. A
paid endpoint with a no-training term makes the question moot — set
`origin_policy: off`.

**Redaction is not here, and deliberately.** It happens in the browser before
anything is written to disk, so by the time this file could be read the decision
has already been taken. The recorder popup owns it, under *Redaction*, before
you press Start — and the level travels on the recording, so two sessions made
under different settings can sit in one project and each still means what it
meant when it was made.

| | |
|---|---|
| `full` | the default. Emails, cards, tokens and anything typed into a password field become placeholders. |
| `secrets_only` | the pattern scan is off; passwords are still hidden. For an application whose real data looks sensitive — an order reference that scans as a card number. |
| `off` | nothing is hidden. |

Below `full`, `no_placeholder_leak` warns instead of refusing to render — you
cannot ask for the raw values and also gate on their absence — and the run is
**refused** unless `origin_policy` is `off`.

**Adding a Gherkin style** is writing `server/pipeline/styles/<name>.md`: one
good feature file in that style, with its annotations beside it, and the name in
`STYLES`. Nothing else in the pipeline changes. That is the point — every
attempt here to change output with a *rule* measured at or near zero uptake, and
every improvement came from a better example.

A `Scenario Outline` appears when the **author** decided the flow was genuinely
repeated with different values. That is a judgement about test design and is
distinct from `parameters: outline`, which is a rendering setting.

**What a verdict can say.** A claim carries the SHAPE of what it asserts, and
the gate re-checks that shape against the stored retrieval: `contains` (the
default), `first_of` (sorting and ranking), `count` (*"the list drops to 9"*)
and `absent` (*"the error is gone"*). Without it the check was substring
containment, so a sentence saying FIRST was proved by a string appearing
anywhere.

---

## Reading the review screen

Three panes. Left the test case, middle the selected step, right the feature
file — with **Why this step** one click away when you want the retrieval chain.

- **A step with no expected result and a sentence explaining why** is the
  designed outcome when the recording does not contain a verdict. A visible gap
  beats an invisible falsehood. It is the one thing on the screen only a person
  can close.
- **Coverage suggestions are marked UNVERIFIED** in every renderer and are
  refused at the gate if they read back as a step. They are prompts for a human,
  never part of the test.
- **A bug report sits beside the test case, not inside it.**
- **The judge's findings never appear here.** They go to the author; what a
  reviewer sees is prose in their own language.

Approving is recorded. It is the only source of the difficulty labels
`effort_difficulty.py` needs, so a few real reviews are worth more than they
look.

---

## When it goes wrong

**The run stops with a quota error.** The free tier allows five requests a
minute and twenty a day on some models. `runs/_budget.json` tracks the day.
`--offline` re-runs from cassettes for free.

**`--offline` says there is no cassette.** A prompt changed, so the key changed.
That is the cassette being honest; run it live once.

**A replay is blocked rather than run.** It is missing a parameter, or nothing
is listening at the recording's `startUrl`. Both are stated in the output.

**Schema drift on `check.sh`.** Something under `server/models/generated/` or
`extension/src/types/` was hand-edited. Edit `schema/*.schema.json` and run
`pnpm codegen`; the generated files are never edited directly.

**The e2e suite is not in `check.sh`.** Run `pnpm e2e` when you touch the
recorder or the popup. That gap is how a green suite once hid a dead path for
months.

---

## Deliberately not built

- **Verified coverage suggestions.** Coverage can only suggest what it can see
  in the recording. Confirming a suggested path exists needs a live browser.
- **A golden-set eval harness.** Deferred on the argument that a golden set
  built after watching the pipeline fail on real recordings beats one written
  against imagined failure modes. Keep every recording; they are that set.
- **Replaying a scenario that was split out of a longer session.** It runs — the
  shared opening is replayed as preconditions — but a scenario cut from one
  linear flow can reach a state the original did not. Read a green second
  scenario with that in mind.
