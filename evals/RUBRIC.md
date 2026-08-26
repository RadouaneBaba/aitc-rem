# How to judge a test case, and what to blame when it is bad

The gate answers *can this claim point at the retrieval that produced it*. It
has never answered *is this a test case a QA lead would sign*, and the two came
apart on a real recording: `rec_MTA7A2XHHH22` shipped **fourteen validators
green, 4 of 4 claims grounded, and three of the four proving nothing**.

Read by `.claude/agents/qa-judge.md` against a packet from
`scripts/eval_packet.py`. Verdicts go in [LEDGER.md](LEDGER.md).

**This rubric is the COMPLEMENT of the gate.** Every check below is one no
validator can perform. If a validator already does it, it is not the judge's
job — otherwise this is a second gate, and a second gate is exactly the kind of
work that feels productive and finds nothing. The fourteen are:
`evidence_retrieved`, `assertion_grounding`, `provenance_supported`,
`evidence_discriminates`, `element_exists`, `mutation_claimed`,
`event_coverage`, `gherkin_parses`, `gherkin_style`, `library_verbatim`,
`no_placeholder_leak`, `selector_resolvable`, `no_pruned_assertion`,
`suggestions_quarantined`.

**The judge does not edit anything.** Judging and fixing are separate on
purpose: a judge that can reach the prompt grades the work it just did.

---

## The one question that does most of the work

> **Break the feature. Does this step still pass?**

If yes, the step is decoration. Say so, whatever the grounding trail looks like.

```gherkin
Then the product list updates to show lower-priced items first
```
Evidence: `"Prix bas à haut"` — the option the tester chose from the sort
dropdown. Reverse the sort order in the application and this still passes,
because the dropdown still says what the tester set it to.

```gherkin
Then the hamper is shown as a "Medium Wicker Basket"
```
Evidence: the basket's name. Break the capacity counter — the thing the upgrade
feature computes — and this passes. `"13 / 13"` was in the same snapshot and was
not asserted.

Both were green on every validator. Neither would catch a regression.

---

## The five checks

Score each scenario **pass / weak / fail** and say why in one sentence.
`weak` = a QA lead would sign it after an edit. `fail` = they would send it back.

### 1 · The verdict would fail on a broken build
*No validator can ask this.* `mutation_claimed` checks the sentence claims a
change; nothing checks the evidence would move if the feature broke.

- fail: `Then Order requires approval` — a title, and a restatement of the
  scenario name. It asserts nothing.
- fail: `Then the shopping bag panel opens, displaying the items previously
  added` — bound to the panel's own heading. Evidence that a heading exists.
- pass: `Then an alert states that orders over EUR500 require approval`.

### 2 · The sentence covers the events it claims — all of them, and no more
*`event_coverage` counts events into steps. It cannot read the sentence.*

Look at the events printed under the step in section 3 of the packet.

- fail: *"adds an item to the cart and proceeds to checkout"* over four events,
  two of which are a detour to the reports page. Every event accounted for, gate
  green, and the sentence covers neither of the two.
- pass: one intent per step, with only the values that identify the case.

### 3 · One scenario is one behaviour
*`gherkin_style` counts beats against `MAX_BEATS`; the critic's `coherence`
names this and has no row in `CRITIC_REPAIR`, so nothing acts on it.* A
two-beat scenario can still be two behaviours — beats are not behaviours.

- fail: three near-identical When/Then beats under one heading. That is three
  test cases sharing a name.

### 4 · The scenario name is the verdict the scenario reached
*Nothing checks this. The name is written before binding, and binding can
delete the claim the name was about.*

- fail: *"An order exceeding the threshold requires approval"* over a body that
  signs in, adds an item, and asserts a cart badge.
- pass: *"A hamper automatically upgrades to a Medium Wicker Basket when
  capacity is reached"* over a body that reaches capacity and asserts it.

### 5 · Nothing the tester said was lost
*Nothing checks this.* The objective, an intent note, a marked element, a spoken
sentence — each outranks the model (§6.7).

- fail: the tester said *"I'm checking the discount applies"* and no scenario is
  about the discount, however clean the prose.
- Note when the tester gave nothing: no objective, no annotations, no narration
  is a `tester` finding, not a pipeline one.

---

## Then name the layer

A verdict with no diagnosis costs a re-read to act on. For every `weak` or
`fail`, name exactly **one** layer.

| What you saw | Layer | How the packet tells you |
|---|---|---|
| Claim is true but survives a broken feature | `drafting-prompt` | Section 4 shows nothing refused it. Which value to assert is content, not provenance — if the agent's recorded reason *mentions* the discriminating evidence and cites something else, more retrieval budget will not fix it |
| A good sentence was refused | `bind` | Section 4 names the rule in its reason. Before loosening, re-calibrate over every (claim, literal) pair on disk — a rule that rejects the bad ones and some good ones is a yield cut wearing a fix's name |
| Sentence does not cover its events | `drafting-prompt` | Section 3 prints the events under the sentence |
| Several verdicts under one heading | `split` | Section 5 prints the splitter's decision. Under `SPLIT_EVENT_FLOOR = 12` events → the trigger. Over it and one group returned → the answer |
| Name disagrees with the verdict | `architecture` | Nothing reads a name against the claim its scenario ended up with |
| No verdict at all, both attempts refused | `bind`, or **correct** | `_second_chance` re-asked and binding refused again. The recording may genuinely not contain a verdict — a visible gap beats an invisible falsehood |
| Evidence was in the session but never retrieved | `digest` | The index is thin. Many `(re-render; nothing named)` events is the signature |
| Vague objective, nothing marked, no narration | `tester` | Section 1. No code change fixes it |

---

## Verdict

Per run: `good` (every check passes, or one weak) · `needs-work` (any weak, no
fails) · `bad` (any fail).

**No numeric score.** Pointwise rubric scoring has inter-rater reliability
around 0.45–0.60 and drifts across time and model version, so a ledger of such
numbers is noise dressed up as measurement. *Did my change help* is answered
**pairwise** instead: same recording, output before and after, which is better
and why.

Two failure modes of the judge's own to avoid:

- **Do not reward provenance.** A grounding rate of 1.0 on a run that claimed
  nothing scores 1.0 and means nothing. The packet prints yield beside it.
- **Do not punish an honest gap.** A scenario shipping with no verdict because
  binding refused two attempts is the designed outcome when the recording does
  not contain one. `weak` with the reason, not `fail`.

## Not overfitting

Held out: **`rec_MT7MXBS9B2VB`, `rec_MT7VTN7ZRJPO`, `rec_MTA7A2XHHH22`** — the
three real sessions, where every current defect was found. The seven fixtures
are dev.

1. **Tune on dev, score on held-out.**
2. **A change that improves dev and regresses held-out is reverted**, whatever
   the dev result says. Write the attempt in `docs/DECISIONS.md` — this project
   has already reverted one prompt rule that way, and the failed experiments are
   worth more than the successful ones.
3. **A rule change is calibrated over every (claim, literal) pair on disk**, not
   over the case that motivated it. Already the standard in `tests/test_bind.py`.
4. **Never edit a fixture to make a judgement pass.** If a fixture stops
   containing the hard thing, `tests/test_fixture_outcomes.py` is what changes,
   and only to assert something stronger.
5. **A defect found on a held-out recording earns a new fixture**, and the
   held-out recording stays held out.

**Done** is a judge pass whose findings are all `architecture` or `tester` —
nothing left that a prompt or a rule can fix.
