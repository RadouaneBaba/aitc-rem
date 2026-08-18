# AITC-REM — Specification

**Recorded browser session → structured, formal test case.**

Version 1.0 · 2026-08-17 · Status: design complete, not yet implemented
Supersedes `SPEC-OLD.md` (earlier draft, retained for reference only).

---

## 1. What this is

A QA tester records themselves using a web application. The tool turns that recording into **formal test artifacts** — Gherkin `.feature` files, Excel test case sheets, or Jira issues — using an agentic pipeline in which **every claim the system makes is licensed by evidence it went and retrieved.**

### 1.1 The core problem

A raw browser recording is a stream of low-level events:

```
click on <button class="css-1x7f2k">   @ 14:03:22
input on <input id="mui-4471">          @ 14:03:24
click on <div role="option">            @ 14:03:26
```

A useful test case is eight sentences a human wrote on purpose:

```gherkin
When the tester submits the order form
Then the confirmation banner appears
```

Everything in this document exists to close that gap **without inventing anything.**

### 1.2 The failure mode that kills tools like this

Silently producing a plausible-sounding wrong test case. A tester who finds three fabricated assertions stops trusting the tool and never comes back.

The root cause is specific and worth naming precisely, because the whole architecture is a response to it:

> **When a language model is handed a fixed payload and asked to produce a test case in one shot, and the payload does not contain the evidence for step 7's expected result, the model has exactly two options: invent, or refuse. It cannot ask.**

Models overwhelmingly invent. Pre-loading more context raises the ceiling but never removes it — you cannot pre-push everything a model might need, and a one-shot model has no channel to signal what is missing.

**This system removes the option to invent.** The recording is exposed as a queryable evidence store, the agent retrieves what it needs, and — see §3 — an assertion is only valid if it can point at the retrieval that produced it. Ungrounded output is rejected mechanically before a human ever sees it.

---

## 2. Positioning

### 2.1 The landscape

| Category | Examples | What they do | Gap |
|---|---|---|---|
| Action recorders | Chrome DevTools Recorder, Playwright codegen | Record → replayable script | Produce **code**, not test documentation. No intent, no expected results |
| Low-code automation | Testim, Mabl, Reflect, Katalon | Record → maintained automated test | Heavy platforms; assume a team committing to automation |
| Managed QA services | QA Wolf, Rainforest | Outsource the testing | Not a tool the in-house tester uses |
| AI test-case writers | testcompanion.ai and similar | Recording → written test case | Nearest neighbours. Closed; unknown grounding discipline |

### 2.2 The wedge

Most of that market serves **automation** teams. The larger population — manual QA testers who write test cases in Excel, Jira, or Gherkin and execute them by hand — is served badly or not at all. They spend hours transcribing what they just did into a document nobody enjoys writing.

Three things differentiate this tool, in order of durability:

1. **Verifiable grounding.** Every assertion carries a pointer to the tool call that retrieved its evidence, and a deterministic validator resolves that pointer. Competitors ask you to trust the output; this one lets you audit it, per sentence.
2. **A step library that keeps the suite coherent.** Ten testers recording the same login produce one phrasing, not ten. This is the difference between a test suite and a pile of generated text — and it is what makes output feel permanent rather than disposable.
3. **It reasons about what wasn't tested.** A tool that only transcribes is a stenographer. Coverage suggestions (§9.8) require reasoning about the unobserved, which no non-agentic system can do.

### 2.3 Honest value claim

The speed argument is weaker than it first appears. A tester writing a test case from memory is not slow; realistic saving is roughly **2×**, not 10×.

**The stronger claim is consistency and completeness.** Hand-written test cases omit the steps the author considered obvious, use different words each time, and quietly drop expected results the author didn't consciously notice. The recording did not. Consistent phrasing, complete steps, and evidence-backed expected results are the value proposition — speed is a side effect.

---

## 3. What "agentic" means here, and how it is proven

This section is the centre of the document. Every other section is downstream of it.

### 3.1 The claim is testable or it is marketing

"Agentic" is a claim that gets asserted far more often than it gets demonstrated. A prompt chain with structured output is a *transformation*, not an agent, regardless of the framework it is written in. This system commits to an operational definition and produces the evidence for each clause.

| Property | This system | Artifact that proves it |
|---|---|---|
| **Decides its own actions** | The agent chooses which evidence to retrieve, per step | Tool-call trace varies across recordings; no fixed call sequence exists |
| **Observes results** | Output content derives from tool responses | Every assertion carries a `toolCallId`; a validator resolves it (§3.2) |
| **Adapts to what it finds** | Investigation effort scales with difficulty | Effort/difficulty correlation (§3.4) |
| **Terminates by judgment** | The agent decides when it has enough | Recorded `stopReason` per step, not a fixed loop count |

### 3.2 Evidence binding — the mechanism that welds agency to correctness

**This is the single most important technical decision in the document.**

It is not enough that a quoted string exists *somewhere* in the recording. A claim is valid only if the string appeared **in a tool response this agent actually received during this run.**

Every tool call is logged with a content-addressed response:

```ts
interface ToolCall {
  id: string;                  // "tc_0447"
  stage: string;               // which pipeline stage issued it
  stepId?: string;
  tool: string;                // "get_snapshot"
  args: Record<string, unknown>;
  responsePath: string;        // runs/<rec>/tools/tc_0447.json
  responseHash: string;        // sha256 of the serialized response
  timestamp: number;
}
```

Every assertion must name one:

```ts
evidence: {
  literal: "Order confirmed",   // exact string
  toolCallId: "tc_0447",        // the retrieval that produced it
  eventId: "evt_027",
  kind: "a11y_node"
}
```

The `evidence_retrieved` validator (§9.7) resolves `tc_0447` in the trace, loads the stored response, verifies the hash, and confirms `literal` occurs in it. If the call does not exist, or the literal is absent, **the assertion is rejected.**

Three consequences, each independently worth the cost:

- **Tool calling stops being an implementation style and becomes the mechanism by which claims are licensed.** Disable tools and the pipeline cannot emit a single valid assertion — not "degrades", *cannot*.
- **It defuses paraphrase thrash.** Prose is free (`the confirmation banner appears`); the checkable literal is a retrieved artifact (`Order confirmed`). The model is never forced to write stiff sentences to satisfy a string match.
- **It is the proof.** "Is it really agentic?" is answered by a script that walks every assertion in every output and resolves its pointer. Not a diagram — a pass/fail number.

A single-prompt architecture cannot do this at any price: there is no retrieval event to point at.

### 3.3 The investigation budget

Agency includes deciding *how much* work a decision deserves.

```ts
interface StepInvestigation {
  stepId: string;
  initialUncertainty: string[];   // what the agent could not determine up front
  toolCallIds: string[];
  budgetUsed: number;
  budgetMax: number;              // default 8, configurable per stage
  stopReason:
    | 'no_investigation_needed'   // evidence was already sufficient
    | 'evidence_sufficient'       // resolved after N calls
    | 'budget_exhausted'          // gave up; emits low confidence + reason
    | 'escalated';                // formulated a specific question for the human
}
```

A step like `click Save → POST /api/orders 201 → alert "Saved"` should cost **zero** tool calls. An ambiguous click with no visible outcome should cost eight. That variance is not inefficiency — it is the observable signature of adaptive behaviour.

`escalated` is a first-class outcome, not a failure. An agent that says *"I cannot tell whether the export succeeded — did a file download?"* is more useful than one that guesses, and the review UI renders it as a direct question next to the step.

### 3.4 The effort/difficulty correlation

Log tool calls per step alongside whether a human edited that step in review. Then plot them.

**If investigation effort correlates with human edit rate, the agent is spending effort where the work is genuinely hard.** A chain has flat cost per step by construction, so the scatter plot alone separates the two architectures — using production data, with no hand-written golden set required.

This costs one extra column in the trace and one chart. It is the cheapest strong evidence in the project.

### 3.5 The ablation — the thesis deliverable

Three pipeline configurations, one flag, the same recordings:

| Config | Description |
|---|---|
| `A0` | Single prompt, all context pre-loaded, no tools — the shape this project replaces |
| `A1` | Tools available, no critic, no repair loop |
| `A2` | Full pipeline |

| Metric | Source | Needs human labels? |
|---|---|---|
| Assertion grounding rate | validators | No |
| Ungrounded / fabricated assertions | validators | No |
| Validator pass rate (first attempt) | validators | No |
| Tool calls per step | trace | No |
| Repair-loop convergence rate | trace | No |
| Steps edited by a human in review | review UI | Collected passively |
| Step-boundary accuracy | golden set | Yes — later |

**Six of seven metrics are already computed by machinery built for other reasons.** The ablation is a config flag and a script, not an eval harness — which is why it lands in Phase 1 (§17) rather than at the end.

This table is the defence. It converts "we believe agentic is better" into a measured claim about *this* system. And if `A1 ≈ A2`, that is a genuine finding worth knowing in month two rather than month five.

### 3.6 Why a fixed skeleton does not weaken the claim

Segmentation and validation are deterministic code. The agentic work happens between them. This is a stronger design than one free-roaming agent, for reasons that are about quality rather than caution:

- **Context volume.** A six-minute session with full snapshots far exceeds any context window. A single agent burns context on retrieval and loses the thread by step 40. Scoped stages retrieve only what the current decision needs.
- **Consistency.** Step-library reuse requires disciplined search-before-invent. A free agent improvises, and step explosion returns.
- **Reproducibility.** QA artifacts are audit material. The same recording producing materially different step *counts* twice is a real problem for users.
- **Debuggability.** One giant trace tells you nothing about which decision broke.

And decisively: **the evidence binding of §3.2 makes agency verifiable per assertion.** A free-roaming agent cannot offer that, because there is no stage boundary at which to check. The skeleton is what makes the proof possible.

---

## 4. Scope and phases

Sequenced so each phase ends with something demoable. Nothing below is cut; the phases order it.

### Phase 1 — The provable spine

| Capability | § |
|---|---|
| Chrome extension recorder (content script) | §6 |
| In-browser PII/secret redaction | §7 |
| Recording exposed as a queryable evidence store | §8 |
| Deterministic segmentation | §9.2 |
| Agentic naming with tool access | §9.4 |
| Evidence binding + deterministic validators | §9.7 |
| Agent trace as a schema'd artifact | §9.10 |
| **Ablation harness** | §3.5 |
| Gherkin renderer | §11.1 |

**Demo:** a real test case from a real recording, plus the ablation table proving tools change the outcome.

### Phase 2 — The usable product

| Capability | § |
|---|---|
| Scenario decomposition — one recording → N test cases | §9.3 |
| Noise pruning and setup/test classification | §9.3 |
| Assertion proposal with provenance | §9.5 |
| Review UI, including the evidence/trace panel | §13 |
| Step library with semantic reuse | §12 |
| Excel + Jira renderers | §11 |
| Effort/difficulty correlation from review data | §3.4 |

**Demo:** a tester records fifteen minutes, gets three coherent test cases, reviews and exports without touching a terminal.

### Phase 3 — Smart

| Capability | § |
|---|---|
| LLM critic + bounded repair loop | §9.9 |
| Coverage suggestions — what wasn't tested | §9.8 |
| Bug report mode | §14 |
| Multi-tab / popup capture | §6.6 |
| Full eval harness with golden set | §16.1 |

### Explicitly deferred beyond Phase 3

| Deferred | Why | What the tool does instead |
|---|---|---|
| Canvas / drag-and-drop semantics | Needs a vision pipeline; low frequency in business-app QA | Fidelity warning on the step |
| Byte-level file capture | Not needed to describe a flow | Record name/size/MIME; emit `<<fixture: name.csv>>` |
| Smart cross-tab timeline stitching | Expensive; linear ordering is usable | "A new window opened", inline |
| Xray / Zephyr integration | Two more third-party APIs | Plain Jira issue behind the same `Exporter` interface |
| Duplicate / overlap detection | Feature, not foundation | Build the semantic index anyway (§12) so it becomes a query |
| Test-case maintenance / re-record diffing | Large surface; needs a stable product first | Noted as the highest-value follow-on (§16.2) |
| Multi-tenancy, auth, billing | Local-only tool | Seams only (§15) |
| Live-app verification pass | Requires credentials + test data | Optional add-on; the pipeline never depends on it |

---

## 5. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ CHROME EXTENSION (recorder)                                     │
│   content scripts · all_frames · shadow-root traversal          │
│   ├─ per-action capture bundle (semantic snapshots)             │
│   ├─ IN-BROWSER REDACTION   ← secrets never persist             │
│   ├─ optional narration + stated objective                      │
│   └─ tester annotations (checkpoints, assertions, notes)        │
└───────────────────────────┬─────────────────────────────────────┘
                            │  recording.json  (the contract)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ EVIDENCE STORE  — the recording, indexed and queryable          │
│   exposed to agents as tools (§8). Every response is logged,    │
│   hashed and addressable: tc_0447 → runs/…/tools/tc_0447.json   │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ PIPELINE (local background job, minutes allowed)                │
│                                                                 │
│  [code]  segment    ──► deterministic step boundaries           │
│  [agent] decompose  ──► N test cases · setup vs test · noise    │
│  [agent] name       ──► one sentence per step                   │
│  [agent] assert     ──► ranked expectations, each evidence-bound│
│  [agent] library    ──► reuse approved phrasing                 │
│  [code]  VALIDATE   ──► grounding gate. hard fail.              │
│  [agent] CRITIC     ──► quality judgment          (Phase 3)     │
│           └── findings feed back, bounded retries ──┐           │
│                                                     │           │
│  Agentic stages retrieve evidence via §8 tools.                 │
│  Every retrieval is logged; every claim points at one.          │
└───────────────────────────┬─────────────────────────────────────┘
                            │  TestCaseIR[] + AgentTrace
                            ▼
┌──────────────┬───────────────────────┬──────────────────────────┐
│ REVIEW UI    │  RENDERERS            │  STEP LIBRARY            │
│ human gate   │  Gherkin / XLSX /Jira │  grows on approval       │
│ + WHY panel  │                       │                          │
└──────────────┴───────────────────────┴──────────────────────────┘
```

**Four principles govern the whole system:**

1. **The recording is ground truth.** Nothing enters the output that isn't traceable to it.
2. **Claims require retrieval.** A statement the agent did not go and verify is not admissible (§3.2).
3. **Deterministic where possible, agentic where necessary.** Boundaries, redaction and validation are code. Interpretation, judgment and ambiguity resolution are agentic.
4. **Fail loudly.** Every uncertainty surfaces as a visible warning or an explicit question, never as a confident guess.

---

## 6. The recorder (Chrome extension)

### 6.1 Capture mechanism — content scripts, not CDP

**Decision: MV3 content scripts injected with `all_frames: true`, plus a service worker for coordination. The Chrome DevTools Protocol is not used.**

The rejected alternative was `chrome.debugger` + CDP (`Accessibility.getFullAXTree`, `DOM.*`, `Network.*`). It is genuinely more powerful. It is also disqualified by its user:

| CDP cost | Impact |
|---|---|
| Undismissable "started debugging this browser" infobar | Present for the entire session, on the tester's own browser |
| Hard conflict with DevTools | **QA testers open DevTools constantly.** Only one client may attach |
| Attaches to the whole browser | Uncomfortable permission surface for a tool run on real work accounts |

The capability argument for CDP does not survive scrutiny either. Content scripts reach **cross-origin iframes** via `all_frames: true` plus host permissions, and **open shadow roots** via `element.shadowRoot`. Closed shadow roots are unreachable either way. What is lost is `Network.*` interception and the browser-computed accessibility tree — both addressable (§6.3, §6.4).

### 6.2 The capture bundle

The extension captures a **bundle per user action**, not a continuous stream. Scroll, hover and mousemove are recorded as context, never as steps.

```ts
interface CapturedEvent {
  id: string;                      // stable; referenced by every downstream stage
  seq: number;
  timestamp: number;               // ms since recorder start
  type: 'click' | 'input' | 'select' | 'keypress' | 'navigate'
      | 'submit' | 'file_select' | 'tab_open' | 'tab_close' | 'dialog';

  target: {
    role: string;                  // computed accessible role, not the tag name
    name: string;                  // computed accessible name — the human label
    value?: string;                // REDACTED before persistence
    selectors: {                   // ranked, most-stable first
      testId?: string;
      role?: string;               // getByRole('button', { name: 'Submit' })
      text?: string;
      css: string;                 // last resort
    };
    frame: FramePath;
  };

  before: SemanticSnapshot;
  after:  SemanticSnapshot;        // captured after settle (§6.5)
  diff:   SnapshotDiff;            // computed at capture time

  network: NetworkCall[];          // requests in the action's time window
  console: ConsoleEntry[];         // errors and warnings only
  screenshot: string;              // path to PNG on disk

  annotations?: TesterAnnotation[];
  fidelity: FidelityFlag[];        // §6.7 — how much to trust this event
}

type FramePath = Array<
  | { kind: 'iframe'; url: string; index: number }
  | { kind: 'shadow'; host: string }
>;
```

### 6.3 Semantic snapshots

The pipeline is fed a **semantic snapshot** — role, accessible name, state — never raw DOM HTML.

| Representation | Size per snapshot | Usable signal |
|---|---|---|
| Raw DOM HTML | 50–200 KB | Buried in framework noise |
| Semantic snapshot | 2–6 KB | Exactly what a human perceives |

Raw DOM doesn't merely cost more — it overflows the context window and produces incoherent output on any model.

```ts
interface SemanticNode {
  role: string;          // button, textbox, heading, alert, status, row, …
  name: string;          // accessible name
  value?: string;        // redacted
  state?: string[];      // disabled, checked, expanded, invalid, selected, …
  landmark?: string;     // nav, main, dialog — for locating the node
  children?: SemanticNode[];
}
```

**Accessible names are computed with `dom-accessibility-api`** (the npm implementation of the W3C accname spec used by Testing Library). This is the practical replacement for CDP's `getFullAXTree`: correct enough for real pages, runs in the content script, no debugger attachment.

Snapshots are **scoped, not whole-page**. Capturing the entire tree twice per action across 120 actions is wasteful and slow on large enterprise apps. Default scope:

1. The target element's nearest landmark or dialog ancestor
2. Plus all `alert`, `status`, `log` and `alertdialog` nodes anywhere in the document (outcomes appear far from the click)
3. Plus the document title and URL

A whole-page snapshot is available on demand through the `get_full_snapshot` tool (§8) — the agent asks for it when the scoped view proves insufficient. **This is itself agentic behaviour: the cheap view by default, the expensive one on demand.**

### 6.4 Network capture without CDP

A `fetch`/`XMLHttpRequest` wrapper injected into page context, forwarding metadata to the content script:

- Method, URL, status, timing, initiator
- Request/response bodies **redacted in page context before they leave it** (§7)
- Headers stripped to a safe allowlist; `Authorization` and `Cookie` never recorded

This misses requests issued before injection and by service workers. Both are flagged (`network_incomplete`) rather than silently omitted.

### 6.5 Outcome capture — the settle window

**The `after` snapshot is not taken immediately.** Naively snapshotting on the next tick captures the state *before* the application has responded, which is the most common way a recorder loses the very evidence the assertion needs.

The `after` snapshot is taken when the earliest of these occurs:

1. No DOM mutation for 300 ms, **and** no in-flight request started by this action
2. A new `alert` / `status` / `alertdialog` node appears (capture immediately, then again at settle)
3. A URL change completes
4. Hard timeout at 5000 ms → flag `settle_timeout`

Additionally, transient outcomes are captured on appearance regardless of settle: toasts frequently vanish within three seconds, and an assertion about a toast that disappeared before the snapshot is an assertion the system will otherwise be unable to ground.

### 6.6 Narration and the stated objective

Both optional; both are the strongest signals in the system when present.

**Stated objective.** Before recording, one free-text line: *"Check that an order over €500 triggers the approval flow."* This is the one input the tool can never observe. It is carried into every stage and is the primary source for the test case title and for deciding what the assertions are actually *about*.

**Narration.** The tester may speak while recording. Audio is transcribed locally, with segment timestamps anchored to the recorder clock, and interleaved with the event stream by time.

Narration is a **direct read on the test oracle** — *"now I'm checking that the total updates"* states the expected result outright, where snapshot-diff inference can only guess at it. It is exposed to agents through the `get_narration(timeWindow)` tool rather than pre-loaded, so the agent retrieves it when a step is ambiguous and pays nothing when it isn't.

*Phase 1 records audio and stores transcripts. Phase 2 wires narration into the assertion stage.*

### 6.7 Tester annotations

| Annotation | How | Effect |
|---|---|---|
| **Checkpoint** | Hotkey or toolbar button | Forces a step boundary; overrides the segmenter |
| **Intent note** | Type one line mid-recording | Becomes the step name verbatim; the model does not rewrite it |
| **Assertion** | Click an element, mark "this is what I'm verifying" | Becomes a `Then` step with `provenance: annotated` |
| **Scenario break** | Hotkey | "A new test case starts here" — overrides decomposition (§9.3) |
| **Bug marker** | Hotkey | Flags the session as a bug report; marks the failing step |

**The tool must be fully usable with zero annotations.** They raise quality; they are never required.

### 6.8 Fidelity flags — degrading loudly

Every event carries flags describing what the recorder could *not* determine. These propagate to the step and are rendered prominently in review.

| Flag | Meaning | UI treatment |
|---|---|---|
| `canvas_interaction` | Click landed on `<canvas>`; only coordinates known | ⚠️ "I can only tell you the tester clicked at (x, y). Please describe what happened." |
| `no_accessible_name` | Element has no label, alt text or aria-label | ⚠️ "This element has no label — my description may be wrong." |
| `closed_shadow_root` | Component uses a closed shadow root | ⚠️ "Contents of this component were not readable." |
| `cross_origin_frame_blocked` | iframe not injectable (missing host permission / sandboxed) | ⚠️ "Contents of this embedded frame were not accessible." |
| `drag_interaction` | Drag/drop detected | ⚠️ Reduced-confidence description |
| `file_content_omitted` | File selected, bytes not captured | ℹ️ "Emitted as `<<fixture: …>>` — attach the real file before running." |
| `rapid_sequence` | Events too fast to attribute to distinct intents | ℹ️ Grouped; review boundaries |
| `settle_timeout` | Page never quiesced within 5 s | ⚠️ "The outcome I captured may be incomplete." |
| `network_incomplete` | Requests may have been missed | ℹ️ Suppresses `mutation_claimed` rejection; downgrades to warning |

**A tool that admits what it doesn't know stays trusted. One that confabulates gets abandoned after the third bad test case.** This table is the cheapest insurance in the project.

---

## 7. Privacy and redaction

Redaction happens **in the browser, before anything is written to disk.** Raw secrets never exist in a persisted artifact.

### 7.1 Rules

| Category | Detection | Replacement |
|---|---|---|
| Passwords | `input[type=password]`, autocomplete hints | `<<password>>` |
| Auth headers / cookies | Header and cookie names | Stripped entirely |
| Email addresses | Pattern | `<<user_email_1>>` (stable within a session) |
| Card numbers | Luhn check | `<<card_number>>` |
| Phone numbers | Pattern | `<<phone_1>>` |
| National IDs | Pattern | `<<national_id>>` |
| Request/response bodies | Recursive key + value scan, in page context | Per-field |
| Project custom rules | CSS selector or regex, per project | `<<custom_name>>` |

### 7.2 Redaction is a feature, not just compliance

Placeholders carry forward into the generated test as **parameters**:

```gherkin
When the tester signs in as "<<user_email>>" with "<<password>>"
```

Which makes `Scenario Outline` generation a natural extension rather than a separate feature. The privacy work pays for itself.

### 7.3 Project rules and the pre-send screen

Each project has a `redaction.yaml`:

```yaml
sensitive:
  - selector: "[data-field='ssn']"
    placeholder: national_id
  - regex: "ACC-\\d{8}"
    placeholder: account_number
allowlist:
  - selector: ".demo-data"      # explicitly NOT sensitive
```

Before the first model call on a project, the UI shows **exactly what will be sent**, with redactions applied and highlighted. One-time gate per project, not per recording.

### 7.4 Screenshots

- Stored locally; shown in the review UI.
- **Not sent to any model.** The pipeline is snapshot-driven.
- If a vision stage is ever added, screenshot redaction becomes a prerequisite, not an afterthought.

### 7.5 Narration audio

Transcribed locally by default. Audio files are stored alongside the recording and are never uploaded. If a hosted transcription service is configured, the pre-send screen (§7.3) covers it explicitly.

---

## 8. The recording as a queryable evidence store

**The contract is not a format. It is queryability.** This is what makes tool calling possible and therefore what makes the system agentic; a recording that can only be dumped into a prompt forces the one-shot architecture this project exists to replace.

On ingest, the recording is indexed: events by id and time, snapshot nodes by role and name, network calls by time window and URL, console entries by severity, narration by time.

### 8.1 The tools

| Tool | Purpose |
|---|---|
| `get_snapshot(eventId, when)` | Scoped semantic snapshot before/after an event |
| `get_full_snapshot(eventId, when)` | Whole-page snapshot — expensive, on demand |
| `query_element(eventId, selector \| role+name)` | One element, its state, and its neighbours |
| `get_diff(eventId)` | Structured before/after difference |
| `get_network(eventId \| timeWindow)` | Calls in a window, with redacted bodies |
| `get_console(eventId \| timeWindow)` | Console output |
| `get_narration(timeWindow)` | Transcript segments overlapping a window |
| `get_events(range)` | Raw events in a range |
| `find_text(query, scope)` | Where a string appears across snapshots — grounding lookup |
| `search_step_library(query)` | Semantic search over approved steps |
| `get_objective()` | The tester's stated objective |
| `get_neighbouring_segments(id, n)` | Surrounding context for ambiguity |

Exposed over MCP so the same tools are reachable from an SDK client, a local agent, or an inspector during development.

### 8.2 Every response is logged

Each call writes `runs/<recordingId>/tools/<toolCallId>.json` and appends a `ToolCall` record (§3.2) to the trace, including a hash of the response.

**This log is not debug output.** It is:

- the substrate the `evidence_retrieved` validator resolves against (§9.7),
- the data behind the review UI's "why does this step say that?" panel (§13.3),
- the raw material for the agency proof (§3).

It is a schema'd, first-class artifact and is designed as one from the start.

---

## 9. The pipeline

### 9.1 Shape

A **fixed deterministic skeleton with agentic stages.** Each stage reads a file and writes a file, so when output is wrong you open the intermediate artifact and see exactly which stage lied. Rationale in §3.6.

### 9.2 Stage 1 — Segmentation *(deterministic, code)*

Cuts the event stream into candidate steps using rules only. No model.

**Boundary triggers**, highest priority first:

1. Tester checkpoint annotation
2. URL / route change
3. Form submit
4. State-mutating network call (`POST`/`PUT`/`PATCH`/`DELETE`) that completes
5. Idle gap > 2000 ms
6. Major region replacement (>60% of named nodes changed)
7. Hard cap: 12 events per segment

Deterministic boundaries mean the same recording always produces the same segment count — which matters for the audit trail and makes merge/split in the review UI predictable.

**Output:** `segments.json` — every event assigned to exactly one segment, none dropped.

### 9.3 Stage 2 — Decomposition *(agentic)*

**This stage is what makes the tool usable on real sessions, and it is the most defensibly agentic task in the system.**

Real QA sessions are not one clean scenario. A tester opens the app and works for fifteen minutes across several flows, gets lost twice, and backtracks. A verbatim transcript of that is a bad test case, and it is the fastest route to output that feels disposable.

The agent reads the segment list with lightweight labels, retrieves evidence where the flow is unclear, and produces two decisions.

**Decision A — how many test cases are in here, and where does each begin?**

Signals: return to a known start state, the stated objective changing focus, a scenario-break annotation, a long idle gap, a logical completion (confirmation reached) followed by a fresh flow.

**Decision B — what role does each segment play?**

```ts
type SegmentRole =
  | 'setup'        // getting to the state under test — becomes Background/precondition
  | 'test_step'    // the thing being tested
  | 'teardown'
  | 'exploratory'  // the tester looking around; pruned from the narrative
  | 'abandoned';   // a false start the tester backed out of; pruned
```

This produces the two things the output most needs and no rule can supply:

- **Preconditions and `Background` blocks.** Setup steps common to several test cases lift into a shared `Background`, which is the difference between a usable feature file and a bloated one.
- **A clean narrative.** Exploratory and abandoned segments are removed from the test case **but kept in the trace**, and the review UI shows an expandable *"3 exploratory actions omitted"* marker so nothing is silently lost.

No deterministic rule can do this: navigating away and back is sometimes a false start and sometimes a legitimate test step. Distinguishing them requires reading the whole flow against the stated objective — exactly the judgment agency exists for.

**Output:** `decomposition.json` — N test-case shells, each with ordered segments, roles, and shared setup identified.

### 9.4 Stage 3 — Naming *(agentic)*

For each segment, produce one sentence describing tester intent.

**Baseline input:** the segment's events, its first and last scoped snapshots, the diff, a network summary, and the top step-library matches.

**Then the agent investigates.** It states what it cannot determine, retrieves evidence via §8 tools until it can, and records why it stopped (§3.3). A step with an obvious outcome costs zero calls; an ambiguous one costs several.

**Rules:**
- Describe *intent*, not mechanics. "Submits the order" beats "clicks the blue button".
- Use the application's own vocabulary, taken from accessible names.
- Never state application state the snapshots do not show.
- If the library has a semantic match, reuse it verbatim (§12).
- If still uncertain, emit `confidence: low` with the reason, or `escalate` with a specific question. Never guess silently.

### 9.5 Stage 4 — Assertion proposal *(agentic)*

A recording captures what the tester *did*, never what they were *checking*. Assertions come from ranked sources, and **the ranking matters more than any other ordering in this document — it is where a system like this fails.**

| Priority | Source | Provenance | Why it ranks here |
|---|---|---|---|
| 1 | Tester annotation | `annotated` | The tester pointed at it and said "this is what I'm verifying". Unambiguous |
| 2 | Narration in the step's time window | `narrated` | The tester *said* the expected result out loud. A direct read on the oracle |
| 3 | Stated objective, matched to this step | `objective` | Tells the agent what the test is *about*, so it selects the assertion that matters |
| 4 | Captured outcome signals | `inferred` | New `alert`/`status` node, error/success vocabulary, meaningful URL change |
| 5 | State-diff inference | `inferred` | Counter change, row count, enabled/disabled flip, successful mutation |
| 6 | Human confirmation in review | `confirmed` | Final gate |

**Sources 1–3 are direct statements of intent; 4–5 are guesses about it.** Systems that lead with inference produce assertions that are true but pointless — "a timestamp appeared" — because nothing tells them which of forty state changes is the one under test. Every layer above inference exists to answer *which change matters*, and each is retrieved on demand rather than pre-loaded.

**Every assertion is evidence-bound (§3.2).** The `literal` must come from a tool response received during this run. An assertion whose evidence cannot be retrieved is not emitted.

**Noise suppression — hard-excluded:**

- Timestamps and relative times ("2 minutes ago")
- UUIDs, session IDs, generated identifiers
- Ad / analytics containers
- Anything matching a redaction placeholder
- Values that differ between two runs of the same recording

Each step gets **2–3 ranked candidates**, never one. The review UI presents them as checkboxes over the step screenshot; the tester accepts or rejects in seconds.

### 9.6 Stage 5 — Step library matching *(agentic)*

See §12. Runs before rendering; rewrites step text to reuse approved phrasing where a semantic match exists.

### 9.7 Stage 6 — Validators *(deterministic, code, no model)*

**The highest-value code in the system.** You have ground truth *and* a retrieval log, so hallucination is mechanically checkable. This is a rare luxury — use it.

| Validator | Check | On failure |
|---|---|---|
| `evidence_retrieved` | Every assertion's `toolCallId` exists in the trace, its response hash verifies, and `literal` occurs in that response | **Reject** — regenerate |
| `assertion_grounding` | `literal` also occurs in the recording at the referenced event | **Reject** |
| `element_exists` | Every referenced element id exists in the recording | **Reject** |
| `mutation_claimed` | A step claiming data was saved has a matching successful mutating request | **Reject** (warn if `network_incomplete`) |
| `event_coverage` | Every event is accounted for — assigned to a step, or explicitly classified `exploratory`/`abandoned`. None silently dropped | **Reject** |
| `gherkin_parses` | Output is valid Gherkin | **Reject** |
| `library_verbatim` | A step marked reused matches its library entry exactly | **Reject** |
| `no_placeholder_leak` | No unredacted-looking secret in the output | **Hard fail — do not render** |
| `selector_resolvable` | Every emitted selector was present in the captured DOM | **Warn** |
| `no_pruned_assertion` | No assertion depends on a segment classified `exploratory`/`abandoned` | **Reject** |

These are unglamorous and they catch the majority of what would otherwise destroy trust. **Write them before the stages they guard.**

Each run emits a validator report; the **grounding rate is logged from day one** as a free regression signal (§16.1).

### 9.8 Stage 7 — Coverage suggestions *(agentic, Phase 3)*

The one output that cannot exist without reasoning about the unobserved.

After a test case is grounded and validated, the agent examines what the recording *revealed* about the application — form fields and their constraints, validation messages seen elsewhere, API error shapes, disabled states, branches visible in the UI — and proposes what a tester might record next:

> - You submitted the form with valid data. The email field has `type=email` and a validation message exists in the DOM — an invalid-email path is untested.
> - `POST /api/orders` documents a 409 conflict. No recording exercises it.
> - The approval banner appears only above €500. The boundary at exactly €500 is untested.

**Strictly quarantined.** Suggestions live in their own IR block, are never rendered as steps, are never exported as test cases, and are labelled *unverified*. They are a prompt for the tester, not an artifact.

This is the "especially if it was smart" the testers asked for, and it is the clearest functional line between this tool and a transcription tool.

### 9.9 Stage 8 — Critic and the repair loop *(agentic, Phase 3)*

The critic judges what code cannot:

- Is this step name meaningful, or is it "User clicks the button"?
- Is this assertion testing something that matters, or incidental noise?
- Does the scenario read as a coherent test to a human?
- Does it match the project's vocabulary and style?
- Are there unexplained state jumps between steps?

**Findings feed back.** They are not merely reported — the offending stage re-runs with the criticism as additional input, and with tool access to resolve what the critic flagged.

```
generate → validate (code) → critique (model) → repair → validate → …
```

Bounded at **3 attempts per stage**. On exhaustion the step is surfaced to the human with the unresolved finding stated plainly — never silently accepted.

Convergence rate (how often repair fixes the finding within budget) is a trace metric and an ablation column (§3.5).

### 9.10 The agent trace

A schema'd artifact, versioned with the run, containing:

- Every `ToolCall` (§3.2) with hashed response
- Every `StepInvestigation` (§3.3) with its uncertainties and stop reason
- Every stage's input/output artifact path
- Every validator result and repair attempt
- Decomposition decisions with their rationale

Consumed by the validators, the review UI, and the ablation. **Designed as a product artifact, not a log file.**

### 9.11 Execution model

- **Background job.** Stop recording → notification → draft ready in 2–5 minutes.
- Minutes are permitted deliberately: this is the *permissive* constraint that unlocks multi-pass analysis, tool calls and repair loops. Testers move on to the next test rather than watching a spinner.
- Progressive/streaming display and a fast-draft-then-refine pass are UX polish, addable without touching the pipeline.
- Every stage's input and output is written to `runs/<recordingId>/<stage>.json`.

### 9.12 Models

All model calls route through **one thin client.** Model selection per stage is configuration, not code.

```yaml
# models.yaml
stages:
  decompose: { provider: <tbd>, model: <tbd> }
  name:      { provider: <tbd>, model: <tbd> }
  assert:    { provider: <tbd>, model: <tbd> }
  library:   { provider: <tbd>, model: <tbd> }
  critic:    { provider: <tbd>, model: <tbd> }
```

- **Provider and model are deliberately undecided.** Any hosted API or local endpoint plugs into the same client. The choice is recorded in §18 once made.
- **Non-negotiable requirement: the chosen model must support reliable multi-turn tool calling.** This is not a preference — §3.2 makes tool calling the mechanism by which claims are licensed. A model that cannot hold a tool loop cannot run this pipeline at all.
- **Quality first, cost later.** Get the pipeline producing test cases worth trusting, measure what it costs, then optimize. Premature cost constraints remove the signal needed to tell a pipeline bug from a weak model.
- Per-stage config means stages need not share a model. `decompose` and `critic` carry the judgment load and should be upgraded first; bulk naming tolerates weaker models.
- The pipeline makes 20–60 model calls per recording. Make retry and rate-limit backoff **visible in the job log** — a pipeline that appears slow is usually a pipeline sleeping in a backoff loop.

#### Budget strategy — free first, paid only where free fails

**This is a development-phase posture, not a permanent one.** The project runs on a personal budget of roughly nothing while the pipeline is being built and proven, so the operating rule is: use free tiers until they stop doing the job, then pay the smallest amount that fixes it. Once the pipeline demonstrably produces test cases worth trusting, the model tier is expected to move up — the constraint here is a starting condition, not a design goal, and §9.12's "quality first, cost later" still governs. In practice the development configuration is a chain rather than a choice — Gemini Flash on the Google AI Studio free tier as the daily driver (its tokens-per-minute ceiling is high enough that a tool loop never throttles), Mistral's free tier as overflow, and a paid ultra-budget endpoint such as DeepSeek V4 Flash (cents per recording) when a run needs to be reproducible or the free tiers fall short. The thin client above absorbs this: a 429 rolls to the next provider in the chain instead of failing the job.

Four things constrain the strategy and must not be traded away for price:

- **The gate is tool-calling reliability, not cost.** §3.2 makes tool calling the mechanism by which claims are licensed. A cheaper model that drops calls mid-loop is not cheaper — it is unusable, and it makes pipeline bugs indistinguishable from model failures.
- **Tokens per minute is the binding limit, not requests per day.** The investigation loop (§3.3) is multi-turn, so each turn resends the accumulated conversation; a single 8-call investigation can send ~95K tokens, and a recording 300–800K. Free tiers advertising generous request counts but small token windows are unusable here regardless of headline limits.
- **Free tiers may train on what is sent.** Free-tier prompts are frequently eligible for provider training. §7 exists so secrets never reach disk; shipping a real client application's snapshots to a training-eligible endpoint would undo that. **Free tiers are for development recordings and demo applications only** — anything recorded against a real application goes to a paid endpoint carrying a no-training term. The pre-send screen (§7.3) states which tier is in use.
- **The ablation (§3.5) is the exception to free-first.** It pins one provider and one model across `A0`/`A1`/`A2` — fallback routing and throttling are fine in daily use and fatal to the comparison, which would otherwise measure provider variance instead of architecture. It also runs on the strongest tool-calling model the budget allows, not the free default: the ablation *is* the proof the pipeline works, so it cannot be the thing that waits for the pipeline to be proven. It is a bounded set of runs over a fixed recording set, so this costs tens of dollars, not an ongoing bill.

Providers, limits and prices here were checked in August 2026 and move constantly; they are a starting configuration, not a commitment. The per-stage config makes being wrong cheap.

---

## 10. The intermediate representation

One canonical structure. Gherkin, Excel and Jira are **renderers over it** — no format is second-class, and a fourth output means writing a renderer, not touching the pipeline.

A recording produces **an array** of these (§9.3).

```ts
interface TestCaseIR {
  id: string;
  recordingId: string;
  runId: string;                  // links to the agent trace
  kind: 'test_case' | 'bug_report';

  title: string;
  description: string;
  objective?: string;             // the tester's stated objective, verbatim
  preconditions: Precondition[];  // from segments classified 'setup'
  tags: string[];

  steps: Step[];
  parameters: Parameter[];        // from redaction placeholders

  omitted: OmittedSegment[];      // exploratory/abandoned — shown, not hidden
  suggestions?: CoverageSuggestion[];   // §9.8 — never rendered as steps

  metadata: {
    capturedAt: string;
    durationMs: number;
    browser: string;
    viewport: { w: number; h: number };
    startUrl: string;
    projectId: string;
    ownerId: string;
  };

  warnings: Warning[];            // unresolved fidelity + critic findings
}

interface Step {
  id: string;
  keyword: 'Given' | 'When' | 'Then' | 'And';
  text: string;

  eventIds: string[];             // traceability into the recording
  investigationRef: string;       // → StepInvestigation in the trace
  screenshotRef: string;
  selectorHints: SelectorHint[];  // for later automation; comments in Gherkin

  assertions: Assertion[];
  libraryRef?: string;            // set when reused from the step library

  confidence: 'high' | 'medium' | 'low';
  escalation?: string;            // a specific question for the human
  fidelity: FidelityFlag[];
  criticNotes?: string[];
}

interface Assertion {
  text: string;                                   // prose — free
  provenance: 'annotated' | 'narrated' | 'objective' | 'inferred' | 'confirmed';
  evidence: {
    literal: string;                              // exact retrieved string
    toolCallId: string;                           // ← §3.2. the retrieval
    eventId: string;
    kind: 'semantic_node' | 'url' | 'network' | 'console' | 'narration';
  };
  accepted: boolean;
}

interface OmittedSegment {
  segmentId: string;
  reason: 'exploratory' | 'abandoned';
  eventCount: number;
  summary: string;                // "browsed the reports page, returned"
}
```

**Two backlinks carry the whole trust story.** `eventIds` proves the sentence came from the recording. `toolCallId` proves the agent went and looked.

---

## 11. Renderers

### 11.1 Gherkin

```gherkin
# Generated by aitc-rem from recording rec_01J8X2 — 2026-08-17
# Objective: verify that orders over €500 require approval
# Steps marked ⚠ need human review.

@checkout @smoke
Feature: Order checkout

  Background:
    Given the tester is signed in as "<<user_email>>"
    And the cart is empty

  Scenario: Submitting a valid order shows the confirmation
    When the tester adds "Blue Widget" to the cart
    # evidence: evt_012, evt_013 · POST /api/cart 201 · tc_0231
    Then the cart badge shows 1

    When the tester submits the order form
    # evidence: evt_027 · POST /api/orders 201 · tc_0447
    Then the "Order confirmed" banner appears
    And the order reference is displayed

  # 3 exploratory actions omitted between steps 2 and 3 — see review UI
```

Selectors live in comments and IR metadata, not in step text — the feature file stays human-readable while retaining what automation needs later.

### 11.2 Excel

One sheet per test case, or one row per step in a flat sheet:

| # | Step | Action | Expected result | Evidence | Confidence |
|---|---|---|---|---|---|
| 1 | Sign in | Sign in as `<<user_email>>` | Dashboard loads | evt_003–007 | High |
| 2 | Add to cart | Add "Blue Widget" | Cart badge shows 1 | evt_012–013 | High |

Plus a preconditions sheet, a parameters sheet, and a warnings sheet.

### 11.3 Jira

**Phase 2: plain issues.** Works for 100% of Jira users, zero plugin dependency.

- Issue type configurable per project (`Test`, `Task`, `Story`)
- Steps rendered as an ADF table in the description
- Attachments: `.feature` file, screenshots, `recording.json`
- Labels from IR tags
- Auth: API token, stored locally

**Later: Xray / Zephyr** as real structured Test entities behind the same interface. The interface is designed now; the implementation waits.

```ts
interface Exporter {
  name: string;
  export(ir: TestCaseIR, config: ProjectConfig): Promise<ExportResult>;
}
```

---

## 12. The step library

### 12.1 The problem it solves

The number-one reason generated-Gherkin tools get abandoned. Ten testers record ten sessions and you get ten phrasings of one action:

```
I log in as admin
I sign in with admin credentials
the user authenticates as an administrator
```

The suite becomes unmaintainable and the output feels disposable.

### 12.2 The mechanism

Every **approved** step (approved in the review UI, not merely generated) is stored per project with an embedding of its text.

On each new recording, the naming stage **must** search the library before inventing phrasing:

1. Semantic search for the drafted step text
2. Match above threshold → **reuse the library entry verbatim**, set `libraryRef`
3. No match → invent new phrasing, flag `new_step` in the review UI
4. On approval, the new step enters the library

The `library_verbatim` validator (§9.7) enforces that a step marked reused actually matches its entry.

### 12.3 Bootstrapping

On project setup, optionally import existing `.feature` files or exported Jira test cases. The library then speaks the team's established vocabulary from day one instead of inventing its own.

### 12.4 Why the index matters beyond phrasing

The same semantic index makes duplicate detection a **query** later, not new infrastructure:

- "Steps 1–3 match your existing *Admin Login* test — replace with a `Background` reference?"
- Whole-recording duplicate warnings
- Coverage views across the project

The feature is deferred; the foundation is not.

---

## 13. Review UI

A local web app. The tester never touches a terminal.

### 13.1 Layout

```
┌────────────┬──────────────────────────────┬─────────────────────┐
│ Test cases │ Selected step                │ Evidence  ·  Why    │
│ ─────────  │                              │                     │
│ ▸ Checkout │ When the tester submits the  │ [screenshot]        │
│   1 Sign in│      order form              │                     │
│   2 Add    │ ─────────────────────────    │ diff:               │
│   3 Submit⚠│ Expected results:            │  + alert "Order     │
│   4 Confirm│  ☑ "Order confirmed" banner  │      confirmed"     │
│   ⋯3 omitted│  ☑ Order reference shown    │  + text "#48812"    │
│ ▸ Refund   │  ☐ Timestamp is 14:03 ← noise│                     │
│ ▸ Approval │                              │ network:            │
│            │ ⚠ I couldn't tell whether    │  POST /api/orders   │
│ + merge    │   the export finished — did  │       → 201         │
│ + split    │   a file download?           │                     │
│            │                              │ WHY THIS STEP ▾     │
│            │                              │  ? outcome unclear  │
│            │                              │  → get_network      │
│            │                              │  → get_snapshot(aft)│
│            │                              │  → found alert node │
│            │                              │  ✓ evidence found   │
└────────────┴──────────────────────────────┴─────────────────────┘
```

### 13.2 Required interactions

| Action | Why |
|---|---|
| Accept / reject each assertion | The core review loop; must take seconds |
| Edit step text inline | The human always has final say |
| Merge / split steps (drag) | Segmentation rules will sometimes be wrong |
| Reorder steps | Rare but necessary |
| Move a step between test cases | Decomposition will sometimes be wrong |
| Expand omitted segments | Nothing is silently discarded |
| Answer an escalation | Turns the agent's question into `confirmed` provenance |
| View evidence per step | Screenshot + diff + network + console |
| Approve → export | Approval is what feeds the step library |

### 13.3 The "why this step" panel

Renders the step's `StepInvestigation` (§3.3) as a readable narrative: what the agent didn't know, what it went and looked at, what it found, why it stopped.

This does double duty and both are load-bearing:

- **Trust.** A tester who sees *the tool went and looked, and here is what it found* accepts the output. A confident sentence with no provenance gets doubted.
- **Proof.** It is the agency evidence from §3, rendered for a human instead of a script.

### 13.4 Trust affordances

- Every assertion shows its provenance badge (`annotated` / `narrated` / `objective` / `inferred` / `confirmed`).
- Every step links to the raw events that produced it and the tool calls that grounded it.
- Low-confidence steps and escalations are visually distinct, never hidden.
- Warnings are never collapsed by default.

### 13.5 Passive measurement

Every human edit is recorded: which step, what kind of change, how large. This is not analytics — it is the `steps edited by a human` column of the ablation (§3.5) and the y-axis of the effort/difficulty correlation (§3.4), collected for free from normal use.

---

## 14. Bug report mode *(Phase 3)*

The same recording, a different artifact. Test cases are future-facing and reusable; bug reports are historical and evidentiary.

### 14.1 Detection

Auto-detected, with tester override:

| Signal | Weight |
|---|---|
| Tester pressed the bug-marker hotkey | Decisive |
| Uncaught JS exception in console | Strong |
| HTTP 5xx response | Strong |
| HTTP 4xx on a state-mutating request | Medium |
| `role="alert"` with error vocabulary appearing | Medium |
| Repeated identical action (retry behaviour) | Weak |

Above threshold, the tool offers a bug report **alongside** the test case rather than instead of it — the tester chooses at review time.

### 14.2 Bug report IR

```ts
interface BugReport extends TestCaseIR {
  kind: 'bug_report';
  reproSteps: Step[];             // steps up to and including the failure
  failureStepId: string;
  expected: string;               // annotated/narrated, or inferred from the flow
  actual: string;                 // grounded in captured failure evidence
  evidence: {
    consoleErrors: ConsoleEntry[];
    failedRequests: NetworkCall[];
    screenshotAtFailure: string;
    environment: { browser: string; viewport: string; url: string };
  };
}
```

`expected` and `actual` are subject to the same evidence binding (§3.2) — `actual` must quote something the agent retrieved.

---

## 15. Tech stack

**TypeScript for browser-facing code. Python for everything server-side.**

The conventional shape of a web product, not a polyglot compromise:

| Surface | Language | Why |
|---|---|---|
| Extension | TypeScript | Chrome MV3 — no alternative |
| Review UI | TypeScript / React | Browser |
| Pipeline, tools, renderers, library, evals | Python | See below |

### 15.1 Why Python server-side

**Local embeddings for the step library — the deciding factor.** The library (§12) is core, not decorative: it is what stops step explosion from making the output disposable. `sentence-transformers` runs a small model on CPU, embedding thousands of steps per second, free, offline, no rate limits. Re-indexing the whole library after a threshold change costs nothing, so the similarity threshold can be tuned aggressively rather than guessed once.

Calling an embeddings API instead adds cost, latency and a network dependency to a core feature, and makes re-indexing something you avoid.

**Secondary:** the ablation (§3.5), the eval harness (§16.1), local transcription, and any future vision fallback are all Python-shaped. Bulk data work over recordings — computing metrics, diffing snapshots, analysing failure modes — is more ergonomic there.

### 15.2 The schema contract

The recording, IR and trace schemas are **JSON Schema, checked into `schema/`, and the single source of truth.** Both sides generate from it:

```
schema/recording.schema.json
schema/ir.schema.json
schema/trace.schema.json
  ├─ datamodel-code-generator  →  server/models/*.py       (Pydantic)
  └─ json-schema-to-typescript →  extension/src/types.ts   (TS)
                                  ui/src/types.ts
```

Generation runs in CI and fails the build on drift. The cross-language boundary is a build step, not an ongoing hazard.

The TypeScript interfaces in this document are illustrative; the schema files are authoritative.

### 15.3 Repo layout

```
aitc-rem/
├── schema/                  # JSON Schema — single source of truth
│   ├── recording.schema.json
│   ├── ir.schema.json
│   ├── trace.schema.json
│   └── codegen.sh
├── extension/               # TypeScript · Chrome MV3 content-script recorder
├── ui/                      # TypeScript · React review app
├── server/                  # Python · FastAPI
│   ├── api/                 # serves UI, job endpoints
│   ├── evidence/            # the evidence store + MCP tool server (§8)
│   ├── pipeline/            # stages, validators, critic, trace
│   ├── renderers/           # gherkin / xlsx / jira
│   ├── library/             # step library + embeddings index
│   ├── storage/             # Storage seam (§16)
│   ├── ablation/            # §3.5 — configs + metrics
│   └── evals/               # golden set + metrics (Phase 3)
├── recordings/              # local recording store (gitignored)
├── runs/                    # per-run artifacts + tool responses (gitignored)
├── SPEC.md
└── SPEC-OLD.md              # superseded draft
```

### 15.4 Key dependencies

| Area | Choice |
|---|---|
| Extension | Chrome MV3, content scripts (`all_frames`), TypeScript |
| Accessible names | `dom-accessibility-api` (W3C accname implementation) |
| UI | React + Vite + TypeScript |
| Server | Python 3.12 + FastAPI (serves the UI and the job API) |
| Tool server | MCP over stdio, local |
| Schema | JSON Schema → `datamodel-code-generator` + `json-schema-to-typescript` |
| Runtime validation | Pydantic server-side; generated Zod client-side |
| Gherkin | `gherkin-official` (Cucumber's parser) for parse-validation |
| Excel | `openpyxl` |
| Jira | REST v3 via `httpx` |
| Embeddings | `sentence-transformers`, local, CPU |
| Vector index | SQLite + `sqlite-vec` (FAISS if the library outgrows it) |
| Transcription | Local Whisper (`faster-whisper`) |
| Jobs | in-process `asyncio` behind the `JobRunner` seam (§16) |
| Storage | SQLite + local filesystem (Postgres behind the seam later) |

---

## 16. Production seams

Build local-only. Keep exactly three interfaces thin so local → hosted is a swap, not a rewrite. Roughly 60 lines of indirection buys the whole path.

```ts
interface Storage {
  saveRecording(id: string, data: Recording): Promise<void>;
  loadRecording(id: string): Promise<Recording>;
  saveArtifact(runId: string, stage: string, data: unknown): Promise<void>;
  saveToolResponse(runId: string, toolCallId: string, data: unknown): Promise<void>;
  // local FS now · S3 later
}

interface JobRunner {
  enqueue(recordingId: string): Promise<JobId>;
  status(id: JobId): Promise<JobStatus>;
  // in-process now · queue later
}

interface ModelClient {
  complete(req: CompletionRequest): Promise<CompletionResponse>;   // must support tool calling
  embed(texts: string[]): Promise<number[][]>;
  // provider-agnostic — hosted API or local endpoint, chosen later
}
```

**Also:** carry `projectId`, `ownerId` and `createdAt` in the schema from day one. Unused locally; no migration when the tool becomes multi-user.

**Explicitly not built:** auth, tenancy, billing, org management. These slow the MVP and none of them are one-way doors.

---

## 17. Known gaps

Recorded honestly rather than glossed over.

### 17.1 Evaluation

**The ablation (§3.5) is Phase 1. The full eval harness is Phase 3.** These are different things and conflating them is what makes eval work feel unaffordable.

The ablation needs no hand-written references — six of its seven metrics come from validators and the trace, which exist for other reasons. It answers one question ("does agency help, here, measurably?") and it is the thesis deliverable.

The full harness needs a golden set with hand-written reference test cases, and it answers a broader question ("is this change better?"). It is sequenced late deliberately: evals written against imagined failure modes measure the wrong things, and a golden set built after watching the pipeline fail on real recordings is far better.

**The cost of that sequencing, stated plainly:** until the harness exists, every prompt change is partly a guess. Two things soften it — **log the validator grounding rate from day one**, and **keep every recording made during development**, because they become the golden set rather than work you repeat.

### 17.2 Other open items

| Gap | Impact | Plan |
|---|---|---|
| Model provider undecided | Quality ceiling and per-recording cost both unknown | Deliberate. Build against the thin client (§9.12), pick on evidence, record in §18. Constraint: must do reliable tool calling |
| Canvas / drag steps carry no semantics | Some flows unrecordable in detail | Fidelity warning; vision pipeline later |
| Closed shadow roots unreadable | Some component libraries partly opaque | Flagged, not guessed. Unfixable without CDP, which is rejected for other reasons |
| Network capture misses pre-injection and service-worker requests | `mutation_claimed` can produce false rejections | `network_incomplete` flag downgrades that validator to a warning |
| No live-app verification | Generated tests aren't proven runnable | Optional add-on once a project supplies a URL + credentials |
| Cross-tab timeline is linear | Confusing narrative for OAuth popups | Acceptable through Phase 2; smart stitching later |
| Screenshot PII unaddressed | Blocker if a vision stage is added | Prerequisite for any vision work |
| Non-determinism in naming | The same recording may name steps slightly differently | Boundaries are deterministic; naming is not. Measure once the ablation exists |
| Snapshot performance on large enterprise apps | Two snapshots per action × 120 actions | Scoped snapshots by default (§6.3). **Validate early on a real heavy app — this is the main unvalidated capture assumption** |
| Test-case maintenance is unsolved | Real QA teams spend more time maintaining than authoring | The highest-value follow-on: re-record → diff against an existing test case. Out of scope, but the IR's `eventIds`/`libraryRef` backlinks are what would make it possible |

---

## 18. Build order

Each milestone produces something inspectable. Phases per §4.

### Phase 1 — The provable spine

| # | Milestone | Done when |
|---|---|---|
| 1 | Schema + codegen | JSON Schema for Recording, IR and Trace; `codegen.sh` emits Pydantic and TS; CI fails on drift |
| 2 | Extension: basic capture | Click/input events with scoped semantic snapshots land in `recording.json` |
| 3 | Extension: frames, shadow roots, settle window | Can record a login inside an iframe; a toast that vanishes is still captured |
| 4 | Extension: redaction | No password ever appears in a persisted file |
| 5 | Segmenter (deterministic) | `segments.json` with full event coverage |
| 6 | Evidence store + MCP tools | An agent can query snapshots/network/narration offline; every call is logged and hashed |
| 7 | Naming stage with investigation budget | Readable step sentences; trace shows variable tool calls per step |
| 8 | **Validators, incl. `evidence_retrieved`** | A deliberately fabricated assertion is rejected; an assertion pointing at a non-existent tool call is rejected |
| 9 | Gherkin renderer | Valid `.feature` file end to end |
| 10 | **Ablation harness** | `A0`/`A1`/`A2` run on the same recordings and produce the §3.5 table |

**Steps 6, 7, 8 and 10 are the thesis.** Step 8 belongs before the stages it guards — never ship a pipeline you cannot verify.

### Phase 2 — The usable product

| # | Milestone | Done when |
|---|---|---|
| 11 | Decomposition stage | A 15-minute session yields 3 coherent test cases with a shared `Background` and pruned noise |
| 12 | Assertion stage | Ranked candidates, each with a resolvable `toolCallId` |
| 13 | Review UI + "why this step" panel | Accept/reject/edit/merge/split/move, answer escalations, then export |
| 14 | Step library | A second recording reuses phrasing from the first |
| 15 | Excel + Jira exporters | All three outputs from one IR |
| 16 | Narration wired into assertions | A spoken expected result becomes a `narrated` assertion |
| 17 | Effort/difficulty correlation | The §3.4 chart, from real review data |

### Phase 3 — Smart

| # | Milestone | Done when |
|---|---|---|
| 18 | Critic + repair loop | Vague step names get regenerated automatically; convergence rate is measured |
| 19 | Coverage suggestions | Untested branches surfaced, quarantined from grounded output |
| 20 | Bug mode | A failure recording produces a repro report |
| 21 | Extension: multi-tab, file stubs | OAuth popup recorded without data loss |
| 22 | Eval harness | Golden set + scored metrics wired to CI |

---

## 19. Decision log

| Decision | Chosen | Rejected | Reason |
|---|---|---|---|
| Agency definition | Operational, with four measurable properties | Asserted in prose | A claim you cannot test is marketing (§3.1) |
| **Evidence binding** | **Claims must resolve to a logged tool response** | Grounding against the raw recording only | Welds agency to correctness; makes the proof a script rather than a diagram (§3.2) |
| Investigation | Per-step budget with recorded stop reason | Fixed retrieval per step | Effort/difficulty correlation is observable proof of adaptivity (§3.4) |
| Proof of thesis | Ablation `A0`/`A1`/`A2` in Phase 1 | Eval harness at the end | Six of seven metrics are already computed; it is a flag and a script |
| Capture | Chrome extension, content scripts | `chrome.debugger` + CDP | Debugger banner and the DevTools conflict are disqualifying for QA testers; iframes and open shadow roots are reachable anyway |
| Accessible names | `dom-accessibility-api` in page | `Accessibility.getFullAXTree` | Practical replacement without debugger attachment |
| Data contract | Queryable evidence store | A payload format | Queryability is what makes tool calling — and therefore agency — possible (§8) |
| Snapshot scope | Scoped by default, full on demand | Whole page every time | Cheap default, expensive view on request — itself an agentic decision |
| Outcome capture | Settle window + transient capture | Snapshot on next tick | Assertions about toasts are otherwise ungroundable (§6.5) |
| Assertion ranking | Annotation > narration > objective > outcome > diff | Inference-first | Inference produces true but pointless assertions; the upper layers say *which change matters* (§9.5) |
| Decomposition | Agentic, one recording → N test cases | One recording = one test case | Real sessions are multi-scenario and messy; no rule separates a false start from a test step (§9.3) |
| Noise handling | Prune from output, keep in trace, show a marker | Verbatim transcript, or silent deletion | A verbatim transcript is unusable; silent deletion is untrustworthy |
| Segmentation | Deterministic rules | LLM boundaries | Reproducible step counts; audit-friendly; predictable merge/split |
| Validation | Deterministic gate + LLM critic | Human review only | Ground truth plus a retrieval log makes hallucination mechanically checkable |
| Coverage suggestions | Separate, quarantined, labelled unverified | Mixed into steps | Cannot exist without agency; must never contaminate grounded output |
| Agent shape | Fixed skeleton with agentic stages | Single free-roaming agent | Context, consistency, reproducibility — and per-assertion verifiability, which a free agent cannot offer (§3.6) |
| Output | One IR, three renderers | Format-first | No format second-class; new outputs are renderers |
| Privacy | In-browser redaction + project rules | Server-side scrubbing | Secrets never touch disk; placeholders become test parameters |
| Value claim | Consistency and completeness | 10× speed | Realistic saving is ~2×; the durable argument is quality (§2.3) |
| Hosting | Local + three seams | SaaS from day one | Features defer cleanly; shapes do not |
| Models | Deferred — thin swappable client; must support tool calling | Baking a provider in | Quality first, cost later; tool calling is non-negotiable per §3.2 |
| Model budget | Free tiers first, paid only where free fails; fallback chain in the thin client | Committing to one paid provider | Personal budget. Free is preferred until it cannot do the job — but never at the cost of tool-calling reliability, and never for real application data (§9.12) |
| Stack | TS browser-side, Python server-side | TypeScript everywhere | Local embeddings make the step library free to tune; schema drift is solved by codegen, not by sharing a language |
