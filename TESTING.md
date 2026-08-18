# Testing against a real website

A runbook for recording a public site and putting it through the pipeline.

Nothing here has been validated against a real site yet — only against the
bundled fixture app. Expect to find something. The last section is about what to
do when you do.

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

- **One test case per recording.** Splitting a long session into several is
  Phase 2, so a fifteen-minute session becomes one long test case.
- **At most one expected result per step**, always `inferred`. Ranked candidates
  from annotations and narration are Phase 2.
- **No review UI.** You read the terminal and the `.feature` file.
- **No Excel or Jira export.** Gherkin only.
- **No multi-tab capture.** An OAuth popup will not be recorded.
- **Narration is not wired in.** Audio is not captured yet.
