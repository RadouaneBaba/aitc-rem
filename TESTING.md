# Testing against a real website

A developer runbook: record a public site, run it through the pipeline from a
terminal, and read the trace when something looks wrong.

**If you are a QA tester, you want [docs/RECORDING.md](docs/RECORDING.md)
instead** — everything here can be done from a browser, and that document is
about doing it well rather than about the plumbing.

This has now been run against a real site in a real browser. The last section is
about what to do when you find something anyway.

---

## 0. Once, before you start

```bash
pnpm install
pnpm --filter @aitc-rem/extension build
```

The build writes `extension/dist/`. Rebuild after any change to
`extension/src/`.

Check the key is in place (it is read from `.env`, never committed):

```bash
.venv/Scripts/python -c "from server.util.env import load_env; import os; load_env(); print('key:', bool(os.environ.get('GEMINI_API_KEY')))"
```

## 1. Load the extension

1. Chrome → `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. **Load unpacked** → select `D:\files\Projects\aitc-rem\extension\dist`
4. Pin the extension so its icon is visible

**Reload any tab you already had open.** Content scripts inject on navigation,
so a page loaded before the extension existed has no recorder in it. This is the
single most common reason a recording comes out empty.

To see the recorder's own logs, click **service worker** on the extension card
at `chrome://extensions`.

## 2. Pick a site

Already allowlisted, and safe to send to a free-tier model:

| Site | Login |
|---|---|
| `https://www.saucedemo.com` | `standard_user` / `secret_sauce` |
| `https://the-internet.herokuapp.com` | none |
| `https://opensource-demo.orangehrmlive.com` | `Admin` / `admin123` |
| `https://demo.opencart.com` | none |

For anything else, add the origin to `config/allowed_origins.yaml`:

```yaml
allowed:
  - https://www.saucedemo.com
  - https://your-site.example.com     # <- add it here
```

The origin must match exactly — scheme and host, no trailing slash, no path.

> Only demo and public sites. Free-tier prompts are used for training and may be
> read by human reviewers, so do not record a site while signed into a real
> account of yours until you are on a paid endpoint.

## 3. Record

1. Open the site **and leave that tab focused**
2. Click the extension icon
3. Type what you are checking, e.g.
   *"Check that adding two items updates the cart badge and the checkout total"*
4. **Start recording** — the icon shows a red `REC` badge
5. Do the flow. Take it at human speed; clicking faster than about 150 ms apart
   raises `rapid_sequence` on the events
6. Optional, from the popup: **Checkpoint** (force a step boundary),
   **New scenario**, **Mark a bug**, **Note…** (becomes the step name verbatim)
7. **Stop & export**

A tab opens showing what was captured, whether it validates against the schema,
and exactly which values were redacted. Read that page — it is the pre-send
screen.

8. **Save recording.json and screenshots** → lands in
   `Downloads/aitc-rem/<recordingId>/`

### Before moving on

```bash
cd ~/Downloads/aitc-rem/rec_XXXXXXXX

python -c "import json;d=json.load(open('recording.json',encoding='utf-8'));print(d['metadata']['origins']);print(len(d['events']),'events');print(d['metadata'].get('fidelitySummary'))"

grep -c "your-password-here" recording.json    # must print 0
```

If the password appears, stop and tell me — that is a redaction bug and it
matters more than anything else in this document.

## 4. Run the pipeline

```bash
cd D:/files/Projects/aitc-rem
.venv/Scripts/python -m server.cli run ~/Downloads/aitc-rem/rec_XXXXXXXX/recording.json --run-id site_001
```

Useful flags:

| Flag | Why |
|---|---|
| `--rpm 10` | pace requests; raise if your quota allows, lower on 429s |
| `--config A0` | no tools, for comparison |
| `--offline` | replay from cassettes only, no provider calls |
| `--model gemini-3.5-flash` | try a different model |
| `--budget 4` | fewer tool calls per step |

Everything lands in `runs/<recordingId>/site_001/`:

```
segments.json     step boundaries, deterministic
ir.json           the intermediate representation
trace.json        every tool call, model call and validator result
tools/tc_*.json   one file per retrieval, hashed
*.feature         the output
```

## 5. Check the output

```bash
.venv/Scripts/python scripts/prove_grounding.py runs/<recordingId>/site_001
```

Wants: `PASS: every assertion resolves to a retrieval` — and ideally
`Calls per step: ... (varies)` rather than `FLAT`, which is the sign the agent
spent effort where the work was hard.

Then read the feature file. What "good" looks like:

- Step text describes **intent** — "the tester submits the order", not "clicks
  the blue button"
- It uses the **site's own words**, taken from accessible names
- `Then` lines have a `# evidence:` comment underneath naming an event and a
  `tc_` id
- Steps marked `!!` are ones it is unsure about — that is the system working
- The validator report at the top of the terminal output shows `ok` or a
  specific reason

### The comparison worth running

```bash
.venv/Scripts/python -m server.cli ablate ~/Downloads/aitc-rem/rec_XXXXXXXX/recording.json
```

A0 has no tools, so it has no retrieval to cite. Watch whether it omits the
expected result (honest) or invents a citation (what the gate exists to catch).

## 6. When something breaks

It is a new kind of site, so this is expected rather than a failure of the run.

**Empty or tiny recording** — the tab was open before the extension loaded.
Reload it and record again.

**Steps read as "generic" or unnamed** — the site uses divs with no roles or
labels. Check `no_accessible_name` in the fidelity summary. This is the recorder
correctly reporting that it could not tell, not a crash.

**Everything flagged `settle_timeout`** — the site has a long-poll, an SSE
stream or an analytics beacon that never completes. Look at
`settle.inFlightAtEnd` on the events in `recording.json`.

**`closed_shadow_root` everywhere** — a component library using closed shadow
roots. Unreadable by any tool, CDP included. Flagged, not guessed.

**A step name that is confidently wrong** — the interesting case. Open
`runs/<rec>/site_001/trace.json` and find the step's `StepInvestigation`: it
records what the agent did not know, what it retrieved, and why it stopped.

**Slow, or 429s** — free-tier quota. Lower `--rpm`, or re-run with `--offline`
to replay what was already recorded.

**Anything else** — the three files worth sending me are `recording.json`,
`trace.json` and the terminal output. Between them they say what was captured,
what the agent did, and what the gate thought of it.

## What is not built yet

So you are not surprised:

- **No multi-tab capture.** An OAuth popup will not be recorded. This is the one
  gap in this list with no design behind it yet.
- **No golden set.** The ablation measures whether agency helps; it does not
  measure whether a given change made the output *better* against hand-written
  references. Every recording you make is a candidate for that set, so keep
  them.

Everything else in this file's previous version of this list has since shipped,
in case you remember otherwise: decomposition (one recording, N test cases, with
wrong turns pruned and reported), the step library, narration through a real
microphone, replay against the live app, the review UI
(`python -m server.cli serve`), and Excel/Jira/Qase export.

## What Phase 3 added, and what to look at

Three things, all of which show up in a run without being asked for:

- **A critic and a bounded repair loop.** Only in `--config A2`. When a step
  name is vague or an expected result is about the wrong thing, the offending
  stage re-runs with the criticism as input, up to three attempts. What it
  cannot fix is stated on the step rather than dropped — look for
  `criticNotes` in `ir.json` and the `Critic:` lines in the sidecar.
- **Coverage suggestions.** What the recording revealed that nothing exercised.
  They are quarantined: never in the `.feature`, always under an UNVERIFIED
  heading, and `suggestions_quarantined` fails the run if one reads back as a
  step. `coverage.json` has them, with what each rests on.
- **Bug mode.** If the session actually broke — a 5xx, an uncaught exception, or
  you pressed **Mark a bug** — you get a `.bug.md` repro report *alongside* the
  test case, not instead of it. `bug.json` shows the detector's arithmetic,
  including on runs where it decided this was not a bug.

A 4xx that the test is *about* — "orders over €500 require approval" — is
deliberately not enough to trigger bug mode. If you think you have found a real
failure and no report appeared, open `bug.json`: it lists every signal that
fired and the threshold it did not reach.

The comparison worth reading in the ablation table is `Findings` beside
`Converged`. A convergence rate on its own is 100% when the critic found
nothing, in the same way a grounding rate is 100% when the tool claims nothing.

## What Phase 4 changed, and what to look at

The generator was rebuilt. Nothing about how you run it changed; what changed
is what comes out, and the reason is worth reading before you judge a run.

Against the seven fixtures the old output was good. Against a recording made on
a real commercial site — 34 clicks, no annotations, no narration, which is what
a tester's first recording actually looks like — it produced a scenario with no
`Given`, a dangling `When` at the end, six unrelated checks in a row, and a
confidently wrong number that the same run's own warnings said was ungrounded.
Every fixture passed throughout, because every one of them carries an
annotation, a narration track or a scenario break, and §6.7 says in bold that
those are optional.

**So look at these first when you read a run:**

- **`draft.json`** — the whole document as one author wrote it, before anything
  was proved. This is the model's actual contribution to the run; if a test
  case is shaped wrongly, it is shaped wrongly here.
- **`assertions.json`** — what happened to each proposed expected result:
  `bind`, `revise` or `unsupported`, with the reason. **A deleted claim is a
  normal outcome**, not a failure. The drafter proposes what it believes the
  test should check; anything the recording will not support is removed rather
  than softened, so a scenario with fewer expected results than you expected is
  usually the tool declining to guess.
- **`toolCallsPerStep`** in `trace.json`. It should VARY. On `checkout` it
  reads `{step_002: 1, step_003: 4, step_004: 1}` — four retrievals on the
  rejected-order step and one each on the others. A flat column would mean
  retrieval had gone back to being a toll paid per step rather than effort
  spent where the work was hard.

**A0 now emits nothing at all.** It used to fabricate: thirteen assertions,
none grounded. It cannot any more, because the model never supplies a
`toolCallId` and there is nothing for a claim to rest on without retrieval. So
A0 vs A1 is a comparison about **Yield**, not about grounding rate, and
`Fabric.` is structurally zero in every row. Read `Grounded` beside `Yield`:
a rate of 1.0 means nothing for a configuration that claims nothing.
