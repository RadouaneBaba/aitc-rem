# Decisions

Judgement calls made while building, with what would change my mind. Failed
experiments are in here too — the reverted value-preference rule is worth more
written down than forgotten, and a decision with no falsification condition is a
preference with a heading.

Newest first.

---

## 2026-08-26 · The critic reads the artifact; every quality defect lives between the artifact and the recording

**Decided.** Show the critic each step's `eventIds` — the way `split.py` already
shows its agent — and add one clause to the `step_name` axis. Nothing else
changes.

**The defect, as a reproduction.** `rec_MT7MXBS9B2VB`, `step_003`:

```
text:     the tester increases the quantity of items until the hamper upgrades
eventIds: ... evt_017 = click button "Upgrade"
```

The sentence attributes to the application an action the tester performed. Same
class on three more recordings in the same baseline: `rec_MT7VTN7ZRJPO`
(*"Given the tester is on the coffee capsules page"* claims `evt_001`, a click
on button "Add"), `rec_MTA7A2XHHH22` (*"filters by 'In stock'"* claims two
combobox clicks), `rec_MTA1O4R3SSR5` (`step_003` swallows a promo-widget click).
**Four of ten recordings, dev and held-out alike.**

**Why nothing catches it, and this is the shape finding.** `event_coverage`
counts events into steps and cannot read a sentence — `evals/RUBRIC.md` says so
itself. The drafting prompt already argues against it with a BAD/GOOD worked
example (`draft.py`, the "Accounting for the session" section) and it happens
anyway. And the critic — the system's **only** judgement layer — cannot see it,
because `critic._prompt` prints the step id, keyword, text and accepted
assertions, and never the `eventIds` or what those events were.
`split._prompt` prints exactly that (`[{events}]`) plus the whole digest, for
its own agent, twenty lines away.

Generalise it and it explains the baseline. Three of the largest classes the
judge found — sentence-does-not-cover-its-events, label-instead-of-computed-
value, quotes-a-value-the-tester-did-not-type — are all defects in the
*relationship between the artifact and the recording*, and the critic is shown
only one side of that relationship. **The eval packet built this week is
strictly a better critic input than the critic's own prompt, and the two were
designed independently.** That is the finding: not a missing stage, a judgement
layer looking at the wrong surface.

**The guarantee at stake.** §11.1 — the `.feature` body is prose and nothing
else. It is not at risk: that rule governs the rendered file, and `_prompt`'s
own docstring already says the ids travel alongside because a critic that cannot
name a step is useless. Event ids travel by the same argument.

**Options.**

1. *Do nothing; the reviewer catches it.* This is genuinely right for some
   defects here — a scenario with no verdict ships warned, on purpose. It is
   wrong for this one. The sentence reads perfectly in isolation; you can only
   catch it by comparing against the recording, which is the one thing a reviewer
   reading a `.feature` file does not have in front of them. Cost: it is the
   defect most likely to reach a tester.
2. *A fifteenth validator.* Rejected. "Does this sentence describe these events"
   is a judgement — a token-overlap rule rejects *"signs in"* over a
   type/type/click (correct, one intent) and accepts the hamper defect (the word
   "upgrade" is in both). That is a yield cut wearing a fix's name, and the gate
   is not where judgement goes.
3. *Show the critic the mapping.* The route already exists end to end:
   `CRITIC_REPAIR["step_name"] = PipelineStage.name` → `rewrite_steps`, which
   walks the drafted steps and touches text only — never `eventIds`, never
   `step_id` — so §3.6 holds by construction, and `narrative.would_collapse`
   already refuses a rewrite that would merge two steps. A2 only, which is
   correct: §3.5 defines A2 as the critic, and this gives that column a quality
   difference it has never had.

**Chosen: 3.** It is a prompt-and-input change, not a stage, and it is handed
back as such — but it is only safe because of where it sits. The critic runs
**after** `split_scenarios`, so unlike the reverted value-preference rule it
cannot perturb the splitter at all.

**What would change my mind.** Precision. If the critic, given the events,
raises `step_name` findings on steps that are fine, the repair loop spends its
budget making good sentences worse — the `hardpaths` regression again. Calibrate
over every step on disk the way `tests/test_bind.py` calibrates a bind rule; if
fewer than half the findings are real, revert and say so here.

## 2026-08-26 · The label-versus-value class is one finding, not eleven — and the objective asked for the label

**Decided.** Do not retry the value-preference rule in the drafting prompt. If
the question is asked at all, it is asked in the critic's `assertion` axis, and
only as a free rider on the change above.

**Two corrections to the framing, both from `verdicts.latest.json` rather than
from prose.**

*First, the count.* Eleven is the `drafting-prompt` **layer** total, not a class.
Exactly **one** finding is the label-instead-of-computed-value defect
(`rec_MT7MXBS9B2VB`: both verdicts assert the basket name; `"13 / 13"` sits in
the same snapshot). The other ten are four sentence-does-not-cover-its-events,
two *"quotes 500, the tester entered 750"*, one disjunctive verdict, one claim
contradicted by the retrieval it cites, two name/structure. `LEDGER.md`'s
headline equates the layer with the class; the JSON does not support it. The
largest real class is the one in the entry above.

*Second, whose defect it is.* The objective on that recording is **"check if
hamper sizes change correctly"**. The drafter asserted the hamper **size**. It
did what it was told; the capacity counter is a value the tester never named.
That is partly a `tester` finding, and the deterministic objective coach shipped
for it three entries down this file — and it is the fourth "correctly"/"working"
objective to produce a `bad` run out of four.

**The guarantee at stake.** A drafting-prompt change perturbs every stage
downstream, and the splitter is the stage least able to absorb it. Already
decided, already paid for once: the rule half-took (1 of 3 capacity values) and
cost the split.

**Options.** Retry the drafter rule — same lever, same stage, splitter still
unstable, no. Route it through the critic's `assertion` axis, which is downstream
of the split, cannot change the step count, and is already protected by
`_keep_provable` (a proven claim is not replaced by an unprovable one). Or leave
it as the honest edge, which is what the explainer already says.

**Chosen:** the second, and *only* as one clause added while the critic's prompt
is open anyway. It is not worth a run of its own. The third option remains
correct if the first change is not made.

**What would change my mind.** A second recording where the computed value is
asserted nowhere **and the objective named it**. One instance whose objective
pointed at the label is a preference; two with the objective pointing the other
way is a class, and then it is worth its own experiment.

## 2026-08-26 · No stage is missing. Do the one change above, re-judge, and write the report

**Decided.** The shape is right. Stop building.

**The reproduction is the absence of one.** Twenty-seven findings over ten
recordings, and **every one routes to a stage that already exists or to the
tester.** Nothing is in the position `coherence` was in when `split.py` was
written — reported repeatedly, correctly, with nowhere to go. The one candidate
for that shape is in the first entry, and its route (`step_name` →
`rewrite_steps`) is already built and already wired. That is what a system with
no missing stage looks like from the outside.

Two things checked and found already answered, so they do not become work:

- **"Bug mode has no `NOISE` equivalent"** (judged `architecture`, five findings
  in that layer). `bugmode.py` already has `_first_party_stack`, `OPAQUE` /
  `_informative`, the `third_party_5xx` demotion and per-message dedup, and a
  written decision at `bugmode.py:255-262` that a *stackless* exception is not
  demoted — "the threshold exists to stop obvious third-party noise, not to
  require proof of guilt." The jQuery warning got through that door on purpose.
  It is a calibration question with the argument already on the record, not a
  hole in the shape.
- **§18 milestone 22, the eval harness.** It exists. `evals/` — rubric, ledger,
  packets, held-out split — is that harness, and it arrived by the exact route
  §17.1 predicted: after watching the pipeline fail on real recordings, not
  before. Mark the milestone closed in the report rather than building it.

**Nothing is worth deleting either**, and I looked. The step library is the only
real candidate — no corpus, `library_verbatim` vacuously green, the per-step
search already removed, and a protected-step rule enforced in two places to
guard entries that do not exist. It is still §12 built and working, and tearing
out a demonstrable spec section to remove cost from a codebase nobody will
maintain is negative value against a finish line that is a demo and a report.
Leave it; say in the report that it recommends and never substitutes, which is
the interesting half anyway.

**Options.** Build a "does this sentence match the recording" stage — no, the
first entry shows the route exists. Build milestone 21 or 22 — no, both have
written reasons and 22 is done. Or: make the one change, re-judge the three
held-out recordings pairwise, and ship.

**Chosen: the third.** The strongest artifact still available is a **second row
in `LEDGER.md`** showing the loop closing on the recordings that moved. A
project that built a judge, was told something specific, changed one thing and
measured the result is a better report than a project with fifteen validators —
and `evals/LEDGER.md` already has the harder half of that written.

**What would change my mind.** The first entry's change lands and the held-out
verdicts do not move. Then the critic is not the lever, the author's judgement
genuinely is the ceiling, and the conclusion is *blocked on a stronger model than
`gemini-3.1-flash-lite`* — which belongs in the report as a finding, stated
plainly, not worked around with another stage.

## 2026-08-26 · The judge is the gate's complement, and never a second gate

**Decided.** `evals/RUBRIC.md` contains only checks no validator can perform.
Anything the fourteen already do is out of scope for it by construction.

**Why.** The failure mode of adding an LLM judge to a system that already has a
gate is that it re-checks what the gate checks, produces confident agreement,
and feels productive. The five checks that survived — would this fail on a
broken build, does the sentence cover its events, is this one behaviour, does
the name match the verdict, did the tester's intent survive — are each provably
outside all fourteen.

**What would change my mind.** A judge finding that a validator *should* have
caught. That means the rubric drifted into the gate's territory, or a validator
has a hole worth naming.

## 2026-08-26 · No numeric scores in the ledger

**Decided.** Verdicts are `good` / `needs-work` / `bad` plus findings. "Did my
change help" is answered pairwise on the recordings that moved.

**Why.** Pointwise rubric scoring has inter-rater reliability around 0.45–0.60
and drifts across time and model version. A ledger of such numbers would look
like measurement and behave like noise — and this project already has enough
metrics that mean less than they appear to.

**What would change my mind.** Enough recordings that pairwise comparison stops
scaling. At ten it is fine.

## 2026-08-26 · Two instruments, and neither can write

**Decided.** `qa-judge` (one packet, frequently) and `system-review` (whole
repo, rarely) are read-only. Every edit is made by the session driving them.

**Why.** Separate context windows and freedom from self-preference bias are the
only things an agent buys here that is not available inline. A judge that can
reach the prompt grades the work it just did. Three agents were proposed and one
was cut — a `pipeline-tuner` would have re-read the non-negotiables cold on
every spawn to make a three-line edit.

**Confirmed in practice, twice.** Both errors the judge made came from the
packet being incomplete, not from the judge reasoning badly. Verification before
acting on a finding is not optional.

## 2026-08-26 · The packet must show what the PIPELINE sees, not what the file holds

**Decided.** `eval_packet.py` calls `attach_narration` exactly as the CLI does.

**Why.** It read recordings straight off disk and printed "Narration: none" for
two recordings the tester had narrated — the e2e suite deliberately rewrites
fixtures with an empty `narration` and the transcript is produced from the
committed audio at run time. The packet is the judge's only window, so it
asserted silence where there was speech, and the judge produced a confident
finding against a validator that was doing its job.

**The general rule this earns:** a missing input does not produce a cautious
verdict, it produces a wrong one. Every field added to the packet is checked
against the pipeline's view, never the file's.

## 2026-08-26 · A declared-break split renames the first group too

**Decided.** When a tester's declared scenario break cuts a drafted scenario,
*both* halves are renamed by `_scenario_from` after what they verify.

**Why.** Groups 2..n were already renamed; group 1 kept the name the drafter
wrote for the whole session, and after a cut that body no longer exists.
`twoflows` shipped *"An order exceeding the threshold requires approval"* over a
body that signs in, adds one item, and asserts a cart badge.

**What would change my mind.** A recording where the drafter's original name is
right for the first group and `_scenario_from`'s is worse. The negative case is
already pinned: a scenario nothing splits keeps its name.

## 2026-08-26 · Narration before the first click is indexed

**Decided.** `digest._event_block` uses a window from the session start for the
first event, instead of emitting nothing.

**Why.** It emitted `said:` only `if previous is not None`. Testers state their
objective *before* they start clicking. On one real recording four of five
segments fell before the first event, including *"I will test if I can add the
coffee products correctly to the cart"* — the objective, spoken aloud, on a
recording an earlier judgement had called "no objective, no annotations, no
narration".

**Same family as the `scenario_break` defect:** a session-level fact that no
per-event block can carry, silently absent rather than wrong.

## 2026-08-26 · The objective coach is deterministic, and advises "delete it"

**Decided.** A regex-based check in the popup, live as the tester types. No
model call. It never blocks recording and never rewrites the objective.

**Why.** `docs/RECORDING.md` already holds a measured three-way ablation: a
vague objective is *worse than none*. Checked again against the judge's verdicts
over every recording on disk — four of four objectives containing
"correctly"/"working" produced `bad` test cases; five of five "Check that
⟨proposition⟩" produced acceptable ones. The signal is linguistic and cheap, so
paying a model call for it would buy latency and nothing else.

**The advice is the valuable half.** Telling a tester to *clear the box* is the
project's own measured result and something no one would guess.

**Not rewriting is a rule, not a limitation.** The objective is one of the three
inputs that outrank the model (§6.7). An AI that silently sharpened it would
invert the ladder. Same shape as the step library: recommends, never substitutes.

**What would change my mind.** A real objective the checker flags wrongly. It is
calibrated against every one on disk plus the doc's own worked examples; the
next miss earns a new case, not a loosened rule.

---

## Raised, not decided

### Un-approving a run

The review UI has no way to withdraw an approval, and I did not add one.

Approval is §13.5's record of who signed a run off, and it is the project's only
source of difficulty labels — the ablation's "steps edited by a human" column
and §3.4's y-axis. A withdrawn approval changes what that record *means*, and
whether the edits made before it still count. That is an architectural question
about the measurement, not a missing button.

**What it needs:** a decision about whether the record is append-only. Until
then the Approve button confirms first and says it cannot be undone.

### The author asserts the label, not the computed value

The largest open defect class, and it is judgement rather than provenance. On
one run the snapshot held both `"Medium Wicker Basket"` and `"13 / 13"` and the
author asserted the name; nothing refused it, because nothing was wrong with it.

A prompt rule for this was **tried and reverted** before this session: it
half-took, and the run came back as a single scenario with three beats under one
heading. The loss could not be cleanly attributed, which is itself the finding —
a drafting-prompt change perturbs every stage downstream, and the splitter reads
the draft.

**What it needs:** either a deterministic preference (assert the value that
would change if the feature broke — hard to define without a model) or a
stronger author. It is the honest edge of the design and it is stated as such in
the explainer.
