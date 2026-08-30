# AI Test Case Generator

A tool that turns a QA tester's recorded browser session (clicks, inputs,
navigation + spoken/typed narration) into a structured, formal test case —
Gherkin, Excel, or a Jira issue.

## State of the project

**v2 is built and verified end to end.** The trust problem v2 existed to fix —
we recorded what the tester *did*, never what the page *did back*, so
`expected_result` had one thin source and the model invented the rest — is
addressed at every link of the chain:

- **Capture**: container context, page identity, `<select>` option labels, and
  **outcome events** (what the app did back), all hard-capped, with a per-site
  context switch.
- **Send**: app name, start URL, page transitions, pause annotations, labeled
  narration, context attached only where the element description is ambiguous.
- **Generate**: prompt v4, with an explicit evidence hierarchy for
  `expected_result` (observed > narrated > modest inference).
- **Check**: `app/services/critic.py`, deterministic only, findings stored on
  the row and rendered as **advisory** review questions with proposed answers.
- **Review**: the dashboard at `/app` — edit as a new version, never overwrite.
- **Measure**: `eval/`, run against the real Groq path on every change.

`changes/2026-08-06-improvement-plan.md` is the original v2 reasoning and
`changes/2026-08-06-v2-implementation.md` is what actually got built, including
where the plan was wrong. Read both for the *why* before changing this area.

**Every folder is fair game to read, edit, refactor, or delete.** There are no
ownership boundaries left and no sign-off to wait for. A few comments still
mention who owned what or which milestone something landed in — that history is
over; delete the stale clause, but keep the reasoning that follows it (e.g.
`schemas/event.py` explains *why* `type` is a plain string, which still matters).

- `backend/` — FastAPI + PostgreSQL, session storage, exporters, critic, and the
  dashboard (`app/dashboard/`, static, served at `/app`). The mature part.
- `ai/` — the Groq pipeline: prompts, generation chain, transcription.
- `Extension/` — Manifest V3 capture UI. **Capture only** — it links to the
  dashboard once a session is saved and never renders a test case.
- `eval/` — the evaluation set: fixtures, runner, session importer.

The one thing that stays disciplined is the **shape** of the data — not because
anyone owns it, but because the schemas are what let the extension, the
database, and the exporters agree with each other. See "The contract" below.

## Non-negotiable architectural rules

These have each already paid for themselves. Do not erode them casually.

1. **Capture and persist first, generate as a separate step.** The extension
   never triggers the LLM directly. A session is stored raw; generation is an
   explicit, re-runnable action on a stored session
   (`POST /sessions/{id}/generate`). This avoids data loss, allows regeneration
   as prompts improve, and keeps debugging tractable.

2. **Structured data in the database, formatting at the edges.**
   `test_cases.content` stores the TestCase as JSONB — never a pre-formatted
   Gherkin string. Gherkin/Excel/Jira are rendered on demand from that JSON.
   Adding a fourth export format costs one file.

3. **The AI is reached through a seam, never called directly from a route.**
   `app/services/ai_client.py` wraps
   `generate_test_case(events, transcripts, *, app_name, start_url,
   spoken_segments) -> GenerationResult`; `app/services/transcription.py` wraps
   the audio seam and returns `(text, segments | None)`. Both are selectable by
   env var (`AI_CLIENT` / `TRANSCRIBER` = `fake|real`), and the real
   implementations are imported lazily — keep them lazy. Routes call only the
   public entry points, never the `_fake_*`/`_real_*` functions.

   `GenerationResult` carries `test_cases` (a **list** — one recording can
   cover several behaviours), `plans` (the Analyst's slice per scenario) and
   `judge_findings`. It also raises `NothingToTest` when a recording contains
   no verifiable behaviour, which the route answers as 422, not 502: a
   recording of someone clicking around a menu genuinely has no test in it,
   and saying so beats writing up the browsing.

   The seam also owns **formatting** — `_format_click_log` / `_format_narration`
   decide what the prompt gets to read. That's the "send selectively" half of
   the governing rule below, and it lives here rather than in `ai/` so the
   backend's schemas (which know about `context`, `option_label`, outcomes) can
   be read directly.

   Worth keeping even though we own `ai/` too: it is what makes the entire test
   suite runnable with no API key, and what made swapping local Ollama for
   hosted Groq a change to two files and nothing else.

4. **The AI emits the contract — never an export format.** `ai/chain.py`'s
   output schema mirrors `TestCase` field for field. `adapters.py` is a
   *validator*, not a translator — it validates shape, not truth, and is
   deliberately tolerant (key aliases, string-or-list, keyword stripping,
   coerced test-data map) because models drift from their declared schema. A 502
   on an otherwise-good generation costs more than being lenient.

   **Do not reintroduce an intermediate export-shaped schema.** The chain was
   once constrained to Gherkin (`given`/`when[]`/`then[]`) and it went wrong
   twice over: the keyword was added by the prompt, stripped by the adapter, and
   re-added by the exporter; and Gherkin prose has nowhere to put a captured
   input value, so `test_data` and `steps[].data` were structurally impossible
   to fill. Gherkin is one of three renderings. It is not the shape.

   ⚠️ `ai/` declares its own copy of the shape so it stays importable without
   the backend package. The test that caught drift between the two
   (`tests/test_adapter.py::test_ai_schema_matches_the_contract`, referenced in
   `ai/chain.py`'s docstring) **is not present in this tree** — so drift is
   currently silent. Change one copy, change the other by hand.

5. **Never commit secrets.** Everything through env vars. Real `.env` is
   git-ignored; `.env.example` documents every variable and must stay in sync
   with `app/config.py`.

6. **Capture generously, send selectively — two decisions, two places.**
   Capture (extension) is greedy and the only irreversible step: you can
   regenerate a test case a hundred times, but you can never re-record a
   session that missed the product name. Storage is effectively free. The
   prompt is the real budget, and what goes in it is decided at format time,
   changeable for free. Consequence: **every captured field has a hard
   character cap decided before it is written, and no field is ever a raw dump
   of a DOM node.** The v1 `outerHTML` disaster happened because one field had
   no cap.

7. **Nothing the tester or model produced is ever overwritten.** Generation
   inserts; editing inserts a new version with `parent_id` set. The audit trail
   is the point, and the diff between a row and its parent is the reliability
   metric. There is no PATCH on a test case, deliberately.

8. **The critic is deterministic and advisory; the judge is advisory too.**
   `app/services/critic.py` is plain Python — no model call — and validates
   the *contract*, never Gherkin syntax. Its findings carry `source:
   "critic"`.

   v3 adds a **judge** pass (`ai/pipeline.py:judge`) that reads the *rendered*
   Gherkin and flags genre problems code cannot see: is this a test or a
   transcript, would this `Then` fail on a broken app, does the title name a
   behaviour. Its findings carry `source: "judge"` and are clamped to
   `warning` — a model's opinion never outranks a deterministic error.

   This does **not** reopen the loop Rule 4 exists to prevent. That loop
   formed because the *prompt* asked for Gherkin, the adapter stripped the
   keywords and the exporter re-added them. The judge's findings go to the
   **tester**, never back into the Author prompt, so nothing it says can push
   the model toward emitting Gherkin. The judge never rewrites; it only
   flags, with a proposed replacement the human accepts or ignores.

   Nothing from either blocks generation, storage, or export.

## Stack

Python 3.11+, FastAPI, SQLAlchemy + Alembic, PostgreSQL, Pydantic v2,
LangChain + Groq (hosted LLM and Whisper), openpyxl, Jira REST API v3,
Docker Compose. The extension is plain JS with no build step.

## The contract

Source of truth: `backend/app/schemas/`. Mirrored in the OpenAPI docs at
`/docs`, and depended on by the extension, the database models, and every
exporter. Changing a field is allowed — but it is a deliberate, all-at-once
change across producer, storage, and consumers, never a drive-by rename.

- **Event**: `type` (click|input|navigation|submit|**page**|**outcome**),
  `timestamp` (ISO-8601 UTC), `sequence` (0-based), `url`, `target`
  (`description` required + optional `tag`/`selector`/`attributes`/`context`/
  `heading`/`option_label`), `value` (input text, else null).
- **POST /sessions** body: `app_name?`, `start_url`, `objective?`,
  `written_narration?`, `events[]`. Response: `{ session_id, status }`.
- **TestCase**: `feature?`, `title`, `preconditions[]`, `steps[]` (`action`,
  `data?`, `fields?`, `rows?`, `expected?`), `test_data` (map),
  `expected_result`, `tags?`.

  `feature` is the capability under test; `title` is the one behaviour this
  scenario verifies. They were the same string, which rendered `Feature: X /
  Scenario: X` — the clearest sign nobody wrote the file by hand.

  A step carries values in exactly one of three ways: `data` (one loose
  value), `fields` (a form filled in one go → a vertical Gherkin table), or
  `rows` (one interaction repeated over items → a table with a header row).
  Both table forms are needed and are not interchangeable: a login form is
  vertical, "two products with quantities" is horizontal.

  `steps[].expected` is an assertion that holds *at that point*. Without it,
  mid-flow observations piled into `expected_result` out of order, which
  produced an assertion that was outright false as an end state.

  ⚠️ **`test_data` is derived, not authored.** The model is not asked for it;
  `schemas/test_case.derive_test_data(steps)` builds it, and both the generate
  and the versions route call that. Values belong to the step that used them —
  a separately-maintained summary drifted from the steps and silently
  overwrote a field used twice (a run that chose two sort values reported
  one). `ai/chain.NOT_AUTHORED` names the exemption and the drift tripwire
  knows about it.

Two event types are **observations, not actions** — the page speaking, not the
tester. `page` carries `title`/`h1` in `attributes`; `outcome` carries
`messages`/`dialog`. They flow through the same pipeline (Rule 1: a tolerant
`type` string means no migration and no rejected sessions), but anything that
treats an event as something the user *did* must filter them out — see
`_VERBS` in `ai_client.py` and `ACTION_TYPES` in `critic.py`. They consume no
Action number in the click log.

Transcripts have three `source` values: `objective` (the tester's one-sentence
goal), `typed`, `audio`. Audio may also carry `audio_started_at` + `segments`,
which is what makes time-aligned narration possible.

Two conventions the whole pipeline depends on:

- **Clauses are stored without Gherkin keywords and without capitals**
  (`the user clicks sign in`), because each exporter adds its own framing.
  Gherkin prefixes `When `; Excel capitalises for a spreadsheet cell
  (`exporters/excel.py`).
- **Steps carry a subject.** `the user clicks…`, not `click…`, so that
  prefixing a keyword yields English rather than "When click the button".

Two properties worth knowing before you extend it:

- **`Event.type` is a plain string, not an enum.** An unrecognized future type
  must never cause `POST /sessions` to reject an entire recording (Rule 1).
  Strict handling belongs downstream, in generation/export, where failing on one
  odd event is far cheaper than losing a session.
- **`Event.target` is JSONB.** Adding fields *inside* `target` needs **no
  Alembic migration** — relevant to most of the planned capture work.

## Database (4 tables)

`sessions` → `events` (FK cascade), `transcripts` (FK cascade), `test_cases`
(FK to session, **no** cascade — a generated test case outlives its session).
See `app/db/models.py` for the implementation.

Generation inserts a new `test_cases` row every time rather than overwriting,
and so does a tester's edit (with `parent_id` pointing at what it was edited
from). That history is deliberate: it is what lets you compare output across
prompt changes, and what makes edit distance a reliability metric. Both list
endpoints are newest-first, so element 0 is the current one.

v2 columns: `test_cases.parent_id`, `test_cases.findings` (the critic's
advisory report — kept out of `content`, which is the frozen contract),
`transcripts.audio_started_at` + `transcripts.segments` (the common clock for
narration alignment). All nullable; older rows stay valid.

`transcripts` has `order_by="Transcript.created_at"` on the relationship —
generation joins the texts, so without it the objective/typed/audio order would
be whatever Postgres happened to return.

## API endpoints (stable paths/methods)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check (no DB touch — process-up check only) |
| POST | `/sessions` | Create session + store events + optional objective/typed narration |
| GET | `/sessions` | List sessions newest-first (summary + counts; `limit`/`offset`) |
| GET | `/sessions/{id}` | Session with events + transcripts |
| DELETE | `/sessions/{id}` | Delete a recording + its events/transcripts. **409** if generated test cases still point at it — they outlive the session by design |
| POST | `/sessions/{id}/narration` | Add typed narration to a stored session, then regenerate |
| POST | `/sessions/{id}/audio` | Multipart `audio` (+ `started_at`) → transcribe → store transcript |
| POST | `/sessions/{id}/generate` | Analyst → Author×N → Judge → critic → persist. Returns a **list**; 422 if nothing testable |
| POST | `/sessions/{id}/preview` | Every current scenario rendered as one `.feature` (body `{style?}`) |
| POST | `/sessions/{id}/export` | The whole recording as one `.feature`. Gherkin only |
| POST | `/test-cases/{id}/preview` | One test case rendered to Gherkin, for on-screen review |
| GET | `/test-cases` | List test cases newest-first (`session_id` filter, `limit`/`offset`) |
| GET | `/test-cases/{id}` | One test case (structured JSON + `findings`) |
| POST | `/test-cases/{id}/versions` | Store a tester's edit as a new version (`parent_id` → this row) |
| POST | `/test-cases/{id}/export` | Body `{ target: excel\|jira\|gherkin }` |
| GET | `/app/` | The dashboard (StaticFiles mount, same origin as the API) |

⚠️ CORS `allow_methods` in `main.py` is `["GET", "POST", "DELETE", "OPTIONS"]`.
Adding a route whose method is missing from that list leaves it **silently
blocked in the browser** while working fine from curl — add the method in the
same change that adds the route. (`DELETE` was added for `DELETE /sessions/{id}`.)
Editing is still `POST .../versions` rather than PATCH, which is the
semantically correct choice anyway (Rule 7).

Note both preview endpoints are `POST` despite being read-only: they take a
`style` body, and POST is already allowed.

## Working on the AI pipeline

**It is three passes, not one call** (`ai/pipeline.py`):

```
analyze(click_log, narration)          -> Plan      1 call, the whole log
author(slice_log, narration, scenario) -> TestCase  1 call per scenario
judge(rendered_feature)                -> findings  1 call, all scenarios
```

The split exists because one call had to both *transcribe* the recording and
*decide what the test was*, and transcription always won — the evidence for it
is right there and the judgement is hard. A 26-action recording became a
14-step `When` block ending in "the user is able to create a hamper".

The Analyst returns **action numbers**, which is what makes selection
inspectable rather than emergent: the Author is handed only its slice
(`_format_click_log(..., only_actions=...)`) and so *cannot* write steps for
anything else, the critic verifies coverage, and the dashboard shows the
tester what was dropped and why. Cost is ~2.5x one call, not Nx — the log is
split across the Author calls, not repeated.

Plain functions and one `if`. **No graph framework**: three nodes with no
cycles is a sequence. Revisit at 5+ stages with real cycles.

- **Literal braces in `ai/prompts.py` must be doubled** (`{{` / `}}`). Those
  strings go through LangChain's `ChatPromptTemplate`, which treats `{name}` as a
  variable to substitute. A single brace in a JSON example raises a KeyError at
  *invoke* time, naming a variable after the JSON key — and there are now three
  prompts full of JSON examples. No fake-seam test catches it, so
  `tests/test_pipeline_prompts.py` asserts each template's declared variables
  match exactly what `pipeline.py` passes. Run it after any prompt edit.
- **`ai_client._format_click_log` and the prompt are one unit.** Every line
  shape it emits is described in `ai/prompts.py`. Change the format, change the
  prompt with it. The shapes today:

  ```
  APPLICATION: <name> / RECORDING STARTS AT: <url>     header
  — Page: <title> (main heading: "<h1>")               page marker, unnumbered
  - Action N (+Ns): <type> on '<desc>' (Tag, ID) (within: "<context>") [value: …]
  - Action N: the page navigates to <url>
    → Observed: <what the app did back>                unnumbered
    [tester says, +M:SS]: "<spoken phrase>"            unnumbered
  ```

- **Never send everything you captured.** Container context goes in only when a
  description is ambiguous (a `Counter` over the event list decides), page
  identity only when it changed. Capture-richness and token cost are separate
  numbers on purpose (Rule 6).
- `ai/` reads its config from `os.getenv` directly, not from the backend's
  `Settings`, so it stays importable without the backend package.
- **A 429 is a wait, not a failure.** `ai/chain.py` retries twice, honoring
  `retry-after`. The free tier also has a *daily* token limit — when that one
  trips, retrying can't help and the eval run will fail honestly.

- ⚠️ **Do not verify changes by regenerating.** The daily cap does not refill
  until tomorrow, and it burns fastest exactly while you are iterating. Almost
  nothing here needs a live call: the critic, the judge post-processing, the
  plan slicing, the exporters and the finding routing are all deterministic,
  and `tests/test_pipeline_offline.py` replays **recorded real responses**
  through the entire pipeline for free. Change code → run pytest. A live call
  is warranted only to judge *prompt quality* — whether the Analyst selects
  sensibly and the Author writes good English — and one run answers that, not
  ten. If a prompt change alters the response shape, re-record: one real
  generation, paste the plan and authored dicts into that file.

## Working on the extension

- **The extension captures; the dashboard does everything else.** The popup has
  no generate button, no test-case card, no export. One renderer per contract:
  a `TestCase` field change should mean one UI to update, not two.
- **The MV3 service worker is killed after ~30s idle.** Nothing important lives
  in memory — `chrome.storage.local` is the only state that survives, keyed by
  `AITC.STORAGE.*` in `config.js`.
- **All API calls belong in `background.js`**, not the popup. The popup is
  destroyed the moment it loses focus, and saving a session (plus its audio
  upload) must survive that.
- **Outcome watching is tied to `report()`.** Each action closes the previous
  action's watch window before emitting (so ordering stays correct — the
  service worker assigns `sequence` in arrival order) and opens a new one after.
  Watch only the named signal list; watching "DOM changes" drowns in
  animations, chat widgets and polling. A cookie banner matches nothing on that
  list, which is the point — no filtering logic needed.
- **Context capture is off-switchable per origin**
  (`STORAGE.contextDisabledOrigins`); basic event capture never is. If you add
  a new field that reads *surrounding page content*, gate it on
  `contextCaptureEnabled`. Fields describing the element's own state (like
  `option_label`) are not gated.
- **Only the service worker assigns `sequence` and owns the buffer.** Appends
  are serialised through one promise chain (`appendQueue`); when both sides
  wrote to storage, fast typing raced itself and lost events. The content script
  observes and reports — it decides nothing about ordering or persistence.
- **`config.js` assigns onto `globalThis` behind a guard**, and `content.js`
  guards on `__aitcContentScriptLoaded`, because both are injected again on
  every navigation. A top-level `const` throws on the second injection and takes
  the whole content script down; a missing content guard double-reports every
  interaction.
- **Passwords are redacted in the page** (`AITC.REDACTED`), before anything is
  sent. The real characters reach neither the database nor the model. This is a
  decided policy — don't relax it.
- **Build DOM with `textContent`, never `innerHTML`.** Every string rendered in
  the popup comes from a web page or an LLM.
- Navigation is captured in `background.js` via `chrome.webNavigation`, not the
  content script — a full page load destroys the script that would have observed
  it, and `onHistoryStateUpdated` is what catches SPA route changes.

## Working agreements

- Changing a schema field or an endpoint path is allowed, but update every side
  in the same change: Pydantic schema, SQLAlchemy model + migration, exporters,
  extension, tests.
- **Explain the "why"** briefly for non-obvious design choices, especially QA
  conventions (what a precondition is, how Gherkin maps, typical QA Excel
  layout). Backend/LLM background here, new to QA.
- **Write tests as you go**, not at the end.
- **Verify the real path by running it.** The fake seams cannot catch prompt
  bugs, and prompt bugs are the common kind. A generation that passes every
  test can still fail on the first real call — see the doubled-brace hazard
  above.
- Keep the app runnable — every step should leave it in a working state.
- Boring, readable code over cleverness.

## Testing

`backend/tests/` is git-ignored but **present in this tree**: the schema-drift
tripwire (`test_adapter.py`), the critic (`test_critic.py`), the prompt-input
formatting (`test_ai_client_formatting.py`), the prompt templates and log
slicing (`test_pipeline_prompts.py`), and the whole pipeline replayed from
recorded model responses (`test_pipeline_offline.py`). **All of them run with
no database and no API key** — 65 tests, under a second. `Extension/tests/`
and `Extension/package.json` are still absent. **Check that a test file exists
before assuming it does** — some docstrings still cite tests that aren't here.

Two of these earn their keep specifically because the failures they catch are
otherwise invisible until a paid call: `test_pipeline_prompts.py` asserts each
template's declared variables match what `pipeline.py` passes (the doubled-brace
hazard, which raises only at *invoke* time), and `test_pipeline_offline.py`
exercises slicing, authoring, validation, rendering, the critic and the judge
filter without a model.

```bash
# Backend — the current suite is pure-unit; no Postgres needed for these three
cd backend && PYTHONPATH=.. pytest

# With a database, for tests that need one:
DATABASE_URL="postgresql+psycopg2://aitc:aitc_dev_password@localhost:5432/aitc" \
  PYTHONPATH=.. pytest

# Extension — jsdom, no build step (suite not in this tree)
cd Extension && npm install && npm test
```

**Tests don't measure quality — `eval/` does.** A prompt or capture change that
keeps every test green can still make output worse; the fixtures are how you'd
know:

```bash
AI_CLIENT=real python eval/run.py    # real numbers (needs GROQ_API_KEY)
python eval/run.py                   # fake seam: harness plumbing only
```

Fixtures come in deliberate pairs (`cart-ambiguity`/`cart-context`,
`no-narration`/`login-outcome`) so a capture change shows up as a before/after
on the same flow. Keep the "before" fixtures at their old capture fidelity —
they're regression cases, not stale data.

Nothing runs them automatically (no CI), so run them yourself before calling
work done. `pyproject.toml` disables class-based collection
(`python_classes = "DoNotCollectAnyClasses"`) so the `TestCase`/`TestCaseStep`
schemas aren't collected as test classes — keep that if you add tests.

⚠️ **The pytest suite truncates the same database the dev app uses.** Running
it wipes whatever you were looking at through `/docs` or the extension.

## Running it

```bash
cp .env.example .env
docker compose up --build                           # db + backend
docker compose exec backend alembic upgrade head    # apply migrations
curl localhost:8000/health
open http://localhost:8000/app/                     # the dashboard
```

The migration is not optional on a fresh database: `/health` deliberately
doesn't touch the DB, so it answers `ok` before the tables exist and the first
`POST /sessions` is what fails instead.

The dashboard is served by the same app, so it needs no separate command and
no CORS entry — it exists as soon as the backend is up.

The AI provider is hosted, so there is no model host in this compose stack —
the real path needs only `GROQ_API_KEY` in `.env` plus
`AI_CLIENT=real` / `TRANSCRIBER=real`.

The extension's `chrome-extension://<id>` origin must be added to
`ALLOWED_ORIGINS`; an unpacked extension's id is generated at load time, so it
can't be pre-configured, and `"*"` is invalid because credentials are enabled.

⚠️ **`docker compose restart` does not reload `.env`.** It restarts the same
container with its original environment. After editing `.env`, use
`docker compose up -d backend` to recreate it. (The README used to say
`restart` in the extension setup section; that was corrected during v2.)

## Open by choice, not unfinished

- **No authentication** on any endpoint, including the dashboard. Right for a
  local tool, blocking for a shared deployment — and the dashboard makes it
  more tempting to share, so this is the first thing to fix if anyone suggests
  hosting it.
- **Captured page context is unmasked** and goes to a third-party API on the
  real path. Deliberate (masking would delete the value context was added to
  provide — `"Nike Air Max 90 · €120"` and a customer's IBAN are structurally
  the same kind of string), mitigated by the per-site switch and password
  redaction. Revisit the moment this points at real customer data.
- **No CI.** Moot while the test suites stay git-ignored.
- **The evaluation set is a stand-in.** All ten fixtures are hand-built on
  public demo apps because no real tester sessions existed yet, so the v2
  improvements are well-evidenced but not proven on real recordings.
  Supervisors are expected to supply those; `eval/import_session.py` turns one
  into a fixture skeleton. Replace or outnumber the synthetic ones as real
  sessions arrive — but keep the deliberate before/after pairs
  (`cart-ambiguity`/`cart-context`, `no-narration`/`login-outcome`) at their
  original capture fidelity; they are regression cases, not stale data.

## Working notes

`changes/` (git-ignored) is where notes per working session go — what changed
and, more usefully, why, including the dead ends. Two files:

- `2026-08-06-improvement-plan.md` — the v2 *plan*, written before any of it
  existed. Still the best statement of the reasoning; its §7 ("where this plan
  could be wrong") called several things correctly.
- `2026-08-06-v2-implementation.md` — what was actually built, what the plan
  got wrong, and what was measured. Read this one first.

Earlier logs from v1 are not in this tree, so a docstring citing one is a dead
pointer, not a file you failed to find.

`README.md` is the documentation of record for anyone cloning the repo and
deliberately carries none of this.
