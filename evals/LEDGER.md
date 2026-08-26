# The judge's ledger

What the output was judged to be, and when. `runs/` is gitignored and cleared
between milestones, so without this file two verdicts on the same recording
never exist at the same time and *did my change help* has no answer.

Verdicts come from `.claude/agents/qa-judge.md` against
[RUBRIC.md](RUBRIC.md), reading packets from `scripts/eval_packet.py`.
Machine-readable form in `verdicts.latest.json`.

**No scores.** Pointwise rubric scoring drifts; *did my change help* is answered
pairwise on the recordings that actually moved.

---

## `baseline` — 2026-08-26

The first time this project's output was judged on quality rather than
provenance. Ten recordings, five checks each.

| | good | needs-work | bad |
|---|---|---|---|
| dev (7 fixtures) | 3 | 2 | 2 |
| **held-out (3 real sessions)** | **0** | **0** | **3** |

27 findings: 11 fail, 16 weak.

**Read that beside the gate it passed.** Nine of ten runs report a grounding
rate of 1.0 and six report validator pass 1.0. The gate was right every time.

### The one observation

> The gate is doing its job and the author is not.

**Correction, 2026-08-26, after the system review.** This section originally read
*"the largest defect class — eleven findings — is the drafter asserting the label
rather than the value the feature computes"*. That was wrong, and wrong twice.

*Eleven is the `drafting-prompt` **layer** total, not a class.* Counted by check
rather than by layer, `verdicts.latest.json` gives:

| check | findings |
|---|---|
| `verdict_fails_on_broken_build` | 7 |
| `sentence_covers_its_events` | 7 |
| `name_matches_verdict` | 5 |
| `tester_intent_kept` | 5 |
| `one_scenario_one_behaviour` | 3 |

Exactly **one** finding is label-instead-of-computed-value. The rest of the
eleven are four sentence-vs-events, two *"quotes 500, the tester entered 750"*,
one disjunctive verdict, one claim contradicted by its own retrieval, two
name/structure.

*And on that one, the objective asked for the label.* It reads **"check if
hamper sizes change correctly"** — the drafter asserted the hamper **size**. It
did what it was told; the capacity counter is a value the tester never named.
That makes it partly a `tester` finding, and the fourth "correctly"/"working"
objective to produce a `bad` run out of four.

The observation still stands; its evidence is different. The largest real class
is **sentence-does-not-cover-its-events**, and it has a home — see `m5` below.

Every fixture that scored `good` did so on a recording whose objective already
named the verdict. All three held-out sessions — where the tester gave clicks
and a vague sentence — came out `bad`. That is the same result
`docs/RECORDING.md` already measured from the other direction.

### By layer

| layer | findings | the pattern |
|---|---|---|
| `drafting-prompt` | 11 | mostly sentences that swallow the events they claim (4); label-not-value is **one** — see the correction above |
| `architecture` | 5 | bug-mode has no `NOISE` equivalent, so a jQuery plugin warning reached threshold on `rec_MT7VTN7ZRJPO` |
| `split` | 4 | trigger missed a three-verdict scenario at 10 events / 3 beats — under both floors; a split left scenario 2's precondition in scenario 1 |
| `bind` | 3 | `_own_input` refuses a dropdown label and accepts the same substance as a URL; `twoflows` bound a verdict to an event in the *other* test case |
| `validator` | 2 | two gate holes, below |

### Verified by hand before acting

- **`Then Order requires approval`** (`twoflows`) — named exactly by both
  `gherkin_style` and `evidence_discriminates`, as warnings, and it shipped
  through three repair attempts. Real.

### Raised and rejected

- **`bugged` ships a `.feature` saying the export failed and a `.bug.md`
  expecting it to succeed.** Judged `architecture`; **not a defect**. SPEC §14.1:
  the tool offers a bug report *alongside* the test case rather than instead of
  it, and the tester chooses at review time. Those are the two valid readings of
  one session.

- **`provenance: "narrated"` on a recording with `narration: []`.** Judged a
  gate hole. **Not a defect, and the instrument was at fault.** The e2e suite
  rewrites every fixture with an empty `narration`; the transcript is produced
  from the committed audio at RUN time by `attach_narration` — the same call the
  CLI and `test_fixture_outcomes.py` both make, and for the same reason.
  `provenance_supported` was correct, and the fixture-outcome test is satisfied
  by the feature.

  **`eval_packet.py` was reading the raw file and printing "Narration: none" for
  a recording the tester had narrated.** The packet is the judge's only window,
  so it asserted silence where there was speech. Fixed: the packet now attaches
  narration exactly as the run does, and says *unknown* rather than *none* when
  it cannot transcribe. Two of ten packets were affected —
  `rec_MTA1OK3S1NX1` (1 segment) and **`rec_MT7VTN7ZRJPO` (5 segments), a
  held-out session** whose check 5 was therefore judged blind. Both re-judged
  below.

**The lesson is about the instrument, not the judge.** A packet that omits an
input does not produce a cautious verdict, it produces a confident wrong one —
and the finding it invented pointed at a validator that was doing its job. Every
future field added to the packet gets checked against what the *pipeline* sees,
not what the file holds.

### Re-judged with the narration restored

- **`rec_MTA1OK3S1NX1`: `needs-work` → `good`.** All five checks pass. Narration
  works exactly as designed on the fixture built to demonstrate it: the tester
  says *"Now I'm checking that an order this size needs manager approval"*, the
  digest lands it on the step carrying the only `Then`, and the claim rests on a
  snapshot literal rather than the transcript. §9.5's ladder, working.
- **`rec_MT7VTN7ZRJPO`: `bad` → `bad`**, but with a different and much better
  diagnosis — below.

---

## `m2-deterministic` — 2026-08-26

Three fixes, all code, no model involved. Two of them found because the judge
was given a better packet.

### 1 · A declared-break split left the first group with the old name

`run._split_on_declared_breaks` gave groups 2..n `name=""` so `_scenario_from`
could name them after what they verify, and left **group 1 holding the name the
drafter wrote for the whole session**. After a cut, that body no longer exists.

Fixed by clearing the first group's name too, but only when a cut actually
happened — a scenario nothing split keeps the drafter's name, which saw the
whole session. `twoflows`, live re-run:

```gherkin
# before
Scenario: An order exceeding the threshold requires approval
  When the tester signs in and adds an item to the cart
  Then The cart badge updates to show 'Cart contains 1 items', confirming the item was successfully added
Scenario: Order requires approval
  ...
  Then Order requires approval

# after
Scenario: The cart badge displays a count of 1
  When the tester signs in and adds a "Blue Widget" to the cart
  Then the cart badge displays a count of 1
Scenario: The order is rejected with an approval required status
  ...
  Then the order is rejected with an approval required status
```

One change, three findings closed: the name/verdict mismatch (check 4), the
run-on `Then`, and `Then Order requires approval` — the title-shaped assertion
STATUS had open, which both `gherkin_style` and `evidence_discriminates` warned
about and which shipped through three repair attempts anyway.

### 2 · Everything the tester said before their first click was thrown away

`digest._event_block` emitted its `said:` line only `if previous is not None`.
There is no window before the first recorded event, **and that is the window a
tester states their objective in** — before they start clicking, not during.

On `rec_MT7VTN7ZRJPO` the events begin at 15.6s and four of five segments fall
in 0.9s–14.9s. The only sentence the drafter ever saw was *"And I will add to
bag a…"*. Thrown away, including:

> *"I will test if I can add the coffee products correctly to the cart"*

— the objective, said out loud, by a tester on a recording the earlier pass had
called *"no objective, no annotations, no narration"*. That was wrong twice: the
tester gave an objective, and a code change fixes it.

**The `scenario_break` defect in a second costume** — a session-level fact no
per-event block can carry, silently absent rather than wrong. `test_digest.py`
had no narration test at all, which is why it survived; it has two now, the
second being that `include_narration=False` still withholds everything.

### 3 · The packet lied about silence

Covered above. The instrument fix that produced findings 1 and 2.

### Still open, and now better understood

`rec_MT7VTN7ZRJPO` remains `bad`. With the transcript visible the diagnosis
sharpened rather than softened: the tester said they were checking that coffee
**adds correctly**, and the run shipped a negative-path test about a quantity
limit they never mentioned, while the one step covering their actual check
shipped with no verdict. One claim — *"prevents the addition … and displays an
error"* — is contradicted by the retrieval it cites: the same diff shows
`"Added"` beside `"Maximum Quantity allowed is 3"` on a POST that returned
**200**. That is a `drafting-prompt` finding and the digest fix may move it on
its own; it has not been re-run.

---

## `m5-critic-sees-events` — 2026-08-26

One change, from the whole-system review. Not yet scored — see the cost below.

### The critic was shown one side of what it judges

`critic._prompt` printed each step's id, keyword, text and accepted assertions,
and **never the events the step claims**. `split._prompt` had been printing
`[{events}]` for its own agent the whole time, twenty lines away in a sibling
file.

That single omission explains the baseline better than any prompt rule. The
largest real defect class — **7 of 27 findings, on four of ten recordings, dev
and held-out alike** — is a sentence that does not cover the events it claims,
and every instance of it *reads perfectly in the artifact alone*:

```
text:     the tester increases the quantity of items until the hamper upgrades
eventIds: ... evt_017 = click button "Upgrade"
```

The sentence hands the application an action the tester performed. `event_coverage`
counts events into steps and cannot read a sentence; the drafting prompt already
argues against this with a worked example and it happens anyway; and the only
judgement layer in the system could not see it.

**The eval packet built this week was a strictly better critic input than the
critic's own prompt, and the two were designed independently.** That is the
finding — not a missing stage, a judgement layer looking at the wrong surface.

Fixed by passing `runner.store` into `_prompt` and printing, under each step,
what the tester did in the words the step is judged in — role and accessible
name, capped at `MAX_EVENTS_SHOWN = 8`. Plus one clause on the `step_name` axis.

Safe where a drafting-prompt change would not have been: the critic runs
**after** `split_scenarios`, so it cannot perturb the splitter, and
`CRITIC_REPAIR["step_name"] → rewrite_steps` touches text only — never
`eventIds`, never `step_id` — so §3.6 holds by construction.

### What it costs, stated plainly

**The critic's cassettes are invalidated by construction** — the key is the exact
request. Under `--offline` the critic now records
`failed: CassetteMiss` and contributes zero findings until the recordings are run
live again. Nothing raises; that graceful path exists precisely so "crashed" and
"found nothing" stay distinguishable, and it is earning its keep here.

Provider calls stand at **349 against a configured daily limit of 200**, so the
live re-run waits for the budget to roll over. Until then this change is
unit-tested and unscored.

### The next row is the deliverable

Re-run the three held-out recordings live, judge them pairwise against
`baseline`, and write the result — whichever way it goes.

**What would falsify the change:** the held-out verdicts do not move. Then the
critic is not the lever, the author's judgement is the ceiling, and the honest
conclusion is *blocked on a model stronger than `gemini-3.1-flash-lite`* —
which belongs in the report stated plainly, not worked around with another stage.
