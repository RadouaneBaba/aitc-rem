# Phase 2 — status and what remains

Working plan, kept in the repo so it travels with the code. [SPEC.md](SPEC.md)
is the design and does not change; this is where the build order lives.
[CLAUDE.md](CLAUDE.md) carries the rules you need in order to change things
safely.

Last updated 2026-08-19.

---

## Done

### The output quality pass

Phase 1 proved the thesis and left the artifact to fall out of the pipeline by
default. It showed: `Feature:` and `Scenario:` both set to the tester's raw
objective string, seven `When`s in a row, `!!` glued into sentences a step
definition has to match, and a traceability comment under every step.

Root cause: naming was the only agentic stage and it sees one segment at a time.
Nothing ever decided what the *document* was.

| Landed | What |
|---|---|
| `pipeline/compose.py` | Agentic. Reads the whole named flow at once: feature title, scenario name, description, tags, per-step role, and merge groups for segments that are one intent. Degrades to a deterministic fallback rather than costing the run |
| `pipeline/narrative.py` | Deterministic. Roles → Given/When/Then, `And` collapsing, assertion placement, beats. `Given` belongs to the opening block only |
| `pipeline/investigate.py` | The decide-retrieve-observe loop, extracted so every agentic stage records effort the same way |
| `renderers/gherkin.py` | Rewritten. Pure Gherkin body — no comments, no ids, no review markers |
| `renderers/trace_md.py` | The evidence sidecar: everything the body stopped carrying |
| `validators/style.py` | `gherkin_style`, warn-only, so none of it regresses silently |
| `config/project.yaml` | House style: voice, tags, sidecar, parameter rendering, exports, Jira settings |

### Milestone B — ranked assertions (§9.5)

`pipeline/assertions.py`. Provenance ladder (annotated > narrated > objective >
inferred), up to three candidates per step, top-ranked accepted and the rest
proposed. Noise suppression in code, not prompt. Naming no longer writes
expected results at all.

Yield doubled: 0.222 → 0.444 grounded assertions per step, still 100% grounded.

### Milestone D — zero terminal (§13)

`server/api/` + `ui/`. The recorder posts to a local server, the pipeline runs
as a background job, review happens in a browser: accept/reject, edit, merge,
answer escalations, rename, approve, export. Every edit is recorded with its
size (§13.5) — the ablation's `steps edited by a human` column and §3.4's
y-axis.

### Milestone F — Excel + Jira (§11.2, §11.3)

`renderers/base.py` defines the `Exporter` seam; `xlsx.py` and `jira.py`
implement it. Jira builds the ADF issue and writes it to disk rather than
posting — sending needs a site, a project key and a token.

### Where the numbers stand

```
Config   Assert   Grounded    Yield   Fabric.   Valid1st   Calls/step   Spread
A0            3        0.0      0.0         3     0.7525          0.0      0.0
A1            4        1.0   0.4444         0        1.0        1.556    1.083
A2            4        1.0   0.4444         0        1.0        1.556    1.083
```

---

## Remaining

### C · Full decomposition (§9.3, milestone 11)

Extend `compose.py`: one recording → N test cases, `Background` lifted from
setup shared across them, `exploratory`/`abandoned` segments pruned into
`omitted` with markers.

Most of the machinery is already there — `SegmentRole` covers all five roles,
`DecompositionDecision` is in the trace schema, `build_narrative` takes
`lift_background`, and `OmittedSegment` renders in every format.

**The real cost is not the code.** Both fixtures are single-scenario, so
"one recording → N test cases" cannot be demonstrated on them. Showing it work
needs a new multi-flow recording, which means a new Playwright spec against the
demo app writing to a *new* fixture file — do not regenerate
`tests/fixtures/{checkout,hardpaths}.recording.json`, or every cassette keyed on
their content is invalidated.

Watch: `event_coverage` already accepts events covered by an `omitted` segment,
and `no_pruned_assertion` currently skips because nothing is ever pruned. Both
become live.

### E · Step library (§12, milestone 14)

`server/library/` is empty. `sentence-transformers` + `sqlite-vec` are declared
in the `library` extra and **not installed** — it pulls torch, multi-GB, so
install deliberately:

```bash
.venv/Scripts/python -m pip install -e ".[library]"
```

Embeddings run local on CPU; §15.1 says that is the deciding factor for Python
server-side, so re-indexing after a threshold change is free and the threshold
can be tuned rather than guessed.

Search-before-invent goes into the naming stage. `library_verbatim` already
exists and currently skips. A step enters the library on human **approval**
(§12.2) — `review.approved` is already recorded, which is the hook.

Changing the naming prompt invalidates its cassettes; budget one re-record of
both fixtures.

### G · Narration and the effort/difficulty chart (milestones 16, 17)

**Narration → assertions.** Transcription is local Whisper (`transcription`
extra, not installed). The ranking machinery is built and tested but completely
unexercised: no fixture contains an annotation or a spoken word, so every
assertion in existence is `inferred`. That is the honest ceiling on output
quality — with nothing but inference, the agent sometimes picks a true but
incidental outcome, which is exactly what §9.5's upper tiers exist to prevent.

Unblocking this and C need the same thing: a recording made with the annotation
buttons and narration actually used.

**Effort/difficulty correlation (§3.4).** Cheapest item left. `review.json`
already records which steps a human edited and by how much;
`trace.metrics.toolCallsPerStep` already sums retrievals per step across every
stage. It is one scatter plot from two files that already exist.

---

## Known gaps

- **The extension's "Send to aitc-rem" button has never been clicked against a
  live server.** It compiles, and the endpoint is tested from both sides, but
  that seam is unproven — it needs a human in Chrome.
- **The review UI has no unit tests.** `pnpm typecheck` in `check.sh` is what
  stops it drifting from the API shapes in `server/api/app.py`.
- **`runs/_cassettes/` is gitignored.** ~145 files, ~2 MB. Losing it means
  every offline run starts calling the real model again. Carry it between
  machines deliberately.
