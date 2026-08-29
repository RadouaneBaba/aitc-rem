# Open defects, as they stood before the 2026-08-28 rebuild

**Archived 2026-08-29. Every defect below is about a stage that no longer
exists.** They name `_own_input`, `evidence_discriminates`, `_second_chance`,
`bind`, `split` and the critic/repair loop -- all deleted -- so read as a work
list this was three pages of fiction, and a reader looking for something to fix
would have gone hunting for files.

It is kept because the reasoning is the record of how the real cause was
eventually found, and because several of these were fixed CORRECTLY and were
still fighting downstream of a recorder that never captured the page. That is
the more useful lesson than any individual entry.

---

## Part 1 · Open defects

**None of the nine defects from 2026-08-25 remain.** They are listed as closed
in Part 2 with what was actually done. What follows is what the re-run found
afterwards and has not been resolved.

### The scenario name and the verdict can disagree

On `twoflows`, the drafter named its first scenario *"An order exceeding the
threshold requires approval"* and gave it one step: signing in and adding an
item. `_second_chance` then correctly earned it a verdict — *the cart badge
updates to show 'Cart contains 1 items'* — and the result is a scenario whose
name promises approval and whose body proves a badge count.

Both halves behaved. The name was written for a scenario the split later cut in
two, and nothing re-reads a name against the verdict its scenario ended up
with. `gherkin_style` has no rule for it and probably should not: "does this
name describe this body" is a judgement, and the critic's `coherence` finding is
the right home for it. It is not routed there today.

### An expected result can read as a title rather than a sentence

Same run: `Then Order requires approval` — capitalised, and a restatement of the
scenario name rather than a statement about what the application did. Bound to a
real literal, so every grounding check passes; it simply says nothing.

`_clean` normalises whitespace and a trailing full stop and does not touch case,
deliberately — lowercasing a leading proper noun would be worse than the
capital. The checkable half is the restatement: an expected result identical to
its scenario's name adds no verdict. That is a `gherkin_style` warning waiting
to be written, and it has a clean negative case (a name derived FROM the
assertion, which `_scenario_from` does legitimately).

### Grounded and vacuous: two ways found on one real recording

`rec_MTA7A2XHHH22` — a French storefront, 15 events, sort and filter controls,
objective *"check if filters are working correctly"*. **Thirteen validators
green, 4 of 4 claims grounded, and three of the four proved nothing.** Both
mechanisms are now caught; both are worth knowing about because neither is a
grounding failure.

**1. The claim rested on the tester's own input.**

```
claim:   the product list updates to show lower-priced items first
literal: "Prix bas à haut"     <- the option they selected in the sort dropdown
```

It proves the dropdown says what they set it to, and reads identically if the
list came back sorted the wrong way. This is `Export the order` again — the
label on the button just pressed — reaching the candidate set through a door
`_changed_at` cannot close, because choosing an option really does change the
page.

**The agent had the discriminating evidence and cited the other thing.** Its
recorded reason: *"The URL changed to include `order:ASC` (ascending price) and
the combobox value..."*. It found `order:ASC`, reasoned about it correctly, and
quoted the label. So no amount of extra retrieval budget fixes this.

Fixed in two tiers, the shape `_unwitnessed` already uses: `_Candidate.conclusive`
DECLINES to the agent (because "the quantity field shows 3" after typing 3 is
thin but not false, and only something reading the page can tell those apart),
and `bind._own_input` REFUSES the agent's own answer. Calibrated against every
accepted claim with a recording on disk: 2 refused of 26, both the same bad
claim.

**2. Two claims rested on the same generic announcement.**

```
the product list is filtered to show only available items      <- "Results updated."
the product list updates to show items matching the processors <- "Results updated."
```

An aria-live region saying that *something* changed. It is the bare number of
`_Candidate.conclusive` in another costume — a literal that supports any claim
of its shape whatsoever. `_unwitnessed` cannot see it: neither claim quotes a
value or contains a digit, so there is no checkable content to compare, and
prose framing is deliberately untouched there.

`evidence_discriminates` is the fourteenth validator and the check is
language-independent by construction: **if one literal is the whole evidence
for two claims that say different things, it tells them apart from nothing.**
A warning, not a rejection — it can say two claims cannot both be right about
this evidence, not which. Measured over every run on disk: 4 hits, all four
genuine defects (three are the `twoflows` restatement below, one is this).

**Outcome on the same recording, re-run.** 4 grounded-and-vacuous claims became
3 that each rest on distinct, discriminating evidence:

```
the product list is filtered to show only available items
  <- https://setupgame.ma/.../meta/_stock_status:instock/...     (the URL)
the product list updates to show items matching the processors
  <- "Results updated."
the product list updates to show all products
  <- "9 produits affichés"
```

Refusing the dropdown label pushed the agent to the URL, which is the evidence
it had already found and not cited — and that in turn dissolved the
`Results updated.` collision, because only one claim still needs it. Retrieval
went 18 calls to 32, concentrated on the contested steps
(`{step_003: 5, step_004: 7, step_006: 10, step_007: 10}`), which is SS3.3's
signature.

The sorting scenario now ships with **no verdict at all**, warned twice by
`gherkin_style`. Both attempts to bind one were refused, and that is the honest
answer: the recording may simply not show that the list re-sorted. A visible gap
beats an invisible falsehood, and it is the reviewer's to close.

**And a third defect fell out of it, which had been latent.**
`run._second_chance` re-proposes for a verdictless scenario and then re-binds —
but re-binding runs over the WHOLE document, so every step that had already
bound cleanly bound again, and assembly emitted both. It shipped as `Then the
product list is filtered to show only available items` immediately followed by
`And the product list is filtered to show only available items`, same step,
differing only in the evidence behind them. `merge_repeats` folds duplicate
STEPS and never looked at this.

`BindResult.for_step` is a SELECTION and `claims` is a HISTORY; conflating them
was the bug. It now keys on the drafter's original sentence, last attempt wins,
and the full history stays for the reviewer and for SS3.4.

### The size-triggered split is not stable across drafts

The trigger is deterministic; the ANSWER is a model call, and on the same
recording it has now given two different answers.

Measured while testing an unrelated prompt change on `rec_MT7MXBS9B2VB`. The
trigger fired identically both times — *33 events in one scenario, over the
floor of 12* — and the agent returned two named groups on one run and ONE group
(meaning "this is a single test case") on the other. Nothing about the split
stage changed between them. What changed was the draft it was reading: the step
texts were worded as a more continuous narrative the second time, and the
splitter read that as one flow.

That is a reproducibility problem of the kind SS3.6 cares about — the same
recording produced one test case and two — and it is worth being precise about
what it is NOT. A tester's DECLARED break still overrides the model
deterministically (`_split_on_declared_breaks`), and the net on the answer
(`accept`) is deterministic. Only the judgement of "is this long scenario one
behaviour or several" varies, which is the one part that is genuinely a
judgement.

Options, none of them free: seed the split call with the scenario's own
`expect` sentences rather than only its step texts (verdicts are what the
decision is about, and they are more stable than prose); or run it twice and
take a split only when both agree, which doubles the cost of the one stage
that fires rarely; or accept it and let the critic's `coherence` finding catch
the miss, which is what happened here — it fired, correctly, and had nowhere to
go.

### The value-preference rule was tried and reverted

**The experiment, and it failed.** The flagship's verdicts assert basket NAMES
(*the hamper is shown as a "Medium Wicker Basket"*) rather than the capacity
counter, which is the thing a broken feature would break. Note first what this
is not: nothing was rejected. `_unwitnessed` played no part — the drafter simply
never proposed the capacity, and binding took what it was given.

So the lever has to be the prompt, because choosing which value to assert on is
content. Added to the drafting prompt: *"Assert the value that would BREAK if
the feature broke"*, with a label-versus-state worked example.

Result on `rec_MT7MXBS9B2VB`:

| | before | with the rule |
|---|---|---|
| capacity values asserted | 0 of 3 | **1 of 3** |
| accepted expected results | 2 | 3 |
| test cases | **2** | 1 |
| splitter | cut into two | returned one group |

It half-took, and the run came back as a single scenario with three beats under
one heading — the exact defect the splitter exists for. The loss cannot be
cleanly attributed to the rule (see the instability above; the splitter reads
the draft, and the draft changed), which is itself the finding: **a prompt
change to the drafter perturbs every stage downstream of it, and the splitter
is the stage least able to absorb that.**

Reverted. One capacity number is not worth losing the split, and a rule with
1-of-3 uptake is a prompt line rather than a guarantee. Retry it after the
splitter is stable, not before.

### The drafter never retrieves, and the experiment says that is fine

0 of 30 drafting investigations made a single retrieval — every one stops at
`no_investigation_needed`, including on the 34-event commercial recording. The
per-step effort the ablation reports comes entirely from `bind.py`, `split.py`
and repair.

The open question was whether the drafter declines because the index is
sufficient or because the prompt made declining easy. **Run, on
`rec_MT7MXBS9B2VB`, with the decision rule fixed in advance:** keep the sentence
*"making no tool calls at all is a perfectly good outcome"* unless removing it
BOTH raises retrieval AND improves the document.

| | prompt as it is | the sentence removed, and "look before you write an expect" added |
|---|---|---|
| drafter retrieval | 0/8 | **0/8** |
| accepted expected results | 2 | 3 |
| validator pass, final | **1.000** | 0.889 |
| critic findings | 3 | 2 |

Retrieval did not move at all, and the document got worse — it lost the
quoted values in its step text and reached two verdicts under one scenario
name, which `gherkin_style` caught as a voice inconsistency. The sentence
stayed.

So the answer is the first one: the index really is sufficient for these
recordings. That is a result about `digest.py` being good rather than about the
drafter being lazy, and it means SS3.3's effort variance lives in binding, which
is where the genuinely contested claims are. Worth re-running on a recording
where the index is thin — one with many `(re-render; nothing named)` events.

### `Converged` needs an honest denominator

Measured on 2026-08-26: A2 raised 9 critic findings and resolved 1 within
budget, which reads as a repair loop that barely works. **Five of the seven
findings that survived to the final critique are `coherence`, which has no row
in `CRITIC_REPAIR` by design** — acting on one means re-drafting and re-drafting
can change the step count. `repairAttempts` is 0 on four of the seven runs: the
loop never started, because there was nothing it was permitted to touch.

So the column currently measures *how much of what the critic said the loop was
allowed to act on*. Convergence over ROUTABLE findings is the honest
denominator. Changing it means re-running the ablation, so it was left as
measured and documented rather than adjusted after the fact.

This is the sixth column in which this project has met the same trap. Assume it
is in the next one too.

### SS3.4 has no data, and only a human can supply it

`effort_difficulty.py` now requires eight edited and eight untouched steps
before it reports a coefficient, and prints *not enough data* until then. That
is the honest state: the correlation needs review activity, and the only run in
the repo that ever had an edited step was deleted with the rest of `runs/`.

Not a code defect. Open a few drafts in the review UI, change what is wrong with
them, and the number appears. Nothing else will produce it.

---

