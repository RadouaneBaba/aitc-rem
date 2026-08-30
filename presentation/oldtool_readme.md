# AI Test Case Generator

A tool that turns a QA tester's recorded browser session (clicks, inputs,
navigation + spoken/typed narration) into a structured, formal test case —
Gherkin, Excel, or a Jira issue.

It runs end to end today: record a real browser session, and get back a
reviewable test case in the format your team already uses.

- **Chrome extension** (`Extension/`) — captures what the tester does *and what
  the page does back*, plus audio, and calls the backend's API.
- **Backend** (`backend/`) — FastAPI + PostgreSQL, session storage, the
  exporters (Gherkin, Excel, Jira), and the dashboard.
- **Dashboard** (`backend/app/dashboard/`, served at
  [localhost:8000/app](http://localhost:8000/app/)) — review, edit and export
  test cases. Plain HTML/JS, no build step, same origin as the API.
- **AI pipeline** (`ai/`) — transcription plus the chain that turns
  `(events, narration) -> TestCase`. Runs on Groq.

## How it works

The central rule is **capture first, generate as a separate step**:

```
extension ──POST /sessions───────────► raw session stored (events + narration)
          ──POST /sessions/{id}/audio─► audio transcribed → transcript stored
                                        (no AI generation happens yet)

dashboard ──POST /sessions/{id}/narration─► add context to an old recording
          ──POST /sessions/{id}/generate──► AI seam → TestCase (JSONB) + critic findings
          ──POST /test-cases/{id}/versions─► a tester's edit, as a NEW version
          ──POST /test-cases/{id}/export───► rendered on demand: .feature / .xlsx / Jira
```

Three ideas make this work:

1. **A session is never lost.** It's persisted raw before any AI runs, so a
   flaky model or a bad prompt can't destroy a recording, and generation can be
   re-run on the same session as prompts improve.
2. **`TestCase` is the single canonical shape.** The database stores structured
   JSON, never a pre-formatted Gherkin string. Gherkin, Excel, and Jira are all
   *renderings* of that one object, produced on demand. Adding a new export
   format later costs one file.
3. **Nothing is ever overwritten.** Each generation inserts a new row; each
   tester edit inserts another, pointing at the version it came from. The model's
   original always survives, and how much a human had to change is measurable.

### Quality is a chain, and the model is one link

The thing a tester judges a test case by is `expected_result` — the assertion.
Most of the reliability here comes from the links around the model, not the
model itself:

| Link | Where |
|---|---|
| Capture what the app *did back*, not just what the tester did | `Extension/content.js` |
| Align spoken narration to actions by timestamp, in Python | `backend/app/services/ai_client.py` |
| Generation | `ai/chain.py` |
| Deterministic checks on the result, before a human sees it | `backend/app/services/critic.py` |
| Tester review: targeted questions with proposed answers | dashboard |
| Measurement across a fixed set of sessions | `eval/` |

## Getting started

### Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker + Docker Compose v2 | any current release | running the app (`docker compose`, not `docker-compose`) |
| Python | 3.11+ | running the backend test suite outside Docker |
| Node.js | 18+ | running the extension test suite |
| Google Chrome | any current release | loading the extension |

Nothing else is required to run the app — **no API key, no GPU, no model
host**. The AI seams default to `fake`, which returns deterministic output
offline. Add a Groq key later only when you want real generation
(see [Enabling the real pipeline](#enabling-the-real-pipeline)).

Ports **8000** (backend) and **5432** (Postgres) must be free.

### Install and run

```bash
git clone <this-repo-url> ai-test-generator
cd ai-test-generator

# 1. Create your local config. The defaults work as-is for a local run;
#    .env is git-ignored, .env.example is the documented template.
cp .env.example .env

# 2. Build and start Postgres + the backend (first build takes a few minutes).
docker compose up --build

# 3. In a second terminal: create the database tables. Required once on a
#    fresh clone, and again after any schema change.
docker compose exec backend alembic upgrade head

# 4. Confirm it's alive.
curl localhost:8000/health         # -> {"status": "ok"}
```

Step 3 is not optional. `/health` deliberately does not touch the database, so
it answers `ok` even before the tables exist — skip the migration and the first
`POST /sessions` is what fails instead.

Interactive API docs (auto-generated from the request/response schemas) are at
[localhost:8000/docs](http://localhost:8000/docs). Walk through the whole flow
from there without any client: see
[Trying it out via /docs](#trying-it-out-via-docs).

To use it the intended way — recording a real browser session — continue to
[Using the Chrome extension](#using-the-chrome-extension).

### Stopping and resetting

```bash
docker compose down        # stop; database contents survive
docker compose down -v     # stop and delete the Postgres volume (start clean;
                           # re-run the migration afterwards)
```

### Configuration

All settings come from environment variables — see `.env.example` for the full
list with comments. `.env.example` stays in sync with `backend/app/config.py`.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `…@db:5432/aitc` | Postgres connection (`db` in compose, `localhost` outside) |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins. Add the extension's `chrome-extension://<id>` once known. **Never `*`** — combined with credentials, browsers reject it outright. |
| `AI_CLIENT` | `fake` | `fake` \| `real` — which generator the AI seam uses |
| `TRANSCRIBER` | `fake` | `fake` \| `real` — which transcriber the audio seam uses |
| `GROQ_API_KEY` | empty | Required only when either seam is `real` |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Generation model |
| `GROQ_TRANSCRIBE_MODEL` | `whisper-large-v3-turbo` | Speech-to-text model |
| `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_PROJECT_KEY` | empty | Required only for Jira export |

## Exporting a test case

```bash
# gherkin and excel come back as file downloads
curl -s -X POST localhost:8000/test-cases/$TCID/export \
     -H 'Content-Type: application/json' -d '{"target":"gherkin"}' -o test.feature
curl -s -X POST localhost:8000/test-cases/$TCID/export \
     -H 'Content-Type: application/json' -d '{"target":"excel"}'   -o test.xlsx

# jira creates the issue and returns a link
curl -s -X POST localhost:8000/test-cases/$TCID/export \
     -H 'Content-Type: application/json' -d '{"target":"jira"}'
# -> {"issue_key":"KAN-6","url":"https://…/browse/KAN-6"}
```

The issue is created as a **Task**, with the rendered Gherkin embedded in the
description as an ADF code block — so a QA reviewer reads the whole
Given/When/Then, test data included, without leaving the ticket.

> **`JIRA_PROJECT_KEY` is the key, not the name.** It's the uppercase prefix on
> issue ids (the `KAN` in `KAN-6`), which Jira generates at project creation and
> which often resembles nothing you chose — a project named "QA Testing" can
> have the key `KAN`. Getting this wrong returns *"The target project doesn't
> exist or you don't have permission to create issues in it."* To list the keys
> you have access to:
>
> ```bash
> curl -s -u "$JIRA_EMAIL:$JIRA_API_TOKEN" \
>      "$JIRA_BASE_URL/rest/api/3/project/search" |
>   python3 -c 'import sys,json;[print(p["key"], "-", p["name"]) for p in json.load(sys.stdin)["values"]]'
> ```

> **Where do exported files go?** Nowhere on the server — by design. Exports are
> streamed back in the HTTP response and saved wherever the client puts them
> (for the extension, that's the browser's normal download). The database is the
> source of truth; formatted files are always re-rendered fresh, so they can
> never go stale.

A rendered `.feature` looks like:

```gherkin
@login @negative
Feature: Login with a wrong password

  # Test data:
  #   Email field: sara@test.com
  #   Password field: [REDACTED]
  Scenario: Login with a wrong password
    Given the user has a registered account
    When the user enters the email address (data: "sara@test.com")
    And the user enters the password (data: "[REDACTED]")
    And the user clicks the sign in button
    Then an invalid credentials error is displayed
    And the user stays on the login page
```

That's the real pipeline. The **fake** generator produces the same shape with
mechanical phrasing ("the user clicks Sign in button") instead of natural QA
English, so exports and the extension can be exercised without an API key.

Test data is rendered as Gherkin *comments* rather than an `Examples:` table,
because `Examples:` belongs to a Scenario Outline — a parameterised template
run once per row — and this is a single concrete scenario.

## The AI seams

The backend **never calls an LLM directly**. Both AI touchpoints go through a
seam with a `fake` and a `real` implementation, selected by env var:

| Seam | File | Real implementation |
|---|---|---|
| Generation | `backend/app/services/ai_client.py` | `ai/chain.py` (LangChain + Groq, `llama-3.3-70b-versatile`) |
| Transcription | `backend/app/services/transcription.py` | `ai/transcription.py` (Groq, `whisper-large-v3-turbo`) |

`fake` is the default: it returns deterministic output with **no API key and no
extra dependencies**, so the app runs and the whole test suite passes offline.
The real implementations are imported *lazily*, so nothing loads unless you opt
in.

`ai/chain.py` emits the `TestCase` shape directly and
`backend/app/services/adapters.py` validates it into the real contract. That
validator is deliberately tolerant (accepts key aliases, string-or-list fields,
coerces the test-data map) because models drift from their declared output
schema.

It used to be a *translation*: the chain was constrained to a Gherkin-shaped
object (`feature`/`given`/`when[]`/`then[]`) that the adapter converted. That
was circular — the prompt asked the model to write `"When I click login"`, the
adapter stripped the `When ` off, and the Gherkin exporter added it back — and
it was lossy, because Gherkin prose has nowhere to put a captured input value.
Gherkin is one of three renderings, so it had no business being the shape the
model produced.

### Enabling the real pipeline

1. Get a free API key at [console.groq.com](https://console.groq.com) — no
   credit card required.
2. Put it in `.env` and flip the seams:

   ```ini
   GROQ_API_KEY=gsk_...
   AI_CLIENT=real
   TRANSCRIBER=real
   ```
3. `docker compose up -d --build backend`

That's it. The `ai` extra (`langchain-groq`, `groq` — three small pure-Python
packages) is installed in the image, and the compose build context is the repo
root so `ai/` ships inside it. No model host, no ffmpeg, no GPU.

To run it outside Docker instead:

```bash
pip install -e "./backend[ai]"
cd backend && PYTHONPATH=.. uvicorn app.main:app --reload
```

#### Why hosted, after starting local?

The first version ran Ollama + Mistral 7B locally and local Whisper, chosen
because **recorded sessions contain typed input values** — for a login flow,
real credentials — and local inference keeps that on the machine. Two things
overruled it:

- **It didn't fit.** Mistral 7B needs ~4.5 GiB free RAM; the dev machine had
  ~2.3 GiB available and Ollama refused to load the model outright. Whisper
  pulled ~2 GB of torch and needed ffmpeg on top.
- **Small models are bad at the one thing this chain needs.** The whole design
  depends on the model returning a strict schema. A hosted 70B with real
  tool-calling holds that schema far more reliably than a 7B did.

The privacy concern moves to the source instead: the extension **redacts
password-field values before they ever leave the browser**, so credentials
reach neither Groq nor our own database. This landed with the extension rewrite
— see [What it captures](#what-it-captures).

This swap is also the clearest payoff from the seam design: it touched
`ai/chain.py` and `ai/transcription.py` and nothing else. No route, schema,
database, or exporter change.

## Using the Chrome extension

The extension is the intended way in: it records the session, uploads it,
generates the test case, and downloads the export — without leaving the
browser.

**1. Load it.** `chrome://extensions` → enable *Developer mode* → *Load
unpacked* → select the `Extension/` folder.

**2. Allow its origin.** The backend rejects unknown origins, and an unpacked
extension's id is generated at load time, so this can't be pre-configured. Copy
the `chrome-extension://<id>` origin from the extension's card on
`chrome://extensions`, add it to `.env`, and restart:

```ini
ALLOWED_ORIGINS=http://localhost:3000,chrome-extension://<your-extension-id>
```

```bash
docker compose up -d backend
```

Use `up -d`, **not** `restart`: `docker compose restart` restarts the same
container with the environment it was created with, so an edited `.env` is
ignored and the origin stays blocked.

Skipping this makes every request fail CORS — the popup reports a failure and
the browser console shows the blocked origin.

**3. Say what you're checking.** Type one sentence in **Objective** — *"An
expired coupon is rejected at checkout."* This is the one thing the app can
never observe for itself, and it's the strongest signal the model gets.

**4. Record.** Open the page you want to test, optionally leave *Record spoken
narration* ticked, and press **Start**. Interact with the page and say *why*
and *what should happen* — not "now I click the blue button", which the
extension already records better than you can describe it.

**5. Stop.** The session is POSTed, the audio is uploaded and transcribed, and
the popup shows **Open in dashboard**.

**6. Review, edit and export — in the dashboard.** The extension is a capture
tool; everything after capture happens at
[localhost:8000/app](http://localhost:8000/app/). See
[The dashboard](#the-dashboard).

The trade this is meant to be: about 40 seconds of deliberate effort (one
objective sentence, narrate intent rather than actions, one scenario per
recording, a short review at the end) in exchange for a formatted, exportable
test case that would otherwise take 10–20 minutes to write by hand.

### What it captures

Events are recorded in the `Event` contract shape, from the recorded tab only:

- **click** — described the way a tester would say it ("Sign in button"), not
  by tag or id. A click that lands on an icon inside a button is attributed to
  the button.
- **input** — one event per field with its *final* value, not one per
  keystroke. For a `<select>`, the option's visible label ("France"), not just
  the wire value ("FR").
- **navigation** — real page loads *and* SPA route changes.
- **submit** — with the form's field values ordered before it.
- **page** — the page's title and main heading, emitted when they change, so
  the model knows what page each action happened on.
- **outcome** — *what the application did back*: an error or success message
  appearing, a dialog opening, and whatever alert-like text is still on screen
  when you stop.

**Context, not markup.** Each element also carries the visible text of the
block around it — the product card, the table row, the dialog. That is what
turns three identical "Add to cart" clicks into three distinguishable steps. It
is *meaning*, extracted in the page: a product card's HTML is ~1.5 KB of class
names and CDN URLs, while the meaning inside it is `"Nike Air Max 90 · €120.00"`
— 40× smaller and the only part worth sending. Every captured field has a hard
character cap decided before it is written, and raw `outerHTML` is never stored.

**Why capture outcomes at all?** Because they disappear. A tester types a wrong
password, an "Invalid credentials" error appears — *that is the entire test* —
they retype the password, the error vanishes, and they land on the dashboard.
Looking at the page when recording stops would show none of it.

#### Privacy

- **Passwords are redacted in the page**, before anything is sent. Any
  `type="password"` field, or one whose name/id/autocomplete looks like a
  secret, is recorded as `[REDACTED]`. The real characters reach neither the
  database nor the model. The rule is *redact what has no value, capture what
  has value*: a literal password adds nothing to a test case, while the text
  around an element adds a great deal.
- **Captured page context is not masked**, and with `AI_CLIENT=real` the
  session's text — including whatever was on screen — is sent to Groq, a
  third-party API. The escape hatch is per-site: untick **Capture page context
  on this site** in the popup's Settings to record that origin's events without
  reading the surrounding page. Basic capture keeps working.

Treat this as fine for testing against staging and demo applications, and think
twice before pointing it at an application holding real customer data.

## The dashboard

[localhost:8000/app](http://localhost:8000/app/) — available as soon as the
backend is up, no separate deployment, no build step, same origin as the API so
there is no CORS to configure. Three screens:

**Sessions** — every recording, newest first, with its event count and whether
a test case exists yet.

**One session** — its narration, its captured events, and **Generate**.
Two things worth knowing here:

- **Add a note** attaches narration to a recording *after the fact*, then
  regenerate. A thin recording can be improved without re-recording it.
- **Generate** is re-runnable. Each run is kept, so you can compare output
  across prompt changes.

**One test case** — the structured result, its review findings, edit, export,
and version history.

### Review, editing and versions

After each generation, deterministic checks (`backend/app/services/critic.py` —
plain Python, no second model call) look for the failures that matter: a
captured value missing from `test_data`, a step that matches nothing in the
recording, an `expected_result` with no evidence behind it.

Findings appear as a **Review** panel, and where the recording supports it they
arrive **with a proposed answer** — if an error message was captured, the
proposal is that message. Confirming takes two seconds; composing takes two
minutes.

These are **advisory and never block anything.** Exports work with findings
outstanding. The tester is the final authority and the app doesn't pretend
otherwise.

**Editing creates a new version; the model's original is never overwritten.**
That keeps the audit trail, and it makes *how much the tester had to change*
the reliability metric — which turns "we think it's better" into a number.

## Measuring quality

`eval/` holds a fixed set of recorded sessions with known-correct expectations.
Every change to the prompt, the capture format, or the model gets measured
against it instead of judged by eye.

```bash
AI_CLIENT=real python eval/run.py     # real generations — the numbers that matter
AI_CLIENT=fake python eval/run.py     # no API key: checks the harness executes
```

Set `AI_CLIENT` explicitly — unset, the runner reads it from `.env`. On the
fake seam nothing is graded (canned output can't meet quality expectations);
fixtures report `ran`, which proves the pipeline executes.

It touches no database (fixtures go straight through the AI seam) and writes
full results to `eval/results/` for diffing across runs. Fixtures pair up
deliberately — `cart-ambiguity` vs `cart-context`, `no-narration` vs
`login-outcome` — so the value of a capture improvement is visible as a
before/after on the same flow.

Recordings from real testers become fixtures with
`python eval/import_session.py <session-id> --name <name>`; a human then fills
in what "correct" means. See `eval/README.md`.

### Extension tests

> Kept local, like the backend suite — not published to this repository.

```bash
cd Extension
npm install     # jsdom, for the tests only — the extension has no build step
npm test
```

Two suites, both jsdom, no build step:

- `tests/capture.test.js` drives real DOM events through `content.js` and
  asserts on what it reports: description derivation, container context, option
  labels, outcome detection, input coalescing, redaction, and payload hygiene.
- `tests/popup.test.js` renders the real `popup.html` with `chrome.storage`
  stubbed, covering the capture controls and the per-site context toggle.

## Trying it out via /docs

With the app running (`docker compose up --build`), open
[localhost:8000/docs](http://localhost:8000/docs) — this is Swagger UI,
auto-generated from the schemas, and lets you call every endpoint from the
browser via "Try it out" without needing a separate HTTP client.

**Health check.** Expand `GET /health` → "Try it out" → "Execute". Expect
`{"status": "ok"}` with a 200 response.

**Schemas.** Expand any endpoint (e.g. `POST /sessions`) and look at the
"Request body" example and the `Schema` tab — that's the frozen
`Event`/`Session`/`TestCase` shapes rendered straight from the Pydantic models,
no separate documentation to keep in sync.

**Ingest a session.** Expand `POST /sessions` → "Try it out" → replace the
example body with something like:

```json
{
  "app_name": "Demo App",
  "start_url": "https://example.com/login",
  "written_narration": "Logging in with valid credentials",
  "events": [
    {
      "type": "click",
      "timestamp": "2026-07-16T10:00:00Z",
      "sequence": 0,
      "url": "https://example.com/login",
      "target": { "description": "Email field", "tag": "input" },
      "value": null
    },
    {
      "type": "input",
      "timestamp": "2026-07-16T10:00:05Z",
      "sequence": 1,
      "url": "https://example.com/login",
      "target": { "description": "Email field", "tag": "input" },
      "value": "user@example.com"
    },
    {
      "type": "submit",
      "timestamp": "2026-07-16T10:00:10Z",
      "sequence": 2,
      "url": "https://example.com/login",
      "target": { "description": "Login form", "tag": "form" },
      "value": null
    }
  ]
}
```

"Execute" → copy the `session_id` from the response. Then expand
`GET /sessions/{session_id}`, paste that id in, and "Execute" — you should get
the same session back with its events and the typed narration as a transcript.

**Find it again later.** `GET /sessions` lists every recording newest-first, so
you never need to have kept the id. It returns a summary — `event_count` and
`test_case_count` rather than the events themselves, because one recording can
hold hundreds of events — with `limit`/`offset` for paging.

**Add a voice narration.** Expand `POST /sessions/{session_id}/audio`, paste the
same `session_id`, and upload any file in the `audio` field. With
`TRANSCRIBER=fake` the file contents are ignored and a canned narration is
stored — enough to see the flow. (With `TRANSCRIBER=real` it must be real audio
in one of webm/ogg/wav/mp3/m4a/flac, under 25 MB.) Re-fetch the session and you'll see a second
transcript with `"source": "audio"` alongside the `"typed"` one.

**Generate + read a test case.** Expand `POST /sessions/{session_id}/generate`,
paste in the same `session_id`, and "Execute". You'll get back a structured
`TestCase` (title, preconditions, steps, test data, expected result) built from
the events and narration — via the fake stand-in (`AI_CLIENT=fake`) unless you
enabled the real pipeline, so the steps are mechanical ("the user clicks Sign in
button") rather than natural language. Then try `GET /test-cases` to see it
listed, and `GET /test-cases/{id}` to fetch it.

Press "Execute" on `generate` a second time and you'll get a *second* test case
for the same session. That's deliberate — generation is re-runnable, and each
run is kept so you can compare output across prompt changes. `GET /test-cases`
returns them newest-first, and `?session_id=` narrows the list to one
recording's history.

**Export it.** Expand `POST /test-cases/{test_case_id}/export`, paste the test
case `id`, and use body `{"target": "gherkin"}`. Swagger shows a "Download file"
link in the response. Try `{"target": "excel"}` for the workbook.

## Checking the database directly

To confirm the data above is really persisted in Postgres (not just held in
memory by the app), open a database shell:

```bash
docker compose exec db psql -U aitc -d aitc
```

Then run:

```sql
SELECT id, app_name, start_url, status, created_at FROM sessions;
SELECT id, session_id, type, sequence, url, value FROM events;
SELECT id, session_id, source, text, audio_started_at FROM transcripts;
SELECT id, session_id, parent_id, status, created_at FROM test_cases;

-- what the page did back, and the context around each element
SELECT sequence, type, target->>'description', target->>'context' FROM events
  WHERE session_id = '<id>' ORDER BY sequence;
-- the critic's advisory report on a generation
SELECT jsonb_pretty(findings) FROM test_cases WHERE id = '<id>';
```

`\q` to exit.

## Running tests

> The test suites are kept local and are not published to this repository.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e "./backend[dev]"
docker compose up -d db

cd backend
DATABASE_URL="postgresql+psycopg2://aitc:aitc_dev_password@localhost:5432/aitc" \
  alembic upgrade head
DATABASE_URL="postgresql+psycopg2://aitc:aitc_dev_password@localhost:5432/aitc" \
  pytest
```

Tests run against a real Postgres (tables are truncated between tests) and use
the `fake` seams throughout, so the suite needs no AI dependencies.

### What is and isn't verified

Being explicit about this, because "the tests pass" does not mean "the
integration works":

| Area | Status |
|---|---|
| Ingest, generation flow, persistence | ✅ tested against real Postgres |
| Gherkin + Excel export | ✅ tested (the `.xlsx` is re-opened and asserted valid) |
| Audio endpoint (fake transcriber) | ✅ tested, and smoke-tested live |
| CORS, error handling, seam failure paths | ✅ tested |
| Jira export | ✅ **verified live.** A real issue was created on a real Jira Cloud site: `issuetype: "Task"` was accepted, the ADF `codeBlock` description rendered the full Gherkin (test data and `[REDACTED]` intact), and the project required no extra custom fields. |
| Real AI pipeline (Groq) | ✅ **verified live.** Generation and transcription both run end to end against Groq from inside Docker; the model holds the declared schema and the adapter maps it correctly. |
| Input values in generated output | ✅ **fixed and verified live.** The chain emits the `TestCase` shape directly, so `steps[].data` and `test_data` are populated on both the real and fake paths, and rendered by both exporters. Redacted passwords stay `[REDACTED]` through to the export. |
| Extension capture logic | ✅ tested against a real DOM (jsdom) — descriptions, input coalescing, password redaction, payload shape. `cd Extension && npm install && npm test` |
| Extension → API contract | ✅ the exact event shape the extension emits was POSTed through `/sessions` → `/generate` → `/export` |
| Extension in a real browser | ✅ loaded into Chrome and driven through a real record → generate → export flow |
| v2 pipeline (context, page identity, outcomes, alignment) | ✅ **measured**, not asserted: every change was run against `eval/` on the real Groq path, including paired before/after fixtures |
| Dashboard (list → session → generate → review → edit → export) | ✅ driven end to end in a real headless Chrome against the live backend, no console errors |
| Versioning | ✅ verified live — editing and accepting a review suggestion both insert a new row with `parent_id` set; the original stays in history |
| Whisper segment timestamps | ✅ **verified live** against Groq with real synthesized speech: `verbose_json` returns `segments` with `start`/`end`, and they persist to `transcripts.segments`. Note a short clip can come back as one segment — alignment gets coarser, it doesn't break |
| Migrations | ✅ all three v2 migrations upgrade *and* downgrade cleanly on a populated database |

## Project layout

```
backend/
  app/
    api/routes/      sessions.py, test_cases.py
    db/              SQLAlchemy models + session
    schemas/         Pydantic contracts (shared with the extension + exporters)
    services/
      ai_client.py     generation seam + what the prompt gets to read
      transcription.py transcription seam
      adapters.py      chain output → validated TestCase
      critic.py        deterministic checks on a generation (advisory)
      exporters/       gherkin.py, excel.py, jira.py
    dashboard/       review/edit/export UI (static, served at /app)
  alembic/           migrations
ai/                  AI pipeline (Groq): prompts.py, chain.py, transcription.py
eval/                evaluation set: fixtures/, run.py, import_session.py
Extension/           Chrome extension (Manifest V3)
  config.js            shared constants + storage keys
  background.js        service worker: session lifecycle, all API calls
  content.js           DOM capture: descriptions, context, outcomes, redaction
  popup.html/.js       objective, narration, start/stop, link to the dashboard
  record.html/.js      microphone capture → audio upload
```

The schemas in `backend/app/schemas/` are the **stable contract** depended on by
the extension, the database models, and every exporter, and mirrored in the
OpenAPI docs at `/docs`. Changing a field means changing it on all sides in one
deliberate move.

## Milestones

1. ✅ **Skeleton that runs** — Docker Compose (Postgres + backend),
   `.env.example`, FastAPI app, `GET /health`.
2. ✅ **Schemas as code** — Pydantic request/response models, SQLAlchemy ORM
   models, an initial Alembic migration, working `/docs`.
3. ✅ **Ingest** — `POST /sessions` stores a recorded session raw;
   `GET /sessions/{id}` reads it back. No AI call at this step.
4. ✅ **AI seam (stubbed) + generation** — `POST /sessions/{id}/generate`
   produces a structured `TestCase` behind `AI_CLIENT=fake`, swappable to the
   real pipeline via one env var with no route changes.
5. ✅ **Gherkin + Excel export** — `POST /test-cases/{id}/export` renders a
   stored test case's JSON into Gherkin feature text or an Excel workbook,
   returned as file downloads.
6. ✅ **Audio + Jira** — `POST /sessions/{id}/audio` transcription seam; Jira
   issue creation via REST v3 with the Gherkin embedded in the description; the
   real AI pipeline extracted into `ai/` and wired behind the seams.
7. ✅ **Hardening** — configurable CORS for the extension origin, uniform error
   handling (502 for upstream AI/Jira failures, 503 when the real pipeline
   isn't installed, generic 500s that never leak tracebacks), timing logs on
   both seams, and this README.

## Integration and refinement

The backend milestones above are done. These joined the three parts into one
app, and then sharpened it:

1. ✅ **Hosted LLM** — Ollama/Mistral and local Whisper replaced by Groq for
   both seams; the real path works inside Docker and is verified live.
2. ✅ **Extension rewrite** — it calls the API instead of downloading files:
   session lifecycle, contract-shaped events, password redaction, audio
   upload, narration input, and generate + export in the popup. (v2 moved
   generate/edit/export out of the popup and into the dashboard — see below.)
3. ✅ **End-to-end verification** — extension loaded in Chrome, origin added to
   `ALLOWED_ORIGINS`, a real flow recorded → generated → exported.
4. ✅ **The AI emits the contract directly** — the generation chain used to be
   constrained to a Gherkin-shaped schema that was then translated into
   `TestCase`. That round trip was circular and had nowhere to put captured
   input values. See [The AI seams](#the-ai-seams).
5. ✅ **Stored work is reachable** — `GET /sessions` and
   `GET /test-cases?session_id=`, so a recording outlives the popup that made
   it.
6. ✅ **Jira verified live** — a real issue created on a real Jira Cloud site.

## v2 — from "it generates" to "a tester trusts it"

v1 generated a test case from every recording. The problem was that a tester
couldn't trust the output enough to use it, and the root cause was structural,
not a prompt to tune: **we recorded what the tester did, never what the page did
back**, so the field they judge the result by (`expected_result`) had exactly one
source — the narration — and the model filled any gap by inventing.

1. ✅ **Send what was already stored.** The click log dropped the URL and never
   received the app name or start URL at all, so the model didn't know what page
   it was on. It now gets a header, page transitions, pause annotations, and
   narration in labeled sections (objective / typed / spoken) instead of one
   blind `"\n".join`. No schema change; the best value-per-hour in the project.
2. ✅ **The dashboard, editing and versioning** — plus adding narration to an
   old session and regenerating. The biggest trust win, and it needed no AI work
   at all.
3. ✅ **Capture v2** — container context, page identity, `<select>` option
   labels, and a per-site context switch.
4. ✅ **Outcome capture** — the root-cause fix. A short list of named signals
   (alert/status/live regions, dialogs, error/success/toast markup, plus text
   appearing in the container just acted on) watched briefly after each action.
   A cookie banner matches none of them, so it's ignored by construction.
5. ✅ **Time-aligned narration + the critic.** Whisper segments are anchored to
   the recorder's start time and interleaved into the log at the moment each
   phrase was spoken, so "it should show an error" attaches to the click it
   describes by measurement rather than guesswork. Deterministic checks then run
   on every generation and surface as advisory review questions.
6. ✅ **The evaluation set** (`eval/`), so all of the above is measured rather
   than asserted.

Deliberately **not** built: an LLM critic grading the generator's output (the
deterministic checks are unambiguously worth it; a second model call doubles
latency and spend for unproven benefit — revisit only if the eval set says so),
splitting one recording into several test cases (replaced by "one scenario per
recording" plus a nudge at 150 events), async generation (replaced by honest
progress text), and iframe / multi-tab / hover / shadow-DOM capture.

### Known follow-ups

- **No authentication.** Every endpoint is open. Correct for a local tool,
  blocking for a shared deployment — a deliberate open decision, not an
  oversight.
- **No CI.** The test suites are kept local (see "Running tests"), so nothing
  runs them automatically on push.

Resolved:

- ~~**Jira export is deferred.**~~ Verified live: a real issue was created (see
  [Exporting a test case](#exporting-a-test-case)). The one snag was config,
  not code — `JIRA_PROJECT_KEY` wants the project *key*, not its name.
- ~~**Captured input values never reach the generated test case.**~~ Fixed by
  dropping the intermediate Gherkin schema — see
  [The AI seams](#the-ai-seams). The chain now emits the `TestCase` contract
  directly, so values land in `steps[].data` and `test_data`, and both
  exporters render them.
